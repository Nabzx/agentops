"use client";

/** Client provider stack: theme, auth session and toasts (S9). */

import { AuthProvider } from "@/lib/auth";
import { ThemeProvider } from "@/components/theme";
import { ToastProvider } from "@/components/toast";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ToastProvider>{children}</ToastProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
