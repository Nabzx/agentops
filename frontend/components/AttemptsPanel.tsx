"use client";

import { useAuth } from "@/lib/auth";
import { useApiData } from "@/lib/useApi";
import { formatDateTime, titleCase } from "@/lib/format";
import { Badge, EmptyState, Spinner } from "@/components/ui";

export function AttemptsPanel({ jobId }: { jobId: string }) {
  const { api } = useAuth();
  const q = useApiData(() => api.outboxAttempts(jobId), [jobId]);

  if (q.loading) return <Spinner label="Loading attempts" />;
  if (q.error) return <p className="text-sm text-rose-600">{q.error}</p>;
  if ((q.data?.length ?? 0) === 0) return <EmptyState message="No attempts recorded." />;

  return (
    <ol className="space-y-2 text-sm">
      {q.data!.map((att) => (
        <li key={att.attempt_number} className="flex items-center gap-3">
          <Badge tone={att.result_status === "succeeded" ? "positive" : "warning"}>
            #{att.attempt_number}
          </Badge>
          <span className="text-slate-600 dark:text-slate-300">
            {titleCase(att.result_status ?? "started")}
          </span>
          <span className="text-xs text-slate-400">
            worker {att.worker_id} · {formatDateTime(att.started_at)}
            {att.error_code ? ` · ${att.error_code}` : ""}
            {att.retryable != null ? ` · retryable=${att.retryable}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}
