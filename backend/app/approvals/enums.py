"""Approval status and decision enums with validated transitions (S6).

Defined in ``ephor.approvals`` (the extracted core, see ADR-0009) and re-exported here
so every existing import site in this app keeps working unchanged - only the
definition's home moved.
"""

from __future__ import annotations

from ephor.approvals import (
    APPROVAL_TRANSITIONS,
    TERMINAL_APPROVAL_STATUSES,
    ApprovalDecisionType,
    ApprovalStatus,
    is_valid_approval_transition,
)

__all__ = [
    "APPROVAL_TRANSITIONS",
    "TERMINAL_APPROVAL_STATUSES",
    "ApprovalDecisionType",
    "ApprovalStatus",
    "is_valid_approval_transition",
]
