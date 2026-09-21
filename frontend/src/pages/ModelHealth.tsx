import { useEffect, useState } from "react";
import { api } from "../api/client";
import { BANDS, type DriftStatus, type Thresholds } from "../api/types";
import { BandMixOverTime, LatencyOverTime } from "../components/charts";
import { StartStopButton, useStreamActions } from "../components/StreamControls";
import { useStream } from "../hooks/StreamContext";
import { BAND, fmtDateTime, fmtInt, fmtMs, fmtPct } from "../lib/format";

const LATENCY_BUDGET_MS = 200; // DESIGN section 11

const trio = (t: Thresholds) => `${t.step_up} / ${t.review} / ${t.decline}`;

function Panel({ title, note, children, className = "" }: { title: string; note?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`panel p-4 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="panel-title">{title}</h2>
        {note && <span className="text-2xs text-ink-400">{note}</span>}
      </div>
      {children}
    </section>
  );
}

function Tile({ label, value, sub, warn }: { label: string; value: React.ReactNode; sub?: React.ReactNode; warn?: boolean }) {
  return (
    <div className={`panel px-4 py-3 ${warn ? "border-band-stepup/60" : ""}`}>
      <div className="text-2xs text-ink-400">{label}</div>
      <div className={`mt-0.5 text-2xl font-semibold leading-tight ${warn ? "text-band-stepup" : "text-ink-50"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-2xs text-ink-300">{sub}</div>}
    </div>
  );
}

function DriftBanner({ drift, onReset, canReset, resetting }: { drift: DriftStatus | null; onReset: () => void; canReset: boolean; resetting: boolean }) {
  if (!drift) return <div className="panel px-4 py-3 text-xs text-ink-300">Loading drift status…</div>;
  const drifted = drift.state === "drift_detected";
  const last = drift.events[0];
  return (
    <div
      role="status"
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border px-4 py-3 ${
        drifted ? "border-band-stepup/60 bg-band-stepup/10" : "border-band-approve/40 bg-band-approve/10"
      }`}
    >
      <span className={`h-2.5 w-2.5 rounded-full ${drifted ? "bg-band-stepup" : "bg-band-approve"}`} aria-hidden />
      <div>
        <p className={`text-sm font-semibold ${drifted ? "text-band-stepup" : "text-band-approve"}`}>
          {drifted ? "Drift detected" : "Stable"}
        </p>
        <p className="text-xs text-ink-200">
          {drifted
            ? <>Score distribution shifted{last ? ` at ${fmtDateTime(last.ts)}` : ""}. Decision thresholds were tightened to {trio(drift.thresholds)} (baseline {trio(drift.base_thresholds)}).</>
            : <>No drift detected. Decision thresholds are at baseline {trio(drift.base_thresholds)}.</>}
        </p>
      </div>
      {drifted && (
        <button className="btn ml-auto" onClick={onReset} disabled={!canReset || resetting}
          title={canReset ? "Restore baseline thresholds and clear the drift state" : "Only admins can reset drift"}>
          {resetting ? "Resetting…" : "Reset drift"}
        </button>
      )}
    </div>
  );
}

function ReplayPanel() {
  const a = useStreamActions();
  const s = a.status;
  const target = s?.source === "shift" ? "base" : "shift";
  return (
    <Panel title="Replay stream" note={s ? `${fmtInt(s.events_emitted)} events emitted` : undefined}>
      <dl className="grid grid-cols-3 gap-3 text-xs">
        <div><dt className="text-2xs text-ink-400">State</dt><dd className="text-ink-50">{s ? (s.running ? "Running" : "Stopped") : "—"}</dd></div>
        <div><dt className="text-2xs text-ink-400">Source</dt><dd className="text-ink-50">{s ? (s.source === "shift" ? "Shifted" : "Base") : "—"}</dd></div>
        <div><dt className="text-2xs text-ink-400">Rate</dt><dd className="text-ink-50">{s ? `${s.rate_per_sec}/s` : "—"}</dd></div>
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="btn btn-primary"
          disabled={!a.isAdmin || a.busy !== null || !s}
          title={a.isAdmin ? undefined : "Only admins can switch the stream source"}
          onClick={() => a.switchTo(target)}
        >
          {a.busy === "switch" ? "Switching…" : `Switch stream source to ${target === "shift" ? "shifted" : "base"}`}
        </button>
        <StartStopButton />
      </div>
      {!a.isAdmin && <p className="mt-2 text-2xs text-ink-400">Signed in as an analyst. Stream controls need an admin.</p>}
      {a.error && <p role="alert" className="mt-2 text-xs text-band-decline">{a.error}</p>}
      <p className="mt-3 text-2xs leading-relaxed text-ink-400">
        The shifted source replays variant data with a simulated fraud wave added (default 12% fraud rate). It is a demonstration of drift
        handling, not a real-world shift.
      </p>
    </Panel>
  );
}

function ThresholdsPanel({ drift }: { drift: DriftStatus | null }) {
  const rows: { key: keyof Thresholds; label: string; to: string }[] = [
    { key: "step_up", label: "Step up from", to: "Step up" },
    { key: "review", label: "Review from", to: "Review" },
    { key: "decline", label: "Decline from", to: "Decline" },
  ];
  return (
    <Panel title="Decision thresholds" note="Score, 0 to 1000">
      {!drift ? <p className="text-xs text-ink-300">Loading…</p> : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-2xs text-ink-400">
              <th className="py-1 font-medium">Band edge</th><th className="py-1 text-right font-medium">Baseline</th>
              <th className="py-1 text-right font-medium">Current</th><th className="py-1 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const base = drift.base_thresholds[r.key];
              const cur = drift.thresholds[r.key];
              return (
                <tr key={r.key} className="border-t border-ink-800">
                  <td className="py-1.5 text-ink-100">{r.label}</td>
                  <td className="py-1.5 text-right text-ink-300">{base}</td>
                  <td className="py-1.5 text-right font-semibold text-ink-50">{cur}</td>
                  <td className={`py-1.5 text-right ${cur === base ? "text-ink-500" : "text-band-stepup"}`}>{cur === base ? "none" : `${cur - base}`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-2xs text-ink-400">Lower edges send more applications to review or decline.</p>
    </Panel>
  );
}

function DriftLog({ drift }: { drift: DriftStatus | null }) {
  const events = drift?.events ?? [];
  return (
    <Panel title="Drift event log" note={`${events.length} event${events.length === 1 ? "" : "s"}`}>
      {events.length === 0 ? (
        <p className="text-xs text-ink-300">No drift events yet. Switch the stream to the shifted source to trigger one.</p>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>{["Time", "Detector", "Stream", "Thresholds before", "Thresholds after", "Evidence"].map((h) => <th key={h} className="th px-2">{h}</th>)}</tr>
            </thead>
            <tbody>
              {events.map((e) => {
                const d = e.details as Record<string, unknown>;
                const bits = [
                  typeof d.source === "string" ? `source ${d.source}` : null,
                  typeof d.events_seen === "number" ? `${fmtInt(d.events_seen)} events seen` : null,
                  typeof d.window_mean === "number" ? `window mean ${d.window_mean}` : null,
                  typeof d.adwin_delta === "number" ? `delta ${d.adwin_delta}` : null,
                ].filter(Boolean);
                return (
                  <tr key={e.id} className="border-t border-ink-800">
                    <td className="td px-2 text-ink-200">{fmtDateTime(e.ts)}</td>
                    <td className="td px-2 text-ink-100">{e.detector}</td>
                    <td className="td px-2 text-ink-100">{e.stream}</td>
                    <td className="td px-2 text-ink-300">{trio(e.old_thresholds)}</td>
                    <td className="td px-2 text-band-stepup">{trio(e.new_thresholds)}</td>
                    <td className="td px-2 text-ink-400">{bits.join(", ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export function ModelHealth() {
  const { metrics, metricsHistory, buckets, driftEvents, connection } = useStream();
  const { isAdmin } = useStreamActions();
  const [drift, setDrift] = useState<DriftStatus | null>(null);
  const [driftError, setDriftError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  // Poll every 3 s, and refetch straight away when the live feed announces a drift event.
  useEffect(() => {
    let cancelled = false;
    const load = () => api.drift().then((d) => { if (!cancelled) { setDrift(d); setDriftError(null); } })
      .catch((e: unknown) => { if (!cancelled) setDriftError(e instanceof Error ? e.message : "Could not load drift status."); });
    load();
    const t = window.setInterval(load, 3000);
    return () => { cancelled = true; window.clearInterval(t); };
  }, [driftEvents.length]);

  async function reset() {
    setResetting(true);
    try { setDrift(await api.resetDrift()); } catch (e) { setDriftError(e instanceof Error ? e.message : "Reset failed."); } finally { setResetting(false); }
  }

  const overBudget = (metrics?.p99 ?? 0) > LATENCY_BUDGET_MS;

  return (
    <div className="mx-auto max-w-[1500px] space-y-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-semibold text-ink-50">Model health</h1>
        {connection !== "live" && <span className="text-2xs text-band-stepup">Live feed {connection}. Numbers may be stale.</span>}
      </div>

      {driftError && <p role="alert" className="rounded border border-band-decline/40 bg-band-decline/10 px-3 py-2 text-xs text-band-decline">{driftError}</p>}
      <DriftBanner drift={drift} onReset={reset} canReset={isAdmin} resetting={resetting} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Tile label="Latency p50" value={fmtMs(metrics?.p50)} sub={metrics ? `Last ${fmtInt(metrics.window)} decisions` : undefined} />
        <Tile label="Latency p95" value={fmtMs(metrics?.p95)} />
        <Tile label="Latency p99" value={fmtMs(metrics?.p99)} warn={overBudget}
          sub={overBudget ? `Over the ${LATENCY_BUDGET_MS} ms budget` : `Within the ${LATENCY_BUDGET_MS} ms budget`} />
        <Tile label="Throughput" value={<>{metrics ? metrics.decisions_per_sec.toFixed(1) : "—"} <span className="text-xs font-normal text-ink-300">/s</span></>} />
        <Tile label="Decisions recorded" value={metrics ? fmtInt(metrics.total_decisions) : "—"} sub="Since the API started" />
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Panel title="Band mix over time" note="Live feed, 5 s columns" className="lg:col-span-8">
          <BandMixOverTime buckets={buckets} />
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-ink-300">
            {BANDS.map((b) => (
              <span key={b} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm" style={{ background: BAND[b].fill }} aria-hidden />
                {BAND[b].label} {metrics ? <span className="text-ink-100">{fmtPct(metrics.band_mix[b] ?? 0, 1)}</span> : null}
              </span>
            ))}
            <span className="ml-auto text-ink-500">Percentages are the server window of {metrics ? fmtInt(metrics.window) : "—"} decisions</span>
          </div>
        </Panel>
        <div className="space-y-4 lg:col-span-4">
          <ReplayPanel />
        </div>

        <Panel title="Scoring latency over time" note="Sampled every 3 s" className="lg:col-span-8">
          <LatencyOverTime history={metricsHistory} budget={LATENCY_BUDGET_MS} />
        </Panel>
        <div className="lg:col-span-4"><ThresholdsPanel drift={drift} /></div>

        <div className="lg:col-span-12"><DriftLog drift={drift} /></div>
      </div>
    </div>
  );
}
