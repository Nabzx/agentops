"use client";

import Link from "next/link";
import { use, useState } from "react";

import { ApiError } from "@/lib/client";
import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { useToast } from "@/components/toast";
import { formatDateTime, formatMoney, titleCase } from "@/lib/format";
import { canDecide } from "@/lib/roles";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  SimulatedBadge,
  Spinner,
  StatusBadge,
} from "@/components/ui";
import type { DecisionOutcome } from "@/types/api";

export default function ApprovalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { api, me } = useAuth();
  const { notify } = useToast();

  const approval = useApiData(() => api.getApproval(id), [id]);
  const decisions = useApiData(() => api.getDecisions(id), [id]);
  const [busy, setBusy] = useState(false);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");

  const a = approval.data;
  const isRequester = a?.requester_user_id === me?.user_id;
  const pending = a?.status === "pending";
  const failed = a?.status === "execution_failed";

  async function run(
    label: string,
    fn: () => Promise<DecisionOutcome>,
  ): Promise<void> {
    setBusy(true);
    try {
      const outcome = await fn();
      notify(
        `${label} — workflow ${titleCase(outcome.workflow_state)}${
          outcome.outbox_job_created ? " · job queued" : ""
        }`,
        "positive",
      );
      approval.refresh();
      decisions.refresh();
      setReason("");
      setAmount("");
    } catch (err) {
      notify(err instanceof ApiError ? err.message : `${label} failed`, "danger");
    } finally {
      setBusy(false);
    }
  }

  if (approval.loading) return <Spinner label="Loading approval" />;
  if (approval.error || !a) return <ErrorState message={approval.error ?? "Not found"} />;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/dashboard/approvals"
          className="text-sm text-slate-500 hover:underline"
        >
          ← Back to queue
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{titleCase(a.action_type)}</h1>
          <StatusBadge status={a.status} />
          <StatusBadge status={a.risk_level} />
          <SimulatedBadge />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <h2 className="mb-3 font-medium">Details</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <Detail label="Requested">{formatMoney(a.requested_amount_pence)}</Detail>
            <Detail label="Maximum">{formatMoney(a.maximum_allowed_amount_pence)}</Detail>
            <Detail label="Approved">{formatMoney(a.approved_amount_pence)}</Detail>
            <Detail label="Expires">{formatDateTime(a.expires_at)}</Detail>
            <Detail label="Created">{formatDateTime(a.created_at)}</Detail>
            <Detail label="Decided">{formatDateTime(a.decided_at)}</Detail>
            <Detail label="Idempotency key">
              <code className="text-xs">{a.idempotency_key}</code>
            </Detail>
            <Detail label="Snapshot hash">
              <code className="text-xs">{a.evidence_snapshot_hash.slice(0, 16)}…</code>
            </Detail>
            <Detail label="Citations">
              {a.policy_citation_ids.length
                ? a.policy_citation_ids.join(", ")
                : "—"}
            </Detail>
            <Detail label="Reason">{a.request_reason ?? "—"}</Detail>
          </dl>
        </Card>

        <Card>
          <h2 className="mb-3 font-medium">Decision</h2>
          {!pending && !failed ? (
            <p className="text-sm text-slate-500">
              This approval is {titleCase(a.status)}; no action is available.
            </p>
          ) : (
            <div className="space-y-3">
              {pending && canDecide(me) && !isRequester && (
                <>
                  <Field label="Approved amount (pence, optional)">
                    <input
                      type="number"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder={String(a.requested_amount_pence ?? "")}
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
                    />
                  </Field>
                  <Button
                    disabled={busy}
                    onClick={() =>
                      run("Approved", () =>
                        api.approve(id, amount ? { approved_amount_pence: Number(amount) } : {}),
                      )
                    }
                  >
                    Approve
                  </Button>
                </>
              )}
              {pending && canDecide(me) && isRequester && (
                <p className="text-sm text-amber-600">
                  You raised this request, so you cannot decide it (self-approval is
                  refused).
                </p>
              )}
              {(pending || failed) && (
                <Field label="Reason">
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
                  />
                </Field>
              )}
              <div className="flex flex-wrap gap-2">
                {pending && canDecide(me) && !isRequester && (
                  <Button
                    variant="danger"
                    disabled={busy || !reason}
                    onClick={() => run("Rejected", () => api.reject(id, reason))}
                  >
                    Reject
                  </Button>
                )}
                {pending && (isRequester || canDecide(me)) && (
                  <Button
                    variant="secondary"
                    disabled={busy || !reason}
                    onClick={() => run("Cancelled", () => api.cancel(id, reason))}
                  >
                    Cancel
                  </Button>
                )}
                {failed && canDecide(me) && !isRequester && (
                  <Button
                    disabled={busy}
                    onClick={() => run("Retry authorised", () => api.retry(id, reason))}
                  >
                    Authorise retry
                  </Button>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>

      <Card>
        <h2 className="mb-3 font-medium">Decision history</h2>
        {decisions.loading ? (
          <Spinner />
        ) : (decisions.data?.length ?? 0) === 0 ? (
          <EmptyState message="No decisions yet." />
        ) : (
          <ol className="space-y-3">
            {decisions.data!.map((d) => (
              <li key={d.id} className="flex items-start gap-3 text-sm">
                <Badge tone="neutral">{titleCase(d.decision)}</Badge>
                <div>
                  <div className="text-slate-700 dark:text-slate-300">
                    {titleCase(d.previous_status)} → {titleCase(d.new_status)}
                    <span className="ml-2 text-slate-400">({d.actor_role})</span>
                  </div>
                  <div className="text-xs text-slate-400">
                    {formatDateTime(d.created_at)}
                    {d.reason ? ` · ${d.reason}` : ""}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-slate-800 dark:text-slate-200">{children}</dd>
    </div>
  );
}
