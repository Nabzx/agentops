"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/client";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorState, Field } from "@/components/ui";
import { ThemeToggle } from "@/components/theme";

export default function LoginPage() {
  const { login, me, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && me) router.replace("/dashboard");
  }, [loading, me, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Invalid email or password."
          : err instanceof Error
            ? err.message
            : "Sign-in failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-sm">
        <div className="mb-6">
          <span className="rounded-md bg-slate-900 px-2 py-1 text-xs font-bold tracking-wide text-white dark:bg-slate-100 dark:text-slate-900">
            AgentOps
          </span>
          <h1 className="mt-3 text-xl font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-slate-500">
            Support operations console. All effects are simulated.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="Email">
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 dark:border-slate-700 dark:bg-slate-800"
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 dark:border-slate-700 dark:bg-slate-800"
            />
          </Field>
          {error && <ErrorState message={error} />}
          <Button type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
