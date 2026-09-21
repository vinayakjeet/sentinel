import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { fmtDateTime, fmtPct } from "../lib/format";
import { BandBadge } from "./BandBadge";

export function SimilarCases({ decisionId }: { decisionId: string }) {
  const { data, error, loading, reload } = useAsync(() => api.similar(decisionId, 5), [decisionId]);

  if (loading) return <p className="text-xs text-ink-300">Finding similar cases…</p>;
  if (error) {
    return (
      <div className="text-xs">
        <p className="text-band-decline">Could not load similar cases: {error}</p>
        <button className="btn mt-2" onClick={reload}>Try again</button>
      </div>
    );
  }
  const items = data?.items ?? [];
  if (items.length === 0) {
    return <p className="text-xs text-ink-300">No similar cases yet. This case's embedding is created shortly after the decision is made.</p>;
  }
  return (
    <ul className="divide-y divide-ink-800">
      {items.map((c) => (
        <li key={c.decision_id}>
          <Link to={`/cases/${c.decision_id}`} className="block rounded px-1 py-2 hover:bg-ink-800/60">
            <div className="flex items-center gap-2">
              <BandBadge band={c.band} />
              <span className="text-xs font-semibold text-ink-50">{c.score}</span>
              <span className="ml-auto text-2xs text-ink-300" title="Cosine similarity of the case narratives">
                {fmtPct(c.similarity, 1)} similar
              </span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-ink-200">{c.top_reasons[0] ?? "No reason recorded"}</p>
            <p className="mt-0.5 text-2xs text-ink-500">{fmtDateTime(c.created_at)}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
