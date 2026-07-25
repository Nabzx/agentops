/** Pure display formatters (S9). Kept side-effect free so they are easy to unit test. */

export function formatMoney(pence: number | null | undefined, currency = "GBP"): string {
  if (pence === null || pence === undefined) return "—";
  const symbol = currency === "GBP" ? "£" : "";
  return `${symbol}${(pence / 100).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** A short, human relative label such as "in 3h" or "2d ago". */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return "—";
  const diffMs = target - now;
  const abs = Math.abs(diffMs);
  const units: [number, string][] = [
    [86_400_000, "d"],
    [3_600_000, "h"],
    [60_000, "m"],
    [1000, "s"],
  ];
  for (const [ms, label] of units) {
    if (abs >= ms) {
      const value = Math.round(abs / ms);
      return diffMs >= 0 ? `in ${value}${label}` : `${value}${label} ago`;
    }
  }
  return "now";
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export type Tone = "neutral" | "positive" | "warning" | "danger" | "info";

/** Map a backend status string to a display tone for badges. */
export function statusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (["succeeded", "executed", "action_succeeded", "approved", "ok", "resolved", "completed"].some((k) => s.includes(k)))
    return "positive";
  if (["failed", "dead_letter", "rejected", "blocked", "error", "cancelled"].some((k) => s.includes(k)))
    return "danger";
  if (["pending", "processing", "retry", "awaiting", "manual", "expired", "execution_pending"].some((k) => s.includes(k)))
    return "warning";
  return "neutral";
}
