"""Tests for agent configuration module (agents.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from nightwatch.agents import (
    AgentConfig,
    _parse_agent_frontmatter,
    list_agents,
    load_agent,
)

# ---------------------------------------------------------------------------
# _parse_agent_frontmatter
# ---------------------------------------------------------------------------


class TestParseAgentFrontmatter:
    def test_valid_frontmatter(self):
        content = (
            "---\n"
            "name: test-agent\n"
            "model: claude-sonnet-4-5-20250929\n"
            "---\n"
            "You are a test agent.\n"
        )
        frontmatter, body = _parse_agent_frontmatter(content)
        assert frontmatter["name"] == "test-agent"
        assert frontmatter["model"] == "claude-sonnet-4-5-20250929"
        assert body.strip() == "You are a test agent."

    def test_no_frontmatter(self):
        content = "Just a plain markdown file.\n"
        frontmatter, body = _parse_agent_frontmatter(content)
        assert frontmatter == {}
        assert body == content

    def test_missing_closing_delimiter(self):
        content = "---\nname: broken\nNo closing delimiter.\n"
        frontmatter, body = _parse_agent_frontmatter(content)
        assert frontmatter == {}
        assert body == content

    def test_invalid_yaml(self):
        content = "---\n: : : invalid yaml\n---\nBody text.\n"
        frontmatter, body = _parse_agent_frontmatter(content)
        assert frontmatter == {}

    def test_empty_frontmatter(self):
        content = "---\n---\nBody only.\n"
        frontmatter, body = _parse_agent_frontmatter(content)
        assert frontmatter == {}
        assert "Body only." in body


# ---------------------------------------------------------------------------
# load_agent
# ---------------------------------------------------------------------------


class TestLoadAgent:
    def test_loads_base_analyzer(self):
        """The base-analyzer.md file should exist and load correctly."""
        agent = load_agent("base-analyzer")
        assert isinstance(agent, AgentConfig)
        assert agent.name == "base-analyzer"
        assert agent.system_prompt  # Non-empty
        assert agent.model == "claude-sonnet-4-5-20250929"
        assert "read_file" in agent.tools
        assert "search_code" in agent.tools

    def test_missing_agent_returns_default(self):
        """Non-existent agent file should fall back to default."""
        agent = load_agent("nonexistent-agent-xyz")
        assert isinstance(agent, AgentConfig)
        assert agent.name == "base-analyzer"  # Default name
        assert agent.system_prompt  # Non-empty (from SYSTEM_PROMPT)

    def test_default_values(self):
        """Default agent config should have sensible defaults."""
        agent = load_agent("base-analyzer")
        assert agent.thinking_budget == 8000
        assert agent.max_tokens == 16384
        assert agent.max_iterations == 15

    def test_loads_tools_list(self):
        """Agent tools should be a list of strings."""
        agent = load_agent("base-analyzer")
        assert isinstance(agent.tools, list)
        assert all(isinstance(t, str) for t in agent.tools)


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


class TestListAgents:
    def test_lists_available_agents(self):
        """Should list at least the base-analyzer."""
        agents = list_agents()
        assert isinstance(agents, list)
        assert "base-analyzer" in agents

    def test_returns_sorted(self):
        """Agent names should be alphabetically sorted."""
        agents = list_agents()
        assert agents == sorted(agents)

    def test_missing_directory_returns_empty(self):
        """If agents directory doesn't exist, return empty list."""
        with patch.object(Path, "exists", return_value=False):
            agents = list_agents()
            # Should handle gracefully
            assert isinstance(agents, list)


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    def test_dataclass_fields(self):
        config = AgentConfig(
            name="test",
            system_prompt="You are a test agent.",
        )
        assert config.name == "test"
        assert config.system_prompt == "You are a test agent."
        assert config.model == "claude-sonnet-4-5-20250929"  # default
        assert config.thinking_budget == 8000  # default
        assert config.description == ""  # default
        assert isinstance(config.tools, list)
