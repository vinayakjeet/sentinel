import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Band, DecisionResponse } from "../api/types";
import { DecisionTable, type SortKey, type SortState } from "../components/DecisionTable";
import { BAND, fmtInt } from "../lib/format";

const PER_BAND = 200; // API maximum per request
const ALERT_BANDS: Band[] = ["DECLINE", "REVIEW"];

export function AlertQueue() {
  const [rows, setRows] = useState<DecisionResponse[]>([]);
  const [totals, setTotals] = useState<Record<string, number>>({});
  const [bands, setBands] = useState<Set<Band>>(new Set(ALERT_BANDS));
  const [sort, setSort] = useState<SortState>({ key: "score", dir: "desc" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await Promise.all(ALERT_BANDS.map((band) => api.decisions({ band, limit: PER_BAND })));
      setRows(res.flatMap((r) => r.items));
      setTotals(Object.fromEntries(ALERT_BANDS.map((b, i) => [b, res[i].total])));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load alerts.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 10000);
    return () => window.clearInterval(t);
  }, [load]);

  const sorted = useMemo(() => {
    const dir = sort.dir === "asc" ? 1 : -1;
    const val = (d: DecisionResponse) => (sort.key === "created_at" ? Date.parse(d.created_at) : d[sort.key]);
    return rows.filter((d) => bands.has(d.band)).sort((a, b) => (val(a) - val(b)) * dir);
  }, [rows, bands, sort]);

  const onSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  const toggle = (b: Band) =>
    setBands((cur) => {
      const next = new Set(cur);
      if (next.has(b)) next.delete(b); else next.add(b);
      return next.size === 0 ? cur : next;
    });

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-sm font-semibold text-ink-50">Alert queue</h1>
        <div className="flex gap-1" role="group" aria-label="Bands to show">
          {ALERT_BANDS.map((b) => (
            <button
              key={b}
              aria-pressed={bands.has(b)}
              onClick={() => toggle(b)}
              className={`rounded border px-2.5 py-1 text-xs ${bands.has(b) ? `${BAND[b].border}/60 ${BAND[b].bg} ${BAND[b].text}` : "border-ink-700 text-ink-400"}`}
            >
              {BAND[b].label} {totals[b] != null && <span className="text-ink-200">{fmtInt(totals[b])}</span>}
            </button>
          ))}
        </div>
        <span className="text-2xs text-ink-400">
          Showing the latest {PER_BAND} per band, refreshed every 10 s. Sort a column to rank them.
        </span>
        <button className="btn ml-auto" onClick={() => void load()}>Refresh</button>
      </div>

      {error && <p role="alert" className="rounded border border-band-decline/40 bg-band-decline/10 px-3 py-2 text-xs text-band-decline">{error}</p>}

      <div className="panel min-h-0 flex-1 overflow-auto">
        {loading ? (
          <p className="p-6 text-ink-300">Loading alerts…</p>
        ) : (
          <DecisionTable
            rows={sorted}
            sort={sort}
            onSort={onSort}
            empty={<p className="text-xs">No review or decline decisions yet. They appear here as applications are scored.</p>}
          />
        )}
      </div>
    </div>
  );
}
