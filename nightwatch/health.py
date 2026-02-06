"""NightWatch self-health report generator.

Produces a structured health report about NightWatch's own performance,
configuration status, and operational metrics.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from nightwatch.config import get_settings

logger = logging.getLogger("nightwatch.health")


class HealthReport:
    """Generates and stores NightWatch self-health metrics."""

    def __init__(self) -> None:
        self.start_time: float = time.time()
        self.errors_attempted: int = 0
        self.errors_analyzed: int = 0
        self.errors_failed: int = 0
        self.issues_created: int = 0
        self.prs_created: int = 0
        self.total_tokens: int = 0
        self.total_cost_estimate: float = 0.0
        self.api_errors: list[str] = []
        self.warnings: list[str] = []
        self.config_issues: list[str] = []

    def check_configuration(self) -> None:
        """Validate NightWatch configuration and record issues."""
        settings = get_settings()

        if not settings.anthropic_api_key:
            self.config_issues.append("ANTHROPIC_API_KEY not set")
        if not settings.github_token:
            self.config_issues.append("GITHUB_TOKEN not set")
        if not settings.new_relic_api_key:
            self.config_issues.append("NEW_RELIC_API_KEY not set")

        if not getattr(settings, "slack_bot_token", None):
            self.warnings.append("SLACK_BOT_TOKEN not set — Slack reporting disabled")

    def record_analysis(
        self, success: bool, tokens_used: int = 0, error_msg: str | None = None
    ) -> None:
        """Record the result of an error analysis attempt."""
        self.errors_attempted += 1
        if success:
            self.errors_analyzed += 1
        else:
            self.errors_failed += 1
            if error_msg:
                self.api_errors.append(error_msg)
        self.total_tokens += tokens_used

    def record_action(self, action_type: str, success: bool) -> None:
        """Record a GitHub action (issue/PR creation)."""
        if action_type == "issue" and success:
            self.issues_created += 1
        elif action_type == "pr" and success:
            self.prs_created += 1

    def estimate_cost(self) -> float:
        """Estimate API cost based on token usage (Claude Sonnet pricing)."""
        input_tokens = self.total_tokens * 0.7
        output_tokens = self.total_tokens * 0.3
        cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)
        self.total_cost_estimate = round(cost, 4)
        return self.total_cost_estimate

    def generate(self) -> dict[str, Any]:
        """Generate the complete health report."""
        elapsed = time.time() - self.start_time
        self.estimate_cost()

        success_rate = (
            self.errors_analyzed / self.errors_attempted * 100
            if self.errors_attempted > 0
            else 0.0
        )

        return {
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": round(elapsed, 1),
            "analysis": {
                "attempted": self.errors_attempted,
                "succeeded": self.errors_analyzed,
                "failed": self.errors_failed,
                "success_rate": round(success_rate, 1),
            },
            "actions": {
                "issues_created": self.issues_created,
                "prs_created": self.prs_created,
            },
            "resources": {
                "total_tokens": self.total_tokens,
                "estimated_cost_usd": self.total_cost_estimate,
                "avg_tokens_per_error": (
                    round(self.total_tokens / self.errors_analyzed)
                    if self.errors_analyzed > 0
                    else 0
                ),
            },
            "health": {
                "status": self._compute_status(),
                "config_issues": self.config_issues,
                "warnings": self.warnings,
                "api_errors": self.api_errors[-5:],
            },
        }

    def _compute_status(self) -> str:
        """Compute overall health status."""
        if self.config_issues:
            return "degraded"
        if self.errors_failed > self.errors_analyzed:
            return "unhealthy"
        if self.warnings:
            return "warning"
        return "healthy"

    def format_slack_blocks(self) -> list[dict]:
        """Format health report as Slack Block Kit blocks."""
        report = self.generate()
        status_emoji = {
            "healthy": "✅",
            "warning": "⚠️",
            "degraded": "🟡",
            "unhealthy": "🔴",
        }
        emoji = status_emoji.get(report["health"]["status"], "❓")

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *NightWatch Health Report*\n"
                        f"Status: {report['health']['status']} | "
                        f"Duration: {report['duration_seconds']}s | "
                        f"Cost: ${report['resources']['estimated_cost_usd']:.4f}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Analysis*: "
                        f"{report['analysis']['succeeded']}/{report['analysis']['attempted']} "
                        f"({report['analysis']['success_rate']}% success)\n"
                        f"*Actions*: {report['actions']['issues_created']} issues, "
                        f"{report['actions']['prs_created']} PRs\n"
                        f"*Tokens*: {report['resources']['total_tokens']:,} "
                        f"(avg {report['resources']['avg_tokens_per_error']:,}/error)"
                    ),
                },
            },
        ]

        if report["health"]["config_issues"]:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Config Issues*: " + ", ".join(report["health"]["config_issues"]),
                },
            })

        return blocks
