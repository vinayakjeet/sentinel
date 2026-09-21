import type { components } from "./schema";

type S = components["schemas"];
export type Band = S["Band"];
export type DecisionOutcome = S["DecisionOutcome"];
export type DecisionResponse = S["DecisionResponse"];
export type DecisionList = S["DecisionList"];
export type ReasonCode = S["ReasonCode"];
export type GraphSignals = S["GraphSignals"];
export type EntityGraph = S["EntityGraphResponse"];
export type GraphNode = S["GraphNode"];
export type SimilarCasesResponse = S["SimilarCasesResponse"];
export type SimilarCase = S["SimilarCase"];
export type CopilotAskResponse = S["CopilotAskResponse"];
export type MetricsResponse = S["MetricsResponse"];
export type DriftStatus = S["DriftStatus"];
export type DriftEvent = S["DriftEventOut"];
export type Thresholds = S["Thresholds"];
export type StreamStatus = S["StreamStatus"];
export type StreamSource = StreamStatus["source"];
export type TokenResponse = S["TokenResponse"];
export type Role = TokenResponse["role"];
export type AdverseActionNotice = S["AdverseActionNotice"];

export const BANDS: Band[] = ["APPROVE", "STEP_UP", "REVIEW", "DECLINE"];
