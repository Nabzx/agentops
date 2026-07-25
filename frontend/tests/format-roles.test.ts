import { describe, expect, it } from "vitest";

import { formatMoney, relativeTime, statusTone, titleCase } from "@/lib/format";
import { canDecide, hasPermission, visibleNav } from "@/lib/roles";
import type { Me } from "@/types/api";

const agent: Me = {
  user_id: "a",
  email: "agent@x.com",
  role: "support_agent",
  permissions: ["approval_queue_read", "approval_request_create", "action_status_read"],
};
const supervisor: Me = {
  user_id: "s",
  email: "sup@x.com",
  role: "supervisor",
  permissions: [
    "approval_queue_read",
    "approval_decide",
    "action_status_read",
    "outbox_inspect",
  ],
};

describe("format", () => {
  it("formats pence as pounds", () => {
    expect(formatMoney(5900)).toBe("£59.00");
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(1)).toBe("£0.01");
  });

  it("titleCases snake/kebab", () => {
    expect(titleCase("approved_pending_execution")).toBe("Approved Pending Execution");
  });

  it("maps status to tone", () => {
    expect(statusTone("succeeded")).toBe("positive");
    expect(statusTone("dead_letter")).toBe("danger");
    expect(statusTone("execution_pending")).toBe("warning");
    expect(statusTone("received")).toBe("neutral");
  });

  it("gives relative time", () => {
    const now = Date.parse("2026-07-16T12:00:00Z");
    expect(relativeTime("2026-07-16T15:00:00Z", now)).toBe("in 3h");
    expect(relativeTime("2026-07-14T12:00:00Z", now)).toBe("2d ago");
  });
});

describe("roles", () => {
  it("gates by permission", () => {
    expect(hasPermission(agent, "outbox_inspect")).toBe(false);
    expect(hasPermission(supervisor, "outbox_inspect")).toBe(true);
    expect(hasPermission(null, "approval_queue_read")).toBe(false);
    expect(hasPermission(agent, null)).toBe(true);
  });

  it("hides outbox/audit from agents", () => {
    const agentNav = visibleNav(agent).map((n) => n.href);
    expect(agentNav).not.toContain("/dashboard/outbox");
    expect(agentNav).toContain("/dashboard/approvals");
    const supNav = visibleNav(supervisor).map((n) => n.href);
    expect(supNav).toContain("/dashboard/outbox");
    expect(supNav).toContain("/dashboard/audit");
  });

  it("only supervisors can decide", () => {
    expect(canDecide(agent)).toBe(false);
    expect(canDecide(supervisor)).toBe(true);
  });
});
