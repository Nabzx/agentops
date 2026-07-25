"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";
import { roleLabel, visibleNav } from "@/lib/roles";
import { Button, Spinner } from "@/components/ui";
import { ThemeToggle } from "@/components/theme";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { me, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);

  if (loading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading session" />
      </div>
    );
  }

  const nav = visibleNav(me);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <span className="rounded-md bg-slate-900 px-2 py-1 text-xs font-bold tracking-wide text-white dark:bg-slate-100 dark:text-slate-900">
            AgentOps
          </span>
          <nav className="flex flex-1 flex-wrap items-center gap-1 text-sm">
            {nav.map((item) => {
              const active =
                pathname === item.href ||
                (item.href !== "/dashboard" && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-lg px-3 py-1.5 font-medium transition ${
                    active
                      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-3">
            <span className="hidden text-right text-xs text-slate-500 sm:block">
              <span className="block font-medium text-slate-700 dark:text-slate-300">
                {roleLabel(me.role)}
              </span>
              {me.email}
            </span>
            <ThemeToggle />
            <Button variant="ghost" onClick={logout}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-slate-400">
        Demonstration environment — every refund, cancellation and effect is simulated.
      </footer>
    </div>
  );
}
