from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes_audit import router as audit_router
from .api.routes_config import router as config_router
from .api.routes_dashboard import router as dashboard_router
from .api.routes_drafts import router as drafts_router
from .api.routes_incidents import router as incidents_router
from .api.routes_webhook import router as webhook_router
from .auth.routes import router as auth_router

app = FastAPI(
    title="Corvin",
    description="Compliance-aware incident-response orchestrator (MVP)",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(incidents_router)
app.include_router(drafts_router)
app.include_router(audit_router)
app.include_router(config_router)
app.include_router(dashboard_router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
