import { BANDS } from "../api/types";
import { BAND } from "../lib/format";
import { BUCKET_MS, type Bucket, type MetricsSample } from "../hooks/StreamContext";

const W = 640;
const H = 170;
const PAD = { l: 34, r: 8, t: 8, b: 20 };
const plotW = W - PAD.l - PAD.r;
const plotH = H - PAD.t - PAD.b;

const timeLabel = (t: number) => new Date(t).toLocaleTimeString([], { hour12: false });

/** Share of each band per 5 second bucket of the live feed, as 100% stacked columns on a real time axis. */
export function BandMixOverTime({ buckets }: { buckets: Bucket[] }) {
  if (buckets.length === 0) {
    return <p className="grid h-[170px] place-items-center text-xs text-ink-300">Start the replay to see the band mix change over time.</p>;
  }
  const t0 = buckets[0].t;
  const t1 = buckets[buckets.length - 1].t + BUCKET_MS;
  const span = Math.max(t1 - t0, BUCKET_MS * 6);
  const bw = Math.max(2, (BUCKET_MS / span) * plotW - 1);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Band mix over time, 100% stacked columns">
      {[0, 50, 100].map((p) => {
        const y = PAD.t + plotH * (1 - p / 100);
        return (
          <g key={p}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} stroke="#213052" strokeWidth={0.7} />
            <text x={PAD.l - 6} y={y} fontSize={9.5} fill="#6b7ca3" textAnchor="end" dominantBaseline="middle">{p}%</text>
          </g>
        );
      })}
      {buckets.map((b) => {
        const total = BANDS.reduce((n, k) => n + b.counts[k], 0);
        if (total === 0) return null;
        const x = PAD.l + ((b.t - t0) / span) * plotW;
        let acc = 0;
        return (
          <g key={b.t}>
            {BANDS.map((k) => {
              const h = (b.counts[k] / total) * plotH;
              const y = PAD.t + plotH - acc - h;
              acc += h;
              return h > 0 ? <rect key={k} x={x} y={y} width={bw} height={h} fill={BAND[k].fill} /> : null;
            })}
          </g>
        );
      })}
      <text x={PAD.l} y={H - 5} fontSize={9.5} fill="#6b7ca3">{timeLabel(t0)}</text>
      <text x={W - PAD.r} y={H - 5} fontSize={9.5} fill="#6b7ca3" textAnchor="end">{timeLabel(t1)}</text>
    </svg>
  );
}

/** p50 / p95 / p99 sampled from /metrics every 3 s, with the DESIGN latency budget as a dashed reference. */
export function LatencyOverTime({ history, budget }: { history: MetricsSample[]; budget: number }) {
  if (history.length < 2) return <p className="grid h-[170px] place-items-center text-xs text-ink-300">Collecting samples…</p>;
  const t0 = history[0].t;
  const span = Math.max(history[history.length - 1].t - t0, 1);
  const top = Math.max(budget, ...history.map((h) => h.p99)) * 1.12;
  const x = (t: number) => PAD.l + ((t - t0) / span) * plotW;
  const y = (v: number) => PAD.t + plotH * (1 - v / top);
  const series = [
    { key: "p99" as const, colour: "#f0565f", label: "p99" },
    { key: "p95" as const, colour: "#f08a3c", label: "p95" },
    { key: "p50" as const, colour: "#7fb0ff", label: "p50" },
  ];
  const ticks = [0, Math.round(top / 2 / 50) * 50, Math.round(top / 50) * 50].filter((v, i, a) => a.indexOf(v) === i);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Scoring latency percentiles over time">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="#213052" strokeWidth={0.7} />
            <text x={PAD.l - 6} y={y(v)} fontSize={9.5} fill="#6b7ca3" textAnchor="end" dominantBaseline="middle">{v}</text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={y(budget)} y2={y(budget)} stroke="#e8c14a" strokeWidth={1} strokeDasharray="4 3" />
        <text x={W - PAD.r} y={y(budget) - 4} fontSize={9.5} fill="#e8c14a" textAnchor="end">{budget} ms budget</text>
        {series.map((s) => (
          <polyline key={s.key} fill="none" stroke={s.colour} strokeWidth={1.6}
            points={history.map((h) => `${x(h.t).toFixed(1)},${y(h[s.key]).toFixed(1)}`).join(" ")} />
        ))}
        <text x={PAD.l} y={H - 5} fontSize={9.5} fill="#6b7ca3">{timeLabel(t0)}</text>
        <text x={W - PAD.r} y={H - 5} fontSize={9.5} fill="#6b7ca3" textAnchor="end">{timeLabel(history[history.length - 1].t)}</text>
      </svg>
      <div className="mt-1 flex gap-4 text-2xs text-ink-300">
        {series.slice().reverse().map((s) => (
          <span key={s.key} className="flex items-center gap-1.5"><span className="h-0.5 w-3" style={{ background: s.colour }} aria-hidden />{s.label}</span>
        ))}
      </div>
    </div>
  );
}
