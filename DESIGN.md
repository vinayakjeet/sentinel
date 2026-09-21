# SENTINEL — Design

## 1. Problem
Application fraud in digital lending, detected in real time, with every decision explainable in
Reg B terms and a system that notices and reacts when fraud patterns shift. Synchrony frames fraud as three
surfaces (application, account takeover, transaction); we build the application lane fully and design the
entity graph so the other two lanes plug in later.

## 2. Data
- Feedzai Bank Account Fraud (BAF), NeurIPS 2022. `data/raw/Base.csv` + one variant (`Variant II.csv` or `Variant V.csv`).
- Label: `fraud_bool`. Time: `month` (0–7).
- Split: train months 0–5 (month 5 = early-stopping validation), test months 6–7. Never random.
- BAF uses -1 as a missing sentinel in some columns (e.g. prev_address_months_count, bank_months_count,
  current_address_months_count, session_length_in_minutes, device_distinct_emails_8w). Keep -1, add `<col>_missing` flags.
- Categoricals (payment_type, employment_status, housing_status, source, device_os): LightGBM categorical.
- Protected attributes EXCLUDED from features: customer_age, employment_status, income. Kept only for fairness eval.
- Demo DB: 150k stratified sample (all frauds + legit), `data/processed/demo_sample.csv`.
- Synthetic identifiers (BAF has none): deterministic from row index with a seeded RNG:
  device_id, email, phone, ip, address, applicant_name. Then plant 4 fraud rings of 8–15 fraud rows each sharing
  device_id and phone (and some ip). This is disclosed in the README as synthetic linkage for demonstration.
- Replay streams: `data/replay/stream_base.csv` (test months from Base) and `data/replay/stream_shift.csv`
  (same size, from the variant) — both include identifiers and `fraud_bool`.

## 3. Scoring
- LightGBM (`scale_pos_weight`), early stopping on month 5.
- IsolationForest fit on legitimate train rows only; anomaly score min-max normalised on train.
- Blend: `p = 0.75 * lgbm_proba + 0.25 * anomaly_norm` (weights in `ml/artifacts/blend.json`).
- Graph uplift (applied in backend, not a model feature): `p_final = min(1, p + uplift)`,
  `uplift = 0.15*[known_fraud_2hop>=1] + 0.10*[component_size>=5] + 0.05*[distinct_names_per_device>=3]`
  (config-driven, shown separately in the response as `graph_uplift`).
- Score = round(1000 * p_final).
- Bands (config, overridable at runtime by drift tightening):
  APPROVE < 300 ≤ STEP_UP < 650 ≤ REVIEW < 850 ≤ DECLINE.

## 4. Artifacts contract (Lane B writes, Lane A reads — never renamed)
`ml/artifacts/`:
- `model_v1.pkl` — LightGBM Booster/classifier
- `iforest_v1.pkl` — IsolationForest + normaliser (dict {"model","min","max"})
- `preprocess_v1.pkl` — anything needed to turn a raw ApplicationEvent dict into the feature frame
- `features.json` — ordered list of model feature names + categorical list
- `blend.json` — {"w_supervised":0.75,"w_anomaly":0.25}
- `reason_codes.yaml` — feature → {reason, ecoa_category}
- `metrics_v1.json` — all metrics incl. baseline and fairness
Also `ml/featurize.py` exposing `build_features(raw: dict) -> pandas.DataFrame` (1 row). Lane A imports it.

## 5. Explainability
- shap.TreeExplainer on the LightGBM model, created once at startup.
- Top-4 features by positive SHAP contribution (toward fraud) → reason_codes.yaml →
  `[{feature, reason, ecoa_category, contribution}]`. Returned on every decision; required on non-APPROVE.
- `GET /api/v1/decisions/{id}/adverse-action` → Reg B-shaped notice (applicant-facing reasons, no raw features).

## 6. Entity graph
- `entities(id, type[device|email|phone|ip|address], value_hash sha256, first_seen, fraud_flag bool)`
- `entity_links(id, application_id, entity_id, created_at)` — bipartite application↔entity.
- 2-hop = applications sharing any entity with this application; recursive CTE bounded to 200 nodes.
- Graph signals: component_size, distinct_names_per_device, known_fraud_2hop, component_velocity_24h.
- `fraud_flag` set from `fraud_bool` for rows loaded as history (simulated confirmed labels).

## 7. Drift
- river.drift.ADWIN on: (a) score stream (b) error stream once delayed labels arrive (lag configurable, default 200 events).
- On detection: bands shift down by DRIFT_TIGHTEN_DELTA (default 75), row in `drift_events`
  (ts, detector, stream, old_thresholds, new_thresholds). Admin can reset.
- Replay: `POST /api/v1/stream/switch?source=base|shift` (admin), `GET /api/v1/stream` (SSE).

## 8. Semantic layer
- `case_embeddings(decision_id pk, embedding vector(384), metadata jsonb)`, HNSW cosine index.
- Narrative template: band, top reasons, graph signals, key features. Embedded in a background task.
- `GET /api/v1/cases/{decision_id}/similar?k=5`.
- Vector similarity finds cases that LOOK alike; the entity graph finds cases that are CONNECTED. Both shown.

## 9. LLM layer
- `LLMProvider` (Groq impl, Bedrock stub), Jinja2 templates in `backend/app/llm/prompts/`.
- Guardrails: input PII redaction (Presidio, fallback regex), injection pattern scan, length cap;
  output Pydantic validation, may only cite reason codes present on the decision.
- Tool registry: get_decision, get_entity_graph, find_similar_cases — read-only.
- `POST /api/v1/copilot/ask {decision_id, question}` → {answer, cited_reasons, blocked, fallback_used}.
- LLM failure → templated answer from reason codes.

## 10. API (all under /api/v1, JWT except health/ready/docs/auth)
- POST /auth/login {username,password} → {access_token, role}
- POST /decisions/application ApplicationEvent → DecisionResponse
  DecisionResponse: {decision_id, application_id, score, band, decision, reason_codes[], graph_signals{}, graph_uplift,
  model_version, latency_ms, created_at}
- GET /decisions/{id}; GET /decisions?band=&limit=&offset=
- GET /decisions/{id}/adverse-action
- GET /entities/{application_id}/graph → {nodes[{id,type,label,fraud}], edges[{source,target}]}
- GET /cases/{decision_id}/similar?k=5
- GET /stream (SSE of DecisionResponse); POST /stream/switch?source= (admin); POST /stream/start|stop (admin)
- GET /metrics → {p50,p95,p99, decisions_per_sec, band_mix}; GET /metrics/drift → {state, thresholds, events[]}
- POST /copilot/ask
- GET /health, GET /ready

## 11. Latency budget (p99 < 200 ms)
validation 2 · entity upsert 15 · graph CTE 40 · model+IF 10 · SHAP 20 · policy 1 · persist 15 · embed async.

## 12. Metrics
ROC-AUC, PR-AUC, Precision@100, recall at 1% FPR — for rules baseline, LightGBM, IF, blend.
Fairness: FPR and approval rate by age group (<25, 25–50, >50) at the DECLINE threshold.

## 13. Security
bcrypt + JWT (HS256, secret from env, 60 min), roles analyst/admin, slowapi rate limits, CORS allowlist,
body size cap, no stack traces, gitleaks pre-commit + CI.

## 14. Out of scope
Kafka (in-process stream), GNN (SQL graph signals), ATO + transaction lanes, real device fingerprinting,
cloud deployment beyond a best-effort host, online-learning model (ADWIN + threshold tightening instead).
