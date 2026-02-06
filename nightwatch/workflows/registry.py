"""Workflow registration and discovery."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nightwatch.workflows.base import Workflow

logger = logging.getLogger("nightwatch.workflows")

_REGISTRY: dict[str, type[Workflow]] = {}


def register(cls: type[Workflow]) -> type[Workflow]:
    """Decorator to register a workflow class."""
    name = cls.name
    if name in _REGISTRY:
        logger.warning(f"Workflow '{name}' already registered, overwriting")
    _REGISTRY[name] = cls
    logger.debug(f"Registered workflow: {name}")
    return cls


def get_enabled_workflows(
    workflow_names: list[str] | None = None,
) -> list[type[Workflow]]:
    """Get workflow classes for the given names. Defaults to ['errors']."""
    if not workflow_names:
        workflow_names = ["errors"]

    workflows = []
    for name in workflow_names:
        if name in _REGISTRY:
            workflows.append(_REGISTRY[name])
        else:
            logger.warning(
                f"Unknown workflow: '{name}'. Available: {list(_REGISTRY.keys())}"
            )
    return workflows


def list_registered() -> list[str]:
    """List all registered workflow names."""
    return list(_REGISTRY.keys())
