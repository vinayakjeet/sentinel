import { useMemo, useState } from "react";
import { BANDS, type Band } from "../api/types";
import { DecisionTable } from "../components/DecisionTable";
import { StartStopButton } from "../components/StreamControls";
import { BAND, fmtInt, fmtMs, fmtPct } from "../lib/format";
import { useStream } from "../hooks/StreamContext";

type Filter = "ALL" | "ACTION" | Band;

const FILTERS: { id: Filter; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "ACTION", label: "Needs action" },
  ...BANDS.map((b) => ({ id: b as Filter, label: BAND[b].label })),
];

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-2xs text-ink-400">{label}</div>
      <div className="mt-0.5 text-xl font-semibold leading-tight text-ink-50">{value}</div>
      {sub && <div className="mt-0.5 text-2xs text-ink-300">{sub}</div>}
    </div>
  );
}

function MixBar({ counts, total }: { counts: Record<Band, number>; total: number }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-2xs text-ink-400">Band mix this session</div>
      <div className="mt-2 flex h-2.5 w-full overflow-hidden rounded bg-ink-700" role="img"
        aria-label={BANDS.map((b) => `${BAND[b].label} ${counts[b]}`).join(", ")}>
        {total > 0 && BANDS.map((b) => (
          <div key={b} style={{ width: `${(counts[b] / total) * 100}%`, background: BAND[b].fill }} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-2xs">
        {BANDS.map((b) => (
          <span key={b} className="flex items-center gap-1 text-ink-200">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: BAND[b].fill }} aria-hidden />
            {BAND[b].label} <span className="text-ink-50">{total ? fmtPct(counts[b] / total) : "—"}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function LiveStream() {
  const { decisions, fresh, counts, total, ratePerSec, latency, status, driftEvents } = useStream();
  const [filter, setFilter] = useState<Filter>("ALL");
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState(decisions);

  const source = paused ? frozen : decisions;
  const rows = useMemo(() => {
    if (filter === "ALL") return source;
    if (filter === "ACTION") return source.filter((d) => d.band === "REVIEW" || d.band === "DECLINE");
    return source.filter((d) => d.band === filter);
  }, [source, filter]);

  const togglePause = () => {
    if (!paused) setFrozen(decisions);
    setPaused(!paused);
  };
  const running = status?.running ?? false;

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      {driftEvents.length > 0 && (
        <div role="status" className="rounded border border-band-stepup/50 bg-band-stepup/10 px-3 py-2 text-xs text-band-stepup">
          Drift detected. Thresholds tightened from {driftEvents[0].old_thresholds.step_up}/{driftEvents[0].old_thresholds.review}/{driftEvents[0].old_thresholds.decline} to{" "}
          {driftEvents[0].new_thresholds.step_up}/{driftEvents[0].new_thresholds.review}/{driftEvents[0].new_thresholds.decline}. See Model health.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Throughput" value={<>{ratePerSec.toFixed(1)} <span className="text-xs font-normal text-ink-300">decisions/s</span></>}
          sub={running ? `Replay target ${status?.rate_per_sec ?? "—"}/s` : "Replay stopped"} />
        <Stat label="Decisions this session" value={fmtInt(total)} sub={`${fmtInt(counts.REVIEW + counts.DECLINE)} need action`} />
        <Stat label="Scoring latency p50 / p99" value={latency ? <>{fmtMs(latency.p50)} <span className="text-ink-500">/</span> {fmtMs(latency.p99)}</> : "—"}
          sub={latency ? `Last ${latency.n} decisions · latest ${fmtMs(latency.last)}` : "Waiting for decisions"} />
        <MixBar counts={counts} total={total} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Filter by band">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              aria-pressed={filter === f.id}
              className={`rounded border px-2.5 py-1 text-xs transition-colors ${
                filter === f.id ? "border-steel-dim bg-steel-dim/25 text-steel" : "border-ink-700 text-ink-300 hover:text-ink-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {paused && <span className="text-2xs text-band-stepup">Feed paused. New decisions keep counting.</span>}
          <button className="btn" onClick={togglePause}>{paused ? "Resume feed" : "Pause feed"}</button>
          <StartStopButton />
        </div>
      </div>

      <div className="panel min-h-0 flex-1 overflow-auto">
        <DecisionTable
          rows={rows}
          fresh={paused ? undefined : fresh}
          empty={
            filter === "ALL" ? (
              <div>
                <p className="text-sm text-ink-100">No decisions yet.</p>
                <p className="mt-1 text-xs">{running ? "The replay is running. The first decisions will appear here." : "The replay is stopped. An admin can start it from the button above."}</p>
              </div>
            ) : (
              <p className="text-xs">No {filter === "ACTION" ? "review or decline" : BAND[filter as Band].label.toLowerCase()} decisions in the current feed.</p>
            )
          }
        />
      </div>
    </div>
  );
}
