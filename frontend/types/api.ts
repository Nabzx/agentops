/** Typed shapes for the AgentOps backend API responses (S9).
 *
 * These mirror the PII-safe response models the backend returns — identifiers, statuses,
 * amounts and hashes only. No customer contact detail or free-text message is ever
 * present, so the UI cannot render PII that the API does not send.
 */

export type Role = "support_agent" | "supervisor";

export interface TokenPair {
  access_token: string;
  refresh_token?: string | null;
  token_type?: string;
  expires_in?: number;
}

export interface Me {
  user_id: string;
  email: string;
  role: Role;
  permissions: string[];
}

export interface ApprovalSummary {
  id: string;
  status: string;
  action_type: string;
  risk_level: string;
  required_role: string | null;
  workflow_run_id: string;
  ticket_id: string;
  order_id: string | null;
  requester_user_id: string;
  requested_amount_pence: number | null;
  maximum_allowed_amount_pence: number | null;
  approved_amount_pence: number | null;
  idempotency_key: string;
  policy_citation_ids: string[];
  evidence_snapshot_hash: string;
  draft_response_subject: string | null;
  request_reason: string | null;
  created_at: string;
  expires_at: string;
  decided_at: string | null;
}

export interface DecisionSummary {
  id: string;
  decision: string;
  actor_user_id: string | null;
  actor_role: string;
  previous_status: string;
  new_status: string;
  reason: string | null;
  requested_amount_pence: number | null;
  decided_amount_pence: number | null;
  created_at: string;
}

export interface DecisionOutcome {
  approval: ApprovalSummary;
  workflow_state: string;
  outbox_job_created: boolean;
}

export interface ActionSummary {
  id: string;
  action_type: string;
  status: string;
  business_effect_reference: string;
  amount_pence: number | null;
  currency: string;
  approval_request_id: string;
  workflow_run_id: string;
  order_id: string;
  result_hash: string;
  completed_at: string;
}

export interface OutboxJobSummary {
  id: string;
  status: string;
  action_type: string;
  approval_request_id: string;
  workflow_run_id: string;
  idempotency_key: string;
  payload_hash: string;
  priority: number;
  attempt_count: number;
  maximum_attempts: number;
  next_attempt_at: string;
  last_error_code: string | null;
}

export interface AttemptSummary {
  attempt_number: number;
  worker_id: string;
  previous_status: string;
  result_status: string | null;
  error_code: string | null;
  retryable: boolean | null;
  duration_ms: number | null;
  started_at: string;
}

export interface AuditEventSummary {
  id: string;
  sequence: number;
  event_type: string;
  actor_user_id: string | null;
  actor_role: string;
  subject_type: string;
  subject_id: string | null;
  correlation_id: string;
  summary: string;
  metadata: Record<string, unknown>;
  previous_hash: string;
  entry_hash: string;
  occurred_at?: string;
}

export interface ChainVerification {
  ok: boolean;
  checked: number;
  broken_sequence: number | null;
  reason: string | null;
}

/** The backend's structured error envelope: {code, message, request_id}. */
export interface ApiErrorEnvelope {
  code?: string;
  message?: string;
  request_id?: string;
  detail?: unknown;
}
