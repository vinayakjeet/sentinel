# SENTINEL — Real-Time Fraud Detection for Digital Lending
Synchrony hackathon submission. Email goes Tue 22 Sep 2026, 12:00 IST (hard cutoff 13:00).

Three agents work in this ONE repo at the same time, each in its own lane:
- Lane A (Claude account A): backend/  (except backend/app/semantic/ and backend/app/llm/)
- Lane B (Claude account B): ml/, data scripts, backend/app/semantic/, backend/app/llm/; Reviewer from 21:45
- Lane F (frontend agent):   frontend/
Never edit another lane's folder. If something outside your lane is broken, report it, don't fix it.
Commit ONLY your own paths (`git add backend/` etc.) — never `git add .` or `git add -A`.
Only Lane A runs `docker compose`. Others connect to the same Postgres on localhost:5432.

Read DESIGN.md for the full technical design and contracts. Your task list is in START-<lane>.md.

## Stack (do not change without asking)
- Backend: FastAPI + Python 3.11, Pydantic v2, SQLAlchemy 2.0, Alembic
- DB: PostgreSQL 16 + pgvector (image pgvector/pgvector:pg16)
- ML: LightGBM, scikit-learn, river (ADWIN drift), SHAP, sentence-transformers (all-MiniLM-L6-v2)
- LLM: Groq (llama-3.3-70b-versatile) behind an LLMProvider interface; Bedrock stub
- Frontend: React 18 + Vite + TypeScript + Tailwind
- Infra: Docker Compose

## Non-negotiable invariants
1. The LLM layer has NO write path to a risk score or decision. Read-only tools only.
2. Every decision persists: inputs, score, band, model_version, top-4 reason codes, latency_ms, request_id, timestamp.
3. No secrets in code. Config via pydantic-settings from env. Only .env.example is committed.
4. Every API route has Pydantic request AND response models.
5. Protected attributes (customer_age, employment_status, income) are NEVER model features. Fairness evaluation only.
6. Temporal splits only. Never random-split fraud data.
7. Real numbers only. Never invent metrics.
8. docs/openapi.json is frozen at 16:00 Monday. Changes after that need the human's OK.

## Conventions
- backend/app layout: api/v1 (thin routes) → services/ (logic) → repositories/ (all SQL) → models/ (ORM); schemas/ (Pydantic); core/ (config, logging, security)
- pytest; tests for critical paths, not coverage %.
- Structured JSON logging with request_id on every line.
- Conventional commits: feat: / fix: / test: / docs: / chore:

## Model policy (Claude lanes)
Default Sonnet. Ask the human to switch to Opus ONLY for: planning, A4 entity graph CTE, A5 drift logic,
B6 guardrails/LLM invariant, R1 audit, or a bug that survived 2 fix attempts. Ask to switch back after.
One line: "Switch to Opus for <task> — <reason>." Then wait.

## Current status
- Lane A: GATE 1 passed 16:25 (A3 done). Real model lgbm-if-v1 + SHAP top-4 reasons live; docs/openapi.json FROZEN (18 routes).
  API http://localhost:8000 (/docs), Postgres localhost:5432 (creds in .env). Live: /auth/login, /decisions/*, /adverse-action,
  /cases/{id}/similar, /copilot/ask (Lane B routers wired + embed hook). A4 DONE 17:05: entity graph + uplift live.
  GATE 2 passed 18:25 (A5): POST /stream/start → /stream/switch?source=shift → drift in ~9 s, bands 300/650/850 → 225/575/775.
  All 18 routes live. SSE: GET /stream?token=<jwt> (event: decision | drift). Shift source = variant rows with a SIMULATED
  fraud wave (12% fraud, REPLAY_SHIFT_FRAUD_RATE) — README must disclose.
  A6 DONE 18:55: AUTH ENFORCED. Every route except /health /ready /docs /auth/login needs `Authorization: Bearer <jwt>`
  (SSE: ?token=). Analyst = read; admin = + /stream/start|stop|switch, /metrics/drift/reset. Tokens last 60 min: long
  loads must re-login on 401. Rate limits per user: 600/min default, 3000/min POST /decisions/application, login 10/min/IP.
  CORS allows http://localhost:5173. R1 handover items 1-4 all done. Next: A7 (Lane F integration).
  WSL note: Docker lives in WSL Ubuntu; a detached `wsl.exe … sleep infinity` keepalive stops the distro idling out. After a reboot or `wsl --shutdown`, ask Lane A to restart it.
- Lane B: R1 audit done (docs/audit-R1.md). gitleaks CLEAN on history. Fixed 3 in my lane incl. a HIGH that crashed Lane A startup (features.json key). LANE A MUST DO: requirements pins, A6 auth enforcement, router wiring, alembic/env.py import.
- Lane F: not started
