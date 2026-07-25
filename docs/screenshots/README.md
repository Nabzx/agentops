# Screenshots

Captured from the actual running dashboard against the seeded synthetic data (viewport
1440×900 at 2× for crisp images). Regenerate with
[`frontend/scripts/capture-screenshots.mjs`](../../frontend/scripts/capture-screenshots.mjs)
— it drives the system Chrome over the DevTools Protocol, no extra dependencies, fully local.

| File | Screen |
| --- | --- |
| `01-login.png` | Sign-in |
| `02-overview.png` | Overview — pending approvals + outbox stats |
| `03-approval-queue.png` | Approval queue |
| `04-approval-detail.png` | Approval detail + decision panel |
| `05-health-outbox.png` | System health + outbox + demo control |
| `06-actions.png` | Executed actions (simulated refund `SIM-REF-…`) |
| `07-audit.png` | Hash-chained audit log ("chain intact") |
| `08-journey.png` | Ticket journey timeline by correlation id |
| `09-audit-dark.png` | Audit log, dark theme |

Every consequential figure shown is **simulated**.
