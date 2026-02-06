"""Pattern analysis workflow — detects systemic patterns across run history."""

from __future__ import annotations

import logging
from collections import Counter

from nightwatch.history import load_history
from nightwatch.workflows.base import (
    SafeOutput,
    Workflow,
    WorkflowAction,
    WorkflowAnalysis,
    WorkflowItem,
    WorkflowResult,
)
from nightwatch.workflows.registry import register

logger = logging.getLogger("nightwatch.workflows.patterns")


@register
class PatternAnalysisWorkflow(Workflow):
    """Detects systemic patterns across accumulated error history."""

    name = "patterns"
    description = "Detect recurring error patterns across NightWatch run history"
    safe_outputs = [SafeOutput.CREATE_ISSUE, SafeOutput.SEND_SLACK]

    def fetch(self, **kwargs) -> list[WorkflowItem]:
        """Fetch and aggregate run history."""
        history = load_history(days=30)
        if not history:
            logger.info("No run history available for pattern analysis")
            return []

        error_counts: Counter = Counter()
        error_details: dict[str, list] = {}

        for run in history:
            for error in run.get("errors_analyzed", []):
                error_class = error.get("error_class", "Unknown")
                error_counts[error_class] += 1
                if error_class not in error_details:
                    error_details[error_class] = []
                error_details[error_class].append(error)

        items = []
        for error_class, count in error_counts.most_common(20):
            items.append(
                WorkflowItem(
                    id=error_class,
                    title=f"{error_class} ({count} occurrences)",
                    raw_data=error_details.get(error_class, []),
                    metadata={"count": count, "error_class": error_class},
                )
            )
        return items

    def filter(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowItem]:
        """Only analyze patterns with minimum occurrences."""
        min_occurrences = kwargs.get("min_occurrences", 3)
        return [
            item for item in items
            if item.metadata.get("count", 0) >= min_occurrences
        ]

    def analyze(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowAnalysis]:
        """Analyze recurring patterns."""
        analyses = []
        for item in items:
            count = item.metadata.get("count", 0)
            if count >= 10:
                severity = "critical"
            elif count >= 5:
                severity = "high"
            else:
                severity = "medium"
            analyses.append(
                WorkflowAnalysis(
                    item=item,
                    summary=(
                        f"Recurring {item.metadata.get('error_class', 'Unknown')} "
                        f"({count} occurrences)"
                    ),
                    details={
                        "severity": severity,
                        "count": count,
                        "error_class": item.metadata.get("error_class"),
                    },
                    confidence=min(0.95, 0.5 + count * 0.05),
                )
            )
        return analyses

    def act(self, analyses: list[WorkflowAnalysis], **kwargs) -> list[WorkflowAction]:
        """Create GitHub issues for detected patterns."""
        actions = []
        dry_run = kwargs.get("dry_run", True)
        for analysis in analyses:
            if analysis.confidence > 0.6 and self.check_safe_output(
                SafeOutput.CREATE_ISSUE
            ):
                actions.append(
                    WorkflowAction(
                        action_type=SafeOutput.CREATE_ISSUE,
                        target=(
                            f"Pattern: "
                            f"{analysis.item.metadata.get('error_class', 'Unknown')}"
                        ),
                        details={
                            "severity": analysis.details.get("severity"),
                            "dry_run": dry_run,
                        },
                        success=not dry_run,
                    )
                )
        return actions

    def report_section(self, result: WorkflowResult) -> list[dict]:
        """Generate Slack blocks for pattern analysis report."""
        if not result.analyses:
            return []

        severity_emoji = {
            "critical": "🔴", "high": "🟠",
            "medium": "🟡", "low": "🟢",
        }
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Pattern Analysis* — "
                        f"{len(result.analyses)} systemic patterns detected"
                    ),
                },
            }
        ]
        for analysis in result.analyses[:5]:
            emoji = severity_emoji.get(
                analysis.details.get("severity", "medium"), "⚪"
            )
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} {analysis.summary} "
                        f"(confidence: {analysis.confidence:.0%})"
                    ),
                },
            })
        return blocks
