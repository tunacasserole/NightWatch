"""NightWatch validation system.

Re-exports legacy API for backward compatibility.
New code should use: from nightwatch.validation.orchestrator import ValidationOrchestrator
"""

from nightwatch.validation._legacy import _check_ruby_syntax, validate_file_changes

__all__ = ["validate_file_changes", "_check_ruby_syntax"]
