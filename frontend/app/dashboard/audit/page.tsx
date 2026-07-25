"use client";

import { useState } from "react";

import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { formatDateTime, titleCase } from "@/lib/format";
import { Badge, Card, EmptyState, ErrorState, Spinner } from "@/components/ui";

export default function AuditPage() {
  const { api } = useAuth();
  const [correlation, setCorrelation] = useState("");

  const events = useApiData(
    () =>
      correlation
        ? api.auditForCorrelation(correlation)
        : api.listAudit({ limit: "50" }),
    [correlation],
  );
  const chain = useApiData(() => api.verifyChain(), []);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Audit log</h1>
          <p className="mt-1 text-sm text-slate-500">
            Immutable, hash-chained record of every consequential and security event.
          </p>
        </div>
        {chain.data && (
          <Badge tone={chain.data.ok ? "positive" : "danger"}>
            {chain.data.ok
              ? `Chain intact · ${chain.data.checked} events`
              : `Chain broken at #${chain.data.broken_sequence}`}
          </Badge>
        )}
      </div>

      <input
        value={correlation}
        onChange={(e) => setCorrelation(e.target.value.trim())}
        placeholder="Filter by correlation id…"
        className="w-full max-w-md rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
      />

      <Card className="p-0">
        {events.loading ? (
          <div className="p-6">
            <Spinner />
          </div>
        ) : events.error ? (
          <div className="p-6">
            <ErrorState message={events.error} />
          </div>
        ) : (events.data?.length ?? 0) === 0 ? (
          <div className="p-6">
            <EmptyState message="No audit events match." />
          </div>
        ) : (
          <ol className="divide-y divide-slate-100 dark:divide-slate-800">
            {events.data!.map((e) => (
              <li key={e.id} className="px-4 py-3">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-slate-400">#{e.sequence}</span>
                  <Badge tone="info">{titleCase(e.event_type)}</Badge>
                  <span className="text-slate-400">({e.actor_role})</span>
                </div>
                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                  {e.summary}
                </p>
                <p className="mt-0.5 font-mono text-xs text-slate-400">
                  {formatDateTime(e.occurred_at)} · {e.correlation_id} ·{" "}
                  {e.entry_hash.slice(0, 12)}…
                </p>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
