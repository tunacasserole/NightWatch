"""Error analysis workflow — the original NightWatch pipeline as a workflow."""

from __future__ import annotations

import logging

from nightwatch.workflows.base import (
    SafeOutput,
    Workflow,
    WorkflowAction,
    WorkflowAnalysis,
    WorkflowItem,
    WorkflowResult,
)
from nightwatch.workflows.registry import register

logger = logging.getLogger("nightwatch.workflows.errors")


@register
class ErrorAnalysisWorkflow(Workflow):
    """Analyzes production errors from New Relic using Claude AI."""

    name = "errors"
    description = "Analyze production errors from New Relic and create GitHub issues/PRs"
    safe_outputs = [
        SafeOutput.CREATE_ISSUE,
        SafeOutput.CREATE_PR,
        SafeOutput.SEND_SLACK,
    ]

    def fetch(self, **kwargs) -> list[WorkflowItem]:
        """Fetch errors — items passed in via kwargs from the runner."""
        items = kwargs.get("items", [])
        return [
            WorkflowItem(
                id=str(i),
                title=(
                    f"{getattr(item, 'error_class', 'Unknown')} "
                    f"in {getattr(item, 'transaction', 'Unknown')}"
                ),
                raw_data=item,
            )
            for i, item in enumerate(items)
        ]

    def filter(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowItem]:
        """Filter to top N errors by severity — already done by runner."""
        max_errors = kwargs.get("max_errors")
        if max_errors and len(items) > max_errors:
            return items[:max_errors]
        return items

    def analyze(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowAnalysis]:
        """Track analyses passed back from the runner."""
        analyses = kwargs.get("analyses", [])
        return [
            WorkflowAnalysis(
                item=item,
                summary=getattr(a, "root_cause", "") if a else "",
                confidence=getattr(a, "confidence", 0.0) if a else 0.0,
                tokens_used=getattr(a, "tokens_used", 0) if a else 0,
            )
            for item, a in zip(items, analyses, strict=False)
        ]

    def act(self, analyses: list[WorkflowAnalysis], **kwargs) -> list[WorkflowAction]:
        """Create GitHub issues and PRs — delegates to runner pipeline."""
        actions = []
        for action_data in kwargs.get("actions_taken", []):
            action_type = action_data.get("type", SafeOutput.CREATE_ISSUE)
            if self.check_safe_output(action_type):
                actions.append(
                    WorkflowAction(
                        action_type=action_type,
                        target=action_data.get("target", ""),
                        details=action_data.get("details", {}),
                        success=action_data.get("success", False),
                    )
                )
        return actions

    def report_section(self, result: WorkflowResult) -> list[dict]:
        """Generate Slack blocks for error analysis report."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Error Analysis* — "
                        f"{result.items_analyzed} errors analyzed"
                    ),
                },
            }
        ]
        for analysis in result.analyses[:5]:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• {analysis.item.title}: {analysis.summary[:100]}",
                },
            })
        return blocks
