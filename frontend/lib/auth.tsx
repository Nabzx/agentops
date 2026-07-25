"use client";

/** Auth context: session, current user and the authenticated API client (S9). */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Api } from "@/lib/api";
import { createClient } from "@/lib/client";
import { createSessionStore } from "@/lib/session";
import type { Me } from "@/types/api";

interface AuthState {
  me: Me | null;
  api: Api;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const store = useRef(createSessionStore());
  const api = useMemo(() => new Api(createClient(store.current)), []);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  // On mount, try to restore a session from an existing refresh token.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (store.current.getRefresh()) {
        const refreshed = await api.me().then(
          (m) => m,
          () => null,
        );
        if (!cancelled && refreshed) setMe(refreshed);
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [api]);

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await api.login(email, password);
      store.current.set(tokens);
      setMe(await api.me());
    },
    [api],
  );

  const logout = useCallback(() => {
    store.current.clear();
    setMe(null);
  }, []);

  const value = useMemo(
    () => ({ me, api, loading, login, logout }),
    [me, api, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
