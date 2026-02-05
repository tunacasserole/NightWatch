"""GitHub integration — code reading tools, issue/PR creation, duplicate detection."""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime

from github import Github, GithubException
from github.ContentFile import ContentFile
from github.Issue import Issue
from github.Repository import Repository

from nightwatch.config import get_settings
from nightwatch.models import (
    Analysis,
    CreatedIssueResult,
    CreatedPRResult,
    ErrorAnalysisResult,
    ErrorGroup,
)

logger = logging.getLogger("nightwatch.github")


class GitHubClient:
    """Sync GitHub client for code tools, issues, and PRs."""

    def __init__(self) -> None:
        settings = get_settings()
        self.github = Github(settings.github_token)
        self.repo_name = settings.github_repo
        self.base_branch = settings.github_base_branch
        self._repo: Repository | None = None

    @property
    def repo(self) -> Repository:
        if self._repo is None:
            self._repo = self.github.get_repo(self.repo_name)
        return self._repo

    # ------------------------------------------------------------------
    # Claude's tools (read_file, search_code, list_directory)
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> str | None:
        """Read a file from the repository."""
        try:
            content: ContentFile = self.repo.get_contents(path, ref=self.base_branch)
            if isinstance(content, list):
                return None
            return base64.b64decode(content.content).decode("utf-8")
        except GithubException as e:
            if e.status == 404:
                return None
            raise

    def search_code(self, query: str, file_extension: str | None = None) -> list[dict]:
        """Search for code patterns in the repository."""
        search_query = f"{query} repo:{self.repo_name}"
        if file_extension:
            search_query += f" extension:{file_extension}"

        try:
            results = self.github.search_code(search_query)
            return [
                {"path": item.path, "name": item.name, "html_url": item.html_url}
                for i, item in enumerate(results)
                if i < 20
            ]
        except GithubException as e:
            logger.error(f"Search error: {e}")
            return []

    def list_directory(self, path: str) -> list[dict]:
        """List files in a directory."""
        try:
            contents = self.repo.get_contents(path, ref=self.base_branch)
            if not isinstance(contents, list):
                contents = [contents]
            return [
                {"name": item.name, "path": item.path, "type": item.type}
                for item in contents
            ]
        except GithubException as e:
            if e.status == 404:
                return []
            raise

    # ------------------------------------------------------------------
    # Issue creation + duplicate detection
    # ------------------------------------------------------------------

    def find_existing_issue(self, error: ErrorGroup) -> Issue | None:
        """Find an existing open nightwatch issue for this error.

        Multi-level matching:
        1. Best: error_class + transaction in title/body
        2. Good: error_class only
        3. Fallback: transaction only
        """
        if not error.error_class and not error.transaction:
            return None

        try:
            open_issues = self.repo.get_issues(state="open", labels=["nightwatch"])
        except GithubException:
            return []

        error_class_lower = error.error_class.lower()
        transaction_lower = error.transaction.lower()

        # Extract action suffix (e.g. "products/show" from "Controller/products/show")
        action_name = None
        parts = error.transaction.split("/")
        if len(parts) >= 2:
            action_name = "/".join(parts[-2:]).lower()

        best = None
        good = None

        for issue in open_issues:
            body = issue.body or ""
            combined = f"{issue.title} {body}".lower()

            has_class = error_class_lower in combined
            has_tx = transaction_lower in combined
            has_action = action_name and action_name in combined

            if has_class and (has_tx or has_action):
                return issue  # Exact match
            if has_class and good is None:
                good = issue
            if (has_tx or has_action) and best is None:
                best = issue

        return good or best

    def get_open_nightwatch_issue_count(self) -> int:
        """Count open issues with the 'nightwatch' label."""
        try:
            return sum(1 for _ in self.repo.get_issues(state="open", labels=["nightwatch"]))
        except GithubException:
            return 0

    def create_issue(
        self,
        result: ErrorAnalysisResult,
        correlated_prs_section: str | None = None,
    ) -> CreatedIssueResult:
        """Create a GitHub issue for an analyzed error."""
        error = result.error
        analysis = result.analysis

        title = _build_issue_title(error, analysis)
        body = _build_issue_body(result, correlated_prs_section)
        labels = _build_labels(analysis)

        issue = self.repo.create_issue(title=title, body=body, labels=labels)
        logger.info(f"Created issue #{issue.number}: {title}")

        return CreatedIssueResult(
            error=error,
            analysis=analysis,
            action="created",
            issue_number=issue.number,
            issue_url=issue.html_url,
        )

    def add_occurrence_comment(
        self,
        issue: Issue,
        error: ErrorGroup,
        analysis: Analysis | None = None,
    ) -> CreatedIssueResult:
        """Add an occurrence comment to an existing issue."""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        body = f"""## New Occurrence

| Field | Value |
|-------|-------|
| **Time** | {timestamp} |
| **Error** | `{error.error_class}` |
| **Transaction** | `{error.transaction}` |
| **Occurrences** | {error.occurrences} |
"""
        if analysis and analysis.reasoning:
            body += f"\n### Quick Analysis\n{analysis.reasoning[:500]}\n"

        body += "\n---\n*Logged by NightWatch*"

        issue.create_comment(body)
        logger.info(f"Added occurrence comment to issue #{issue.number}")

        return CreatedIssueResult(
            error=error,
            analysis=analysis or Analysis(
                title="", reasoning="", root_cause="", has_fix=False, confidence="low"
            ),
            action="commented",
            issue_number=issue.number,
            issue_url=issue.html_url,
        )

    # ------------------------------------------------------------------
    # PR creation
    # ------------------------------------------------------------------

    def create_pull_request(
        self,
        result: ErrorAnalysisResult,
        issue_number: int,
    ) -> CreatedPRResult:
        """Create a draft PR with the proposed fix."""
        error = result.error
        analysis = result.analysis

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        safe_class = error.error_class.split("::")[-1][:30].lower().replace(" ", "-")
        branch_name = f"nightwatch/fix-{safe_class}-{timestamp}"

        # Create branch
        base_ref = self.repo.get_branch(self.base_branch)
        self.repo.create_git_ref(
            ref=f"refs/heads/{branch_name}", sha=base_ref.commit.sha
        )

        # Commit file changes
        files_changed = 0
        for change in analysis.file_changes:
            if change.action in ("create", "modify") and change.content:
                try:
                    existing = self.repo.get_contents(change.path, ref=branch_name)
                    sha = existing.sha if not isinstance(existing, list) else None
                except GithubException:
                    sha = None

                if sha:
                    self.repo.update_file(
                        path=change.path,
                        message=f"fix: {analysis.title}",
                        content=change.content,
                        sha=sha,
                        branch=branch_name,
                    )
                else:
                    self.repo.create_file(
                        path=change.path,
                        message=f"fix: {analysis.title}",
                        content=change.content,
                        branch=branch_name,
                    )
                files_changed += 1

        # Create draft PR
        changes_list = "\n".join(
            f"- `{c.path}`: {c.action}" for c in analysis.file_changes
        )
        pr_body = f"""## Fixes #{issue_number}

### Analysis
{analysis.reasoning[:2000]}

### Root Cause
{analysis.root_cause}

### Changes
{changes_list}

### Confidence: **{analysis.confidence.upper()}**

---
*Draft PR created by NightWatch*"""

        pr = self.repo.create_pull(
            title=f"fix: {analysis.title} [NO-JIRA]",
            body=pr_body,
            head=branch_name,
            base=self.base_branch,
            draft=True,
        )

        logger.info(f"Created draft PR #{pr.number}")

        return CreatedPRResult(
            issue_number=issue_number,
            pr_number=pr.number,
            pr_url=pr.html_url,
            branch_name=branch_name,
            files_changed=files_changed,
        )


# ---------------------------------------------------------------------------
# Helpers (module-level)
# ---------------------------------------------------------------------------


def _build_issue_title(error: ErrorGroup, analysis: Analysis) -> str:
    """Build a descriptive issue title."""
    # Short transaction: "products/show" from "Controller/products/show"
    short_tx = None
    if error.transaction:
        parts = error.transaction.replace("Controller/", "").split("/")
        short_tx = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]

    short_msg = None
    if error.message:
        first_line = error.message.split("\n")[0].strip()
        short_msg = first_line[:57] + "..." if len(first_line) > 60 else first_line

    if error.error_class and short_tx and short_msg:
        return f"{error.error_class} in {short_tx}: {short_msg}"
    if error.error_class and short_tx:
        return f"{error.error_class} in {short_tx}"
    if error.error_class:
        return error.error_class
    if analysis.title and analysis.title != "Unknown Error":
        return analysis.title
    return "Production Error"


def _build_labels(analysis: Analysis) -> list[str]:
    """Build GitHub labels for an issue."""
    labels = ["nightwatch"]
    if analysis.has_fix:
        labels.append("has-fix")
    else:
        labels.append("needs-investigation")
    labels.append(f"confidence:{analysis.confidence}")
    return labels


def _build_issue_body(
    result: ErrorAnalysisResult,
    correlated_prs_section: str | None = None,
) -> str:
    """Build the GitHub issue body markdown."""
    error = result.error
    analysis = result.analysis

    sections: list[str] = []

    # Error details
    sections.append(f"""## Error Details

- **Exception**: `{error.error_class}`
- **Transaction**: `{error.transaction}`
- **Occurrences**: {error.occurrences}
- **Message**: {error.message[:500]}
- **Impact Score**: {error.score:.2f}""")

    # Correlated PRs
    if correlated_prs_section:
        sections.append(correlated_prs_section)

    # Analysis
    if analysis.reasoning:
        sections.append(f"## Analysis\n\n{analysis.reasoning[:3000]}")

    # Root cause
    if analysis.root_cause:
        sections.append(f"## Root Cause\n\n{analysis.root_cause}")

    # Proposed fix
    if analysis.has_fix and analysis.file_changes:
        changes_list = "\n".join(
            f"- `{c.path}`: {c.action} — {c.description}" for c in analysis.file_changes
        )
        sections.append(f"## Proposed Fix\n\n{changes_list}")

    # Next steps
    if analysis.suggested_next_steps:
        steps = "\n".join(f"- [ ] {s}" for s in analysis.suggested_next_steps)
        sections.append(f"## Next Steps\n\n{steps}")

    sections.append("---\n*Created by [NightWatch](https://github.com/g2crowd/NightWatch)*")

    return "\n\n".join(sections)
