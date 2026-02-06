"""Base workflow definitions and safety enforcement."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger("nightwatch.workflows")


class SafeOutput(StrEnum):
    """Allowed output actions for workflows."""

    CREATE_ISSUE = "create_issue"
    CREATE_PR = "create_pr"
    ADD_COMMENT = "add_comment"
    ADD_LABEL = "add_label"
    SEND_SLACK = "send_slack"
    WRITE_FILE = "write_file"


@dataclass
class WorkflowItem:
    """A single item to be analyzed by a workflow."""

    id: str
    title: str
    raw_data: Any = None
    metadata: dict = field(default_factory=dict)


@dataclass
class WorkflowAnalysis:
    """Analysis result for a single workflow item."""

    item: WorkflowItem
    summary: str = ""
    details: dict = field(default_factory=dict)
    confidence: float = 0.0
    tokens_used: int = 0


@dataclass
class WorkflowAction:
    """An action taken by a workflow."""

    action_type: SafeOutput
    target: str = ""
    details: dict = field(default_factory=dict)
    success: bool = False


@dataclass
class WorkflowResult:
    """Complete result from a workflow run."""

    workflow_name: str
    items_fetched: int = 0
    items_analyzed: int = 0
    analyses: list[WorkflowAnalysis] = field(default_factory=list)
    actions: list[WorkflowAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class Workflow(ABC):
    """Abstract base class for all NightWatch workflows."""

    name: str = "base"
    description: str = ""
    safe_outputs: list[SafeOutput] = []

    def check_safe_output(self, action_type: SafeOutput) -> bool:
        """Verify an action is allowed for this workflow."""
        if action_type not in self.safe_outputs:
            logger.warning(
                f"Workflow '{self.name}' attempted unauthorized action: "
                f"{action_type}. Allowed: {self.safe_outputs}"
            )
            return False
        return True

    @abstractmethod
    def fetch(self, **kwargs) -> list[WorkflowItem]:
        """Fetch items to analyze."""
        ...

    @abstractmethod
    def filter(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowItem]:
        """Filter and prioritize items."""
        ...

    @abstractmethod
    def analyze(self, items: list[WorkflowItem], **kwargs) -> list[WorkflowAnalysis]:
        """Analyze filtered items."""
        ...

    @abstractmethod
    def act(self, analyses: list[WorkflowAnalysis], **kwargs) -> list[WorkflowAction]:
        """Take actions based on analyses."""
        ...

    @abstractmethod
    def report_section(self, result: WorkflowResult) -> list[dict]:
        """Generate Slack Block Kit blocks for reporting."""
        ...
