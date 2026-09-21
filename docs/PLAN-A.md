# PLAN — Lane A (backend)

Owner: Lane A. Scope: `backend/` (except `backend/app/semantic/`, `backend/app/llm/`), `docker-compose.yml`,
`.env.example`, `.pre-commit-config.yaml`, `docs/openapi.json`, this file.
Commits: `git commit -m "<type>: …" -- <my paths>` (only-paths mode, so another lane's staged files are never swept in).

## Environment facts (checked 12:45)
- Docker is **not** on Windows. Docker 28.2.2 daemon runs inside **WSL Ubuntu** (user in `docker` group),
  but the **compose v2 plugin is missing**. All compose commands run as
  `wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/LENOVO/Desktop/sentinel && docker compose …"`.
  WSL2 localhost forwarding exposes :5432 / :8000 to Windows (check in A1).
- WSL idles the distro out a few seconds after the last `wsl.exe` session exits, which kills dockerd and the API.
  A keepalive (`wsl.exe -d Ubuntu -- sleep infinity`, launched via Win32_Process.Create so it outlives tool shells) holds it up.
  Relaunch after a reboot or `wsl --shutdown`.
- Host Python is 3.13 only (no 3.11). Backend tests run **inside the api container** (python:3.11-slim), not on the host.

## Tasks

| # | Slot | Task | Acceptance check | Est | Needs from Lane B | Model |
|---|------|------|------------------|-----|-------------------|-------|
| A0 | 12:50 | Install compose v2 plugin to `~/.docker/cli-plugins` in WSL (user-local, no sudo) | `docker compose version` prints v2 | 10m | — | Sonnet: mechanical |
| A1 | 13:00 | Scaffold | `compose up` → api healthy; `curl :8000/ready` = 200 from Windows | 45m | — | Sonnet: boilerplate |
| A2 | 13:45 | Tables, schemas, stub scoring, decisions API | `curl POST /decisions/application` → persisted row; pytest 422 + band edges green | 70m | — | Sonnet: CRUD |
| A3a | 14:55 | Contract skeleton: every DESIGN §10 route with request+response models (stubs where not built) | `/docs` lists all routes; openapi validates | 30m | Shapes for `/cases/…/similar`, `/copilot/ask` (DESIGN §8/§9 used if none) | Sonnet |
| A3 | 15:25 | Real scoring + SHAP + adverse action | determinism test; curl gives 4 reason codes; latency logged | 35m | `ml/artifacts/*`, `ml/featurize.py`, pinned `ml/requirements.txt` | Sonnet |
| G1 | 16:00 | **GATE 1** + export `docs/openapi.json` (freeze) | curl → score, band, decision, 4 reasons, persisted | — | — | — |
| A4 | 16:00 | Entity graph | two apps sharing a device → 1 device node, 2 links; CTE < 50 ms (EXPLAIN ANALYZE) | 90m | — | **Opus**: recursive CTE bounds + latency |
| A5 | 17:30 | Replay stream + ADWIN drift | unit test: ADWIN fires on synthetic mean shift; live: switch→drift→bands tighten | 120m | `data/replay/stream_base.csv`, `stream_shift.csv` | **Opus**: drift logic |
| G2 | 19:30 | **GATE 2** | switch source → drift event row → `/metrics/drift` thresholds lowered | — | — | — |
| — | 19:30 | Buffer (G2 slip, B5/B6 router wiring) | — | 45m | — | — |
| A6 | 20:15 | Security | pytest 401, 403, 429 green; no stack trace in 500 body | 75m | — | Sonnet |
| A7 | 21:45 | Integration fixes for Lane F, CORS :5173 | F's screens load real data | ~2h | — | Sonnet |
| A8 | 00:30 | Clean-from-zero demo (optional deploy, hard stop 01:30) | `compose down -v && up` + one load script → working demo | 60m | B4 load script | Sonnet |
| G3 | 01:30 | **GATE 3** | — | — | — | — |

### A1 — Scaffold
Files: `docker-compose.yml`, `.env.example`, `.pre-commit-config.yaml`, `backend/Dockerfile`, `backend/requirements.txt`,
`backend/alembic.ini`, `backend/alembic/{env.py,versions/0001_vector.py}`, `backend/app/{main.py,core/config.py,core/logging.py,core/middleware.py,api/v1/health.py,db/session.py}`
- `db`: pgvector/pgvector:pg16, named volume `pgdata`, `pg_isready` healthcheck. `api`: build `backend/`, depends_on db healthy,
  runs `alembic upgrade head && uvicorn` (inline CMD — no .sh files, avoids CRLF breakage), healthcheck on /health.
  Mounts `./ml:/srv/ml:ro` and `./data:/srv/data:ro` so Lane B's artifacts/replay files need no rebuild.
- One uvicorn worker (stream + ADWIN state live in-process).
- pydantic-settings `Settings`; JSON log formatter; middleware sets/propagates `X-Request-ID` into a contextvar that every log line carries.
- `/health` (process up), `/ready` (`SELECT 1` → 200, else 503).
- `.pre-commit-config.yaml`: ruff (scoped `^backend/`) + gitleaks. I will NOT run `pre-commit install` (it would hook every lane's commits) — your call.
- Sync SQLAlchemy 2.0 + psycopg3; bcrypt used directly (passlib is broken with bcrypt 4.x).

### A2 — Tables + decisions API
Files: `backend/app/models/*.py`, `backend/alembic/versions/0002_core_tables.py`, `backend/app/schemas/{application.py,decision.py,common.py}`,
`backend/app/services/{scoring.py,policy.py,decision_service.py}`, `backend/app/repositories/{decision_repo.py,audit_repo.py}`,
`backend/app/api/v1/decisions.py`, `backend/tests/{conftest.py,test_validation.py,test_policy.py}`
- Tables: applications, decisions (inputs jsonb, score, band, decision, model_version, reason_codes jsonb, graph_signals jsonb,
  graph_uplift, latency_ms, request_id, created_at), entities, entity_links, drift_events, audit_log.
- `ApplicationEvent` strict: all 31 BAF feature columns with dataset bounds + `month`, identifiers
  (device_id, email, phone, ip, address, applicant_name), optional `fraud_bool` + `history: bool` (fraud_bool honoured only when history).
- `DecisionResponse` exactly per DESIGN §10; `graph_signals` is a typed model with the 4 DESIGN §6 keys (zeros until A4).
- `ScoringService` Protocol → `StubScoringService` (0.5). `PolicyEngine` bands from config, runtime-overridable (for A5).
- Tests use a separate `sentinel_test` database created by conftest.

### A3a — Contract skeleton (so the 16:00 freeze is complete)
The freeze lands before A4–A6 exist, so every DESIGN §10 route must already exist in the OpenAPI with its final models:
`/auth/login`, `/entities/{id}/graph`, `/stream` (text/event-stream), `/stream/switch|start|stop`, `/metrics`, `/metrics/drift`,
`/cases/{id}/similar`, `/copilot/ask`. Unbuilt ones return 501. Routes carry a `get_current_user` bearer dependency from day one
(no-op until A6), so adding auth later doesn't change the contract.
Lane B routes: if B hasn't landed schemas by 15:30 I write stub routers in `backend/app/api/v1/_contract_stubs.py`
using the DESIGN shapes; B's real routers replace them keeping the exact shapes.

### A3 — Real scoring
Files: `backend/app/services/{model_registry.py,explain.py,scoring.py}`, `backend/app/api/v1/decisions.py` (adverse-action),
`backend/app/schemas/adverse_action.py`, `backend/tests/test_scoring_determinism.py`, `docs/openapi.json`
- ModelRegistry loads the 6 artifacts once at startup (lifespan); `ml.featurize.build_features`; blend per blend.json;
  shap.TreeExplainer once; top-4 positive SHAP → reason_codes.yaml. `latency_ms` measured end-to-end and logged.
- **Pickle risk:** artifacts pickled on host 3.13 load in a 3.11 container. `backend/requirements.txt` must pin the same
  lightgbm / scikit-learn / numpy / pandas / shap versions as `ml/requirements.txt`. I'll mirror B's pins.
- Fallback if artifacts late: keep the stub, finish endpoint shape, export openapi.json at 16:00 anyway.

### A4 — Entity graph (Opus)
Files: `backend/app/services/{entity_resolver.py,graph_service.py}`, `backend/app/repositories/graph_repo.py`,
`backend/app/api/v1/entities.py`, `backend/tests/test_entity_graph.py`, config for uplift weights.
- Normalise (lowercase/strip, digits-only phone, etc.) → sha256 → upsert `entities` (ON CONFLICT on (type,value_hash)),
  insert links; history rows with fraud_bool=1 set `fraud_flag`.
- Recursive CTE over the bipartite app↔entity graph, 2 hops, `LIMIT 200` nodes, indexes on entity_links(entity_id), (application_id).
- Signals: component_size, distinct_names_per_device, known_fraud_2hop, component_velocity_24h → config-driven uplift → `p_final`.

### A5 — Stream + drift (Opus)
Files: `backend/app/services/{replay.py,drift.py,metrics.py}`, `backend/app/repositories/drift_repo.py`,
`backend/app/api/v1/{stream.py,metrics.py}`, `backend/tests/test_drift.py`
- Async replay task reads `data/replay/stream_{base,shift}.csv`, same `DecisionService` path, fans out to SSE subscribers (asyncio queues).
- river ADWIN on score stream + delayed-label error stream (lag 200); on detection lower bands by DRIFT_TIGHTEN_DELTA,
  write drift_events; admin reset. `/metrics` p50/p95/p99 from a rolling window.
- Fallback: lower ADWIN delta / exaggerate the shift so it fires on camera.

### A6 — Security
Files: `backend/app/core/security.py`, `backend/app/api/v1/auth.py`, `backend/app/core/{errors.py,limits.py}`, `backend/tests/test_security.py`
- python-jose HS256 60 min, bcrypt, analyst/admin demo users from env, admin-only stream control, slowapi, CORS allowlist from env,
  body-size cap middleware, global exception handler (request_id, no stack trace).

### A7 / A8 — see START-A.md.

## Cross-lane coordination (please relay to Lane B)
1. **Artifacts by ~15:25**, plus `ml/requirements.txt` with exact pins (I mirror them in the image).
2. **Alembic chain:** mine are `0001_vector` → `0002_core_tables`. B's `case_embeddings` migration uses
   `revision="0003_case_embeddings"`, `down_revision="0002_core_tables"`. If I need a later one I chain after 0003.
3. **Heavy deps for B5/B6** (sentence-transformers, presidio, groq, jinja2) go in `backend/requirements.txt` (mine): B sends me
   the list. torch comes from the CPU wheel index, otherwise the image pulls CUDA (~2 GB).
4. **Router wiring:** B hands me `from app.semantic.router import router` / `from app.llm.router import router`; I add the
   `include_router` lines plus a post-persist hook (`BackgroundTasks`) calling B's `embed_decision(decision_id)`.
5. **B4 timing clash:** B4 is slotted at 16:00 and needs A4, but A4 only lands ~17:30. The load has to happen after A4,
   otherwise no entity links or fraud_flags get written. Suggest B does B5 first and runs B4 at ~17:30.

## Questions for you
- OK to install the compose plugin user-locally in WSL (A0)?
- OK to commit `docs/PLAN-A.md` and my `CLAUDE.md` status line alongside backend commits?
- Per model policy: after "go", switch me to **Sonnet** for A0–A3 (back to Opus at 16:00 for A4).

## Progress
- [x] A0 (compose v5.5.1 in ~/.docker/cli-plugins)  - [x] A1 (13:15; /ready 200 from Windows; 2 tests green in container)  - [x] A2 (13:20; curl POST 201 → GET 200 identical, DB row + audit; 31 tests green)  - [x] A3a (13:27; 18 paths in draft docs/openapi.json, login real, rest 501; 41 tests + ruff green)  - [x] A3 (16:25; Lane B pins verbatim, lgbm-if-v1 loaded at startup, SHAP top-4, B routers + embed hook wired)  - [x] G1 (16:25, 25 min late: score/band/decision/4 reasons/persisted; openapi.json FROZEN)  - [x] A4 (17:05; resolver+hashing, bounded recursive CTE (200 nodes, 300-app hub < 50 ms), signals+uplift, graph API; e2e p99 84 ms)  - [x] A5 (18:25; replay+SSE+ADWIN score/error streams+tightening+metrics; exact vectorised IF 19→0.1 ms)  - [x] G2 (18:25: 2000 base events, switch → drift in 9 s / ~179 events, bands 300/650/850 → 225/575/775; under load p99 124 ms, 26.5 ev/s. ADWIN_DELTA=0.1 + simulated fraud wave REPLAY_SHIFT_FRAUD_RATE=0.12 — the real variant shift alone is too subtle to fire reliably, see commit msg)  - [ ] A6  - [ ] A7  - [ ] A8  - [ ] G3
