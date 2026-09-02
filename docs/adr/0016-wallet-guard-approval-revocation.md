# 0016. wallet-guard: revoke unlimited token approvals, exactly once, without a header

- **Status:** Accepted
- **Date:** 2026-09-03
- **Driven by:** maintainer decision, no Wayfinder ticket (a second detector proving
  the core generalises - engineering proof, not a locked business direction; see
  ADR-0014, which shelved crypto as a *product* direction while leaving this kind of
  proof-of-reusability work open)

## Context

`stripe-recovery/` proves Ephor's core works for one Adapter. It doesn't prove the core
*generalises* - a single data point can't. A second, genuinely different Adapter is the
actual test: a payments API with a built-in `Idempotency-Key` header is one shape;
something with no such header at all is a much harder, more honest test of whether
`ephor.effects.Adapter`'s contract (ADR-0006) really is generic, or quietly
Stripe-shaped underneath.

An EVM chain's approval model is that shape. An ERC-20 `approve(spender, amount)` call
grants `spender` the right to move up to `amount` of a token from the owner's wallet.
Wallet-draining exploits routinely target **unlimited** approvals - `amount` set to the
maximum representable `uint256` - left over from some protocol the owner used once and
forgot about. Revoking one is a single, well-understood, safe operation: call
`approve(spender, 0)`. No payments provider, no request-level idempotency key, no
"soft decline" concept - a materially different domain from Stripe's.

## Decision

**Build `wallet-guard/`, a second top-level package mirroring `stripe-recovery/`'s
shape exactly, with one deliberately different piece: exactly-once execution is earned
through nonce discipline, not a provider-supplied header.**

1. **v1 action set: revoke an unlimited approval, and only that** - the same discipline
   ADR-0011 applied to Stripe. The allow-list is exact equality against the canonical
   `2**256 - 1` sentinel, never "a large but finite amount" - fails safe on any
   approval that isn't unmistakably, maximally dangerous. Judging "large" is a
   real decision deferred to a later version, the same way ADR-0011 deferred dunning.
2. **Exactly-once without a header.** Stripe volunteers an `Idempotency-Key` convention
   at the API level; a chain has nothing equivalent - the network's only relevant
   guarantee is that each account has a strictly increasing nonce, and finalises at
   most one transaction per (account, nonce). That guarantee only becomes an
   exactly-once property for *this system* if the caller commits to a nonce for a
   given idempotency key **once**, before ever broadcasting, and always resubmits
   with that same nonce on retry - never asks "what's the next free nonce" again on a
   second attempt. `WalletGuardAdapter.is_idempotent = True` is earned by that
   discipline living in the client (`FakeChainClient._nonce_by_key`), not assumed.
3. **`FailedCharge`'s shape becomes `TokenApproval`; `charge_id` becomes an opaque
   `approval_id`** - same pattern as ADR-0008 intended: a detector-defined identifier,
   opaque to the core, living in the Snapshot rather than forcing
   `ApprovalRequest.subject_id: uuid.UUID | None` to accommodate a non-UUID identity a
   second time.
4. **No currency amount.** `requested_amount_pence` is left unset - the field is
   optional precisely so a non-monetary action doesn't have to invent a fake amount to
   satisfy a Stripe-shaped field. This is the first real usage proving that part of
   ADR-0008's generic Snapshot design actually holds for something that isn't money.
5. **Zero setup, same as `stripe-recovery`.** `FakeChainClient` is the only client;
   no RPC endpoint, no wallet, no real chain, ever, in this package or its CI job. A
   real EVM-RPC-backed `ChainClient` is a distinct, later concern - not built here,
   deliberately, matching ADR-0013's own scoping for the real Stripe client.

## Alternatives considered

- **Also flag large-but-finite approvals** - rejected for v1: "large" is a judgement
  call with no canonical threshold the way `2**256 - 1` is canonical; an exact-match
  allow-list is unambiguous and fails safe, a threshold is a guess.
- **Support `setApprovalForAll` (NFT collection-wide approvals) alongside ERC-20** -
  rejected for v1: a different revocation call shape for no proof-of-generality
  benefit this version needs: ERC-20 alone already forces the header-vs-nonce question
  that's the actual point of this exercise.
- **Derive the nonce directly from a hash of the idempotency key** - rejected: real
  EVM nonces must be the account's exact current sequential count, not an arbitrary
  value: an out-of-sequence nonce is simply invalid, not merely inefficient. The
  caller has to track "which nonce did I commit to for this key" as real state, not
  compute it - `FakeChainClient` models exactly that with `_nonce_by_key`, which a
  real implementation would need to persist durably (its own small ledger), not
  invent afresh per call.

## Consequences

- `ephor.effects.Adapter`'s contract now has two real implementations behind it with
  materially different idempotency mechanisms (a header vs. nonce discipline) - the
  generality claim rests on two data points, not one.
- `ephor.approvals`'s `requested_amount_pence: int | None` and `ephor.actions`'s
  opaque `parameters`/`evidence` dicts are now proven, not just designed, to carry a
  non-monetary action cleanly.
- A real EVM-RPC-backed `ChainClient` (reading `allowance()`, writing
  `approve(spender, 0)` against a real testnet) is real follow-up work, same shape as
  ADR-0013's `StripeTestModeClient` - not scoped here.
- `stripe-recovery/README.md`'s "the first detector built on Ephor" line and this
  package's own README both stay accurate as written; ROADMAP.md's Phase 5 gets one
  concrete example instead of a placeholder list.
