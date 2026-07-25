"use client";

/** Minimal toast notifications for action outcomes (S9). */

import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type { Tone } from "@/lib/format";

interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

const ToastContext = createContext<{ notify: (m: string, tone?: Tone) => void } | null>(
  null,
);

const TONE: Record<Tone, string> = {
  neutral: "bg-slate-800 text-white",
  positive: "bg-emerald-600 text-white",
  warning: "bg-amber-600 text-white",
  danger: "bg-rose-600 text-white",
  info: "bg-sky-600 text-white",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((message: string, tone: Tone = "neutral") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded-lg px-4 py-2 text-sm shadow-lg ${TONE[t.tone]}`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): { notify: (m: string, tone?: Tone) => void } {
  const ctx = useContext(ToastContext);
  if (!ctx) return { notify: () => undefined };
  return ctx;
}
