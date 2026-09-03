"""Runs security_benchmark.py's suite and asserts it still matches what it claims.

Every case's ``passed`` means "matches what this case documents" - for a "defended"
case that's the attack being blocked; for a "known_limitation" case that's the gap
being successfully reproduced. Either kind returning ``passed=False`` means the
write-up (this file, security_benchmark.py, docs/security-benchmark.md) has gone
stale: a defended case broke, or a documented limitation has silently closed - both
are worth knowing, neither should pass silently.
"""

from __future__ import annotations

from tests.security_benchmark import CASES, run_all


async def test_every_case_still_matches_its_write_up() -> None:
    results = await run_all()
    stale = [
        f"{case.name} ({case.kind}): {result.detail}"
        for case, result in results
        if not result.passed
    ]
    assert not stale, "\n".join(stale)


def test_every_category_has_at_least_one_case() -> None:
    categories = {case.category for case in CASES}
    assert categories == {
        "access-control",
        "audit-integrity",
        "exactly-once",
        "idempotency",
    }


def test_case_names_are_unique() -> None:
    names = [case.name for case in CASES]
    assert len(names) == len(set(names))
