from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api.routes_audit import router as audit_router
from .api.routes_config import router as config_router
from .api.routes_dashboard import router as dashboard_router
from .api.routes_drafts import router as drafts_router
from .api.routes_incidents import router as incidents_router
from .api.routes_webhook import router as webhook_router
from .auth.deps import LoginRequired
from .auth.routes import router as auth_router
from .config import get_settings

logger = logging.getLogger("corvin")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    insecure = settings.insecure_defaults_in_use()
    if insecure and settings.is_production:
        raise RuntimeError(
            f"Refusing to start with placeholder secrets in production: {', '.join(insecure)}. "
            "Set them in the environment (see .env.example)."
        )
    if insecure:
        logger.warning("Running with placeholder secrets (%s). Fine for a demo, not for real use.", insecure)
    yield


app = FastAPI(
    title="Corvin",
    description="Compliance-aware incident-response orchestrator (MVP)",
    version="0.2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(incidents_router)
app.include_router(drafts_router)
app.include_router(audit_router)
app.include_router(config_router)
app.include_router(dashboard_router)


@app.exception_handler(LoginRequired)
async def _redirect_to_login(_: Request, __: LoginRequired) -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
