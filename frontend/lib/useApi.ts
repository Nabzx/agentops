"use client";

/** A tiny data-fetching hook: loading / error / data, with manual refresh (S9). */

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/client";

export interface AsyncData<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

export function useApiData<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
): AsyncData<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcher().then(
      (result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      },
      (err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.status === 403
                ? "You do not have permission to view this."
                : err.message
              : "Failed to load.",
          );
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, refresh };
}
