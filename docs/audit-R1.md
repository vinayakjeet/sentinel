# R1 — Repository audit

Audited 21 Sep 2026, 15:00–15:20, at commit `4970f33`, against the eight invariants in `CLAUDE.md`
and the brief (clean modular code, API-first, no hardcoded secrets, input validation, auth
everywhere, responsible data handling, explainability).

**State at audit time:** Lane A had landed A0–A3a plus uncommitted A3 work; their stack was down
(`:5432` and `:8000` both refusing). Lane F had not started — there is no `frontend/`. So this pass
covers `ml/`, `backend/app/semantic/`, `backend/app/llm/` in full, and Lane A's backend as far as it
exists. It will need repeating once A4–A6 land.

Everything below was checked by running something, not by reading alone.

---

## 1. Findings

| # | Sev | Where | Issue | Fix | Status |
|---|---|---|---|---|---|
| 1 | **HIGH** | `backend/app/services/model_registry.py:52` | `feats["features"]` — my `features.json` published the key as `feature_order`, so **`load_artifacts` raises `KeyError: 'features'` at API startup**. This blocks A3 and Gate 1 outright. | Publish both spellings of the same list from `FEATURE_ORDER` (`ml/featurize.py`). Additive, no change to Lane A's code. | **fixed (mine)** |
| 2 | **HIGH** | `backend/app/core/security.py:96`, `:113` | `get_current_user` returns `Principal(username="anonymous", role="admin")` when there is no token, and `require_admin` is a pass-through. **Every route is currently open, and open as admin** — including `/stream/switch` and `/metrics/drift/reset`. | A6 turns both into enforcement (401/403). Deliberate and annotated as such, but it must not ship this way. | **Lane A — A6** |
| 3 | **MED** | `backend/requirements.txt:19-27` | ML pins differ from `ml/requirements.txt` on **all seven** artifact-critical libraries (numpy 2.2.5 vs 2.4.6, pandas 2.2.3 vs 3.0.6, scikit-learn 1.6.1 vs 1.9.1, lightgbm 4.6.0 vs 4.7.0, shap 0.47.2 vs 0.51.0, joblib 1.5.0 vs 1.6.0, PyYAML 6.0.2 vs 6.0.3). Artifacts pickled against one set, unpickled against another. | Copy the `[artifact-critical]` block verbatim. Also missing: `river` (their A5 needs it), and the semantic deps. CI now fails on this drift. | **Lane A** |
| 4 | **MED** | `ml/train.py` (iforest artifact) | `iforest_v1.pkl` carried no feature contract, so `model_registry._anomaly_norm` fell back to implicit column order. Correct today by coincidence of ordering; a reorder would not raise, it would just return **wrong anomaly scores**. | Publish `features` in the artifact, and fit the forest on a named DataFrame so sklearn validates names on every predict. A mismatch is now a loud `ValueError`. | **fixed (mine)** |
| 5 | **MED** | `backend/app/llm/service.py:_reason_universe` | If `reason_codes.yaml` could not be found, the function returned an empty set and the foreign-reason guardrail silently became a no-op. A guardrail that quietly stops guarding is worse than one that is absent. | Log at ERROR naming every path tried and stating the guardrail is inactive. Citation filtering was, and remains, unaffected. | **fixed (mine)** |
| 6 | **MED** | `backend/app/core/errors.py:19` | Only `RequestValidationError` is handled. No global exception handler yet, so an unhandled error returns FastAPI's default 500 (no stack trace in the body, but DESIGN §13 asks for the handler). | A6. | **Lane A — A6** |
| 7 | **MED** | `backend/alembic/env.py:6` | Imports `app.models` only. `case_embeddings` lives in `app/semantic/models.py`, so it is absent from `Base.metadata` and a future `alembic revision --autogenerate` would emit **`DROP TABLE case_embeddings`**. | One line: `from app.semantic import models as _semantic_models  # noqa: F401`. I did not add it — it is their file. | **Lane A — 1 line** |
| 8 | LOW | `backend/app/services/model_registry.py:29` | `_FALLBACK_REASON` uses `ecoa_category: "Other"`, which is outside the controlled vocabulary in `ml/reason_codes.py`. Unreachable while coverage is 100% (test-enforced), so cosmetic. | Align to `"Other - application channel and device"`, or leave as a deliberate belt-and-braces default. | Lane A, optional |
| 9 | LOW | `backend/app/llm/guardrails.py:36` | The mutation pattern blocks legitimate analyst phrasings such as "what would change the score?". | Accepted. The copilot is explanatory only, so failing closed costs a rephrase; loosening a security control late costs more. Documented here rather than silently tuned. | accepted |
| 10 | LOW | `ml/scripts/load_demo_db.py` | Prints up to 300 chars of an error response body on the first failure of each status code. | Lane A's validation handler already strips submitted values, so there is nothing personal to echo. Console only, not logged. | accepted |
| 11 | — | `frontend/` | Does not exist; Lane F has not started. | Project risk, not a code defect. Flagged for the human. | Lane F |

No finding was found in Lane B code that was not fixed in this pass.

## 2. Invariants

| # | Invariant | Verdict | Evidence |
|---|---|---|---|
| 1 | LLM has no write path to a score or decision | **PASS** | Four independent barriers: registry rejects non-read-only tools; unknown tool names refused; every tool runs in a Postgres `SET TRANSACTION READ ONLY` transaction always rolled back; the response model has no field a score could return in. `test_llm_cannot_mutate_decision` plus a static test that fails on any write SQL in `app/llm/`. 19 tests pass. |
| 2 | Every decision persists inputs, score, band, model_version, top-4 reasons, latency_ms, request_id, timestamp | **PASS** | `applications.features` (JSONB) holds the inputs; `decisions` holds score, band, decision, p_model, graph_uplift, reason_codes, graph_signals, thresholds, model_version, latency_ms, request_id, created_at. Applicant name is stored as `name_hash` (sha256), not in clear. |
| 3 | No secrets in code; config via pydantic-settings; only `.env.example` committed | **PASS** | gitleaks 8.30.1 over **14 commits: no leaks found**. `.env` is gitignored (`.gitignore:151`) and **never appears in history**. `.env.example` is tracked with every value empty. The 6 working-tree hits are all in `.env` itself; the other 174 are in `.venv/`. |
| 4 | Every route has Pydantic request **and** response models | **PASS** | All 20 routes across 9 routers declare `response_model`; request bodies are Pydantic models. |
| 5 | Protected attributes never model features | **PASS** | `customer_age`, `employment_status`, `income` absent from `FEATURE_ORDER`; recorded in `features.json`; `test_protected_attributes_never_appear_as_features_or_reasons` fails the build if one becomes a feature *or* a citable reason. Note DESIGN §2 contradicted itself here; resolved in favour of the invariant and documented. |
| 6 | Temporal splits only | **PASS** | Train months 0–5 (5 = early-stopping validation), test 6–7, asserted disjoint in `prepare_data.py`. No random split anywhere. Rules-baseline thresholds come from train quantiles only, so the baseline comparison carries no test leakage. |
| 7 | Real numbers only | **PASS** | Every metric is produced by a script and read back from `metrics_v1.json`. The unflattering ones are reported unchanged: the blend is *worse* than LightGBM alone on PR-AUC, and the model **fails a four-fifths test at 0.721**. One number was corrected during this session when found to come from a throwaway run. |
| 8 | `docs/openapi.json` frozen at 16:00 | n/a | Not yet due at audit time; the file is Lane A's draft. My two routers match the frozen stub contract exactly (`k` bounded 1–20, same response models, same 404 shape, auth dependency present). |

## 3. Brief

| Requirement | Verdict | Note |
|---|---|---|
| Clean, modular code | **PASS** | `api/v1 → services → repositories → models`, schemas and core separated. All SQL lives in repositories. ruff clean across `backend/` and `ml/` at 120 cols. |
| API-first | **PASS** | The demo loader posts 150k applications through `POST /decisions/application` rather than writing SQL, so demo data comes from the same path a real application takes. |
| No hardcoded secrets | **PASS** | See invariant 3. The LLM layer reads its own `LLMSettings` from env because `core/config.py` belongs to Lane A; no secret has a default. |
| Input validation | **PASS** | `ApplicationEvent` is `strict=True, extra="forbid"` with per-field bounds taken from the real data (`raw_columns.json`). 200 sampled rows validate unchanged. Validation errors do not echo submitted values. |
| Auth everywhere | **PARTIAL** | Route coverage is correct — everything carries `get_current_user` except `/health`, `/ready`, `/auth/login`, exactly as CLAUDE.md §10 allows, and admin routes use `require_admin`. But both dependencies are no-ops until A6 (finding 2). |
| Responsible data handling | **PASS** | Identifiers are sha256-hashed into `entities.value_hash`; applicant name stored as a hash; **no identifier ever enters an embedded narrative** (test-enforced); PII redacted before any LLM call; synthetic IPs confined to RFC 1918. `docs/responsible-ai.md` states the fairness failure rather than burying it. |
| Explainability | **PASS** | Top-4 positive SHAP contributions per decision, mapped to applicant-facing text plus ECOA category; adverse-action endpoint; build fails if any feature lacks a mapping, if text leaks a column name or model mechanics, or if the published YAML drifts from its source module. |

## 4. Handover to Lane A

In priority order. Items 1–3 are blocking; 4 is a one-line correctness fix.

1. **Pins** (finding 3) — replace the ML block in `backend/requirements.txt` with the
   `[artifact-critical]` block from `ml/requirements.txt`, verbatim. Add `river==0.26.1`, and
   `sentence-transformers==6.1.0`, `torch==2.14.0`, `transformers==5.17.0` for the semantic layer
   (torch from `--index-url https://download.pytorch.org/whl/cpu`, else the image pulls ~2 GB of CUDA).
2. **A6 auth enforcement** (finding 2) — until then the API is open and every caller is an admin.
3. **Router wiring** — swap both contract stubs for the real routers, add the post-persist
   `BackgroundTasks` hook calling `embed_decision(decision.id)`. Exact lines are in the module
   docstrings of `app/semantic/__init__.py` and `app/llm/__init__.py`.
4. **`alembic/env.py`** (finding 7) — add
   `from app.semantic import models as _semantic_models  # noqa: F401`.

Finding 1 needs nothing from Lane A: their `load_artifacts` now works unmodified. Verified by
running **their** `load_artifacts` → `ModelScoringService.score()` against the published artifacts:
31 features, blend 0.75/0.25, four SHAP reason codes per decision, and identical scores on repeat
calls (their own A3 determinism test).

## 5. Reproducing this audit

```bash
gitleaks git  --no-banner --redact .        # history: 14 commits, no leaks
gitleaks dir  --no-banner --redact .        # tree: hits only in .venv/ and the gitignored .env
ruff check backend ml
python -m pytest ml/tests -q                # 9 passed
cd backend && python -m pytest tests -q     # needs Postgres; 28 pass without it via --noconftest
```

---

# R1b — Re-audit of A4, A5, A6

Audited 21 Sep 2026, at commit `096cc1d`, against the same invariants. This pass covers **only what
landed after R1**: A4 (entity graph), A5 (replay stream + ADWIN drift), A6 (auth, RBAC, rate limits,
error handling), plus the CI workflow written in R2. Lane A's stack was live throughout, so every
claim below was checked against the running API rather than read off the source.

`frontend/` still does not exist.

## 1b.1 — R1 handover items: all four closed

| R1 item | Status | Evidence |
|---|---|---|
| 1. ML pins mirrored into `backend/requirements.txt` | **closed** | Zero mismatches across all nine artifact-critical packages; `river==0.26.1` present. |
| 2. A6 auth enforcement (R1 finding 2 — the API was open, and open as admin) | **closed** | Live status codes below. |
| 3. Router wiring + `embed_decision` hook | **closed** | `decisions.py:41` schedules `embed_decision` as a BackgroundTask; both routers are on the real implementations. |
| 4. `alembic/env.py` semantic models import (R1 finding 7) | **closed** | `backend/alembic/env.py:9`. |

Auth, checked live against `http://localhost:8000`:

| Request | Result |
|---|---|
| `GET /api/v1/decisions` no token | **401** |
| `GET /api/v1/decisions` malformed token | **401** — body is `{"detail":"invalid or expired token","request_id":…}`, nothing more |
| `GET /api/v1/stream` (SSE) no token | **401** |
| `POST /api/v1/stream/start` as **analyst** | **403** |
| `POST /api/v1/metrics/drift/reset` as **analyst** | **403** |
| `POST /api/v1/auth/login` wrong credentials | **401** |
| `GET /health` no token | **200** (allowed by CLAUDE.md §10) |

R1 finding 6 (no global exception handler) is also closed: `core/errors.py` registers a handler for
bare `Exception` that logs the traceback server-side and returns an opaque `internal server error`
plus the `request_id`.

## 1b.2 — New findings

| # | Sev | Where | Issue | Fix | Status |
|---|---|---|---|---|---|
| 12 | **MED** | `.github/workflows/ci.yml` — "Artifacts load from a cold interpreter" | The step asserted `set(ifo) == {"model","min","max"}`. R1's own finding-4 fix added `features` and `categorical_encoding` to `iforest_v1.pkl`, so **this assertion was guaranteed to fail on the first real CI run** — a green-looking workflow that had never executed. | Assert the required keys are present (`⊆`) and, more usefully, that `ifo["features"] == features.json["feature_order"]` — the property whose violation would silently produce wrong anomaly scores. | **fixed (mine)** |
| 13 | **MED** | `ml/scripts/load_demo_db.py` | The loader logged in **once**. A6 sets a 60-minute token life, and measured sustained throughput against the live stack is **13.2 req/s**, not the 30/s the loader requests — so a 40k load takes ~50 min and would have begun taking 401s before finishing, recording them as failures and dropping those rows from the demo data. | Token refresh on 401 (guarded, so a burst of concurrent 401s causes one login, not six), plus `--resume`, which reads the external_refs already in the database and skips them — history rows are not de-duplicated, so resuming had to be exact rather than approximate. | **fixed (mine)** |
| 14 | **MED** | latency vs DESIGN §11 | Under the 6-worker bulk load, `GET /api/v1/metrics` reports **p50 324 ms, p95 ~450 ms, p99 ~590 ms** against DESIGN §11's < 200 ms budget. This is the *loaded* figure, and `latency_ms` measures scoring + graph + persist only (the case embedding is a BackgroundTask and is outside it, but still competes for the same threadpool). | Measure the idle single-request figure and publish **both**, rather than quoting whichever one flatters. If the loaded figure is the one that matters for the demo, either move embedding off the request path or restate the budget. | **Lane A** |
| 15 | LOW | `backend/app/api/v1/stream.py:36` | `GET /api/v1/stream` declares `response_model=None`, so strictly it is the one route without a response model (invariant 4). | Accepted and documented rather than worked around: a `StreamingResponse` has no single response model. The payloads *are* Pydantic — `DecisionResponse.model_dump_json` and `DriftEventOut.model_dump_json` — and `responses=_SSE_DOC` publishes the schema in OpenAPI. Substantive compliance. | accepted |
| 16 | LOW | `backend/app/services/replay.py:39` | `fraud_wave_rows` builds the simulated wave by sampling the variant file's **real fraud rows with replacement**, so the same fraud row recurs during a long replay. Harmless for drift (ADWIN sees the score/error stream) but it means the wave is resampled real rows, not fresh ones. | Disclose in the README alongside the `REPLAY_SHIFT_FRAUD_RATE` note. | **README (R3)** |

## 1b.3 — Checked and clean

These were the places a defect would have been expensive, so they were checked specifically:

- **Graph SQL injection (A4).** Every statement in `repositories/graph_repo.py` is either SQLAlchemy
  Core or a `text()` with bound parameters — including the recursive CTE, where `:fanout`, `:row_cap`
  and `:node_limit` are bound, not interpolated. No f-string reaches SQL.
- **Lock ordering (A4).** `upsert_entities` documents that `keys` must be sorted so concurrent
  requests touching the same entities lock in the same order. `entity_keys` does return
  `sorted(keys)` — the contract is actually honoured, not merely stated. The 40k concurrent load
  exercised this path with six writers and produced no deadlock.
- **The drift demo cannot contaminate the entity graph.** Replay rows are validated without
  `history`, so `ApplicationEvent.label()` returns `None` and no replay row can set `fraud_flag` on
  an entity. The simulated fraud wave therefore cannot manufacture confirmed-fraud graph signals —
  which would have quietly inflated the graph uplift during the drift demo.
- **Identifiers still never surface.** Graph nodes are labelled `"<type> <hash prefix>"`
  (`graph_service.py`), applications by `external_ref`. No raw identifier is exposed by the graph API.
- **Drift threshold changes are auditable.** Every ADWIN detection writes a `drift_events` row *and*
  an `audit_log` entry with old and new thresholds, including when the tightening cap is reached and
  the thresholds deliberately do not move (`tightened: false`).
- **Rate limiting keys per authenticated user**, falling back to client IP. Keying on IP alone would
  have let this bulk load starve the analyst console, since everything here shares one IP.
- **CORS** is an explicit allowlist with `allow_credentials=False` (bearer tokens, no cookies).

## 1b.4 — For Lane A

1. **Finding 14 — latency.** Publish an idle p50/p95 alongside the under-load numbers. Do not quote
   the idle figure alone against DESIGN §11.
2. Nothing else. A4–A6 introduced no HIGH or MEDIUM defect in Lane A's own code; findings 12 and 13
   are both mine and both fixed.
