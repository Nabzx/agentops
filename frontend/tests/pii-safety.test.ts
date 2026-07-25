import { describe, expect, it } from "vitest";

import type {
  ActionSummary,
  ApprovalSummary,
  AuditEventSummary,
  OutboxJobSummary,
} from "@/types/api";

/** Representative objects shaped exactly like the backend responses the UI renders.
 *  If a PII/secret field were ever introduced to a type, it would surface here. */
const approval: ApprovalSummary = {
  id: "a",
  status: "pending",
  action_type: "request_supervisor_refund_approval",
  risk_level: "high",
  required_role: null,
  workflow_run_id: "w",
  ticket_id: "t",
  order_id: "o",
  requester_user_id: "u",
  requested_amount_pence: 5900,
  maximum_allowed_amount_pence: 5900,
  approved_amount_pence: null,
  idempotency_key: "act-x",
  policy_citation_ids: ["POL-1"],
  evidence_snapshot_hash: "h",
  draft_response_subject: "Update",
  request_reason: "refund please",
  created_at: "2026-07-16T12:00:00Z",
  expires_at: "2026-07-17T12:00:00Z",
  decided_at: null,
};

const action: ActionSummary = {
  id: "x",
  action_type: "simulated_refund",
  status: "succeeded",
  business_effect_reference: "SIM-REF-2026-000001",
  amount_pence: 5900,
  currency: "GBP",
  approval_request_id: "a",
  workflow_run_id: "w",
  order_id: "o",
  result_hash: "h",
  completed_at: "2026-07-16T12:00:00Z",
};

const outbox: OutboxJobSummary = {
  id: "j",
  status: "succeeded",
  action_type: "simulated_refund",
  approval_request_id: "a",
  workflow_run_id: "w",
  idempotency_key: "act-x",
  payload_hash: "h",
  priority: 300,
  attempt_count: 1,
  maximum_attempts: 5,
  next_attempt_at: "2026-07-16T12:00:00Z",
  last_error_code: null,
};

const audit: AuditEventSummary = {
  id: "e",
  sequence: 1,
  event_type: "action_executed",
  actor_user_id: "u",
  actor_role: "system",
  subject_type: "approval",
  subject_id: "a",
  correlation_id: "cor-1",
  summary: "A simulated refund was recorded.",
  metadata: { reference: "SIM-REF-2026-000001" },
  previous_hash: "0",
  entry_hash: "h",
  occurred_at: "2026-07-16T12:00:00Z",
};

const FORBIDDEN = [
  "email",
  "phone",
  "card",
  "password",
  "secret",
  "token",
  "jwt",
  "customer_message",
  "message_body",
  "draft_response_body",
];

describe("frontend PII safety", () => {
  it.each([
    ["approval", approval],
    ["action", action],
    ["outbox", outbox],
    ["audit", audit],
  ])("%s shape carries no PII/secret field", (_name, obj) => {
    for (const key of Object.keys(obj)) {
      expect(FORBIDDEN.some((bad) => key.toLowerCase().includes(bad))).toBe(false);
    }
  });
});
