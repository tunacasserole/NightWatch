"""Tests for nightwatch.observability — Opik config, wrapping, no-op when disabled."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic

import nightwatch.observability as obs
from nightwatch.config import get_settings


class TestConfigureOpik:
    def setup_method(self):
        # Reset the global flag before each test
        obs._opik_configured = False

    def test_disabled_when_no_api_key(self):
        result = obs.configure_opik()
        assert result is False
        assert obs._opik_configured is False

    def test_disabled_when_opik_enabled_false(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("OPIK_API_KEY", "test-key")
        monkeypatch.setenv("OPIK_ENABLED", "false")
        result = obs.configure_opik()
        assert result is False

    def test_enabled_with_api_key(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("OPIK_API_KEY", "test-key")
        monkeypatch.setenv("OPIK_WORKSPACE", "test-ws")
        with patch("opik.configure") as mock_configure:
            result = obs.configure_opik()
        assert result is True
        assert obs._opik_configured is True
        mock_configure.assert_called_once_with(
            api_key="test-key",
            workspace="test-ws",
            use_local=False,
        )

    def test_handles_configure_error(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("OPIK_API_KEY", "test-key")
        with patch("opik.configure", side_effect=RuntimeError("opik broken")):
            result = obs.configure_opik()
        # Should catch exception and return False
        assert result is False


class TestWrapAnthropicClient:
    def setup_method(self):
        obs._opik_configured = False

    def test_returns_unchanged_when_not_configured(self):
        client = MagicMock(spec=anthropic.Anthropic)
        result = obs.wrap_anthropic_client(client)
        assert result is client

    def test_wraps_when_configured(self, monkeypatch):
        obs._opik_configured = True
        client = MagicMock(spec=anthropic.Anthropic)
        mock_tracked = MagicMock()
        with patch("opik.integrations.anthropic.track_anthropic", return_value=mock_tracked):
            result = obs.wrap_anthropic_client(client)
        assert result is mock_tracked

    def test_returns_original_on_wrap_error(self, monkeypatch):
        obs._opik_configured = True
        client = MagicMock(spec=anthropic.Anthropic)
        with patch(
            "opik.integrations.anthropic.track_anthropic",
            side_effect=RuntimeError("wrap failed"),
        ):
            result = obs.wrap_anthropic_client(client)
        assert result is client


class TestTrackFunction:
    def setup_method(self):
        obs._opik_configured = False

    def test_noop_when_not_configured(self):
        decorator = obs.track_function("my_func")

        @decorator
        def my_func():
            return 42

        assert my_func() == 42

    def test_wraps_when_configured(self):
        obs._opik_configured = True
        mock_track = MagicMock(return_value=lambda f: f)
        with patch("opik.track", mock_track):
            decorator = obs.track_function("my_func", tags=["claude"])
        assert callable(decorator)
        mock_track.assert_called_once_with(name="my_func", tags=["claude"])

    def test_noop_on_import_error(self):
        obs._opik_configured = True
        with patch("builtins.__import__", side_effect=ImportError("no opik")):
            decorator = obs.track_function("my_func")

        @decorator
        def my_func():
            return 99

        assert my_func() == 99
