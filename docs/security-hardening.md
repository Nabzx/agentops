# Security hardening

The S8 security checklist with pass/fail evidence. Every item is enforced by a test or an
evaluation hard gate, so a regression fails CI. All checks run offline and deterministically;
every effect remains **simulated**.

## Checklist

| # | Control | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Authentication required on all business endpoints | ✅ | permission-matrix test (unauth → 401) |
| 2 | RBAC enforced per endpoint (agent vs supervisor) | ✅ | permission-matrix test |
| 3 | No IDOR / cross-customer read or action | ✅ | ownership rules, `cross_customer_exposure` gate |
| 4 | No direct production execute endpoint | ✅ | permission-matrix (`/execute` → 404) |
| 5 | Dev-only endpoints gated to development/test | ✅ | `dev_outbox` env gate |
| 6 | Input control-char / null-byte rejection | ✅ | input-validation test (422) |
| 7 | Oversize field & request-body limits | ✅ | validation + reliability tests |
| 8 | Rate limiting (per-client, 429) | ✅ | reliability test |
| 9 | Request timeouts (504 envelope) | ✅ | reliability middleware |
| 10 | Structured error envelope, no stack traces | ✅ | reliability middleware |
| 11 | Payload & snapshot integrity re-verified at execution | ✅ | S6 revalidation, `unsafe_execution` gate |
| 12 | Prompt injection cannot drive an action | ✅ | `prompt_injection_action` gate |
| 13 | Immutable, hash-chained audit of consequential events | ✅ | audit chain verification |
| 14 | Every executed action is audited | ✅ | `unaudited_action` gate |
| 15 | No PII/secret in responses, logs, audit or reports | ✅ | leak-scan test, `pii_leak` gate |
| 16 | Log/secret redaction (PII, cards, JWT, tokens) | ✅ | redaction tests |
| 17 | Production config guard (secret/debug/CORS) | ✅ | config-hardening test |
| 18 | Circuit breaker + deterministic fallback | ✅ | breaker tests |
| 19 | Liveness vs readiness (db + migrations) | ✅ | health tests |
| 20 | Offline dependency/lockfile audit | ✅ | `make deps-audit` (`uv lock --check`) |

## Instruction hierarchy

The core anti-injection guarantee is a strict authority order, enforced structurally:

```
deterministic rules  >  human (Supervisor) decision  >  model proposal  >  untrusted content
```

Untrusted strings — ticket bodies, retrieved policy chunks, tool results — are **data, not
instructions**. They can never (a) approve a request, (b) create an outbox job, or (c)
cause an executed effect: approvals require an authenticated non-requesting Supervisor, and
execution re-runs deterministic revalidation against locked rows. The workflow escalates
prompt-injection tickets rather than acting on them (`prompt_injection_action` gate = 0).

## Input validation

`app/core/validation.py` rejects null bytes and control characters (allowing only ordinary
whitespace) via a reusable `SafeStr` type, applied to authentication inputs; Pydantic
bounds cap field lengths; the reliability middleware caps request size and rate. Adversarial
inputs are refused with a clean 422/413/429 rather than being processed or logged raw.

## PII & secrets

Response schemas are PII-safe by construction (identifiers, statuses and hashes only — the
leak-scan test asserts no field name can carry raw contact details or free-text customer
content). The logging redaction filter scrubs emails, phones, cards, JWTs, bearer tokens
and secret assignments from every emitted record, and audit metadata is redaction-clean
(`pii_leak` gate = 0).

## Configuration

Production startup is refused when `JWT_SECRET` is the dev value or under 32 chars, when
`DEBUG` is on, or when CORS is a wildcard (`app/core/config.py`). `.env.example` carries
only labelled, non-secret development defaults.

## Dependencies

`make deps-audit` runs `uv lock --check` to verify the lockfile is consistent and fully
pinned — offline, no network. A connected environment would add a networked advisory scan
(e.g. `pip-audit`); that is intentionally not required at test/CI runtime.
