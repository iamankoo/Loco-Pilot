"""FastAPI application factory and entrypoint.

Run with: uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.health import router as health_router
from backend.app.api.v1.router import router as v1_router
from backend.app.core.config import get_settings
from backend.app.core.errors import LocoPilotError
from backend.app.core.logging import configure_logging, get_logger
from backend.app.services import runtime_service


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Best-effort: a `locopilot-rt-*` container from a previous backend
    # process life outlives that process (backend.app.services.runtime_service's
    # registry is in-memory only) — stop any still running before this
    # process starts tracking new ones, so a restart never leaks one.
    await runtime_service.sweep_orphaned_containers()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(component="app")

    app = FastAPI(title="LocoPilot API", version="0.1.0", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(LocoPilotError)
    async def locopilot_error_handler(request: Request, exc: LocoPilotError) -> JSONResponse:
        logger.warning("request_failed", code=exc.code, detail=exc.message, path=request.url.path)
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "detail": exc.message})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": "An unexpected error occurred."},
        )

    app.include_router(health_router)
    app.include_router(v1_router, prefix="/api/v1")

    logger.info("app_configured", app_env=settings.app_env)
    return app


app = create_app()
