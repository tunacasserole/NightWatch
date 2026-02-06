"""Batch triage via Anthropic Message Batches API — 50% cost reduction.

Submit errors for quick triage classification in a single batch request,
then collect results asynchronously. Only errors marked "needs_deep_investigation"
proceed to the full agentic analysis loop.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from nightwatch.config import get_settings
from nightwatch.prompts import summarize_traces
from nightwatch.types.core import ErrorGroup

logger = logging.getLogger("nightwatch.batch")

BATCH_STATE_DIR = Path.home() / ".nightwatch" / "batches"

TRIAGE_PROMPT = """Analyze this production error and provide a quick triage classification.
Respond with ONLY a JSON object (no markdown, no explanation):

{{
    "severity": "critical|high|medium|low",
    "likely_root_cause": "1-2 sentence description",
    "needs_deep_investigation": true|false,
    "fix_category": "code_bug|config|dependency|infra|unknown"
}}

Error details:
- Error class: {error_class}
- Transaction: {transaction}
- Message: {message}
- Occurrences: {occurrences}

{trace_summary}
"""


@dataclass
class TriageResult:
    """Result of batch triage for a single error."""

    error: ErrorGroup
    severity: str = "medium"
    likely_root_cause: str = ""
    needs_deep_investigation: bool = True
    fix_category: str = "unknown"
    raw_response: str = ""


@dataclass
class BatchSubmission:
    """Record of a submitted batch."""

    batch_id: str
    submitted_at: str
    error_count: int
    custom_id_map: dict[str, dict] = field(default_factory=dict)


class BatchAnalyzer:
    """Submit errors for batch triage and collect results."""

    def __init__(self) -> None:
        settings = get_settings()
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.nightwatch_model
        BATCH_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def submit_batch(
        self,
        errors: list[ErrorGroup],
        traces_map: dict[str, Any],
    ) -> str:
        """Submit errors as a batch triage request.

        Args:
            errors: List of error groups to triage.
            traces_map: Map of error key -> TraceData.

        Returns:
            batch_id for later collection.
        """
        requests: list[Request] = []
        custom_id_map: dict[str, dict] = {}

        for i, error in enumerate(errors):
            custom_id = f"triage-{i}-{error.error_class[:30]}"
            traces = traces_map.get(f"{error.error_class}:{error.transaction}")

            trace_summary = ""
            if traces:
                trace_summary = summarize_traces(
                    {
                        "transaction_errors": getattr(traces, "transaction_errors", []),
                        "error_traces": getattr(traces, "error_traces", []),
                    }
                )

            prompt = TRIAGE_PROMPT.format(
                error_class=error.error_class,
                transaction=error.transaction,
                message=error.message,
                occurrences=error.occurrences,
                trace_summary=trace_summary,
            )

            requests.append(
                Request(
                    custom_id=custom_id,
                    params=MessageCreateParamsNonStreaming(
                        model=self.model,
                        max_tokens=512,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                )
            )
            custom_id_map[custom_id] = {
                "error_class": error.error_class,
                "transaction": error.transaction,
                "index": i,
            }

        batch = self.client.messages.batches.create(requests=requests)
        logger.info(f"Batch submitted: {batch.id} ({len(requests)} errors)")

        # Save batch state
        submission = BatchSubmission(
            batch_id=batch.id,
            submitted_at=datetime.utcnow().isoformat(),
            error_count=len(requests),
            custom_id_map=custom_id_map,
        )
        state_file = BATCH_STATE_DIR / f"{batch.id}.json"
        state_file.write_text(
            json.dumps(
                {
                    "batch_id": submission.batch_id,
                    "submitted_at": submission.submitted_at,
                    "error_count": submission.error_count,
                    "custom_id_map": submission.custom_id_map,
                },
                indent=2,
            )
        )

        return batch.id

    def poll_results(
        self,
        batch_id: str,
        poll_interval: int = 30,
        max_wait: int = 3600,
    ) -> list[TriageResult]:
        """Poll for batch completion and return triage results.

        Args:
            batch_id: The batch ID to poll.
            poll_interval: Seconds between polls.
            max_wait: Max seconds to wait before giving up.

        Returns:
            List of TriageResult objects.
        """
        # Load saved state
        state_file = BATCH_STATE_DIR / f"{batch_id}.json"
        if not state_file.exists():
            raise FileNotFoundError(f"No saved state for batch {batch_id}")

        state = json.loads(state_file.read_text())
        custom_id_map = state["custom_id_map"]

        elapsed = 0
        while elapsed < max_wait:
            batch = self.client.messages.batches.retrieve(batch_id)
            logger.info(
                f"Batch {batch_id}: {batch.processing_status} "
                f"(succeeded={batch.request_counts.succeeded}, "
                f"errored={batch.request_counts.errored})"
            )
            if batch.processing_status == "ended":
                break
            time.sleep(poll_interval)
            elapsed += poll_interval

        if elapsed >= max_wait:
            logger.warning(f"Batch {batch_id} did not complete within {max_wait}s")
            return []

        # Collect results
        results: list[TriageResult] = []
        for result in self.client.messages.batches.results(batch_id):
            info = custom_id_map.get(result.custom_id, {})

            if result.result.type == "succeeded":
                triage = self._parse_triage(result.result.message)
                triage_result = TriageResult(
                    error=ErrorGroup(
                        error_class=info.get("error_class", "Unknown"),
                        transaction=info.get("transaction", "Unknown"),
                        message="",
                        occurrences=0,
                        last_seen="",
                    ),
                    severity=triage.get("severity", "medium"),
                    likely_root_cause=triage.get("likely_root_cause", ""),
                    needs_deep_investigation=triage.get("needs_deep_investigation", True),
                    fix_category=triage.get("fix_category", "unknown"),
                )
                results.append(triage_result)
            else:
                logger.warning(f"Batch result {result.custom_id}: {result.result.type}")
                # Default to needing investigation for failed results
                results.append(
                    TriageResult(
                        error=ErrorGroup(
                            error_class=info.get("error_class", "Unknown"),
                            transaction=info.get("transaction", "Unknown"),
                            message="",
                            occurrences=0,
                            last_seen="",
                        ),
                    )
                )

        logger.info(
            f"Batch results: {len(results)} total, "
            f"{sum(1 for r in results if r.needs_deep_investigation)} "
            f"need investigation"
        )
        return results

    def _parse_triage(self, message: Any) -> dict:
        """Parse triage JSON from Claude's response."""
        text = ""
        for block in message.content:
            if hasattr(block, "text"):
                text += block.text

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code block
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            logger.warning(f"Could not parse triage response: {text[:200]}")
            return {}

    @staticmethod
    def get_latest_batch_id() -> str | None:
        """Get the most recent batch ID from saved state."""
        if not BATCH_STATE_DIR.exists():
            return None
        files = sorted(
            BATCH_STATE_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return None
        state = json.loads(files[0].read_text())
        return state.get("batch_id")
