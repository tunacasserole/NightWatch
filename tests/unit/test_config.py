"""Tests for nightwatch.config — Settings defaults, overrides, validation, caching."""

from __future__ import annotations

import pytest

from nightwatch.config import get_settings


class TestSettingsDefaults:
    def test_required_fields_from_env(self):
        s = get_settings()
        assert s.anthropic_api_key == "test-anthropic-key"
        assert s.github_token == "test-github-token"
        assert s.github_repo == "test-org/test-repo"
        assert s.new_relic_api_key == "test-nr-key"
        assert s.new_relic_account_id == "12345"
        assert s.new_relic_app_name == "TestApp"
        assert s.slack_bot_token == "xoxb-test-token"
        assert s.slack_notify_user == "testuser"

    def test_optional_defaults(self):
        s = get_settings()
        assert s.nightwatch_max_errors == 5
        assert s.nightwatch_max_issues == 3
        assert s.nightwatch_since == "10 minutes"
        assert s.nightwatch_model == "claude-sonnet-4-5-20250929"
        assert s.nightwatch_max_iterations == 15
        assert s.nightwatch_dry_run is False
        assert s.nightwatch_max_open_issues == 10
        assert s.github_base_branch == "main"

    def test_multi_pass_defaults(self):
        s = get_settings()
        assert s.nightwatch_multi_pass_enabled is True
        assert s.nightwatch_max_passes == 2

    def test_run_context_defaults(self):
        s = get_settings()
        assert s.nightwatch_run_context_enabled is True
        assert s.nightwatch_run_context_max_chars == 1500

    def test_quality_gate_defaults(self):
        s = get_settings()
        assert s.nightwatch_quality_gate_enabled is True
        assert s.nightwatch_quality_gate_correction is True

    def test_compound_defaults(self):
        s = get_settings()
        assert s.nightwatch_compound_enabled is True
        assert s.nightwatch_knowledge_dir == "nightwatch/knowledge"

    def test_token_budget_defaults(self):
        s = get_settings()
        assert s.nightwatch_token_budget_per_error == 30000
        assert s.nightwatch_total_token_budget == 200000

    def test_opik_defaults(self):
        s = get_settings()
        assert s.opik_api_key is None
        assert s.opik_workspace is None
        assert s.opik_project_name == "nightwatch"
        assert s.opik_enabled is True

    def test_schedule_defaults(self):
        s = get_settings()
        assert s.nightwatch_schedule == "0 6 * * 1-5"
        assert s.nightwatch_schedule_timezone == "UTC"

    def test_workflow_defaults(self):
        s = get_settings()
        assert s.nightwatch_workflows == "errors"
        assert s.nightwatch_guardrails_output is None


class TestSettingsOverrides:
    def test_env_override_int(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_MAX_ERRORS", "20")
        s = get_settings()
        assert s.nightwatch_max_errors == 20

    def test_env_override_bool(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_DRY_RUN", "true")
        s = get_settings()
        assert s.nightwatch_dry_run is True

    def test_env_override_str(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_MODEL", "claude-opus-4-6")
        s = get_settings()
        assert s.nightwatch_model == "claude-opus-4-6"

    def test_env_override_opik(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("OPIK_API_KEY", "test-opik-key")
        monkeypatch.setenv("OPIK_WORKSPACE", "my-workspace")
        s = get_settings()
        assert s.opik_api_key == "test-opik-key"
        assert s.opik_workspace == "my-workspace"


class TestSettingsCaching:
    def test_singleton_returns_same_instance(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_returns_fresh_instance(self, monkeypatch):
        s1 = get_settings()
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_MAX_ERRORS", "99")
        s2 = get_settings()
        assert s1 is not s2
        assert s2.nightwatch_max_errors == 99


class TestSettingsValidation:
    def test_missing_required_field_raises(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(Exception):
            get_settings()

    def test_invalid_int_raises(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("NIGHTWATCH_MAX_ERRORS", "not-a-number")
        with pytest.raises(Exception):
            get_settings()
