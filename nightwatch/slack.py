"""Slack integration — Bot Token DM with Block Kit report."""

from __future__ import annotations

import logging
import ssl

import certifi
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from nightwatch.config import get_settings
from nightwatch.models import CreatedIssueResult, CreatedPRResult, RunReport

logger = logging.getLogger("nightwatch.slack")


class SlackClient:
    """Sync Slack client for sending DM reports."""

    def __init__(self) -> None:
        settings = get_settings()
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        self.client = WebClient(token=settings.slack_bot_token, ssl=ssl_ctx)
        self.notify_user = settings.slack_notify_user
        self._user_id_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # User lookup + DM channel
    # ------------------------------------------------------------------

    def _get_user_id(self, display_name: str) -> str | None:
        """Find a Slack user ID by display name (fuzzy match)."""
        if display_name in self._user_id_cache:
            return self._user_id_cache[display_name]

        try:
            result = self.client.users_list()
            if not result["ok"]:
                return None

            name_lower = display_name.lower()
            for member in result["members"]:
                if member.get("deleted") or member.get("is_bot"):
                    continue
                profile = member.get("profile", {})
                names = [
                    member.get("name", "").lower(),
                    member.get("real_name", "").lower(),
                    profile.get("display_name", "").lower(),
                    profile.get("real_name", "").lower(),
                ]
                if name_lower in names or any(name_lower in n for n in names if n):
                    uid = member["id"]
                    self._user_id_cache[display_name] = uid
                    logger.info(f"Found Slack user {display_name}: {uid}")
                    return uid

            logger.warning(f"Slack user not found: {display_name}")
            return None
        except SlackApiError as e:
            logger.error(f"Slack user lookup error: {e}")
            return None

    def _open_dm(self, user_id: str) -> str | None:
        """Open a DM channel with the user."""
        try:
            result = self.client.conversations_open(users=[user_id])
            return result["channel"]["id"] if result["ok"] else None
        except SlackApiError as e:
            logger.error(f"Slack DM open error: {e}")
            return None

    # ------------------------------------------------------------------
    # Report messages
    # ------------------------------------------------------------------

    def send_report(self, report: RunReport) -> bool:
        """Send the daily summary report as a DM."""
        user_id = self._get_user_id(self.notify_user)
        if not user_id:
            return False
        channel = self._open_dm(user_id)
        if not channel:
            return False

        blocks = _build_report_blocks(report)

        try:
            self.client.chat_postMessage(
                channel=channel,
                text=(
                    f"NightWatch: {report.errors_analyzed} errors analyzed,"
                    f" {report.fixes_found} fixes found"
                ),
                blocks=blocks,
            )
            logger.info("Slack report sent")
            return True
        except SlackApiError as e:
            logger.error(f"Slack send error: {e}")
            return False

    def send_followup(
        self,
        issues: list[CreatedIssueResult],
        pr: CreatedPRResult | None,
    ) -> bool:
        """Send a follow-up message with created issues and PR links."""
        user_id = self._get_user_id(self.notify_user)
        if not user_id:
            return False
        channel = self._open_dm(user_id)
        if not channel:
            return False

        blocks = _build_followup_blocks(issues, pr)

        try:
            self.client.chat_postMessage(
                channel=channel,
                text=f"NightWatch: {len(issues)} issues created",
                blocks=blocks,
            )
            logger.info("Slack follow-up sent")
            return True
        except SlackApiError as e:
            logger.error(f"Slack follow-up error: {e}")
            return False


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------


def _build_report_blocks(report: RunReport) -> list[dict]:
    """Build Block Kit blocks for the summary report."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "NightWatch Daily Report"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Errors Found:* {report.total_errors_found} groups"},
                {"type": "mrkdwn", "text": f"*Filtered:* {report.errors_filtered}"},
                {"type": "mrkdwn", "text": f"*Analyzed:* {report.errors_analyzed}"},
                {"type": "mrkdwn", "text": f"*Fixes Found:* {report.fixes_found}"},
            ],
        },
        {"type": "divider"},
    ]

    # One section per analyzed error
    for i, result in enumerate(report.analyses, 1):
        error = result.error
        analysis = result.analysis
        confidence_emoji = {
            "high": ":large_green_circle:",
            "medium": ":large_yellow_circle:",
            "low": ":red_circle:",
        }
        emoji = confidence_emoji.get(
            analysis.confidence, ":white_circle:"
        )
        status = "Fix found" if analysis.has_fix else "Needs investigation"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{i}. {emoji} {error.error_class}*\n"
                    f"`{error.transaction}` · {error.occurrences} occurrences\n"
                    f"{analysis.reasoning[:200]}{'...' if len(analysis.reasoning) > 200 else ''}\n"
                    f"Confidence: *{analysis.confidence.upper()}* · {status}"
                ),
            },
        })

    # Footer
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f":stopwatch: {report.run_duration_seconds:.0f}s · "
                    f"{report.total_api_calls} API calls · "
                    f"{report.total_tokens_used:,} tokens"
                ),
            }
        ],
    })

    return blocks


def _build_followup_blocks(
    issues: list[CreatedIssueResult],
    pr: CreatedPRResult | None,
) -> list[dict]:
    """Build Block Kit blocks for the follow-up message."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "NightWatch: Issues Created"},
        },
    ]

    for issue in issues:
        action_text = "Created" if issue.action == "created" else "Updated"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{action_text}:* <{issue.issue_url}|#{issue.issue_number}> — "
                    f"`{issue.error.error_class}` in `{issue.error.transaction}`"
                ),
            },
        })

    if pr:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":hammer_and_wrench: *Draft PR:* <{pr.pr_url}|#{pr.pr_number}> — "
                    f"{pr.files_changed} files changed"
                ),
            },
        })

    return blocks
