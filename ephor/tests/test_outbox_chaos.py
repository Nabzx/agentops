"""Runs the chaos harness (see ``chaos_harness.py``) as a normal part of the suite.

CI runs a few hundred trials on every push - fast, but already a far larger sample
of the crash-timing state space than the three hand-picked points in
``test_outbox.py``'s acceptance test. ``EPHOR_CHAOS_TRIALS`` overrides the count for
a deeper local sweep (see ``docs/chaos-report.md`` for a large run's numbers).
"""

from __future__ import annotations

import os

from tests.chaos_harness import run_trials

DEFAULT_TRIALS = 300


async def test_exactly_once_holds_under_randomised_crash_injection() -> None:
    trials = int(os.environ.get("EPHOR_CHAOS_TRIALS", DEFAULT_TRIALS))
    summaries = await run_trials(trials)

    violations = [v for s in summaries for v in s.violations]
    assert not violations, "\n".join(str(v) for v in violations)

    total_jobs = sum(s.jobs for s in summaries)
    total_crashes = sum(s.crash_injections for s in summaries)
    # Sanity on the harness itself, not just the guarantee: make sure it actually
    # exercised a meaningful number of jobs and crash points, not zero of either.
    assert total_jobs >= trials * 2
    assert total_crashes >= total_jobs
