/** Typed API helpers for the AgentOps backend (S9).
 *
 * Thin wrappers over the core client so components describe *what* they need, not how
 * requests are built. Health calls stay unauthenticated; everything else carries the
 * bearer token via the client.
 */

import { ApiError, buildUrl, type ApiClient } from "@/lib/client";
import { API_BASE_URL } from "@/lib/config";
import type { HealthResponse, ReadinessResponse } from "@/types/health";
import type {
  ActionSummary,
  ApprovalSummary,
  AttemptSummary,
  AuditEventSummary,
  ChainVerification,
  DecisionOutcome,
  DecisionSummary,
  Me,
  OutboxJobSummary,
  TokenPair,
} from "@/types/api";

export { ApiError, buildUrl };

// --- unauthenticated health (kept from S0) ------------------------------------------
async function getJson<T>(path: string, acceptStatuses: number[] = [200]): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(API_BASE_URL, path), {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`Network error contacting the API at ${API_BASE_URL}`);
  }
  if (!acceptStatuses.includes(response.status)) {
    throw new ApiError(`Unexpected response ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export const getHealth = (): Promise<HealthResponse> =>
  getJson<HealthResponse>("/health");

export const getReadiness = (): Promise<ReadinessResponse> =>
  getJson<ReadinessResponse>("/health/ready", [200, 503]);

// --- authenticated API ---------------------------------------------------------------
export class Api {
  constructor(private readonly client: ApiClient) {}

  login(email: string, password: string): Promise<TokenPair> {
    return this.client.request<TokenPair>("/api/auth/login", {
      method: "POST",
      auth: false,
      body: { email, password },
      acceptStatuses: [200],
    });
  }

  me(): Promise<Me> {
    return this.client.request<Me>("/api/auth/me");
  }

  listApprovals(params: Record<string, string> = {}): Promise<ApprovalSummary[]> {
    const query = new URLSearchParams(params).toString();
    return this.client.request<ApprovalSummary[]>(
      `/api/approvals${query ? `?${query}` : ""}`,
    );
  }

  getApproval(id: string): Promise<ApprovalSummary> {
    return this.client.request<ApprovalSummary>(`/api/approvals/${id}`);
  }

  getDecisions(id: string): Promise<DecisionSummary[]> {
    return this.client.request<DecisionSummary[]>(`/api/approvals/${id}/decisions`);
  }

  approve(id: string, body: Record<string, unknown> = {}): Promise<DecisionOutcome> {
    return this.client.request<DecisionOutcome>(`/api/approvals/${id}/approve`, {
      method: "POST",
      body,
      acceptStatuses: [200],
    });
  }

  reject(id: string, reason: string): Promise<DecisionOutcome> {
    return this.client.request<DecisionOutcome>(`/api/approvals/${id}/reject`, {
      method: "POST",
      body: { reason },
      acceptStatuses: [200],
    });
  }

  cancel(id: string, reason: string): Promise<DecisionOutcome> {
    return this.client.request<DecisionOutcome>(`/api/approvals/${id}/cancel`, {
      method: "POST",
      body: { reason },
      acceptStatuses: [200],
    });
  }

  retry(id: string, reason?: string): Promise<DecisionOutcome> {
    return this.client.request<DecisionOutcome>(`/api/approvals/${id}/retry`, {
      method: "POST",
      body: { reason },
      acceptStatuses: [200],
    });
  }

  listActions(params: Record<string, string> = {}): Promise<ActionSummary[]> {
    const query = new URLSearchParams(params).toString();
    return this.client.request<ActionSummary[]>(
      `/api/actions${query ? `?${query}` : ""}`,
    );
  }

  listOutbox(params: Record<string, string> = {}): Promise<OutboxJobSummary[]> {
    const query = new URLSearchParams(params).toString();
    return this.client.request<OutboxJobSummary[]>(
      `/api/outbox${query ? `?${query}` : ""}`,
    );
  }

  outboxAttempts(id: string): Promise<AttemptSummary[]> {
    return this.client.request<AttemptSummary[]>(`/api/outbox/${id}/attempts`);
  }

  outboxStats(): Promise<Record<string, number>> {
    return this.client.request<Record<string, number>>("/api/outbox/stats");
  }

  listAudit(params: Record<string, string> = {}): Promise<AuditEventSummary[]> {
    const query = new URLSearchParams(params).toString();
    return this.client.request<AuditEventSummary[]>(
      `/api/audit${query ? `?${query}` : ""}`,
    );
  }

  auditForCorrelation(correlationId: string): Promise<AuditEventSummary[]> {
    return this.client.request<AuditEventSummary[]>(
      `/api/audit/correlation/${correlationId}`,
    );
  }

  verifyChain(): Promise<ChainVerification> {
    return this.client.request<ChainVerification>("/api/audit/verify");
  }

  processOne(): Promise<{ processed: number; by_outcome: Record<string, number> }> {
    return this.client.request("/api/dev/outbox/process-one", {
      method: "POST",
      acceptStatuses: [200],
    });
  }

  metrics(): Promise<string> {
    return this.client.request<string>("/metrics", { auth: false, raw: true });
  }
}

/** Pull a handful of interesting lines out of Prometheus exposition text. */
export function summariseMetrics(text: string, prefixes: string[]): string[] {
  return text
    .split("\n")
    .filter((line) => line && !line.startsWith("#"))
    .filter((line) => prefixes.some((p) => line.startsWith(p)));
}
