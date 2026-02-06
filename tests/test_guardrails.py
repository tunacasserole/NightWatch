"""Tests for nightwatch.guardrails module."""

from __future__ import annotations

from nightwatch.guardrails import (
    _extract_module,
    _generate_sign,
    _slugify,
    generate_guardrails,
)


def test_slugify_basic():
    """_slugify converts text to URL-friendly slug."""
    assert _slugify("Hello World") == "hello-world"
    assert _slugify("Net::ReadTimeout in Controller/products/show") == (
        "netreadtimeout-in-controllerproductsshow"
    )


def test_slugify_truncates():
    """_slugify truncates to 50 chars."""
    long_text = "a" * 100
    result = _slugify(long_text)
    assert len(result) <= 50


def test_extract_module_with_hash():
    """_extract_module handles 'Module#method' format."""
    assert _extract_module("ProductsController#show") == "ProductsController"


def test_extract_module_with_slash():
    """_extract_module handles 'path/to/module' format."""
    assert _extract_module("Controller/products/show") == "show"


def test_extract_module_simple():
    """_extract_module returns simple names as-is."""
    assert _extract_module("MyService") == "MyService"


def test_generate_sign_format():
    """_generate_sign produces Ralph-compatible Sign format."""
    analysis = {
        "error_class": "Net::ReadTimeout",
        "transaction": "Controller/products/show",
        "root_cause": "External API call lacks timeout configuration",
        "date": "2026-02-05",
    }
    sign = _generate_sign(analysis, 1)
    assert "### Sign 1: Net::ReadTimeout in show" in sign
    assert "**Trigger**" in sign
    assert "**Instruction**" in sign
    assert "**Added after**" in sign
    assert "**Example**" in sign
    assert "Controller/products/show" in sign


def test_generate_guardrails_high_confidence():
    """Only high-confidence analyses (≥0.7) produce signs."""
    report = {
        "errors_analyzed": [
            {
                "error_class": "Net::ReadTimeout",
                "transaction": "Controller/products/show",
                "root_cause": "Missing timeout",
                "confidence": 0.9,
                "date": "2026-02-05",
            },
            {
                "error_class": "NoMethodError",
                "transaction": "Controller/users/index",
                "root_cause": "Nil reference",
                "confidence": 0.3,
                "date": "2026-02-05",
            },
        ],
    }
    content = generate_guardrails(report)
    assert "Sign 1: Net::ReadTimeout" in content
    assert "NoMethodError" not in content  # Below threshold


def test_generate_guardrails_includes_patterns():
    """Patterns with high confidence also produce signs."""
    report = {
        "errors_analyzed": [],
        "patterns_detected": [
            {
                "error_class": "TimeoutError",
                "confidence": 0.8,
                "count": 5,
                "suggested_action": "Add circuit breaker",
            }
        ],
    }
    content = generate_guardrails(report)
    assert "Recurring TimeoutError" in content
    assert "5 times" in content


def test_generate_guardrails_empty_run():
    """Empty run produces valid guardrails with no signs."""
    report = {"errors_analyzed": []}
    content = generate_guardrails(report)
    assert "NightWatch Guardrails" in content
    assert "No high-confidence signs" in content


def test_generate_guardrails_writes_file(tmp_path):
    """generate_guardrails writes to output_path when specified."""
    output = tmp_path / "guardrails.md"
    report = {
        "errors_analyzed": [
            {
                "error_class": "TestError",
                "transaction": "test",
                "root_cause": "test cause",
                "confidence": 0.9,
            }
        ],
    }
    content = generate_guardrails(report, output_path=str(output))
    assert output.exists()
    assert output.read_text() == content


def test_generate_guardrails_creates_parent_dirs(tmp_path):
    """generate_guardrails creates parent directories if needed."""
    output = tmp_path / "subdir" / "deep" / "guardrails.md"
    report = {"errors_analyzed": []}
    generate_guardrails(report, output_path=str(output))
    assert output.exists()


def test_generate_guardrails_numbering():
    """Signs are numbered sequentially across errors and patterns."""
    report = {
        "errors_analyzed": [
            {
                "error_class": "ErrorA",
                "transaction": "tx_a",
                "root_cause": "Cause A",
                "confidence": 0.9,
            },
            {
                "error_class": "ErrorB",
                "transaction": "tx_b",
                "root_cause": "Cause B",
                "confidence": 0.8,
            },
        ],
        "patterns_detected": [
            {
                "error_class": "ErrorC",
                "confidence": 0.9,
                "count": 7,
                "suggested_action": "Fix it",
            }
        ],
    }
    content = generate_guardrails(report)
    assert "Sign 1: ErrorA" in content
    assert "Sign 2: ErrorB" in content
    assert "Sign 3: Recurring ErrorC" in content
