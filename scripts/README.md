# `scripts/`

Repo-level helper scripts. Application and demo scripts live next to the code they use:

- **`backend/scripts/`** — dataset builders (`build_workflow_dataset.py`,
  `build_model_tasks_dataset.py`) and the demo seeder (`seed_pending_approval.py`, run via
  `make demo-seed-approval`).
- **`frontend/scripts/`** — `capture-screenshots.mjs`, which regenerates the dashboard
  screenshots in [`docs/screenshots/`](../docs/screenshots/).

Most day-to-day workflows are covered by the [`Makefile`](../Makefile) (`make help`).
