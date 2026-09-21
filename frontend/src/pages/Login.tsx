import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";

export function Login() {
  const { login, notice } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError("Username or password is incorrect.");
      else if (err instanceof ApiError && err.status === 429) setError("Too many sign-in attempts. Wait a minute and try again.");
      else setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-full place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <svg width="34" height="34" viewBox="0 0 32 32" aria-hidden>
            <path d="M16 3l11 5v8c0 6.4-4.4 11.2-11 13.4C9.4 27.2 5 22.4 5 16V8z" fill="none" stroke="#7fb0ff" strokeWidth="2" />
            <circle cx="16" cy="15" r="3.4" fill="#f08a3c" />
          </svg>
          <div>
            <h1 className="text-xl font-semibold text-ink-50">Sentinel</h1>
            <p className="text-xs text-ink-300">Application fraud operations for digital lending</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="panel space-y-4 p-5" aria-describedby={error ? "login-error" : undefined}>
          <h2 className="text-sm font-semibold text-ink-50">Sign in</h2>
          {notice && <p className="rounded border border-band-stepup/40 bg-band-stepup/10 px-3 py-2 text-xs text-band-stepup">{notice}</p>}
          <label className="block space-y-1.5">
            <span className="text-xs text-ink-300">Username</span>
            <input className="input" autoComplete="username" autoFocus required value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs text-ink-300">Password</span>
            <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <p id="login-error" role="alert" className="text-xs text-band-decline">{error}</p>}
          <button className="btn btn-primary w-full py-2" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-2xs text-ink-400">
          Analysts can review decisions. Admins can also control the replay stream and reset drift.
        </p>
      </div>
    </div>
  );
}
