"""A named, scored suite of adversarial scenarios - not more unit tests in disguise,
a runnable answer to "what have you actually checked this holds against."

Each case either **defends** (the core structurally blocks or detects the attack) or
is an honest **known limitation** (a trust boundary this core does not, and cannot,
police - documented and demonstrated, not hidden). Both kinds are asserted in
``test_security_benchmark.py``: a known limitation silently starting to pass would
mean this file has gone stale, exactly as much as a defended case starting to fail.

Run the full report with ``uv run python -m tests.generate_security_benchmark_report``
from ``ephor/``.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ephor.approvals import (
    ApprovalStatus,
    SelfDecisionError,
    SnapshotError,
    assert_not_self_decision,
    compute_snapshot_hash,
    is_valid_approval_transition,
    verify_snapshot,
)
from ephor.audit import InMemoryAuditStore
from ephor.outbox import DuplicateIdempotencyKeyError, InMemoryOutboxStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class CaseResult:
    passed: bool
    detail: str


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    category: str
    kind: str  # "defended" or "known_limitation"
    run: Callable[[], Awaitable[CaseResult]]


# --- defended: the core structurally blocks or detects these ------------------------


async def _case_self_approval_blocked() -> CaseResult:
    requester = uuid.uuid4()
    try:
        assert_not_self_decision(requester_id=requester, actor_id=requester)
    except SelfDecisionError:
        return CaseResult(
            True,
            "SelfDecisionError raised - the requester cannot decide their own request",
        )
    return CaseResult(False, "no error raised - self-approval was not blocked")


async def _case_tampered_audit_entry_detected() -> CaseResult:
    store = InMemoryAuditStore()
    await store.append(
        event_type="approval_requested",
        actor_role="agent",
        subject_type="approval",
        correlation_id="corr-1",
        summary="original, untampered summary",
        occurred_at=NOW,
    )
    # Simulate a compromised DB row - a direct edit, not through the append API.
    entries = store._entries
    entries[0] = dataclasses.replace(entries[0], summary="a quietly edited summary")

    verification = await store.verify_chain()
    if verification.ok:
        return CaseResult(False, "verify_chain() did not notice the tampered entry")
    return CaseResult(True, f"chain broken as expected: {verification.reason}")


async def _case_tampered_snapshot_detected() -> CaseResult:
    original = {
        "action_type": "retry_charge",
        "charge_id": "ch_1",
        "amount_pence": 4700,
    }
    stored_hash = compute_snapshot_hash(original)
    tampered = {**original, "amount_pence": 999_999}  # an attacker inflating the amount
    try:
        verify_snapshot(tampered, stored_hash)
    except SnapshotError:
        return CaseResult(
            True, "SnapshotError raised - the tampered snapshot was caught"
        )
    return CaseResult(False, "no error raised - the tampered snapshot was accepted")


async def _case_executed_approval_cannot_be_reapproved() -> CaseResult:
    if is_valid_approval_transition(ApprovalStatus.EXECUTED, ApprovalStatus.APPROVED):
        return CaseResult(
            False, "EXECUTED -> APPROVED was allowed by the state machine"
        )
    return CaseResult(
        True, "EXECUTED -> APPROVED correctly rejected by the state machine"
    )


async def _case_non_idempotent_adapter_never_auto_retried() -> CaseResult:
    """A condensed version of test_outbox.py's ADR-0005 acceptance test - the same
    guarantee, asserted here as one scored line in this suite.
    """
    from ephor.outbox import UNCLAIMABLE_STATUSES, OutboxStatus

    store = InMemoryOutboxStore()
    job = await store.create(
        proposal_id=uuid.uuid4(),
        action_type="retry_charge",
        payload_json={},
        idempotency_key="benchmark-key",
        next_attempt_at=NOW,
    )
    # A worker crashed after the external call landed but before the commit - the
    # real effect may have happened; the adapter can't confirm it either way.
    updated = await store.mark_needs_manual_reconciliation(
        job.id, now=NOW, note="benchmark: crashed after call, before commit"
    )
    if OutboxStatus(updated.status) not in UNCLAIMABLE_STATUSES:
        return CaseResult(
            False, "needs_manual_reconciliation is claimable - would be auto-retried"
        )
    reclaimed = await store.claim_batch(
        worker_id="benchmark-worker", now=NOW, lease_seconds=30, batch_size=10
    )
    if any(j.id == job.id for j in reclaimed):
        return CaseResult(False, "the job was reclaimed despite needing reconciliation")
    return CaseResult(
        True, "never claimable, never auto-retried - routed to a human instead"
    )


# --- known limitations: real, honest, structural gaps --------------------------------


class _LyingAdapter:
    """Declares ``is_idempotent = True`` but does not actually dedup - exactly the
    trust boundary this core cannot police. Nothing checks an Adapter's honesty about
    its own capability; there is no way to.
    """

    is_idempotent = True

    def __init__(self) -> None:
        self.real_effects: list[str] = []

    def call(self, idempotency_key: str) -> None:
        self.real_effects.append(idempotency_key)  # fires every time, no dedup


async def _case_a_lying_adapter_defeats_exactly_once() -> CaseResult:
    adapter = _LyingAdapter()
    key = "same-key-both-times"
    adapter.call(key)  # the "real" attempt
    adapter.call(key)  # a retry, after a crash the adapter can't actually detect
    if len(adapter.real_effects) > 1:
        return CaseResult(
            True,
            f"double-fired ({len(adapter.real_effects)} real effects) - an Adapter "
            "that lies about is_idempotent defeats exactly-once, and nothing in the "
            "core can detect a lie about the Adapter's own capability",
        )
    return CaseResult(False, "did not double-fire - this limitation may have closed")


async def _case_duplicate_idempotency_key_rejected() -> CaseResult:
    """Found as a known limitation while building this benchmark - InMemoryOutboxStore
    silently let two unrelated jobs share one idempotency_key, unlike production
    Postgres's own ``uq_outbox_idempotency_key`` constraint. Fixed on the spot, since
    closing it needed no design decision, just parity with a guarantee already made
    elsewhere - now a defended case, not a documented gap.
    """
    store = InMemoryOutboxStore()
    key = "shared-by-two-unrelated-jobs"
    await store.create(
        proposal_id=uuid.uuid4(),
        action_type="retry_charge",
        payload_json={"charge_id": "ch_a"},
        idempotency_key=key,
        next_attempt_at=NOW,
    )
    try:
        await store.create(
            proposal_id=uuid.uuid4(),
            action_type="revoke_approval",
            payload_json={"approval_id": "appr_b"},
            idempotency_key=key,
            next_attempt_at=NOW,
        )
    except DuplicateIdempotencyKeyError:
        return CaseResult(
            True, "DuplicateIdempotencyKeyError raised - the second job was rejected"
        )
    return CaseResult(False, "a second job with the same idempotency_key was created")


CASES: list[BenchmarkCase] = [
    BenchmarkCase(
        "self-approval-blocked",
        "access-control",
        "defended",
        _case_self_approval_blocked,
    ),
    BenchmarkCase(
        "tampered-audit-entry-detected",
        "audit-integrity",
        "defended",
        _case_tampered_audit_entry_detected,
    ),
    BenchmarkCase(
        "tampered-snapshot-detected",
        "audit-integrity",
        "defended",
        _case_tampered_snapshot_detected,
    ),
    BenchmarkCase(
        "executed-approval-immutable",
        "access-control",
        "defended",
        _case_executed_approval_cannot_be_reapproved,
    ),
    BenchmarkCase(
        "non-idempotent-adapter-never-auto-retried",
        "exactly-once",
        "defended",
        _case_non_idempotent_adapter_never_auto_retried,
    ),
    BenchmarkCase(
        "lying-adapter-defeats-exactly-once",
        "exactly-once",
        "known_limitation",
        _case_a_lying_adapter_defeats_exactly_once,
    ),
    BenchmarkCase(
        "duplicate-idempotency-key-rejected",
        "idempotency",
        "defended",
        _case_duplicate_idempotency_key_rejected,
    ),
]


async def run_all() -> list[tuple[BenchmarkCase, CaseResult]]:
    return [(case, await case.run()) for case in CASES]
