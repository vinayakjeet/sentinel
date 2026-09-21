import { useNavigate } from "react-router-dom";
import type { DecisionResponse } from "../api/types";
import { BAND, fmtMs, fmtTime } from "../lib/format";
import { BandBadge, ScoreBar } from "./BandBadge";

export type SortKey = "created_at" | "score" | "latency_ms";
export interface SortState { key: SortKey; dir: "asc" | "desc" }

interface Props {
  rows: DecisionResponse[];
  fresh?: ReadonlySet<string>;
  sort?: SortState;
  onSort?: (key: SortKey) => void;
  empty: React.ReactNode;
}

function SortHeader({ label, k, sort, onSort }: { label: string; k: SortKey; sort?: SortState; onSort?: (k: SortKey) => void }) {
  if (!onSort) return <th className="th">{label}</th>;
  const active = sort?.key === k;
  return (
    <th className="th" aria-sort={active ? (sort!.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button className={`inline-flex items-center gap-1 hover:text-ink-50 ${active ? "text-ink-50" : ""}`} onClick={() => onSort(k)}>
        {label}
        <span aria-hidden className="w-2 text-steel">{active ? (sort!.dir === "asc" ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );
}

export function DecisionTable({ rows, fresh, sort, onSort, empty }: Props) {
  const nav = useNavigate();
  if (rows.length === 0) return <div className="grid h-full min-h-40 place-items-center p-8 text-center text-ink-300">{empty}</div>;

  return (
    <table className="w-full border-collapse text-xs">
      <thead className="sticky top-0 z-10 bg-ink-900 shadow-[0_1px_0_#213052]">
        <tr>
          <SortHeader label="Time" k="created_at" sort={sort} onSort={onSort} />
          <th className="th">Band</th>
          <SortHeader label="Score" k="score" sort={sort} onSort={onSort} />
          <th className="th">Outcome</th>
          <th className="th">Lead reason</th>
          <th className="th">Linked apps</th>
          <th className="th">Graph uplift</th>
          <SortHeader label="Latency" k="latency_ms" sort={sort} onSort={onSort} />
          <th className="th">Reference</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((d) => {
          const lead = d.reason_codes[0];
          const open = () => nav(`/cases/${d.decision_id}`);
          return (
            <tr
              key={d.decision_id}
              onClick={open}
              className={`cursor-pointer border-b border-ink-800 border-l-2 hover:bg-ink-800/70 ${fresh?.has(d.decision_id) ? "row-new" : ""}`}
              style={{ borderLeftColor: BAND[d.band].fill }}
            >
              <td className="td text-ink-300">
                <a
                  href={`/cases/${d.decision_id}`}
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); open(); }}
                  className="hover:text-steel hover:underline"
                >
                  {fmtTime(d.created_at)}
                </a>
              </td>
              <td className="td"><BandBadge band={d.band} /></td>
              <td className="td"><ScoreBar score={d.score} band={d.band} /></td>
              <td className="td text-ink-200">{d.decision.replace("_", " ")}</td>
              <td className="td max-w-[26rem] truncate text-ink-200" title={lead?.reason}>
                {lead ? lead.reason : <span className="text-ink-500">—</span>}
              </td>
              <td className="td text-ink-200">{d.graph_signals.component_size ?? 0}</td>
              <td className="td text-ink-200">{d.graph_uplift > 0 ? `+${Math.round(d.graph_uplift * 1000)} pts` : <span className="text-ink-500">none</span>}</td>
              <td className="td text-ink-300">{fmtMs(d.latency_ms)}</td>
              <td className="td text-ink-400">{d.external_ref ?? d.decision_id.slice(0, 8)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
