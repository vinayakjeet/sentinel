"""Analyst copilot (DESIGN §9).

CLAUDE.md invariant 1: the LLM layer has NO write path to a risk score or a decision. That is
enforced here in four independent ways, so that no single mistake removes the guarantee:

1. The tool registry refuses to register a tool that is not declared read-only (tools.py).
2. The model can only name tools that are already in the registry; anything else is refused.
3. Tool execution runs inside a Postgres `SET TRANSACTION READ ONLY` transaction that is always
   rolled back — the database itself rejects a write, whatever the code does.
4. The response model (app/schemas/copilot.py, owned by Lane A) has no field that could carry a
   score or a band, so there is nothing for a mutation to travel back in.

Lane A wiring — two lines in app/api/v1/router.py, replacing the contract stub:

    from app.llm.router import router as copilot_router
    api_router.include_router(copilot_router)
"""
