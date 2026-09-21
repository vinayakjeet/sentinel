import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { BandBadge } from "../components/BandBadge";
import { CopilotChat } from "../components/CopilotChat";
import { EntityGraphView } from "../components/EntityGraphView";
import { GraphSignals } from "../components/GraphSignals";
import { ReasonBars } from "../components/ReasonBars";
import { ScoreGauge } from "../components/ScoreGauge";
import { SimilarCases } from "../components/SimilarCases";
import { useAsync } from "../hooks/useAsync";
import { fmtDateTime, fmtMs } from "../lib/format";

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

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-2xs text-ink-400">{label}</dt>
      <dd className="text-xs text-ink-100">{value}</dd>
    </div>
  );
}

function AdverseAction({ decisionId }: { decisionId: string }) {
  const { data, error, loading } = useAsync(() => api.adverseAction(decisionId), [decisionId]);
  if (loading) return <p className="text-xs text-ink-300">Loading notice…</p>;
  if (error || !data) return <p className="text-xs text-ink-300">No adverse action notice is available for this decision.</p>;
  return (
    <div className="space-y-3 text-xs">
      <p className="text-ink-200">Applicant-facing reasons under Reg B. Raw model features are not disclosed.</p>
      <ol className="list-decimal space-y-1 pl-5 text-ink-100">
        {data.principal_reasons.map((r) => <li key={r.rank}>{r.reason} <span className="text-ink-400">({r.ecoa_category})</span></li>)}
      </ol>
      <p className="text-ink-300">{data.ecoa_notice}</p>
      <p className="text-ink-300">{data.right_to_request_reasons}</p>
    </div>
  );
}

export default function CaseDetail() {
  const { decisionId = "" } = useParams();
  const nav = useNavigate();
  const decision = useAsync(() => api.decision(decisionId), [decisionId]);
  const thresholds = useAsync(() => api.drift(), [decisionId]);
  const d = decision.data;
  const graph = useAsync(() => (d ? api.graph(d.application_id) : Promise.resolve(null)), [d?.application_id]);

  if (decision.loading && !d) return <p className="p-6 text-ink-300">Loading case…</p>;
  if (decision.error || !d) {
    const missing = decision.error && /not found|404/i.test(decision.error);
    return (
      <div className="p-6">
        <p className="text-sm text-ink-50">{missing ? "This case does not exist." : "Could not load this case."}</p>
        <p className="mt-1 text-xs text-ink-300">{decision.error}</p>
        <div className="mt-3 flex gap-2">
          <button className="btn" onClick={() => nav(-1)}>Go back</button>
          {!missing && <button className="btn" onClick={decision.reload}>Try again</button>}
        </div>
      </div>
    );
  }
  const action = d.band !== "APPROVE";

  return (
    <div className="mx-auto max-w-[1500px] space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <button className="btn" onClick={() => nav(-1)}>Back</button>
        <div>
          <h1 className="text-base font-semibold text-ink-50">Case {d.external_ref ?? d.decision_id.slice(0, 8)}</h1>
          <p className="text-2xs text-ink-400">Decision {d.decision_id}</p>
        </div>
        <BandBadge band={d.band} className="text-xs" />
        <dl className="ml-auto grid grid-cols-2 gap-x-8 gap-y-1 sm:grid-cols-4">
          <Meta label="Outcome" value={d.decision.replace("_", " ")} />
          <Meta label="Decided" value={fmtDateTime(d.created_at)} />
          <Meta label="Model" value={d.model_version} />
          <Meta label="Scoring latency" value={fmtMs(d.latency_ms)} />
        </dl>
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <Panel title="Risk score" className="lg:col-span-4">
          <ScoreGauge score={d.score} band={d.band} thresholds={thresholds.data?.thresholds ?? null} />
        </Panel>
        <Panel title="Why this score" note="Top 4 reasons, by SHAP contribution" className="lg:col-span-8">
          <ReasonBars reasons={d.reason_codes} />
        </Panel>

        <Panel title="Entity graph" note="Applications linked through shared identifiers" className="lg:col-span-7">
          {graph.loading && <p className="text-xs text-ink-300">Loading graph…</p>}
          {graph.error && (
            <p className="text-xs text-band-decline">
              Could not load the graph{graph.error ? `: ${graph.error}` : ""}. <button className="underline" onClick={graph.reload}>Try again</button>
            </p>
          )}
          {graph.data && <EntityGraphView graph={graph.data} />}
          <div className="mt-4 border-t border-ink-800 pt-3">
            <GraphSignals signals={d.graph_signals} uplift={d.graph_uplift} />
          </div>
        </Panel>

        <div className="space-y-4 lg:col-span-5">
          <Panel title="Similar past cases" note="Look alike, not necessarily connected">
            <SimilarCases decisionId={d.decision_id} />
          </Panel>
          <Panel title="Copilot">
            <CopilotChat decisionId={d.decision_id} />
          </Panel>
        </div>

        {action && (
          <Panel title="Adverse action notice" className="lg:col-span-12">
            <AdverseAction decisionId={d.decision_id} />
          </Panel>
        )}
      </div>
      <p className="pb-4 text-2xs text-ink-500">
        <Link to="/" className="hover:text-steel">Live stream</Link> · Application {d.application_id}
      </p>
    </div>
  );
}
