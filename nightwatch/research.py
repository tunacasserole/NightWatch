"""Pre-analysis research — gather context before Claude's main loop.

Infers likely relevant files from transaction names and stack traces,
pre-fetches source code, and collects correlated PRs. Reduces average
Claude iterations from ~8 to ~5 per error.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from nightwatch.models import CorrelatedPR, ErrorGroup, PriorAnalysis, TraceData

logger = logging.getLogger("nightwatch.research")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ResearchContext:
    """Pre-gathered context injected into analysis prompt."""

    prior_analyses: list[PriorAnalysis] = field(default_factory=list)
    likely_files: list[str] = field(default_factory=list)
    correlated_prs: list[CorrelatedPR] = field(default_factory=list)
    file_previews: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def research_error(
    error: ErrorGroup,
    traces: TraceData,
    github_client: Any,
    correlated_prs: list[CorrelatedPR] | None = None,
    prior_analyses: list[PriorAnalysis] | None = None,
) -> ResearchContext:
    """Gather all available context before the main analysis loop.

    Steps:
    1. Collect prior analyses (passed in from Phase 1)
    2. Infer likely relevant files from transaction name + stack traces
    3. Pre-fetch file previews (first 100 lines of each likely file)
    4. Collect correlated PRs (passed in from existing correlation system)
    """
    # Step 1: Prior analyses
    priors = prior_analyses or []

    # Step 2: Infer likely files
    files_from_tx = _infer_files_from_transaction(error.transaction)
    files_from_traces = _infer_files_from_traces(traces)

    # Deduplicate, preserve order
    seen: set[str] = set()
    likely_files: list[str] = []
    for f in files_from_tx + files_from_traces:
        if f not in seen:
            seen.add(f)
            likely_files.append(f)

    # Step 3: Pre-fetch file previews
    file_previews = _pre_fetch_files(likely_files, github_client)

    # Step 4: Correlated PRs
    prs = correlated_prs or []

    return ResearchContext(
        prior_analyses=priors,
        likely_files=likely_files,
        correlated_prs=prs,
        file_previews=file_previews,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _infer_files_from_transaction(transaction: str) -> list[str]:
    """Extract file paths from Rails transaction name.

    "Controller/products/show" → [
        "app/controllers/products_controller.rb",
        "app/models/product.rb",
    ]
    "Controller/api/v3/reviews/create" → [
        "app/controllers/api/v3/reviews_controller.rb",
        "app/models/review.rb",
    ]
    "Sidekiq/ImportJob" → [
        "app/jobs/import_job.rb",
    ]
    """
    files: list[str] = []
    parts = transaction.split("/")

    if not parts:
        return files

    prefix = parts[0]

    if prefix == "Controller" and len(parts) >= 3:
        # Controller/namespace/.../resource/action
        # Resource is the second-to-last part
        namespace_parts = parts[1:-1]  # everything between Controller and action
        resource = namespace_parts[-1] if namespace_parts else ""
        namespace_path = "/".join(namespace_parts[:-1]) if len(namespace_parts) > 1 else ""

        if resource:
            if namespace_path:
                files.append(f"app/controllers/{namespace_path}/{resource}_controller.rb")
            else:
                files.append(f"app/controllers/{resource}_controller.rb")

            # Infer model (singularize: remove trailing 's')
            model_name = resource.rstrip("s")
            files.append(f"app/models/{model_name}.rb")

    elif prefix == "Sidekiq" and len(parts) >= 2:
        job_name = parts[1]
        # Convert CamelCase to snake_case
        snake = _camel_to_snake(job_name)
        files.append(f"app/jobs/{snake}.rb")

    elif prefix in ("OtherTransaction", "Rake"):
        # These don't map to meaningful files
        pass

    return files


def _infer_files_from_traces(traces: TraceData) -> list[str]:
    """Extract file paths from stack trace frames.

    Looks at error_traces for stack_trace strings.
    Extracts app-relative paths (ignores gem paths).
    Returns top 5 unique paths.
    """
    files: list[str] = []
    seen: set[str] = set()

    # App path pattern: paths starting with app/ or lib/
    app_path_re = re.compile(r"(app/[\w/]+\.rb|lib/[\w/]+\.rb)")

    for trace in traces.error_traces:
        stack = trace.get("error.stack_trace", trace.get("stackTrace", ""))
        if not isinstance(stack, str):
            continue

        for match in app_path_re.finditer(stack):
            path = match.group(1)
            if path not in seen:
                seen.add(path)
                files.append(path)

            if len(files) >= 5:
                return files

    return files


def _pre_fetch_files(
    files: list[str],
    github_client: Any,
    max_lines: int = 100,
    max_files: int = 5,
) -> dict[str, str]:
    """Read the first max_lines of each file from GitHub.

    Returns {path: content} dict. Silently skips files that don't exist.
    Caps at max_files to avoid excessive GitHub API calls.
    """
    result: dict[str, str] = {}

    for path in files[:max_files]:
        try:
            content = github_client.read_file(path)
            if content is not None:
                # Cap at max_lines
                lines = content.split("\n")
                if len(lines) > max_lines:
                    content = "\n".join(lines[:max_lines]) + "\n# ... truncated"
                result[path] = content
        except Exception as e:
            logger.debug(f"  Could not pre-fetch {path}: {e}")

    return result


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
