"""CI Doctor workflow — diagnoses GitHub Actions failures."""

from __future__ import annotations

import logging
import re

from nightwatch.workflows.base import (
    SafeOutput,
    Workflow,
    WorkflowAction,
    WorkflowAnalysis,
    WorkflowItem,
    WorkflowResult,
)
from nightwatch.workflows.registry import register

logger = logging.getLogger("nightwatch.workflows.ci_doctor")

KNOWN_PATTERNS: dict[str, dict] = {
    r"ETIMEDOUT|ECONNREFUSED|network timeout": {
        "root_cause": "Network timeout or connection refused",
        "category": "infrastructure",
        "confidence": 0.95,
        "suggested_fix": "Retry the workflow — likely a transient network issue",
        "is_transient": True,
    },
    r"rate limit|API rate limit exceeded|403.*rate": {
        "root_cause": "API rate limit exceeded",
        "category": "rate_limit",
        "confidence": 0.95,
        "suggested_fix": "Wait and retry, or add rate limiting/caching",
        "is_transient": True,
    },
    r"No space left on device|disk full|ENOSPC": {
        "root_cause": "Disk space exhausted on runner",
        "category": "resource_limit",
        "confidence": 0.95,
        "suggested_fix": "Clean up disk space or use a larger runner",
        "is_transient": False,
    },
    r"Out of memory|OOMKilled|MemoryError": {
        "root_cause": "Out of memory on runner",
        "category": "resource_limit",
        "confidence": 0.90,
        "suggested_fix": "Optimize memory usage or use a larger runner",
        "is_transient": False,
    },
}


@register
class CIDoctorWorkflow(Workflow):
    """Diagnoses GitHub Actions CI failures."""

    name = "ci_doctor"
    description = "Diagnose GitHub Actions failures and post root-cause comments"
    safe_outputs = [
        SafeOutput.ADD_COMMENT,
        SafeOutput.ADD_LABEL,
        SafeOutput.SEND_SLACK,
    ]

    def fetch(self, **kwargs) -> list[WorkflowItem]:
        """Fetch failed workflow runs from GitHub."""
        github_client = kwargs.get("github_client")
        if not github_client:
            logger.warning("No GitHub client provided to CI Doctor")
            return []

        try:
            repo = github_client.get_repo()
            runs = repo.get_workflow_runs(status="failure")
            items = []
            for run in runs[:10]:
                items.append(
                    WorkflowItem(
                        id=str(run.id),
                        title=f"{run.name} #{run.run_number}",
                        raw_data=run,
                        metadata={
                            "branch": run.head_branch,
                            "sha": run.head_sha[:8],
                            "created_at": str(run.created_at),
                            "url": run.html_url,
                        },
                    )
                )
            return items
        except Exception as e:
            logger.error(f"Failed to fetch CI runs: {e}")
            return []

    def filter(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowItem]:
        """Prioritize main branch failures, limit to top N."""
        max_items = kwargs.get("max_items", 5)

        def sort_key(item):
            branch = item.metadata.get("branch", "")
            is_main = branch in ("main", "master")
            return (0 if is_main else 1, item.id)

        sorted_items = sorted(items, key=sort_key)
        return sorted_items[:max_items]

    def analyze(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowAnalysis]:
        """Analyze each failed run — check known patterns first."""
        analyses = []
        for item in items:
            log_text = item.metadata.get("log_text", "")
            known = self._check_known_patterns(log_text)
            if known:
                analyses.append(
                    WorkflowAnalysis(
                        item=item,
                        summary=known["root_cause"],
                        details=known,
                        confidence=known["confidence"],
                    )
                )
            else:
                analyses.append(
                    WorkflowAnalysis(
                        item=item,
                        summary="Requires deeper analysis",
                        details={"category": "unknown", "is_transient": False},
                        confidence=0.0,
                    )
                )
        return analyses

    def _check_known_patterns(self, log_text: str) -> dict | None:
        """Check if failure matches a known pattern."""
        for pattern, diagnosis in KNOWN_PATTERNS.items():
            if re.search(pattern, log_text, re.IGNORECASE):
                return dict(diagnosis)
        return None

    def act(self, analyses: list[WorkflowAnalysis], **kwargs) -> list[WorkflowAction]:
        """Post diagnosis comments on PRs/commits."""
        actions = []
        dry_run = kwargs.get("dry_run", True)

        for analysis in analyses:
            if analysis.confidence > 0.5:
                comment = self._build_diagnosis_comment(analysis)
                if dry_run:
                    logger.info(
                        f"[DRY RUN] Would post comment for {analysis.item.title}"
                    )
                action = WorkflowAction(
                    action_type=SafeOutput.ADD_COMMENT,
                    target=analysis.item.title,
                    details={"comment": comment, "dry_run": dry_run},
                    success=not dry_run,
                )
                actions.append(action)
        return actions

    def _build_diagnosis_comment(self, analysis: WorkflowAnalysis) -> str:
        """Format a diagnosis as a markdown comment."""
        details = analysis.details
        is_transient = "Yes" if details.get("is_transient") else "No"
        return (
            "## 🔍 NightWatch CI Diagnosis\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| **Root Cause** | {analysis.summary} |\n"
            f"| **Category** | {details.get('category', 'unknown')} |\n"
            f"| **Confidence** | {analysis.confidence:.0%} |\n"
            f"| **Suggested Fix** | {details.get('suggested_fix', 'N/A')} |\n"
            f"| **Transient** | {is_transient} |\n"
        )

    def report_section(self, result: WorkflowResult) -> list[dict]:
        """Generate Slack blocks for CI Doctor report."""
        if not result.analyses:
            return []
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*CI Doctor* — "
                        f"{len(result.analyses)} failures diagnosed"
                    ),
                },
            }
        ]
        for analysis in result.analyses[:5]:
            emoji = "✅" if analysis.details.get("is_transient") else "🔴"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} {analysis.item.title}: "
                        f"{analysis.summary} ({analysis.confidence:.0%})"
                    ),
                },
            })
        return blocks
