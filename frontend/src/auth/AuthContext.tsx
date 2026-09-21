import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, configureApi } from "../api/client";
import type { Role } from "../api/types";

interface Session { token: string; role: Role; username: string; expiresAt: number }
interface AuthValue {
  session: Session | null;
  notice: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: (notice?: string) => void;
}

const KEY = "sentinel.session";
const EXPIRED = "Your session expired. Sign in again to continue.";
const Ctx = createContext<AuthValue | null>(null);

function load(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    return s.expiresAt > Date.now() ? s : null;
  } catch { return null; }
}
function save(s: Session | null) {
  try {
    if (s) sessionStorage.setItem(KEY, JSON.stringify(s)); else sessionStorage.removeItem(KEY);
  } catch { /* storage unavailable: the session just will not survive a reload */ }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(load);
  const [notice, setNotice] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(session?.token ?? null);
  tokenRef.current = session?.token ?? null;

  const logout = useCallback((msg?: string) => {
    save(null);
    tokenRef.current = null;
    setSession(null);
    setNotice(msg ?? null);
  }, []);

  useEffect(() => {
    configureApi({
      getToken: () => tokenRef.current,
      onUnauthorized: () => { if (tokenRef.current) logout(EXPIRED); },
    });
  }, [logout]);

  // Tokens last 60 minutes; sign out at expiry instead of waiting for the first 401.
  useEffect(() => {
    if (!session) return;
    const t = window.setTimeout(() => logout(EXPIRED), Math.max(0, session.expiresAt - Date.now()));
    return () => window.clearTimeout(t);
  }, [session, logout]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    const next: Session = {
      token: res.access_token, role: res.role, username, expiresAt: Date.now() + res.expires_in * 1000 - 5000,
    };
    tokenRef.current = next.token;
    save(next);
    setNotice(null);
    setSession(next);
  }, []);

  const value = useMemo(() => ({ session, notice, login, logout }), [session, notice, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
