# PLAN — Lane B (ML / data / semantic / LLM → Reviewer)

Owner: Lane B. Scope: `ml/`, data scripts, `backend/app/semantic/`, `backend/app/llm/`, `docs/` (my files), this file.
Written 12:50 Mon 21 Sep 2026. Currently on **Opus** for planning — switch me back to **Sonnet** with "go".

---

## 0. Phase-0 findings that change the plan

Six things I checked before planning. All three open questions are now answered — see §6.

**F1 — `data/` does not exist.** B1 assumes `data/raw/Base.csv`; there is no `data/` directory at all.
Added **B0** (venv, pinned deps) ahead of B1. Dataset now arrives by manual drop (§6 Q1); it remains the main threat to the artifact gate.

**F2 — Kaggle credentials are incomplete.** `.env` has only `KAGGLE_API_TOKEN` (37 chars, not JSON).
The Kaggle API needs `KAGGLE_USERNAME` **and** `KAGGLE_KEY`, so I cannot authenticate with what is there. Resolved: manual download (§6 Q1) — I never touch the credentials.

**F3 — DESIGN §2 contradicts CLAUDE.md invariant 5.** §2 lists `employment_status` as a LightGBM
categorical, and also excludes it as a protected attribute. Invariant 5 is non-negotiable, so:
**`employment_status` is not a model feature.** Categoricals = `payment_type, housing_status, source, device_os`.
`customer_age`, `employment_status`, `income` are carried for fairness evaluation only. Flagging, not silently choosing.

**F4 — `reason_codes.yaml` is scheduled after Lane A needs it.** It is a B3 deliverable but sits in the §4
contract that A3 reads. Fix: **B2 emits a complete generated `reason_codes.yaml`** (every feature mapped, so A3
is never blocked), **B3 rewrites the wording** to plain applicant English. Same path, no rename.

**F5 — Only Python 3.13.2 exists here** (`Python312/` is an empty leftover; no 3.11). The backend container is
3.11, so artifacts pickled on 3.13 get unpickled on 3.11. Mitigations, all in B0/B2:
exact pins in `ml/requirements.txt` (Lane A mirrors them), `protocol=4`, an additional
`ml/artifacts/model_v1.txt` (LightGBM native text, version-robust — additive, renames nothing),
and a **fresh-interpreter load test** in B2's acceptance.

**F6 — read Lane A's PLAN-A.md; two resequencings follow.**
- Lane A's A4 (entity graph) lands **~17:30, not 16:00**. B4 loads the demo DB through the API and is
  pointless without entity links and fraud_flags. **So B5 moves ahead of B4** — which is exactly what Lane A
  proposed in their coordination note 5. Agreed.
- Lane A's real need-by for artifacts is **15:25** (they inserted A3a, a contract skeleton, at 14:55).
  I still target **14:30** per START-B, and treat 15:25 as the slack, not the plan.

---

## 1. Task order at a glance

| # | Slot | Task | Acceptance check | Est | Model |
|---|------|------|------------------|-----|-------|
| B0 | 12:50 | Bootstrap: venv, **pinned** `ml/requirements.txt`, MiniLM prefetch, `.gitignore` | fresh venv imports lightgbm/sklearn/shap/river | 25m | Sonnet: mechanical setup |
| B1 | 13:10 | `prepare_data.py`: split, 150k sample, identifiers, 4 rings, replay streams | all 5 outputs exist; months disjoint; rings assert shared device_id; 150k rows incl. every fraud | 40m | Sonnet: specified data work |
| B2 | 13:50 | `featurize.py` + `train.py` + **all §4 artifacts** + 3 charts | 7 contract paths exist; fresh interpreter loads each; `build_features` cols == `features.json` order; metrics printed | 60m | Sonnet: mechanical once design is fixed; Opus would cost time I don't have |
| — | **14:30** | **⚑ artifact handoff to Lane A** | — | — | — |
| B3 | 14:50 | Reason codes rewrite + failing-test, fairness, model card | test provably fails when a mapping is deleted; fairness block in `metrics_v1.json` | 60m | Sonnet |
| — | 15:50 | Buffer / Lane A support / openapi freeze at 16:00 | — | 10m | — |
| B5 | 16:00 | Semantic layer: embedder, migration 0003, router, backfill | migration applies on A's head; ring member's top-5 contains ring members | 105m | Sonnet |
| B4 | 17:45 | `load_demo_db.py`, ring uplift numbers, 3 hero cases | rings show component_size ≥ 8; mean ring score higher after uplift; 3 IDs resolve | 60m | Sonnet |
| B5v | 18:45 | B5 verification pass (backfill over B4's data, ring top-5 test) | the ring test above, on real loaded data | 30m | Sonnet |
| — | 19:15 | Buffer | — | 60m | — |
| B6 | 20:15 | LLM layer: providers, prompts, guardrails, tool registry, router | 4 named tests green, `test_llm_cannot_mutate_decision` first | 90m | **Opus**: model policy lists guardrails/LLM invariant |
| R1 | 21:45 | Audit vs invariants + gitleaks, fix HIGH/MED in my lanes | every invariant has a pass/fail line with evidence; gitleaks clean | 105m | **Opus**: model policy lists R1 |
| R2 | 23:30 | Critical-path tests + `.github/workflows/ci.yml` | CI green on a real run, not "should be" | 60m | Sonnet |
| R3 | 00:30 | README + responsible-ai + AWS target arch + Mermaid | a stranger can clone → run → demo from the README | 60m | Sonnet |

B0 and B1 overlap: I write `prepare_data.py` while the dataset is being dropped into `data/raw/`.
B5 is built before B4 and *verified* after it, because the ring top-5 test needs B4's loaded data.

---

## 2. Task detail

### B0 — Bootstrap *(new, prerequisite)*
`.venv` on Python 3.13 (already gitignored, line 153). `ml/requirements.txt` with **exact pins** —
lightgbm, scikit-learn, numpy, pandas, pyarrow, shap, river, pyyaml, matplotlib, joblib, httpx, kaggle,
plus sentence-transformers/torch so the multi-GB wheel pull happens now and not at 16:00.
Dataset arrives by manual download (Q1) — I do not touch Kaggle credentials. Prefetch `all-MiniLM-L6-v2` in the
background. Append a `data/` block to `.gitignore`. Create `data/{raw,processed,replay}/` so the drop target is obvious.
**Files:** `ml/requirements.txt`, `.gitignore` (append-only), `data/raw/*` (ignored).
**→ Lane A: `ml/requirements.txt` pins by ~13:15** — they mirror them into `backend/requirements.txt`, so earlier is better.

### B1 — `ml/scripts/prepare_data.py` *(DESIGN §2)*
Load `Base.csv`; report shape, fraud rate, `-1` counts per column, fraud rate by month. Temporal split
(train 0–5, month 5 = early-stopping validation; test 6–7) → `train.parquet`, `test.parquet`. 150k stratified
`demo_sample.csv` = **all** frauds + sampled legit. Seeded deterministic identifiers from row index
(device_id, email, phone, ip, address, applicant_name). Plant **4 rings of 8–15 fraud rows** sharing device_id
+ phone (some ip), all inside `demo_sample` so B4 can demo them. `data/replay/stream_base.csv` (test months,
Base) and `stream_shift.csv` (same size, variant), both with identifiers + `fraud_bool`. Print a summary.
**Plus, 5 min, unblocks A2:** `ml/artifacts/raw_columns.json` — exact raw columns, dtypes, observed min/max,
and which 6 are synthetic identifiers, so Lane A's strict `ApplicationEvent` bounds come from the data.
**Acceptance:** runs end to end; 5 outputs exist; fraud rate matches known BAF ≈ 1.1%; train/test months
disjoint; in-script assert that ring members share a device_id; `demo_sample.csv` = 150k rows containing every fraud.
**Files:** `ml/scripts/prepare_data.py`, `ml/artifacts/raw_columns.json`, `data/processed/*`, `data/replay/*`.
**→ Lane A:** `raw_columns.json` (~13:50, for A2) and `data/replay/*.csv` (A5 needs them at 17:30 — ~3.5h early).

### B2 — `ml/featurize.py` + `ml/train.py` + artifacts *(DESIGN §3, §4)* ⚑ **critical path**
`build_features(raw: dict) -> pd.DataFrame` (1 row), and **training calls the same function** — no train/serve
skew; that is the point of the task, not a detail. Keep `-1`, add `<col>_missing` flags. Exclude the three
protected attributes (F3). LightGBM with `scale_pos_weight`, early stop on month 5. IsolationForest on legit
train rows only, min-max normalised on train. Blend 0.75/0.25. Rules baseline. Test-set ROC-AUC, PR-AUC,
Precision@100, recall@1%FPR for **baseline / LGBM / IF / blend**. Write every §4 artifact, plus `model_v1.txt`
(F5) and the generated `reason_codes.yaml` (F4). Charts → `docs/charts/{pr_curve,score_distribution_bands,feature_importance}.png`.
**Working-v1-first:** artifacts land before charts and before any tuning. Behind at 14:30 → ship artifacts, return for charts.
**Acceptance:** all 7 §4 filenames at their exact paths; a **fresh interpreter** loads each; `build_features` on one
raw dict returns 1 row whose columns equal `features.json` order exactly; `from ml.featurize import build_features`
works from repo root the way Lane A imports it; metrics printed and non-degenerate — **whatever the real numbers
are** (invariant 7).
**Files:** `ml/featurize.py`, `ml/train.py`, `ml/artifacts/*`, `docs/charts/*`.
**→ Lane A: ⚑ the §4 artifacts + `featurize.py`. Target 14:30; their stated need-by is 15:25.**

### B3 — Reason codes, fairness, model card
Rewrite `reason_codes.yaml` into plain English an applicant would understand + ECOA category per feature.
Test that **fails** if any feature in `features.json` lacks a mapping. Fairness per §12: FPR + approval rate by
age group at the DECLINE threshold.
**Data caveat I will document rather than paper over:** BAF `customer_age` is banded by decade (10, 20, 30, …),
so literal `<25 / 25–50 / >50` buckets do not exist. I use **`≤20 / 30–50 / ≥60`** and state that mapping on the
chart, in the metrics block and in the model card.
**Also in this window, for Lane A (their A3a cutoff is 15:30):** send the response shapes for
`/cases/{decision_id}/similar` and `/copilot/ask`, and the dep list for `backend/requirements.txt`
(sentence-transformers, presidio-analyzer, groq, jinja2 + the torch CPU wheel index note).
**Acceptance:** `pytest ml/tests/test_reason_codes.py` passes, **and I verify it fails when I delete one mapping**;
fairness numbers in `metrics_v1.json` and on `docs/charts/fairness.png`; model card states data, features,
exclusions, metrics, fairness, limitations and the synthetic-linkage disclosure.
**Files:** `ml/artifacts/reason_codes.yaml`, `ml/tests/test_reason_codes.py`, `ml/fairness.py`, `docs/charts/fairness.png`, `docs/model-card.md`, `ml/artifacts/metrics_v1.json`.

### B5 — Semantic layer *(DESIGN §8)*
`backend/app/semantic/`: `CaseEmbedder` with MiniLM **loaded once** at startup; narrative template (band, top
reasons, graph signals, key features); Alembic migration for `case_embeddings` with an **HNSW cosine** index as a
**new file** — per Lane A's coordination note 2: `revision="0003_case_embeddings"`, `down_revision="0002_core_tables"`.
I do not touch their migrations. Background embedding after persist; `GET /api/v1/cases/{decision_id}/similar?k=5`;
backfill script.
**Two lines for Lane A** (they asked; I hand them over rather than editing `main.py`):
`from app.semantic.router import router as semantic_router` → `app.include_router(semantic_router, prefix="/api/v1")`,
and the post-persist `BackgroundTasks` hook `embed_decision(decision_id)` — I will expose exactly that name.
**Acceptance:** migration applies cleanly on Lane A's head; backfill embeds existing rows; **a ring member's top-5
includes other ring members** (verified in B5v, after B4 has loaded the rings); embedder instantiated exactly once.
**Files:** `backend/app/semantic/*`, `backend/alembic/versions/0003_case_embeddings.py`, `ml/scripts/backfill_embeddings.py`.

### B4 — `ml/scripts/load_demo_db.py` *(needs Lane A's A4, ~17:30)*
POST `demo_sample.csv` through the live API at ~50 req/s in history mode (so `fraud_bool` sets entity `fraud_flag`).
Print ring component sizes and mean score **before vs after** graph uplift. Pick 3 hero applications — a
clean-looking ring member, an obvious fraud, a clean approve → `docs/demo_ids.json`.
**Auth note:** Lane A's A6 adds JWT at 20:15, so the loader takes an optional bearer token from env from the
start and will not break when auth lands. Lane A's A8 (clean-from-zero demo) depends on this script.
**Acceptance:** loader completes without errors; DB decision count == rows posted; the 4 planted rings show
component_size ≥ 8; mean ring-member score measurably higher after uplift; 3 hero IDs resolve via `GET /decisions/{id}`.
**Files:** `ml/scripts/load_demo_db.py`, `docs/demo_ids.json`.

### B6 — LLM layer *(DESIGN §9)* — **Opus**
`backend/app/llm/`: `LLMProvider` interface, Groq impl, Bedrock stub; Jinja2 prompts in `backend/app/llm/prompts/`;
guardrails — input PII redaction (Presidio, regex fallback), injection pattern scan, length cap; output Pydantic
validation; answers may cite **only** reason codes present on that decision. Read-only tool registry:
`get_decision`, `get_entity_graph`, `find_similar_cases`. `POST /api/v1/copilot/ask`. LLM failure → templated answer
from reason codes.
**Acceptance:** `test_llm_cannot_mutate_decision`, `test_injection_blocked`, `test_pii_redacted`,
`test_fallback_when_llm_down` all pass. The mutation test is the one that matters — it is invariant 1, and the
thing a judge is most likely to probe.
**Files:** `backend/app/llm/*`, `backend/tests/test_llm_*.py`. **Depends on Q2.**

### R1 — Audit — **Opus**
Whole repo vs CLAUDE.md invariants 1–8 and the brief (clean modular code, API-first, no hardcoded secrets, input
validation, auth everywhere, responsible data handling, explainability). Run gitleaks. Table: severity, `file:line`,
issue, fix. **Fix HIGH/MEDIUM in my lanes only**; hand you a list of Lane A / Lane F items. No new features.

### R2 — Tests + CI
Critical-path tests, then `.github/workflows/ci.yml`: ruff, pytest with a postgres+pgvector service container,
gitleaks. **Acceptance: CI green on a real run.**

### R3 — Docs (00:30)
`README.md` per DESIGN, `docs/responsible-ai.md`, `docs/aws-target-architecture.md`, Mermaid architecture diagram.
README discloses the synthetic identifier linkage explicitly (DESIGN §2).

---

## 3. What Lane A is waiting on from me

| When | Artifact | Lane A task | If it slips |
|------|----------|-------------|-------------|
| ~13:15 | `ml/requirements.txt` **exact pins** | A1 image build; they mirror into `backend/requirements.txt` | they build unpinned, we reconcile at A3 — pickle risk (F5) |
| ~13:50 | `ml/artifacts/raw_columns.json` | A2 `ApplicationEvent` (13:45) | A2 proceeds from DESIGN §2; this only sharpens the bounds |
| ~13:50 | `data/replay/stream_base.csv`, `stream_shift.csv` | A5 (17:30) | ~3.5h of slack, low risk |
| **14:30** | **`ml/featurize.py` + the 7 `ml/artifacts/` files** | **A3 (15:25) → Gate 1 (16:00)** | **A3 keeps the stub scorer and exports `openapi.json` at 16:00 anyway — their stated fallback** |
| ~15:20 | response shapes for `/cases/…/similar` + `/copilot/ask`; backend dep list | A3a (cutoff 15:30) | they write contract stubs from DESIGN §8/§9 and my routers must match them exactly |
| ~17:45 | `include_router` line + `embed_decision(decision_id)` hook | A7 | — |
| ~18:45 | `docs/demo_ids.json` | Lane F demo; Lane A's A8 | — |
| ~21:45 | copilot `include_router` line | A7 | — |

The 14:30 row is the only one that can hurt. Hence B0 is compressed and B2 ships artifacts before charts.

## 4. What I am waiting on from Lane A

- **DB connection values.** START-B says use `.env`, but `.env` holds only the Kaggle token. I will read their
  `.env.example` / `docker-compose.yml` once A1 lands and **ask you** for the real password rather than invent one. Needed by B5.
- **Postgres + pgvector up** (A1) — B5. **Alembic head = `0002_core_tables`** (confirmed in PLAN-A) — B5.
- **A4 entity graph running** (~17:30) — B4.
- I never run `docker compose`, and I never edit `backend/` outside `semantic/` and `llm/`. Heavy deps go to Lane A as a list, not as an edit to their requirements file.

## 5. Top risks

1. **Dataset arrival (Q1).** B1→B2→everything sits behind `data/raw/Base.csv` + one variant landing. Still the
   highest-severity item: B2's 14:30 handoff has ~40 min of float, so files arriving after ~13:30 start eating it.
   I write and dry-run `prepare_data.py` against the documented schema while waiting so the wait costs nothing.
2. **14:30 artifact handoff** — mitigated by artifacts-before-charts, working-v1-over-tuning, and Lane A's 15:25 real need-by.
3. **Pickle 3.13 → 3.11 (F5)** — mitigated by exact pins + `model_v1.txt` + fresh-interpreter load test.
4. **B4 blocked on A4 slipping past 17:30** — B4 and B5 are independent; I reorder rather than idle (already done: F6).
5. **Torch / MiniLM download weight** — pulled forward into B0 so it is not discovered at 16:00.
6. **`GROQ_API_KEY` must be in `.env` by 20:15 (Q2).** If it slips, B6 still ships — guardrails, tool registry and
   the templated fallback are all provider-independent — but the copilot demo degrades to canned answers.

## 6. Decisions taken (answered 12:55)

**Q1 — dataset: you download manually.** B0 therefore does venv + pinned deps only and does **not** need
Kaggle credentials. I need, in `data/raw/`:
- `Base.csv` (required)
- **one** variant — `Variant II.csv` preferred, `Variant V.csv` equally fine — used for `stream_shift.csv`.

Exact filenames matter (`prepare_data.py` looks for them verbatim). Until they appear, B1 is blocked; I run B0
and write `prepare_data.py` against the documented BAF schema meanwhile, so the moment the files land I execute.

**Q2 — Groq key: yes, you will provide it.** B6 wires the live Groq provider
(`llama-3.3-70b-versatile`). I need `GROQ_API_KEY` in `.env` **by 20:15**. The Bedrock stub and templated
fallback still get built and tested regardless — `test_fallback_when_llm_down` requires them.

**Q3 — `.gitignore`: approved.** I append a `data/` block, append-only, committed as its own hunk.

---

## 7. Progress

- [x] B0 bootstrap
- [x] B1 prepare_data
- [x] B2 featurize + train + artifacts ⚑
- [ ] B3 reason codes + fairness + model card
- [ ] B5 semantic layer (build)
- [ ] B4 load demo DB + hero cases
- [ ] B5v semantic verification (ring top-5)
- [ ] B6 LLM layer (Opus)
- [ ] R1 audit (Opus)
- [ ] R2 tests + CI
- [ ] R3 docs
