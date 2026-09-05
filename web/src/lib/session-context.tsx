"use client";

/**
 * The current point of view (PRD section 5.5) plus the roster, shared by
 * every client component: /who, the header account menu, and the People
 * page. Switching accounts updates this context in place — no navigation,
 * no reload (acceptance criterion 42).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { api, ApiRequestError } from "./api";
import type { MeUser, RosterUser, SessionResponse, UsersListResponse } from "./types";

interface SessionContextValue {
  /** null once the initial check has run and no session cookie is valid. */
  user: MeUser | null;
  /** Everyone sees the roster (section 5.5) — loaded once, unauthenticated. */
  roster: RosterUser[];
  /** True until the first /auth/me + /users round trip resolves. */
  loading: boolean;
  /** Chooses an account and makes it the session. Used by /who and the switcher. */
  chooseAccount: (userId: string) => Promise<void>;
  /** Re-fetches the roster, e.g. after /people adds or edits someone. */
  refreshRoster: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeUser | null>(null);
  const [roster, setRoster] = useState<RosterUser[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshRoster = useCallback(async () => {
    const res = await api.get<UsersListResponse>("/users");
    setRoster(res.items);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const res = await api.get<UsersListResponse>("/users");
        if (!cancelled) setRoster(res.items);
      } catch {
        // The roster read has no auth requirement (section 5.5); a failure
        // here means the API itself is unreachable, not that we're signed
        // out. Leave the roster empty and let the page's own state show it.
      }
      try {
        const me = await api.get<{ user: MeUser }>("/auth/me");
        if (!cancelled) setUser(me.user);
      } catch (err) {
        if (!cancelled && err instanceof ApiRequestError && err.isUnauthenticated) {
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  const chooseAccount = useCallback(async (userId: string) => {
    const res = await api.post<SessionResponse>("/auth/session", { user_id: userId });
    setUser(res.user);
  }, []);

  return (
    <SessionContext.Provider value={{ user, roster, loading, chooseAccount, refreshRoster }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return ctx;
}
