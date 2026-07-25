"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/ui";

export default function Home() {
  const { me, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(me ? "/dashboard" : "/login");
  }, [me, loading, router]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <Spinner label="Starting AgentOps" />
    </main>
  );
}
