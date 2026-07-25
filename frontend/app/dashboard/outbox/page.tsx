"use client";

import { Fragment, useState } from "react";

import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { formatDateTime, titleCase } from "@/lib/format";
import { AttemptsPanel } from "@/components/AttemptsPanel";
import { Button, Card, EmptyState, ErrorState, Spinner, StatusBadge } from "@/components/ui";

export default function OutboxPage() {
  const { api } = useAuth();
  const jobs = useApiData(() => api.listOutbox({ limit: "50" }), []);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Outbox</h1>
        <p className="mt-1 text-sm text-slate-500">
          The durable queue: one job per approved action, claimed with lease-based
          concurrency and processed exactly once. Supervisor view.
        </p>
      </div>
      <Card className="p-0">
        {jobs.loading ? (
          <div className="p-6">
            <Spinner />
          </div>
        ) : jobs.error ? (
          <div className="p-6">
            <ErrorState message={jobs.error} />
          </div>
        ) : (jobs.data?.length ?? 0) === 0 ? (
          <div className="p-6">
            <EmptyState message="No outbox jobs." />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Attempts</th>
                  <th className="px-4 py-3">Next</th>
                  <th className="px-4 py-3">Last error</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {jobs.data!.map((j) => (
                  <Fragment key={j.id}>
                    <tr>
                      <td className="px-4 py-3">{titleCase(j.action_type)}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={j.status} />
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        {j.attempt_count}/{j.maximum_attempts}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {formatDateTime(j.next_attempt_at)}
                      </td>
                      <td className="px-4 py-3 text-xs text-rose-600">
                        {j.last_error_code ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Button
                          variant="ghost"
                          onClick={() => setOpen(open === j.id ? null : j.id)}
                        >
                          {open === j.id ? "Hide" : "Attempts"}
                        </Button>
                      </td>
                    </tr>
                    {open === j.id && (
                      <tr>
                        <td colSpan={6} className="bg-slate-50 px-4 py-3 dark:bg-slate-800/50">
                          <AttemptsPanel jobId={j.id} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
