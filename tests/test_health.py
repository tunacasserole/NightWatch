"""Tests for NightWatch self-health report."""

from nightwatch.health import HealthReport


def test_health_report_init():
    h = HealthReport()
    assert h.errors_attempted == 0
    assert h.errors_analyzed == 0


def test_record_analysis_success():
    h = HealthReport()
    h.record_analysis(success=True, tokens_used=5000)
    assert h.errors_attempted == 1
    assert h.errors_analyzed == 1
    assert h.total_tokens == 5000


def test_record_analysis_failure():
    h = HealthReport()
    h.record_analysis(success=False, error_msg="API timeout")
    assert h.errors_attempted == 1
    assert h.errors_failed == 1
    assert len(h.api_errors) == 1


def test_estimate_cost():
    h = HealthReport()
    h.total_tokens = 100000
    cost = h.estimate_cost()
    assert cost > 0
    assert cost < 1.0


def test_generate_report():
    h = HealthReport()
    h.record_analysis(success=True, tokens_used=10000)
    h.record_analysis(success=True, tokens_used=8000)
    h.record_analysis(success=False, error_msg="timeout")
    report = h.generate()
    assert report["analysis"]["attempted"] == 3
    assert report["analysis"]["succeeded"] == 2
    assert report["analysis"]["failed"] == 1
    assert report["resources"]["total_tokens"] == 18000


def test_health_status_healthy():
    h = HealthReport()
    h.record_analysis(success=True, tokens_used=5000)
    report = h.generate()
    assert report["health"]["status"] == "healthy"


def test_health_status_unhealthy():
    h = HealthReport()
    h.record_analysis(success=False, error_msg="err1")
    h.record_analysis(success=False, error_msg="err2")
    report = h.generate()
    assert report["health"]["status"] == "unhealthy"


def test_slack_blocks():
    h = HealthReport()
    h.record_analysis(success=True, tokens_used=5000)
    blocks = h.format_slack_blocks()
    assert len(blocks) >= 2
    assert blocks[0]["type"] == "section"


def test_record_action():
    h = HealthReport()
    h.record_action("issue", True)
    h.record_action("pr", True)
    h.record_action("issue", False)
    assert h.issues_created == 1
    assert h.prs_created == 1
