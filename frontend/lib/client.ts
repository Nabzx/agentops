/** Core typed API client with JWT auth, transparent refresh and error mapping (S9).
 *
 * A single place that attaches the bearer token, sends a per-action correlation id,
 * normalises the backend's `{code, message, request_id}` envelope, and refreshes the
 * access token once on a 401 before retrying. Components use the helpers in `lib/api.ts`.
 */

import { API_BASE_URL } from "@/lib/config";
import type { ApiErrorEnvelope, TokenPair } from "@/types/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** A minimal token holder. Access token lives in memory; the refresh flow rotates it. */
export interface TokenStore {
  getAccess(): string | null;
  getRefresh(): string | null;
  set(tokens: TokenPair): void;
  clear(): void;
}

function newCorrelationId(): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 16)
      : Math.random().toString(16).slice(2, 18);
  return `cor-${rand}`;
}

export function buildUrl(base: string, path: string): string {
  const trimmedBase = base.replace(/\/+$/, "");
  const trimmedPath = path.startsWith("/") ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
}

async function parseError(response: Response): Promise<ApiError> {
  let envelope: ApiErrorEnvelope = {};
  try {
    envelope = (await response.json()) as ApiErrorEnvelope;
  } catch {
    /* non-JSON body */
  }
  const message =
    envelope.message ??
    (typeof envelope.detail === "string" ? envelope.detail : null) ??
    `Request failed (${response.status})`;
  return new ApiError(message, response.status, envelope.code, envelope.request_id);
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
  acceptStatuses?: number[];
  raw?: boolean;
}

export function createClient(tokens: TokenStore) {
  async function refresh(): Promise<boolean> {
    const refreshToken = tokens.getRefresh();
    if (!refreshToken) return false;
    try {
      const response = await fetch(buildUrl(API_BASE_URL, "/api/auth/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      if (!response.ok) return false;
      tokens.set((await response.json()) as TokenPair);
      return true;
    } catch {
      return false;
    }
  }

  async function send(path: string, opts: RequestOptions, retry: boolean): Promise<Response> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      "X-Correlation-ID": newCorrelationId(),
    };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    if (opts.auth !== false) {
      const access = tokens.getAccess();
      if (access) headers["Authorization"] = `Bearer ${access}`;
    }
    let response: Response;
    try {
      response = await fetch(buildUrl(API_BASE_URL, path), {
        method: opts.method ?? "GET",
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        cache: "no-store",
      });
    } catch {
      throw new ApiError(`Network error contacting the API at ${API_BASE_URL}`);
    }
    // Refresh once on an authenticated 401, then retry the original request.
    if (response.status === 401 && opts.auth !== false && retry && (await refresh())) {
      return send(path, opts, false);
    }
    return response;
  }

  async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const accept = opts.acceptStatuses ?? [200, 201];
    const response = await send(path, opts, true);
    if (!accept.includes(response.status)) {
      throw await parseError(response);
    }
    if (opts.raw) return (await response.text()) as unknown as T;
    if (response.status === 204) return undefined as unknown as T;
    return (await response.json()) as T;
  }

  return { request, refresh };
}

export type ApiClient = ReturnType<typeof createClient>;
