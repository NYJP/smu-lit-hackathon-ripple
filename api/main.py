"""FastAPI app: routers, startup, and the section 9 error envelope.

Base path `/api/v1`. Binds to 127.0.0.1 only when run via `run.py dev`
(uvicorn's bind address is set there, not here, so `api.main:app` stays
importable and testable without opening a socket).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # section 5.3: .env at the repository root, read before db/env lookups

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import db
from api.services import openai
from api.errors import ApiError, code_for_status, error_envelope
from api.routers import (
    auth as auth_router,
    changes,
    dashboard,
    dependencies as dependencies_router,
    documents,
    files,
    graph,
    impacts,
    jobs,
    recommendations,
    regulations,
    requirements,
    scans,
    search,
    simulations,
    users as users_router,
)

logger = logging.getLogger("ripple")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Section 5.2 boot sequence: create ./data if absent, run migrations,
    # load sqlite-vec, seed the three default accounts if `users` is empty.
    # No OpenAI calls happen here this wave — see api/routers for the
    # honest reason every content-bearing endpoint still 501s.
    logger.info("Booting Ripple API: running migrations and loading sqlite-vec...")
    conn = db.bootstrap()
    conn.close()
    logger.info("Boot complete.")
    yield


app = FastAPI(title="Ripple API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("RIPPLE_WEB_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(exc.code, exc.message, exc.details),
    )


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic/FastAPI validation failures MUST use the same envelope as
    # every other 4xx (section 9) — never FastAPI's default {"detail": [...]}.
    return JSONResponse(
        status_code=422,
        content=error_envelope("validation_error", "Request validation failed.", exc.errors()),
    )


@app.exception_handler(StarletteHTTPException)
async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(code_for_status(exc.status_code), detail, None),
    )


@app.exception_handler(Exception)
async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_envelope("internal_error", "An unexpected error occurred.", None),
    )


api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health")
def health() -> dict:
    """No session required (section 9). Makes no OpenAI calls this wave —
    see the report for why 'unconfigured' / 'configured' replace section
    9.8's 'ok' / 'unreachable' pair until embeddings actually run."""
    try:
        conn = db.get_connection()
        try:
            conn.execute("SELECT 1")
            db_status = "ok"
        finally:
            conn.close()
    except Exception:
        logger.exception("Health check could not open the database")
        db_status = "error"

    return {
        "status": "ok" if db_status == "ok" else "error",
        "db": db_status,
        "openai": openai.status(),
        "embedding_dims": db.EMBEDDING_DIMS,
    }


api_router.include_router(auth_router.router)
api_router.include_router(users_router.router)
api_router.include_router(regulations.router)
api_router.include_router(requirements.router)
api_router.include_router(documents.router)
api_router.include_router(dependencies_router.router)
api_router.include_router(changes.router)
api_router.include_router(impacts.router)
api_router.include_router(recommendations.router)
api_router.include_router(simulations.router)
api_router.include_router(scans.router)
api_router.include_router(graph.router)
api_router.include_router(search.router)
api_router.include_router(jobs.router)
api_router.include_router(dashboard.router)
api_router.include_router(files.router)

app.include_router(api_router)
