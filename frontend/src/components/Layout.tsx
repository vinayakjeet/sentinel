import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useStream } from "../hooks/StreamContext";

const NAV = [
  { to: "/", label: "Live stream", end: true },
  { to: "/alerts", label: "Alert queue", end: false },
  { to: "/health", label: "Model health", end: false },
];

function Mark() {
  return (
    <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden>
      <path d="M16 3l11 5v8c0 6.4-4.4 11.2-11 13.4C9.4 27.2 5 22.4 5 16V8z" fill="none" stroke="#7fb0ff" strokeWidth="2.2" />
      <circle cx="16" cy="15" r="3.4" fill="#f08a3c" />
    </svg>
  );
}

function StreamPill() {
  const { status, connection } = useStream();
  const running = status?.running ?? false;
  const linkOk = connection === "live";
  return (
    <div className="flex items-center gap-3 text-2xs text-ink-300" role="status" aria-live="polite">
      <span className="flex items-center gap-1.5">
        <span
          className={`h-2 w-2 rounded-full ${linkOk ? "bg-band-approve" : "bg-band-stepup"}`}
          aria-hidden
        />
        {linkOk ? "Feed connected" : connection === "connecting" ? "Connecting…" : "Reconnecting…"}
      </span>
      {status && (
        <span className="rounded border border-ink-600 px-1.5 py-0.5">
          Replay {running ? "running" : "stopped"} · <span className="text-ink-100">{status.source}</span> source
        </span>
      )}
    </div>
  );
}

export function Layout() {
  const { session, logout } = useAuth();
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-11 shrink-0 items-center gap-6 border-b border-ink-700 bg-ink-900 px-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink-50">
          <Mark /> Sentinel
        </div>
        <nav className="flex h-full items-stretch gap-1" aria-label="Main">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex items-center border-b-2 px-3 text-xs font-medium transition-colors ${
                  isActive ? "border-steel text-ink-50" : "border-transparent text-ink-300 hover:text-ink-50"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-5">
          <StreamPill />
          <div className="flex items-center gap-2 text-xs">
            <span className="text-ink-200">{session?.username}</span>
            <span className="rounded bg-ink-700 px-1.5 py-0.5 text-2xs text-ink-200">{session?.role}</span>
            <button className="btn" onClick={() => logout()}>Sign out</button>
          </div>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
