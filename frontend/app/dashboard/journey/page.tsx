"use client";

import { useState } from "react";

import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { formatDateTime, titleCase } from "@/lib/format";
import { Badge, Card, EmptyState, ErrorState, Spinner } from "@/components/ui";

export default function JourneyPage() {
  const { api } = useAuth();
  const [input, setInput] = useState("");
  const [correlation, setCorrelation] = useState("");

  const events = useApiData(
    () => (correlation ? api.auditForCorrelation(correlation) : Promise.resolve([])),
    [correlation],
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Ticket journey</h1>
        <p className="mt-1 text-sm text-slate-500">
          Follow one correlation id across approval, outbox and simulated execution — the
          human-in-the-loop, exactly-once story in order.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setCorrelation(input.trim());
        }}
        className="flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Correlation id (e.g. from an approval or audit event)"
          className="w-full max-w-md rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
        />
        <button
          type="submit"
          className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
        >
          Trace
        </button>
      </form>

      {!correlation ? (
        <EmptyState message="Enter a correlation id to trace its journey." />
      ) : events.loading ? (
        <Spinner />
      ) : events.error ? (
        <ErrorState message={events.error} />
      ) : (events.data?.length ?? 0) === 0 ? (
        <EmptyState message="No events for that correlation id." />
      ) : (
        <Card>
          <ol className="relative space-y-4 border-l border-slate-200 pl-6 dark:border-slate-700">
            {events.data!.map((e) => (
              <li key={e.id} className="relative">
                <span className="absolute -left-[27px] top-1 h-3 w-3 rounded-full bg-sky-500" />
                <div className="flex items-center gap-2">
                  <Badge tone="info">{titleCase(e.event_type)}</Badge>
                  <span className="text-xs text-slate-400">({e.actor_role})</span>
                </div>
                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                  {e.summary}
                </p>
                <p className="mt-0.5 text-xs text-slate-400">
                  {formatDateTime(e.occurred_at)}
                </p>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
