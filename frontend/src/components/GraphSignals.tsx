import type { GraphSignals as Signals } from "../api/types";

// Mirrors the backend uplift rules (DESIGN section 3). The API returns only the total uplift, so this table
// explains it; if the backend config changes, change it here too.
const RULES = [
  { key: "known_fraud_2hop", label: "Known fraud within 2 hops", test: (s: Signals) => (s.known_fraud_2hop ?? 0) >= 1, rule: "1 or more", pts: 150 },
  { key: "component_size", label: "Linked applications", test: (s: Signals) => (s.component_size ?? 0) >= 5, rule: "5 or more", pts: 100 },
  { key: "distinct_names_per_device", label: "Distinct names on one device", test: (s: Signals) => (s.distinct_names_per_device ?? 0) >= 3, rule: "3 or more", pts: 50 },
] as const;

export function GraphSignals({ signals, uplift }: { signals: Signals; uplift: number }) {
  const velocity = signals.component_velocity_24h ?? 0;
  return (
    <div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-2xs text-ink-400">
            <th className="py-1 pr-3 font-medium">Signal</th>
            <th className="py-1 pr-3 text-right font-medium">Value</th>
            <th className="py-1 pr-3 font-medium">Uplift rule</th>
            <th className="py-1 text-right font-medium">Score</th>
          </tr>
        </thead>
        <tbody>
          {RULES.map((r) => {
            const hit = r.test(signals);
            return (
              <tr key={r.key} className="border-t border-ink-800">
                <td className="py-1.5 pr-3 text-ink-100">{r.label}</td>
                <td className="py-1.5 pr-3 text-right font-semibold text-ink-50">{signals[r.key] ?? 0}</td>
                <td className="py-1.5 pr-3 text-ink-300">{r.rule}</td>
                <td className={`py-1.5 text-right ${hit ? "font-semibold text-band-review" : "text-ink-500"}`}>{hit ? `+${r.pts}` : "0"}</td>
              </tr>
            );
          })}
          <tr className="border-t border-ink-800">
            <td className="py-1.5 pr-3 text-ink-100">Applications in last 24 h</td>
            <td className="py-1.5 pr-3 text-right font-semibold text-ink-50">{velocity}</td>
            <td className="py-1.5 pr-3 text-ink-500" colSpan={2}>Shown for context, no uplift</td>
          </tr>
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-200">
        Graph uplift added <span className="font-semibold text-ink-50">{Math.round(uplift * 1000)} points</span> to the score.
      </p>
    </div>
  );
}
