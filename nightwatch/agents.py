"""Agent configuration — load analysis agents from Markdown files.

Agents are defined as Markdown files with YAML frontmatter in
nightwatch/agents/. The body of the file becomes the system prompt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("nightwatch.agents")

AGENTS_DIR = Path(__file__).parent / "agents"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AgentConfig:
    """Configuration for a NightWatch analysis agent."""

    name: str
    system_prompt: str
    model: str = "claude-sonnet-4-5-20250929"
    thinking_budget: int = 8000
    max_tokens: int = 16384
    max_iterations: int = 15
    tools: list[str] = field(
        default_factory=lambda: [
            "read_file",
            "search_code",
            "list_directory",
            "get_error_traces",
        ]
    )
    description: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_agent(name: str = "base-analyzer") -> AgentConfig:
    """Load agent from nightwatch/agents/{name}.md.

    File format: YAML frontmatter + Markdown body (= system prompt).
    Falls back to existing SYSTEM_PROMPT from prompts.py if file not found.
    """
    agent_path = AGENTS_DIR / f"{name}.md"

    if not agent_path.exists():
        logger.debug(f"Agent file not found: {agent_path}, using default SYSTEM_PROMPT")
        return _default_agent()

    try:
        content = agent_path.read_text()
        frontmatter, body = _parse_agent_frontmatter(content)

        # Validate name matches filename
        fm_name = frontmatter.get("name", name)
        if fm_name != name:
            logger.warning(
                f"Agent file name mismatch: file={name}, frontmatter.name={fm_name}"
            )

        return AgentConfig(
            name=fm_name,
            system_prompt=body.strip(),
            model=frontmatter.get("model", "claude-sonnet-4-5-20250929"),
            thinking_budget=frontmatter.get("thinking_budget", 8000),
            max_tokens=frontmatter.get("max_tokens", 16384),
            max_iterations=frontmatter.get("max_iterations", 15),
            tools=frontmatter.get(
                "tools",
                ["read_file", "search_code", "list_directory", "get_error_traces"],
            ),
            description=frontmatter.get("description", ""),
        )
    except Exception as e:
        logger.warning(f"Failed to load agent {name}: {e}, using default")
        return _default_agent()


def list_agents() -> list[str]:
    """List available agent names from agents/ directory."""
    if not AGENTS_DIR.exists():
        return []
    return sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _default_agent() -> AgentConfig:
    """Return AgentConfig with SYSTEM_PROMPT from prompts.py."""
    from nightwatch.prompts import SYSTEM_PROMPT

    return AgentConfig(
        name="base-analyzer",
        system_prompt=SYSTEM_PROMPT,
        description="Default NightWatch error analysis agent",
    )


def _parse_agent_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from Markdown body."""
    if not content.startswith("---"):
        return {}, content

    end = content.find("---", 3)
    if end == -1:
        return {}, content

    yaml_str = content[3:end].strip()
    body = content[end + 3 :].lstrip("\n")

    try:
        data = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError:
        return {}, content

    return data, body
