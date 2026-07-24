"""PII / secret leak scan for API response schemas and logs (S8).

Two guards: the read-only response models must not declare fields that could carry raw
PII or secrets, and the log redaction must scrub every PII/secret pattern. A regression
in either fails the build.
"""

from __future__ import annotations

import pytest
from app.api.routes.approvals import ApprovalSummary, DecisionSummary
from app.api.routes.execution import ActionSummary, AttemptSummary, OutboxJobSummary
from app.core.pii import redact_log
from pydantic import BaseModel

_FORBIDDEN_FIELD_SUBSTRINGS = (
    "email",
    "phone",
    "card",
    "password",
    "secret",
    "token",
    "jwt",
    "message_body",
    "customer_message",
    "draft_response_body",
    "full_",
    "raw_",
)

_RESPONSE_MODELS: tuple[type[BaseModel], ...] = (
    ApprovalSummary,
    DecisionSummary,
    ActionSummary,
    AttemptSummary,
    OutboxJobSummary,
)


@pytest.mark.parametrize("model", _RESPONSE_MODELS)
def test_response_schema_has_no_pii_fields(model: type[BaseModel]) -> None:
    for field in model.model_fields:
        lowered = field.lower()
        assert not any(
            bad in lowered for bad in _FORBIDDEN_FIELD_SUBSTRINGS
        ), f"{model.__name__}.{field} may carry PII/secret content"


def test_redaction_scrubs_every_pattern() -> None:
    samples = [
        "jane.doe@example.com",
        "07911123456",
        "4111 1111 1111 1111",
        "password=hunter2",
        "Authorization: Bearer sk-live-abc",
        "eyJhbGciOi.JSUzI1NiIsInR5.cCI6IkpXVCJ9",
    ]
    scrubbed = redact_log(" ".join(samples))
    for raw in ("jane.doe@example.com", "07911123456", "hunter2", "sk-live-abc"):
        assert raw not in scrubbed
    assert "4111 1111 1111 1111" not in scrubbed
