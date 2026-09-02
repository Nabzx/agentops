"""The seam between this flagship and a chain.

``ChainClient`` is a small Protocol; ``FakeChainClient`` is an in-memory stand-in
seeded with fake approvals, so this whole package runs with zero setup and no wallet,
no RPC endpoint, no real chain - that stays the default everywhere in this repo,
same as ``stripe-recovery``'s ``FakeStripeClient``. A real EVM-backed implementation
of the same Protocol is a distinct, later concern (see ADR-0016) - not built here.

Unlike Stripe, a chain has no "Idempotency-Key" header for us to lean on. Exactly-once
here comes from something more fundamental: every account has a strictly increasing
nonce, and the network only ever finalises one transaction per (account, nonce) pair.
``FakeChainClient`` models the caller-side half of that: an idempotency key is mapped
to a nonce the *first* time it's seen, and every later call with the same key reuses
that same recorded nonce - never asks "what's the next free nonce" again - so a retry
resolves to the transaction already in flight or already mined, not a second one.
See ADR-0016 for why this has to be the caller's discipline, not the chain's gift.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Protocol

# The canonical "infinite approval" sentinel: the maximum representable uint256, the
# value tooling like Etherscan/Revoke.cash itself treats as "no practical limit". An
# allow-list, never a deny-list, per the same reasoning as ADR-0011: only this exact,
# well-known, unambiguously-dangerous value is ever proposed for revocation. A merely
# large-but-finite approval is left alone in v1 - see ADR-0016.
INFINITE_ALLOWANCE: int = 2**256 - 1


@dataclass(frozen=True)
class TokenApproval:
    """One ERC-20 `approve` grant, as a chain's own state would describe it.
    ``allowance`` starts at ``INFINITE_ALLOWANCE`` for a risky one and becomes ``0``
    once revoked.
    """

    id: str
    owner_address: str
    token_address: str
    token_symbol: str
    spender_address: str
    allowance: int


class ChainClient(Protocol):
    """The interface the detector and Adapter talk to. A real implementation would
    wrap an EVM RPC client (reading `allowance()`, writing `approve(spender, 0)`)
    behind this same shape.
    """

    async def list_approvals(self, owner_address: str) -> list[TokenApproval]: ...

    async def revoke_approval(
        self, approval_id: str, *, idempotency_key: str
    ) -> TokenApproval:
        """Set the allowance behind ``approval_id`` to zero (ADR-0016 - never a new
        approval, never a different spender). A resubmission with the same
        ``idempotency_key`` resolves to the same nonce, and so the same transaction -
        never a second real revocation.
        """
        ...


class ApprovalNotFoundError(Exception):
    """Raised when an operation targets an approval id that doesn't exist."""


class FakeChainClient:
    """An in-memory stand-in for a chain. No RPC calls, no wallet, ever."""

    def __init__(self, approvals: list[TokenApproval] | None = None) -> None:
        self._approvals: dict[str, TokenApproval] = {a.id: a for a in (approvals or [])}
        self._nonce_by_key: dict[str, int] = {}
        self._result_by_key: dict[str, TokenApproval] = {}
        self._next_nonce = 0

    def seed(self, approval: TokenApproval) -> None:
        self._approvals[approval.id] = approval

    async def list_approvals(self, owner_address: str) -> list[TokenApproval]:
        return [
            a
            for a in self._approvals.values()
            if a.owner_address == owner_address and a.allowance > 0
        ]

    async def revoke_approval(
        self, approval_id: str, *, idempotency_key: str
    ) -> TokenApproval:
        if idempotency_key in self._result_by_key:
            return self._result_by_key[idempotency_key]  # same nonce, same outcome

        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"no such approval {approval_id}")

        # Committing to a nonce here, once, is the whole guarantee: a crash-and-retry
        # with the same idempotency_key must never ask "what's next" again.
        self._nonce_by_key[idempotency_key] = self._next_nonce
        self._next_nonce += 1

        revoked = dataclasses.replace(approval, allowance=0)
        self._approvals[approval_id] = revoked
        self._result_by_key[idempotency_key] = revoked
        return revoked
