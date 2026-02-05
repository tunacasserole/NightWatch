"""Tests for error ranking algorithm."""

import time

from nightwatch.models import ErrorGroup
from nightwatch.newrelic import (
    filter_errors,
    rank_errors,
    recency_weight,
    severity_weight,
    user_facing_weight,
)


def _make_error(**kwargs) -> ErrorGroup:
    defaults = {
        "error_class": "RuntimeError",
        "transaction": "Controller/test/index",
        "message": "test error",
        "occurrences": 10,
        "last_seen": str(int(time.time() * 1000)),
    }
    defaults.update(kwargs)
    return ErrorGroup(**defaults)


class TestSeverityWeight:
    def test_critical(self):
        assert severity_weight("SystemStackError") == 1.0
        assert severity_weight("NoMemoryError") == 1.0

    def test_high(self):
        assert severity_weight("NoMethodError") == 0.7
        assert severity_weight("ActiveRecord::RecordNotFound") == 0.7

    def test_medium(self):
        assert severity_weight("ArgumentError") == 0.5

    def test_low(self):
        assert severity_weight("NotAuthorizedError") == 0.3
        assert severity_weight("CanCan::AccessDenied") == 0.3

    def test_unknown(self):
        assert severity_weight("SomethingWeird") == 0.5


class TestRecencyWeight:
    def test_very_recent(self):
        # Just happened
        ts = str(int(time.time() * 1000))
        w = recency_weight(ts)
        assert w > 0.9

    def test_old(self):
        # 24 hours ago
        ts = str(int((time.time() - 86400) * 1000))
        w = recency_weight(ts)
        assert w < 0.1

    def test_empty(self):
        assert recency_weight("") == 0.5

    def test_invalid(self):
        assert recency_weight("not-a-number") == 0.5


class TestUserFacingWeight:
    def test_controller(self):
        assert user_facing_weight("Controller/products/show") == 1.0

    def test_api(self):
        assert user_facing_weight("api/v3/reviews") == 1.0

    def test_job(self):
        assert user_facing_weight("SomeJob#perform") == 0.3

    def test_worker(self):
        assert user_facing_weight("Sidekiq/MyWorker") == 0.3

    def test_unknown(self):
        assert user_facing_weight("SomeService") == 0.6


class TestRankErrors:
    def test_higher_occurrences_rank_higher(self):
        e1 = _make_error(occurrences=100)
        e2 = _make_error(occurrences=10)
        ranked = rank_errors([e2, e1])
        assert ranked[0].occurrences == 100

    def test_critical_ranks_higher(self):
        e1 = _make_error(error_class="SystemStackError", occurrences=5)
        e2 = _make_error(error_class="NotAuthorizedError", occurrences=5)
        ranked = rank_errors([e2, e1])
        assert ranked[0].error_class == "SystemStackError"


class TestFilterErrors:
    def test_filter_by_contains(self):
        errors = [
            _make_error(error_class="Net::ReadTimeout", message="timeout"),
            _make_error(error_class="NoMethodError", message="nil"),
        ]
        patterns = [{"pattern": "Net::ReadTimeout", "match": "contains"}]
        filtered = filter_errors(errors, patterns)
        assert len(filtered) == 1
        assert filtered[0].error_class == "NoMethodError"

    def test_no_patterns(self):
        errors = [_make_error(), _make_error()]
        assert len(filter_errors(errors, [])) == 2

    def test_filter_by_exact(self):
        errors = [
            _make_error(error_class="Rack::Timeout"),
            _make_error(error_class="NoMethodError"),
        ]
        patterns = [{"pattern": "Rack::Timeout", "match": "exact"}]
        filtered = filter_errors(errors, patterns)
        assert len(filtered) == 1
