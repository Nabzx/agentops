"use client";

import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { formatDateTime, formatMoney, titleCase } from "@/lib/format";
import { Card, EmptyState, ErrorState, SimulatedBadge, Spinner, StatusBadge } from "@/components/ui";

export default function ActionsPage() {
  const { api } = useAuth();
  const q = useApiData(() => api.listActions({ limit: "50" }), []);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Executed actions</h1>
        <p className="mt-1 text-sm text-slate-500">
          Immutable record of simulated effects. References like{" "}
          <code>SIM-REF-…</code> are demonstration ids — nothing external was contacted.
        </p>
      </div>
      <Card className="p-0">
        {q.loading ? (
          <div className="p-6">
            <Spinner />
          </div>
        ) : q.error ? (
          <div className="p-6">
            <ErrorState message={q.error} />
          </div>
        ) : (q.data?.length ?? 0) === 0 ? (
          <div className="p-6">
            <EmptyState message="No actions have been executed yet." />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-3">Reference</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Amount</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Completed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {q.data!.map((x) => (
                  <tr key={x.id}>
                    <td className="px-4 py-3 font-mono text-xs">
                      {x.business_effect_reference}
                    </td>
                    <td className="px-4 py-3">{titleCase(x.action_type)}</td>
                    <td className="px-4 py-3 tabular-nums">
                      {formatMoney(x.amount_pence, x.currency)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={x.status} />
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {formatDateTime(x.completed_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <SimulatedBadge /> All effects are simulated.
      </div>
    </div>
  );
}
