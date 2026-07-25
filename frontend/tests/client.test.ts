import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, createClient, type TokenStore } from "@/lib/client";
import { Api, summariseMetrics } from "@/lib/api";

function store(access: string | null, refresh: string | null = null): TokenStore {
  let a = access;
  let r = refresh;
  return {
    getAccess: () => a,
    getRefresh: () => r,
    set: (t) => {
      a = t.access_token;
      r = t.refresh_token ?? r;
    },
    clear: () => {
      a = null;
      r = null;
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type FetchMock = ReturnType<typeof vi.fn>;

/** Safely read the RequestInit headers from the nth fetch call. */
function callInit(mock: FetchMock, index: number): { headers: Record<string, string> } {
  const call = mock.mock.calls[index];
  if (!call) throw new Error(`no fetch call at index ${index}`);
  return call[1] as { headers: Record<string, string> };
}

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("attaches the bearer token and correlation id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const client = createClient(store("access-tok"));

    await client.request("/api/thing");

    const init = callInit(fetchMock, 0);
    expect(init.headers["Authorization"]).toBe("Bearer access-tok");
    expect(init.headers["X-Correlation-ID"]).toMatch(/^cor-/);
  });

  it("maps the error envelope to ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "rate_limited", message: "slow down", request_id: "req-9" }, 429),
      ),
    );
    const client = createClient(store("t"));
    await expect(client.request("/x")).rejects.toMatchObject({
      name: "ApiError",
      status: 429,
      code: "rate_limited",
      requestId: "req-9",
    });
  });

  it("refreshes once on 401 then retries", async () => {
    const fetchMock = vi
      .fn()
      // first protected call -> 401
      .mockResolvedValueOnce(jsonResponse({ code: "unauthorized" }, 401))
      // refresh -> new tokens
      .mockResolvedValueOnce(jsonResponse({ access_token: "fresh" }, 200))
      // retry -> success
      .mockResolvedValueOnce(jsonResponse({ ok: true }, 200));
    vi.stubGlobal("fetch", fetchMock);
    const client = createClient(store("stale", "refresh-tok"));

    const result = await client.request<{ ok: boolean }>("/api/thing");
    expect(result.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    // the retry used the refreshed access token
    const retryInit = callInit(fetchMock, 2);
    expect(retryInit.headers["Authorization"]).toBe("Bearer fresh");
  });

  it("does not attach auth to unauthenticated calls", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ access_token: "x" }));
    vi.stubGlobal("fetch", fetchMock);
    const api = new Api(createClient(store("should-not-appear")));

    await api.login("a@b.com", "pw");
    const init = callInit(fetchMock, 0);
    expect(init.headers["Authorization"]).toBeUndefined();
  });
});

describe("summariseMetrics", () => {
  it("keeps only matching, non-comment lines", () => {
    const text = "# HELP x\nprovider_breaker_state{breaker=\"hosted\"} 0.0\nother 1";
    expect(summariseMetrics(text, ["provider_breaker_state"])).toEqual([
      'provider_breaker_state{breaker="hosted"} 0.0',
    ]);
  });
});

describe("ApiError", () => {
  it("is an Error", () => {
    expect(new ApiError("boom") instanceof Error).toBe(true);
  });
});
