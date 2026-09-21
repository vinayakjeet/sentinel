import type { Band } from "../api/types";
import { BAND } from "../lib/format";

export function BandBadge({ band, className = "" }: { band: Band; className?: string }) {
  const m = BAND[band];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-2xs font-semibold ${m.text} ${m.bg} ${m.border}/40 ${className}`}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: m.fill }} aria-hidden />
      {m.label}
    </span>
  );
}

export function ScoreBar({ score, band }: { score: number; band: Band }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="w-9 text-right font-semibold text-ink-50">{score}</span>
      <span className="relative h-1 w-14 overflow-hidden rounded bg-ink-700" aria-hidden>
        <span className="absolute inset-y-0 left-0 rounded" style={{ width: `${Math.min(100, score / 10)}%`, background: BAND[band].fill }} />
      </span>
    </span>
  );
}
