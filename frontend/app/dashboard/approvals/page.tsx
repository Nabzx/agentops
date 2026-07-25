"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { formatMoney, relativeTime, titleCase } from "@/lib/format";
import { Card, EmptyState, ErrorState, SimulatedBadge, Spinner, StatusBadge } from "@/components/ui";

const STATUS_FILTERS = ["", "pending", "execution_pending", "executed", "rejected", "expired"];

export default function ApprovalsPage() {
  const { api, me } = useAuth();
  const [status, setStatus] = useState("pending");
  const [mine, setMine] = useState(false);

  const params: Record<string, string> = { limit: "50" };
  if (status) params.status = status;
  if (mine) params.mine = "true";

  const q = useApiData(() => api.listApprovals(params), [status, mine]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Approval queue</h1>
          <p className="mt-1 text-sm text-slate-500">
            Expiring soonest first. Approve, reject or cancel — every effect is simulated.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <label className="flex items-center gap-1">
            <span className="text-slate-500">Status</span>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-800"
            >
              {STATUS_FILTERS.map((s) => (
                <option key={s} value={s}>
                  {s ? titleCase(s) : "All"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={mine}
              onChange={(e) => setMine(e.target.checked)}
            />
            <span className="text-slate-500">Mine</span>
          </label>
        </div>
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
            <EmptyState message="No approvals match these filters." />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Risk</th>
                  <th className="px-4 py-3">Amount</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Expires</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {q.data!.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-3">
                      <Link
                        href={`/dashboard/approvals/${a.id}`}
                        className="font-medium hover:underline"
                      >
                        {titleCase(a.action_type)}
                      </Link>
                      {a.requester_user_id === me?.user_id && (
                        <span className="ml-2 text-xs text-slate-400">you</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={a.risk_level} />
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {formatMoney(a.requested_amount_pence)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={a.status} />
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {relativeTime(a.expires_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="flex items-center gap-2 text-xs text-slate-400">
        <SimulatedBadge /> Approvals authorise simulated actions only.
      </div>
    </div>
  );
}
