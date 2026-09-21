import { useState } from "react";
import { api } from "../api/client";
import type { StreamSource } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useStream } from "../hooks/StreamContext";

/** Admin actions on the replay stream. Analysts get the buttons disabled with the reason on hover. */
export function useStreamActions() {
  const { session } = useAuth();
  const { status, setStatus } = useStream();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = session?.role === "admin";

  async function run(name: string, fn: () => Promise<typeof status>) {
    setBusy(name);
    setError(null);
    try {
      const s = await fn();
      if (s) setStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stream action failed.");
    } finally {
      setBusy(null);
    }
  }

  return {
    isAdmin, busy, error, status,
    start: () => run("start", () => api.startStream()),
    stop: () => run("stop", () => api.stopStream()),
    switchTo: (source: StreamSource) => run("switch", () => api.switchStream(source)),
  };
}

export function StartStopButton() {
  const a = useStreamActions();
  const running = a.status?.running ?? false;
  return (
    <button
      className={`btn ${running ? "" : "btn-primary"}`}
      disabled={!a.isAdmin || a.busy !== null || !a.status}
      title={a.isAdmin ? undefined : "Only admins can control the replay"}
      onClick={running ? a.stop : a.start}
    >
      {a.busy === "start" ? "Starting…" : a.busy === "stop" ? "Stopping…" : running ? "Stop replay" : "Start replay"}
    </button>
  );
}
