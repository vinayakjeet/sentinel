from fastapi import APIRouter

from app.api.v1 import _contract_stubs, auth, decisions, entities, metrics, stream

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(decisions.router)
api_router.include_router(entities.router)
api_router.include_router(stream.router)
api_router.include_router(metrics.router)
# Lane B: replace each stub with the real router (same paths, same models) when it lands.
api_router.include_router(_contract_stubs.cases_router)
api_router.include_router(_contract_stubs.copilot_router)
