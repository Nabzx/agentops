"use client";

import Link from "next/link";

import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { titleCase } from "@/lib/format";
import { hasPermission } from "@/lib/roles";
import { Card, EmptyState, Spinner, StatusBadge } from "@/components/ui";

export default function OverviewPage() {
  const { api, me } = useAuth();
  const canQueue = hasPermission(me, "approval_queue_read");
  const canOutbox = hasPermission(me, "outbox_inspect");

  const approvals = useApiData(
    () => (canQueue ? api.listApprovals({ status: "pending", limit: "5" }) : Promise.resolve([])),
    [canQueue],
  );
  const stats = useApiData(
    () => (canOutbox ? api.outboxStats() : Promise.resolve(null)),
    [canOutbox],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          Welcome back. Consequential actions are approved by a Supervisor and executed
          exactly once — every effect here is simulated.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <div className="flex items-center justify-between">
            <h2 className="font-medium">Pending approvals</h2>
            {canQueue && (
              <Link
                href="/dashboard/approvals"
                className="text-sm text-sky-600 hover:underline dark:text-sky-400"
              >
                View queue →
              </Link>
            )}
          </div>
          <div className="mt-3">
            {!canQueue ? (
              <EmptyState message="No access to the approval queue." />
            ) : approvals.loading ? (
              <Spinner />
            ) : (approvals.data?.length ?? 0) === 0 ? (
              <EmptyState message="No pending approvals." />
            ) : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {approvals.data!.map((a) => (
                  <li key={a.id} className="flex items-center justify-between py-2">
                    <Link
                      href={`/dashboard/approvals/${a.id}`}
                      className="text-sm hover:underline"
                    >
                      {titleCase(a.action_type)}
                    </Link>
                    <StatusBadge status={a.risk_level} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card>
          <h2 className="font-medium">Outbox</h2>
          <div className="mt-3">
            {!canOutbox ? (
              <EmptyState message="Outbox diagnostics are Supervisor-only." />
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
          </div>
        </Card>
      </div>
    </div>
  );
}
