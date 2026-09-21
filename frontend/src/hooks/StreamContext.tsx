import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, streamUrl } from "../api/client";
import { type Band, type DecisionResponse, type DriftEvent, type StreamStatus } from "../api/types";
import { percentile } from "../lib/format";

const MAX_ROWS = 400;
const LATENCY_WINDOW = 500;
const FLUSH_MS = 250;
const RATE_WINDOW_MS = 5000;
export const BUCKET_MS = 5000;
const MAX_BUCKETS = 72; // 6 minutes

export type Connection = "connecting" | "live" | "reconnecting";
export type BandCounts = Record<Band, number>;
export interface Bucket { t: number; counts: BandCounts }
export interface LatencyStats { p50: number; p95: number; p99: number; last: number; n: number }

interface StreamValue {
  connection: Connection;
  status: StreamStatus | null;
  refreshStatus: () => Promise<StreamStatus | null>;
  setStatus: (s: StreamStatus) => void;
  decisions: DecisionResponse[];
  fresh: ReadonlySet<string>;
  counts: BandCounts;
  total: number;
  ratePerSec: number;
  latency: LatencyStats | null;
  buckets: Bucket[];
  driftEvents: DriftEvent[];
}

const emptyCounts = (): BandCounts => ({ APPROVE: 0, STEP_UP: 0, REVIEW: 0, DECLINE: 0 });
const Ctx = createContext<StreamValue | null>(null);

export function StreamProvider({ token, children }: { token: string; children: ReactNode }) {
  const [connection, setConnection] = useState<Connection>("connecting");
  const [status, setStatus] = useState<StreamStatus | null>(null);
  const [decisions, setDecisions] = useState<DecisionResponse[]>([]);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  const [counts, setCounts] = useState<BandCounts>(emptyCounts);
  const [total, setTotal] = useState(0);
  const [ratePerSec, setRate] = useState(0);
  const [latency, setLatency] = useState<LatencyStats | null>(null);
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const [driftEvents, setDriftEvents] = useState<DriftEvent[]>([]);

  // Decisions arrive at ~30/s. Buffer them and flush a few times a second so React renders at a human pace.
  const buffer = useRef<DecisionResponse[]>([]);
  const arrivals = useRef<number[]>([]);
  const latencies = useRef<number[]>([]);
  const bucketsRef = useRef<Bucket[]>([]);
  const countsRef = useRef<BandCounts>(emptyCounts());
  const totalRef = useRef(0);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.streamStatus();
      setStatus(s);
      return s;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const t = window.setInterval(() => void refreshStatus(), 4000);
    return () => window.clearInterval(t);
  }, [refreshStatus]);

  // Seed the table with recent decisions so the screen is not blank while the replay is stopped.
  useEffect(() => {
    let cancelled = false;
    api.decisions({ limit: 40 }).then((r) => { if (!cancelled) setDecisions((cur) => { const known = new Set(cur.map((d) => d.decision_id)); return [...cur, ...r.items.filter((d) => !known.has(d.decision_id))].slice(0, MAX_ROWS); }); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    let retry: number | undefined;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      setConnection((c) => (c === "live" ? "reconnecting" : "connecting"));
      es = new EventSource(streamUrl(token));
      es.onopen = () => setConnection("live");
      es.addEventListener("decision", (e) => {
        try { buffer.current.push(JSON.parse((e as MessageEvent).data) as DecisionResponse); } catch { /* malformed frame */ }
      });
      es.addEventListener("drift", (e) => {
        try {
          const ev = JSON.parse((e as MessageEvent).data) as DriftEvent;
          setDriftEvents((cur) => [ev, ...cur].slice(0, 50));
        } catch { /* malformed frame */ }
      });
      es.onerror = () => {
        es?.close();
        setConnection("reconnecting");
        retry = window.setTimeout(connect, 2500);
      };
    };
    connect();

    const flush = window.setInterval(() => {
      const batch = buffer.current;
      const now = Date.now();
      arrivals.current = arrivals.current.filter((t) => now - t < RATE_WINDOW_MS);
      if (batch.length === 0) {
        setRate(arrivals.current.length / (RATE_WINDOW_MS / 1000));
        return;
      }
      buffer.current = [];
      for (const d of batch) {
        arrivals.current.push(now);
        countsRef.current = { ...countsRef.current, [d.band]: countsRef.current[d.band] + 1 };
        latencies.current.push(d.latency_ms);
        const t = Math.floor(now / BUCKET_MS) * BUCKET_MS;
        const last = bucketsRef.current[bucketsRef.current.length - 1];
        if (last && last.t === t) last.counts[d.band] += 1;
        else {
          const counts = emptyCounts();
          counts[d.band] = 1;
          bucketsRef.current.push({ t, counts });
        }
      }
      totalRef.current += batch.length;
      if (latencies.current.length > LATENCY_WINDOW) latencies.current = latencies.current.slice(-LATENCY_WINDOW);
      if (bucketsRef.current.length > MAX_BUCKETS) bucketsRef.current = bucketsRef.current.slice(-MAX_BUCKETS);

      const sorted = [...latencies.current].sort((a, b) => a - b);
      setLatency({
        p50: percentile(sorted, 50)!, p95: percentile(sorted, 95)!, p99: percentile(sorted, 99)!,
        last: batch[batch.length - 1].latency_ms, n: sorted.length,
      });
      setRate(arrivals.current.length / (RATE_WINDOW_MS / 1000));
      setCounts(countsRef.current);
      setTotal(totalRef.current);
      setBuckets(bucketsRef.current.map((b) => ({ t: b.t, counts: { ...b.counts } })));
      setFresh(new Set(batch.map((d) => d.decision_id)));
      setDecisions((cur) => {
        // The seed fetch and the live feed can both carry the same decision; keep one copy.
        const known = new Set(cur.map((d) => d.decision_id));
        const incoming = batch.filter((d) => !known.has(d.decision_id)).reverse();
        return [...incoming, ...cur].slice(0, MAX_ROWS);
      });
    }, FLUSH_MS);

    return () => {
      disposed = true;
      window.clearTimeout(retry);
      window.clearInterval(flush);
      es?.close();
    };
  }, [token]);

  const value = useMemo<StreamValue>(
    () => ({ connection, status, refreshStatus, setStatus, decisions, fresh, counts, total, ratePerSec, latency, buckets, driftEvents }),
    [connection, status, refreshStatus, decisions, fresh, counts, total, ratePerSec, latency, buckets, driftEvents],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStream(): StreamValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStream outside StreamProvider");
  return v;
}

