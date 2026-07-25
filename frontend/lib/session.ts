/** Browser token store (S9).
 *
 * The access token is kept in memory; the refresh token in sessionStorage so a page
 * reload keeps the session but closing the tab ends it. Nothing is written to
 * localStorage, and tokens are never rendered.
 */

import type { TokenStore } from "@/lib/client";
import type { TokenPair } from "@/types/api";

const REFRESH_KEY = "agentops.refresh";

export function createSessionStore(): TokenStore {
  let access: string | null = null;

  const readRefresh = (): string | null => {
    if (typeof window === "undefined") return null;
    return window.sessionStorage.getItem(REFRESH_KEY);
  };

  return {
    getAccess: () => access,
    getRefresh: readRefresh,
    set: (tokens: TokenPair) => {
      access = tokens.access_token;
      if (typeof window !== "undefined" && tokens.refresh_token) {
        window.sessionStorage.setItem(REFRESH_KEY, tokens.refresh_token);
      }
    },
    clear: () => {
      access = null;
      if (typeof window !== "undefined") {
        window.sessionStorage.removeItem(REFRESH_KEY);
      }
    },
  };
}
