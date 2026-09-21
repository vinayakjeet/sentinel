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
