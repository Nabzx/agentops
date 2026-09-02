"""The seam between this flagship and Stripe's API.

``StripeClient`` is a small Protocol; ``FakeStripeClient`` is an in-memory stand-in
seeded with fake charges, so this whole package runs with zero setup and no Stripe
account. A real Stripe-SDK-backed implementation of the same Protocol is a distinct,
later concern (see ADR-0011) - not built here.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Protocol

# Decline codes considered safe to retry, per ADR-0011. An allow-list, never a
# deny-list: an unrecognised or future decline code is never treated as retryable.
RETRYABLE_DECLINE_CODES: frozenset[str] = frozenset(
    {"insufficient_funds", "try_again_later", "processing_error"}
)


@dataclass(frozen=True)
class FailedCharge:
    """A charge, as Stripe's own API would describe it. ``status`` starts "failed" and
    becomes "succeeded" once a retry lands.
    """

    id: str
    amount_pence: int
    customer_id: str
    decline_code: str
    status: str = "failed"


class StripeClient(Protocol):
    """The interface the detector and Adapter talk to. A real implementation would wrap
    the Stripe Python SDK behind this same shape.
    """

    async def list_failed_charges(self) -> list[FailedCharge]: ...

    async def confirm_payment_intent(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge:
        """Re-confirm the PaymentIntent behind ``charge_id`` (ADR-0011 - never create a
        new one). Stripe itself dedups on ``idempotency_key``: calling this twice with
        the same key returns the same result, never a second real charge attempt.
        """
        ...


class ChargeNotFoundError(Exception):
    """Raised when an operation targets a charge id that doesn't exist."""


class FakeStripeClient:
    """An in-memory stand-in for Stripe. No network access, ever."""

    def __init__(self, charges: list[FailedCharge] | None = None) -> None:
        self._charges: dict[str, FailedCharge] = {c.id: c for c in (charges or [])}
        self._confirmed_keys: dict[str, FailedCharge] = {}

    def seed(self, charge: FailedCharge) -> None:
        self._charges[charge.id] = charge

    async def list_failed_charges(self) -> list[FailedCharge]:
        return [c for c in self._charges.values() if c.status == "failed"]

    async def confirm_payment_intent(
        self, charge_id: str, *, idempotency_key: str
    ) -> FailedCharge:
        if idempotency_key in self._confirmed_keys:
            return self._confirmed_keys[idempotency_key]  # Stripe's own dedup
        charge = self._charges.get(charge_id)
        if charge is None:
            raise ChargeNotFoundError(f"no such charge {charge_id}")
        succeeded = dataclasses.replace(charge, status="succeeded")
        self._charges[charge_id] = succeeded
        self._confirmed_keys[idempotency_key] = succeeded
        return succeeded
