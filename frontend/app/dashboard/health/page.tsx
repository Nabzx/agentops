"use client";

import { useState } from "react";

import { getHealth, getReadiness, summariseMetrics } from "@/lib/api";
import { ApiError } from "@/lib/client";
import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { useToast } from "@/components/toast";
import { hasPermission } from "@/lib/roles";
import { titleCase } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui";

export default function HealthPage() {
  const { api, me } = useAuth();
  const { notify } = useToast();
  const canOutbox = hasPermission(me, "outbox_inspect");
  const [busy, setBusy] = useState(false);

  const health = useApiData(() => getHealth(), []);
  const ready = useApiData(() => getReadiness(), []);
  const stats = useApiData(
    () => (canOutbox ? api.outboxStats() : Promise.resolve(null)),
    [canOutbox],
  );
  const metrics = useApiData(
    () =>
      api
        .metrics()
        .then((t) => summariseMetrics(t, ["provider_breaker_state", "outbox_jobs_total"]))
        .catch(() => [] as string[]),
    [],
  );

  async function runOne() {
    setBusy(true);
    try {
      const r = await api.processOne();
      const outcomes = Object.entries(r.by_outcome)
        .map(([k, v]) => `${k}=${v}`)
        .join(", ");
      notify(
        r.processed ? `Processed ${r.processed} job (${outcomes})` : "No due jobs",
        r.processed ? "positive" : "neutral",
      );
      stats.refresh();
    } catch (err) {
      notify(err instanceof ApiError ? err.message : "Failed", "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">System health</h1>
        <p className="mt-1 text-sm text-slate-500">
          Liveness, readiness and the durable queue. All telemetry is local and offline.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-medium">Status</h2>
          <div className="space-y-2 text-sm">
            <Row label="Service">
              {health.loading ? "…" : (health.data?.status ?? "unknown")}
            </Row>
            <Row label="Readiness">
              {ready.loading ? (
                "…"
              ) : (
                <Badge tone={ready.data?.status === "ready" ? "positive" : "danger"}>
                  {ready.data?.status ?? "unknown"}
                </Badge>
              )}
            </Row>
            {ready.data?.checks &&
              Object.entries(ready.data.checks).map(([k, v]) => (
                <Row key={k} label={titleCase(k)}>
                  <Badge tone={v === "ok" ? "positive" : "danger"}>{v}</Badge>
                </Row>
              ))}
          </div>
        </Card>

        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-medium">Outbox</h2>
            {canOutbox && (
              <Button variant="secondary" disabled={busy} onClick={runOne}>
                {busy ? "Processing…" : "Run one job"}
              </Button>
            )}
          </div>
          {!canOutbox ? (
            <EmptyState message="Supervisor-only." />
          ) : stats.loading ? (
            <Spinner />
          ) : (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              {Object.entries(stats.data ?? {}).map(([status, count]) => (
                <div
                  key={status}
                  className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800"
                >
                  <dt className="text-slate-500">{titleCase(status)}</dt>
                  <dd className="font-medium">{count}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
      </div>

      <Card>
        <h2 className="mb-3 font-medium">Metrics</h2>
        {metrics.loading ? (
          <Spinner />
        ) : (metrics.data?.length ?? 0) === 0 ? (
          <EmptyState message="No matching metrics." />
        ) : (
          <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-800">
            {metrics.data!.join("\n")}
          </pre>
        )}
      </Card>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-500">{label}</span>
      <span>{children}</span>
    </div>
  );
}
