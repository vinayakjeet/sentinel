from fastapi import APIRouter

from app.api.v1 import auth, decisions, entities, metrics, stream
from app.llm.router import router as copilot_router
from app.semantic.router import router as cases_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(decisions.router)
api_router.include_router(entities.router)
api_router.include_router(stream.router)
api_router.include_router(metrics.router)
# Lane B routers (same paths and models as the frozen contract).
api_router.include_router(cases_router)
api_router.include_router(copilot_router)
