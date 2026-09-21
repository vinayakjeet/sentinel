import type { ReasonCode } from "../api/types";

/** Top reason codes, ranked. Bar length is each reason's share of the strongest one, from the SHAP contribution. */
export function ReasonBars({ reasons }: { reasons: ReasonCode[] }) {
  if (reasons.length === 0) return <p className="text-xs text-ink-300">No reason codes were recorded for this decision.</p>;
  const max = Math.max(...reasons.map((r) => r.contribution), 1e-9);
  return (
    <ol className="space-y-3">
      {reasons.map((r, i) => (
        <li key={r.feature} className="grid grid-cols-[1.25rem_1fr] gap-x-2">
          <span className="pt-0.5 text-right text-xs font-semibold text-ink-400">{i + 1}</span>
          <div className="min-w-0">
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-[13px] leading-snug text-ink-50">{r.reason}</p>
              <span className="shrink-0 text-xs text-ink-200" title="SHAP contribution toward fraud (log-odds)">
                +{r.contribution.toFixed(2)}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded bg-ink-700" aria-hidden>
              <div className="h-full rounded bg-steel" style={{ width: `${Math.max(3, (r.contribution / max) * 100)}%` }} />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-2xs">
              <span className="rounded border border-ink-600 px-1.5 py-0.5 text-ink-200">{r.ecoa_category}</span>
              <span className="text-ink-500">{r.feature}</span>
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
