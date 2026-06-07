# runtime/__init__.py
"""Runtime operational modules — selfcheck, diagnostics, retention."""

from runtime.selfcheck import (
    run_selfcheck, SelfcheckResult, SelfcheckIssue, SelfcheckStatus,
)
from runtime.retention import (
    RetentionPolicy, RetentionPreview, default_retention_policy,
    preview_retention, apply_retention,
)
from runtime.diagnostics import (
    get_diagnostics, DiagnosticReport, ComponentStatus,
)
