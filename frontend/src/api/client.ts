import type {
  AdverseActionNotice, Band, CopilotAskResponse, DecisionList, DecisionResponse, DriftStatus, EntityGraph,
  MetricsResponse, SimilarCasesResponse, StreamSource, StreamStatus, TokenResponse,
} from "./types";

export const API_URL: string = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const V1 = `${API_URL}/api/v1`;

export class ApiError extends Error {
  constructor(public status: number, message: string, public requestId?: string | null) {
    super(message);
  }
}

let tokenGetter: () => string | null = () => null;
let onUnauthorized: () => void = () => {};

export function configureApi(opts: { getToken: () => string | null; onUnauthorized: () => void }) {
  tokenGetter = opts.getToken;
  onUnauthorized = opts.onUnauthorized;
}

async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = tokenGetter();
  if (auth && token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${V1}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the Sentinel API. Check that the backend is running.");
  }
  if (res.status === 401 && auth) onUnauthorized();
  if (!res.ok) {
    let detail = res.statusText;
    let requestId: string | null = null;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      requestId = body.request_id ?? null;
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail, requestId);
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  login: (username: string, password: string) =>
    request<TokenResponse>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }, false),
  decision: (id: string) => request<DecisionResponse>(`/decisions/${id}`),
  decisions: (p: { band?: Band; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams();
    if (p.band) q.set("band", p.band);
    q.set("limit", String(p.limit ?? 50));
    q.set("offset", String(p.offset ?? 0));
    return request<DecisionList>(`/decisions?${q}`);
  },
  adverseAction: (id: string) => request<AdverseActionNotice>(`/decisions/${id}/adverse-action`),
  graph: (applicationId: string) => request<EntityGraph>(`/entities/${applicationId}/graph`),
  similar: (decisionId: string, k = 5) => request<SimilarCasesResponse>(`/cases/${decisionId}/similar?k=${k}`),
  ask: (decision_id: string, question: string) => post<CopilotAskResponse>("/copilot/ask", { decision_id, question }),
  metrics: () => request<MetricsResponse>("/metrics"),
  drift: () => request<DriftStatus>("/metrics/drift"),
  resetDrift: () => post<DriftStatus>("/metrics/drift/reset"),
  streamStatus: () => request<StreamStatus>("/stream/status"),
  startStream: () => post<StreamStatus>("/stream/start"),
  stopStream: () => post<StreamStatus>("/stream/stop"),
  switchStream: (source: StreamSource) => post<StreamStatus>(`/stream/switch?source=${source}`),
};

export const streamUrl = (token: string) => `${V1}/stream?token=${encodeURIComponent(token)}`;
