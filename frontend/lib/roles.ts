/** Role-aware navigation and capability helpers (S9).
 *
 * The UI hides what a role cannot use, but the backend remains the authority — a
 * hidden action is still refused with 403 if attempted, and the UI surfaces that.
 */

import type { Me, Role } from "@/types/api";

export interface NavItem {
  href: string;
  label: string;
  /** Permission required to see this item, or null for any authenticated user. */
  permission: string | null;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Overview", permission: null },
  { href: "/dashboard/approvals", label: "Approvals", permission: "approval_queue_read" },
  { href: "/dashboard/actions", label: "Actions", permission: "action_status_read" },
  { href: "/dashboard/outbox", label: "Outbox", permission: "outbox_inspect" },
  { href: "/dashboard/audit", label: "Audit", permission: "outbox_inspect" },
  { href: "/dashboard/health", label: "Health", permission: null },
];

export function hasPermission(me: Me | null, permission: string | null): boolean {
  if (permission === null) return true;
  if (!me) return false;
  return me.permissions.includes(permission);
}

export function visibleNav(me: Me | null): NavItem[] {
  return NAV_ITEMS.filter((item) => hasPermission(me, item.permission));
}

export function canDecide(me: Me | null): boolean {
  return hasPermission(me, "approval_decide");
}

export function canRequest(me: Me | null): boolean {
  return hasPermission(me, "approval_request_create");
}

export function roleLabel(role: Role | string): string {
  return role === "supervisor" ? "Supervisor" : "Support Agent";
}
