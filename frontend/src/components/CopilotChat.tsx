import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { CopilotAskResponse } from "../api/types";

interface Turn { question: string; answer?: CopilotAskResponse; error?: string }

const SUGGESTIONS = [
  "Why was this application flagged?",
  "What should I check next?",
  "Which linked applications matter most?",
];

export function CopilotChat({ decisionId }: { decisionId: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  // A different case is a different conversation.
  useEffect(() => { setTurns([]); setQuestion(""); }, [decisionId]);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [turns, busy]);

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(true);
    setQuestion("");
    setTurns((t) => [...t, { question: text }]);
    try {
      const answer = await api.ask(decisionId, text);
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, answer } : x)));
    } catch (e) {
      const msg = e instanceof ApiError && e.status === 429
        ? "Too many questions in a short time. Wait a moment and ask again."
        : e instanceof Error ? e.message : "The copilot could not answer.";
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: msg } : x)));
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void ask(question); };

  return (
    <div className="flex flex-col">
      <p className="mb-2 text-2xs text-ink-400">
        Read-only assistant. It explains this case from its recorded reasons and cannot change a score or decision.
      </p>
      <div className="max-h-72 min-h-24 space-y-3 overflow-auto rounded border border-ink-800 bg-ink-950 p-3" aria-live="polite">
        {turns.length === 0 && (
          <div className="space-y-2">
            <p className="text-xs text-ink-300">Ask about this case.</p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="rounded border border-ink-600 px-2 py-1 text-2xs text-ink-200 hover:border-steel-dim hover:text-steel" onClick={() => void ask(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="space-y-1.5">
            <p className="text-xs font-medium text-steel">{t.question}</p>
            {t.answer && (
              <div className="space-y-1.5">
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-100">{t.answer.answer}</p>
                <div className="flex flex-wrap items-center gap-1.5 text-2xs">
                  {t.answer.blocked && <span className="rounded border border-band-decline/50 bg-band-decline/10 px-1.5 py-0.5 text-band-decline">Blocked by guardrail</span>}
                  {t.answer.fallback_used && <span className="rounded border border-band-stepup/50 bg-band-stepup/10 px-1.5 py-0.5 text-band-stepup">Templated answer, the language model was not used</span>}
                  {t.answer.cited_reasons.map((c) => (
                    <span key={c} className="rounded border border-ink-600 px-1.5 py-0.5 text-ink-300">cites {c}</span>
                  ))}
                </div>
              </div>
            )}
            {t.error && <p role="alert" className="text-xs text-band-decline">{t.error}</p>}
            {!t.answer && !t.error && <p className="text-xs text-ink-400">Thinking…</p>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="mt-2 flex gap-2">
        <input
          className="input py-1.5 text-xs"
          placeholder="Ask about this case"
          aria-label="Question for the copilot"
          maxLength={500}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button className="btn btn-primary" disabled={busy || !question.trim()}>{busy ? "Asking…" : "Ask"}</button>
      </form>
    </div>
  );
}
