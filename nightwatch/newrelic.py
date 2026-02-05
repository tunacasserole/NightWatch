"""New Relic API client — batch error fetching, ranking, and trace retrieval."""

from __future__ import annotations

import logging
import time

import httpx
import yaml

from nightwatch.config import get_settings
from nightwatch.models import ErrorGroup, TraceData

logger = logging.getLogger("nightwatch.newrelic")


class NewRelicClient:
    """Sync client for New Relic GraphQL API."""

    BASE_URL = "https://api.newrelic.com/graphql"

    def __init__(self) -> None:
        settings = get_settings()
        self.account_id = settings.new_relic_account_id
        self.app_name = settings.new_relic_app_name
        self.client = httpx.Client(
            headers={
                "Api-Key": settings.new_relic_api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self.client.close()

    # ------------------------------------------------------------------
    # Core NRQL helper
    # ------------------------------------------------------------------

    def query_nrql(self, nrql: str) -> list[dict]:
        """Execute a NRQL query and return results."""
        graphql = f"""{{
          actor {{
            account(id: {self.account_id}) {{
              nrql(query: "{nrql}") {{
                results
              }}
            }}
          }}
        }}"""
        response = self.client.post(self.BASE_URL, json={"query": graphql})
        response.raise_for_status()
        data = response.json()

        # Check for GraphQL errors
        errors = data.get("errors")
        if errors:
            logger.error(f"NRQL query error: {errors}")
            return []

        return (
            data.get("data", {})
            .get("actor", {})
            .get("account", {})
            .get("nrql", {})
            .get("results", [])
        )

    # ------------------------------------------------------------------
    # Batch error fetching (the key new query TheFixer doesn't have)
    # ------------------------------------------------------------------

    def fetch_errors(self, since: str = "24h") -> list[ErrorGroup]:
        """Fetch all TransactionErrors grouped by (error.class, transactionName).

        Returns one ErrorGroup per unique error type with occurrence counts.
        """
        nrql = (
            f"SELECT count(*) AS occurrences, "
            f"latest(error.class) AS error_class, "
            f"latest(error.message) AS error_message, "
            f"latest(transactionName) AS transaction, "
            f"latest(path) AS http_path, "
            f"latest(host) AS host, "
            f"latest(entityGuid) AS entity_guid, "
            f"latest(timestamp) AS last_seen "
            f"FROM TransactionError "
            f"WHERE appName = '{self.app_name}' "
            f"SINCE {since} ago "
            f"FACET error.class, transactionName "
            f"LIMIT 50"
        )

        logger.info(f"Querying New Relic for errors in the last {since}...")
        results = self.query_nrql(nrql)

        groups: list[ErrorGroup] = []
        for row in results:
            groups.append(
                ErrorGroup(
                    error_class=row.get(
                        "error_class",
                        row.get("facet", ["Unknown"])[0],
                    ),
                    transaction=row.get(
                        "transaction",
                        row.get("facet", ["", "Unknown"])[1]
                        if len(row.get("facet", [])) > 1
                        else "Unknown",
                    ),
                    message=str(row.get("error_message", ""))[:500],
                    occurrences=int(row.get("occurrences", 1)),
                    last_seen=str(row.get("last_seen", "")),
                    http_path=row.get("http_path", ""),
                    entity_guid=row.get("entity_guid"),
                    host=row.get("host", ""),
                )
            )

        logger.info(
            f"Found {len(groups)} unique error groups "
            f"({sum(g.occurrences for g in groups)} total occurrences)"
        )
        return groups

    # ------------------------------------------------------------------
    # Trace fetching (per error, for Claude's context)
    # ------------------------------------------------------------------

    def fetch_traces(self, error: ErrorGroup, since: str = "24h") -> TraceData:
        """Fetch detailed traces for a specific error group."""
        # Query 1: Recent TransactionError events for this error
        tx_nrql = (
            f"SELECT error.message, error.class, appName, transactionName, "
            f"path, host, timestamp, traceId, entityGuid "
            f"FROM TransactionError "
            f"WHERE appName = '{self.app_name}' "
            f"AND error.class = '{_escape_nrql(error.error_class)}' "
            f"AND transactionName = '{_escape_nrql(error.transaction)}' "
            f"SINCE {since} ago LIMIT 5"
        )

        # Query 2: ErrorTrace events (more detailed with stack traces)
        trace_nrql = (
            f"SELECT * FROM ErrorTrace "
            f"WHERE appName = '{self.app_name}' "
            f"AND error.class = '{_escape_nrql(error.error_class)}' "
            f"SINCE {since} ago LIMIT 3"
        )

        transaction_errors = self.query_nrql(tx_nrql)
        error_traces = self.query_nrql(trace_nrql)

        logger.info(
            f"Traces for {error.error_class}: "
            f"{len(transaction_errors)} tx errors, {len(error_traces)} stack traces"
        )

        return TraceData(
            transaction_errors=transaction_errors,
            error_traces=error_traces,
        )


# ------------------------------------------------------------------
# Error ranking
# ------------------------------------------------------------------


def rank_errors(errors: list[ErrorGroup]) -> list[ErrorGroup]:
    """Rank errors by impact score: frequency + severity + recency + user-facing."""
    for error in errors:
        error.score = (
            min(error.occurrences / 100, 1.0) * 0.4
            + severity_weight(error.error_class) * 0.3
            + recency_weight(error.last_seen) * 0.2
            + user_facing_weight(error.transaction) * 0.1
        )
    return sorted(errors, key=lambda e: e.score, reverse=True)


def severity_weight(error_class: str) -> float:
    """Weight errors by likely severity category."""
    critical = ["SystemStackError", "NoMemoryError", "SecurityError", "SignalException"]
    high = [
        "NoMethodError", "NameError", "TypeError",
        "ActiveRecord::RecordNotFound", "ActiveRecord::StatementInvalid",
    ]
    medium = ["ArgumentError", "KeyError", "RuntimeError", "StandardError"]
    low = [
        "NotAuthorizedError", "CanCan::AccessDenied",
        "Pundit::NotAuthorizedError", "ActionController::RoutingError",
    ]

    if any(c in error_class for c in critical):
        return 1.0
    if any(c in error_class for c in high):
        return 0.7
    if any(c in error_class for c in medium):
        return 0.5
    if any(c in error_class for c in low):
        return 0.3
    return 0.5  # Unknown → medium


def recency_weight(last_seen: str) -> float:
    """More recent errors score higher. Returns 0.0–1.0."""
    if not last_seen:
        return 0.5
    try:
        ts = float(last_seen) / 1000  # NR timestamps are epoch millis
        age_hours = (time.time() - ts) / 3600
        # 0 hours ago → 1.0, 24 hours ago → 0.0
        return max(0.0, min(1.0, 1.0 - (age_hours / 24)))
    except (ValueError, TypeError):
        return 0.5


def user_facing_weight(transaction: str) -> float:
    """User-facing controllers score higher than background jobs."""
    tx = transaction.lower()
    if "controller" in tx or "api/" in tx:
        return 1.0
    if "job" in tx or "worker" in tx or "sidekiq" in tx:
        return 0.3
    if "mailer" in tx or "notifier" in tx:
        return 0.5
    return 0.6  # Unknown → moderate


# ------------------------------------------------------------------
# Ignore list filtering
# ------------------------------------------------------------------


def load_ignore_patterns(path: str = "ignore.yml") -> list[dict]:
    """Load ignore patterns from YAML file."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("ignore", [])
    except FileNotFoundError:
        logger.debug(f"No ignore file at {path}, skipping filters")
        return []


def filter_errors(
    errors: list[ErrorGroup], ignore_patterns: list[dict]
) -> list[ErrorGroup]:
    """Remove errors matching ignore patterns."""
    if not ignore_patterns:
        return errors

    filtered: list[ErrorGroup] = []
    for error in errors:
        if _matches_ignore(error, ignore_patterns):
            logger.debug(f"Filtered: {error.error_class} in {error.transaction}")
        else:
            filtered.append(error)

    removed = len(errors) - len(filtered)
    if removed:
        logger.info(f"Filtered {removed} known/ignored errors")
    return filtered


def _matches_ignore(error: ErrorGroup, patterns: list[dict]) -> bool:
    """Check if an error matches any ignore pattern."""
    for p in patterns:
        pattern = p.get("pattern", "")
        match_type = p.get("match", "contains")
        target = f"{error.error_class} {error.message} {error.transaction}"

        if match_type == "contains" and pattern in target:
            return True
        if match_type == "exact" and pattern == error.error_class:
            return True
        if match_type == "prefix" and error.error_class.startswith(pattern):
            return True
    return False


def _escape_nrql(value: str) -> str:
    """Escape single quotes for NRQL string literals."""
    return value.replace("'", "\\'")
