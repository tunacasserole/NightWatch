"""Tests for nightwatch.knowledge — compound engineering knowledge base."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nightwatch.knowledge import (
    _extract_tags,
    _match_score,
    _parse_frontmatter,
    _render_frontmatter,
    _slugify,
    compound_result,
    rebuild_index,
    search_prior_knowledge,
    update_result_metadata,
)
from nightwatch.models import (
    Analysis,
    ErrorAnalysisResult,
    ErrorGroup,
    FileChange,
    TraceData,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_knowledge_dir(tmp_path: Path) -> Path:
    """Create a temporary knowledge directory structure."""
    errors_dir = tmp_path / "errors"
    patterns_dir = tmp_path / "patterns"
    errors_dir.mkdir()
    patterns_dir.mkdir()
    return tmp_path


@pytest.fixture
def sample_error() -> ErrorGroup:
    return ErrorGroup(
        error_class="ActiveRecord::RecordNotFound",
        transaction="Controller/orders/update",
        message="Couldn't find Order with 'id'=12345",
        occurrences=87,
        last_seen="2026-02-05T06:00:00Z",
    )


@pytest.fixture
def sample_analysis_result(sample_error: ErrorGroup) -> ErrorAnalysisResult:
    return ErrorAnalysisResult(
        error=sample_error,
        analysis=Analysis(
            title="RecordNotFound in orders/update",
            reasoning="Race condition between order deletion and status update.",
            root_cause="Race condition between order deletion and status update",
            has_fix=True,
            confidence="high",
            file_changes=[
                FileChange(
                    path="app/controllers/orders_controller.rb",
                    action="modify",
                    description="Replace find with find_by",
                )
            ],
            suggested_next_steps=["Add nil guard on Order.find"],
        ),
        traces=TraceData(),
        iterations=6,
        tokens_used=12340,
    )


@pytest.fixture
def fixture_knowledge_doc() -> str:
    """A sample knowledge document with frontmatter."""
    return """---
error_class: "ActiveRecord::RecordNotFound"
transaction: Controller/orders/update
message: Couldn't find Order
occurrences: 50
root_cause: Race condition in order processing
fix_confidence: high
has_fix: true
issue_number: null
pr_number: null
tags:
  - activerecord
  - orders
  - recordnotfound
  - update
first_detected: '2026-02-01'
run_id: '2026-02-01T06:00:00+00:00'
iterations_used: 5
tokens_used: 11000
---

# RecordNotFound in orders/update

## Root Cause

Race condition in order processing

## Analysis

The order is being deleted by a background job while the controller tries to update it.
"""


# ---------------------------------------------------------------------------
# Tag extraction tests
# ---------------------------------------------------------------------------


def test_extract_tags_from_error_class():
    error = ErrorGroup(
        error_class="ActiveRecord::RecordNotFound",
        transaction="Controller/products/show",
        message="",
        occurrences=1,
        last_seen="",
    )
    tags = _extract_tags(error)
    assert "activerecord" in tags
    assert "recordnotfound" in tags


def test_extract_tags_from_transaction():
    error = ErrorGroup(
        error_class="NoMethodError",
        transaction="Controller/products/show",
        message="",
        occurrences=1,
        last_seen="",
    )
    tags = _extract_tags(error)
    assert "products" in tags
    assert "show" in tags
    # "controller" is a noise word, should be filtered
    assert "controller" not in tags


# ---------------------------------------------------------------------------
# Match scoring tests
# ---------------------------------------------------------------------------


def test_match_score_exact_class(sample_error: ErrorGroup):
    solution = {
        "error_class": "ActiveRecord::RecordNotFound",
        "transaction": "Controller/other/action",
        "tags": [],
    }
    score = _match_score(sample_error, solution)
    assert score >= 0.5


def test_match_score_exact_transaction(sample_error: ErrorGroup):
    solution = {
        "error_class": "DifferentError",
        "transaction": "Controller/orders/update",
        "tags": [],
    }
    score = _match_score(sample_error, solution)
    assert score >= 0.3


def test_match_score_no_match():
    error = ErrorGroup(
        error_class="UniqueError",
        transaction="Controller/unique/action",
        message="",
        occurrences=1,
        last_seen="",
    )
    solution = {
        "error_class": "CompletelyDifferent",
        "transaction": "Controller/other/thing",
        "tags": ["unrelated"],
    }
    score = _match_score(error, solution)
    assert score == 0.0


# ---------------------------------------------------------------------------
# Frontmatter parsing tests
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid():
    content = "---\nkey: value\ntitle: Test\n---\n\nBody text here."
    fm, body = _parse_frontmatter(content)
    assert fm["key"] == "value"
    assert fm["title"] == "Test"
    assert "Body text here." in body


def test_parse_frontmatter_no_frontmatter():
    content = "Just plain text without frontmatter."
    fm, body = _parse_frontmatter(content)
    assert fm == {}
    assert body == content


def test_render_frontmatter():
    data = {"key": "value", "number": 42}
    result = _render_frontmatter(data)
    assert result.startswith("---\n")
    assert "key: value" in result
    assert result.endswith("---\n\n")


# ---------------------------------------------------------------------------
# Slugify tests
# ---------------------------------------------------------------------------


def test_slugify():
    assert _slugify("ActiveRecord::RecordNotFound") == "activerecord-recordnotfound"


def test_slugify_truncation():
    long_text = "A" * 100
    result = _slugify(long_text)
    assert len(result) <= 60


# ---------------------------------------------------------------------------
# Compound result tests
# ---------------------------------------------------------------------------


def test_compound_result_creates_file(
    sample_analysis_result: ErrorAnalysisResult,
    tmp_knowledge_dir: Path,
):
    with patch("nightwatch.knowledge.get_settings") as mock_settings:
        mock_settings.return_value.nightwatch_knowledge_dir = str(tmp_knowledge_dir)

        doc_path = compound_result(sample_analysis_result, knowledge_dir=str(tmp_knowledge_dir))

        assert doc_path.exists()
        content = doc_path.read_text()
        fm, body = _parse_frontmatter(content)

        assert fm["error_class"] == "ActiveRecord::RecordNotFound"
        assert fm["transaction"] == "Controller/orders/update"
        assert fm["has_fix"] is True
        assert fm["fix_confidence"] == "high"
        assert "Root Cause" in body
        assert "Race condition" in body


# ---------------------------------------------------------------------------
# Index rebuild tests
# ---------------------------------------------------------------------------


def test_rebuild_index(tmp_knowledge_dir: Path, fixture_knowledge_doc: str):
    # Create 3 fixture docs
    errors_dir = tmp_knowledge_dir / "errors"
    for i in range(3):
        (errors_dir / f"2026-02-0{i+1}_test-error-{i}.md").write_text(
            fixture_knowledge_doc
        )

    with patch("nightwatch.knowledge.get_settings") as mock_settings:
        mock_settings.return_value.nightwatch_knowledge_dir = str(tmp_knowledge_dir)

        rebuild_index(knowledge_dir=str(tmp_knowledge_dir))

    index_path = tmp_knowledge_dir / "index.yml"
    assert index_path.exists()

    index = yaml.safe_load(index_path.read_text())
    assert index["total_solutions"] == 3
    assert len(index["solutions"]) == 3


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


def test_search_prior_knowledge_finds_match(
    sample_error: ErrorGroup,
    tmp_knowledge_dir: Path,
    fixture_knowledge_doc: str,
):
    # Create a matching doc and index
    errors_dir = tmp_knowledge_dir / "errors"
    (errors_dir / "2026-02-01_activerecord-recordnotfound.md").write_text(
        fixture_knowledge_doc
    )

    with patch("nightwatch.knowledge.get_settings") as mock_settings:
        mock_settings.return_value.nightwatch_knowledge_dir = str(tmp_knowledge_dir)

        rebuild_index(knowledge_dir=str(tmp_knowledge_dir))
        results = search_prior_knowledge(sample_error, knowledge_dir=str(tmp_knowledge_dir))

    assert len(results) >= 1
    assert results[0].error_class == "ActiveRecord::RecordNotFound"
    assert results[0].match_score > 0.0


def test_search_prior_knowledge_no_match(tmp_knowledge_dir: Path, fixture_knowledge_doc: str):
    # Create docs but search with unrelated error
    errors_dir = tmp_knowledge_dir / "errors"
    (errors_dir / "2026-02-01_test.md").write_text(fixture_knowledge_doc)

    with patch("nightwatch.knowledge.get_settings") as mock_settings:
        mock_settings.return_value.nightwatch_knowledge_dir = str(tmp_knowledge_dir)

        rebuild_index(knowledge_dir=str(tmp_knowledge_dir))

        unrelated_error = ErrorGroup(
            error_class="CompletlyUnique::NeverSeen",
            transaction="Worker/unique/job",
            message="Something totally different",
            occurrences=1,
            last_seen="",
        )
        results = search_prior_knowledge(unrelated_error, knowledge_dir=str(tmp_knowledge_dir))

    assert len(results) == 0


# ---------------------------------------------------------------------------
# Metadata update tests
# ---------------------------------------------------------------------------


def test_update_result_metadata(
    sample_analysis_result: ErrorAnalysisResult,
    tmp_knowledge_dir: Path,
):
    with patch("nightwatch.knowledge.get_settings") as mock_settings:
        mock_settings.return_value.nightwatch_knowledge_dir = str(tmp_knowledge_dir)

        # Create a doc first
        doc_path = compound_result(sample_analysis_result, knowledge_dir=str(tmp_knowledge_dir))

        # Update with issue number
        updated = update_result_metadata(
            error_class="ActiveRecord::RecordNotFound",
            transaction="Controller/orders/update",
            issue_number=42,
            knowledge_dir=str(tmp_knowledge_dir),
        )

        assert updated is True

        # Verify the frontmatter was updated
        fm, _ = _parse_frontmatter(doc_path.read_text())
        assert fm["issue_number"] == 42
