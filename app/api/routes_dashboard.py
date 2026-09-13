"""Server-rendered dashboard: the human-facing half of the MVP.

Deliberately thin: every handler delegates to the same service layer
(app.services.*) the JSON API uses, so the webhook path and a human
clicking through the UI produce identical audit events and behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_dashboard_user
from ..auth.security import SESSION_COOKIE, authenticate_user, create_access_token, set_session_cookie
from ..clocks.utils import to_local
from ..database import get_db
from ..models import CustomerConfig, Draft, Incident, IncidentSource, IncidentStatus, User
from ..models.audit_event import AuditEvent
from ..schemas.facts import IncidentFacts
from ..services import clock_service, draft_service, incident_service
from .deps import get_customer_config

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _localtime(dt: datetime | None, tz_name: str, fmt: str = "%Y-%m-%d %H:%M %Z") -> str:
    """Timestamps are stored in UTC and displayed in the customer's configured timezone."""
    if dt is None:
        return "—"
    return to_local(dt, tz_name).strftime(fmt)


templates.env.filters["localtime"] = _localtime

_BOOL_FACTS = {
    name for name, field in IncidentFacts.model_fields.items() if field.annotation == (bool | None)
}


def _redirect(url: str, *, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    if msg:
        url = f"{url}{sep}msg={quote(msg)}"
    elif err:
        url = f"{url}{sep}err={quote(err)}"
    return RedirectResponse(url, status_code=303)


def _render(request: Request, name: str, user: User | None, config: CustomerConfig, **ctx: Any):
    return templates.TemplateResponse(
        request,
        name,
        {"user": user, "tz": config.default_timezone, "entity_name": config.entity_name, **ctx},
    )


def _parse_form_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _facts_from_form(form) -> dict:
    facts: dict = {}
    for field in IncidentFacts.model_fields:
        if field in _BOOL_FACTS:
            facts[field] = field in form
            continue
        raw = form.get(field)
        if raw in (None, ""):
            continue
        try:
            facts[field] = float(raw) if "." in raw else int(raw)
        except ValueError:
            facts[field] = raw
    return facts


def _incident_or_redirect(db: Session, incident_id: str) -> Incident | RedirectResponse:
    incident = db.get(Incident, incident_id)
    return incident if incident is not None else _redirect("/dashboard", err="Incident not found")


# --- auth -----------------------------------------------------------------


@router.get("/login")
def login_page(request: Request, config: CustomerConfig = Depends(get_customer_config)):
    return _render(request, "login.html", None, config)


@router.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = authenticate_user(db, username, password)
    if user is None:
        return _redirect("/login", err="Incorrect email or password")
    response = _redirect("/dashboard")
    set_session_cookie(response, create_access_token(subject=user.id, extra_claims={"role": user.role.value}))
    return response


@router.post("/logout")
def logout_submit():
    response = _redirect("/login")
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/")
def index():
    return _redirect("/dashboard")


# --- dashboard --------------------------------------------------------------


@router.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
    config: CustomerConfig = Depends(get_customer_config),
):
    incidents = db.execute(select(Incident).order_by(Incident.created_at.desc())).scalars().all()
    now = datetime.now(UTC)
    open_rows, closed_rows = [], []
    for incident in incidents:
        confirmed_run = incident_service.latest_confirmed_run(incident)
        source_run = confirmed_run or incident_service.latest_classification_run(incident)
        frameworks = (
            {fw: r for fw, r in source_run.results.items() if r["result"] != "not_reportable"}
            if source_run
            else {}
        )
        clocks = clock_service.compute_incident_clocks(incident, confirmed_run)
        nearest = clock_service.nearest_deadline(clocks)
        row = {
            "incident": incident,
            "frameworks": frameworks,
            "nearest_deadline": nearest,
            "is_overdue": nearest is not None and nearest.due_at < now,
        }
        (closed_rows if incident.status is IncidentStatus.CLOSED else open_rows).append(row)
    return _render(request, "dashboard.html", user, config, open_rows=open_rows, closed_rows=closed_rows)


@router.get("/incidents/new")
def incident_new_page(
    request: Request,
    user: User = Depends(get_dashboard_user),
    config: CustomerConfig = Depends(get_customer_config),
):
    return _render(request, "incident_new.html", user, config)


@router.post("/incidents/new")
async def incident_new_submit(
    request: Request, db: Session = Depends(get_db), user: User = Depends(get_dashboard_user)
):
    form = await request.form()
    incident = incident_service.create_incident(
        db,
        title=form.get("title", "").strip() or "Untitled incident",
        description=form.get("description", ""),
        source=IncidentSource.MANUAL,
        facts=IncidentFacts(**_facts_from_form(form)).to_engine_dict(),
        detected_at=_parse_form_datetime(form.get("detected_at")),
        awareness_at=_parse_form_datetime(form.get("awareness_at")),
        created_by=user,
    )
    return _redirect(f"/incidents/{incident.id}", msg="Incident created")


@router.get("/incidents/{incident_id}")
def incident_detail(
    incident_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
    config: CustomerConfig = Depends(get_customer_config),
):
    incident = _incident_or_redirect(db, incident_id)
    if isinstance(incident, RedirectResponse):
        return incident

    latest_run = incident_service.latest_classification_run(incident)
    confirmed_run = incident_service.latest_confirmed_run(incident)
    reportable = (
        {fw for fw, r in confirmed_run.results.items() if r["result"] == "reportable"}
        if confirmed_run
        else set()
    )
    events = (
        db.execute(select(AuditEvent).where(AuditEvent.incident_id == incident.id).order_by(AuditEvent.seq))
        .scalars()
        .all()
    )
    return _render(
        request,
        "incident_detail.html",
        user,
        config,
        incident=incident,
        latest_run=latest_run,
        confirmed_run=confirmed_run,
        facts_changed_since_run=bool(latest_run and latest_run.facts_snapshot != incident.facts),
        clocks=clock_service.compute_incident_clocks(incident, confirmed_run),
        available_stages={fw: s for fw, s in draft_service.FRAMEWORK_STAGES.items() if fw in reportable},
        events=events,
        now=datetime.now(UTC),
    )


@router.post("/incidents/{incident_id}/facts")
async def incident_facts_submit(
    incident_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
):
    incident = _incident_or_redirect(db, incident_id)
    if isinstance(incident, RedirectResponse):
        return incident
    form = await request.form()
    incident_service.update_facts(
        db,
        incident,
        facts=IncidentFacts(**_facts_from_form(form)).to_engine_dict(),
        detected_at=_parse_form_datetime(form.get("detected_at")),
        awareness_at=_parse_form_datetime(form.get("awareness_at")),
        actor=user,
    )
    return _redirect(f"/incidents/{incident.id}", msg="Facts updated -- re-run classification")


@router.post("/incidents/{incident_id}/classify")
def incident_classify_submit(
    incident_id: str, db: Session = Depends(get_db), user: User = Depends(get_dashboard_user)
):
    incident = _incident_or_redirect(db, incident_id)
    if isinstance(incident, RedirectResponse):
        return incident
    incident_service.run_classification(db, incident, user)
    return _redirect(f"/incidents/{incident.id}", msg="Classification engine run -- review and confirm below")


@router.post("/incidents/{incident_id}/confirm")
def incident_confirm_submit(
    incident_id: str,
    run_id: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
):
    incident = _incident_or_redirect(db, incident_id)
    if isinstance(incident, RedirectResponse):
        return incident
    try:
        incident_service.confirm_classification(db, incident, run_id, user)
    except incident_service.StaleClassificationError as exc:
        return _redirect(f"/incidents/{incident.id}", err=str(exc))
    return _redirect(f"/incidents/{incident.id}", msg=f"Classification confirmed by {user.display_label()}")


@router.post("/incidents/{incident_id}/close")
def incident_close_submit(
    incident_id: str, db: Session = Depends(get_db), user: User = Depends(get_dashboard_user)
):
    incident = _incident_or_redirect(db, incident_id)
    if isinstance(incident, RedirectResponse):
        return incident
    incident_service.close_incident(db, incident, actor=user)
    return _redirect(f"/incidents/{incident.id}", msg="Incident closed")


# --- drafts -----------------------------------------------------------------


def _draft_or_redirect(db: Session, incident_id: str, draft_id: str) -> Draft | RedirectResponse:
    draft = db.get(Draft, draft_id)
    if draft is None or draft.incident_id != incident_id:
        return _redirect(f"/incidents/{incident_id}", err="Draft not found")
    return draft


@router.post("/incidents/{incident_id}/drafts")
def incident_generate_draft_submit(
    incident_id: str,
    framework: str = Form(...),
    stage: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
    config: CustomerConfig = Depends(get_customer_config),
):
    incident = _incident_or_redirect(db, incident_id)
    if isinstance(incident, RedirectResponse):
        return incident
    try:
        draft = draft_service.generate_incident_draft(
            db,
            incident,
            incident_service.latest_confirmed_run(incident),
            config,
            framework=framework,
            stage=stage,
            actor=user,
        )
    except draft_service.DraftNotAllowedError as exc:
        return _redirect(f"/incidents/{incident.id}", err=str(exc))
    return _redirect(
        f"/incidents/{incident.id}", msg=f"Draft generated: {stage} v{draft.version} ({draft.model_used})"
    )


@router.post("/incidents/{incident_id}/drafts/{draft_id}/edit")
def incident_edit_draft_submit(
    incident_id: str,
    draft_id: str,
    content: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
):
    draft = _draft_or_redirect(db, incident_id, draft_id)
    if isinstance(draft, RedirectResponse):
        return draft
    draft_service.edit_draft(db, draft, content=content, actor=user)
    return _redirect(f"/incidents/{incident_id}", msg="Draft updated")


@router.post("/incidents/{incident_id}/drafts/{draft_id}/submitted")
def incident_mark_draft_submitted(
    incident_id: str,
    draft_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
):
    draft = _draft_or_redirect(db, incident_id, draft_id)
    if isinstance(draft, RedirectResponse):
        return draft
    try:
        draft_service.mark_draft_submitted(db, draft, actor=user)
    except draft_service.DraftNotAllowedError as exc:
        return _redirect(f"/incidents/{incident_id}", err=str(exc))
    return _redirect(
        f"/incidents/{incident_id}", msg="Recorded as submitted -- dependent clocks now run from this time"
    )


@router.post("/incidents/{incident_id}/drafts/{draft_id}/export")
def incident_export_draft_submit(
    incident_id: str,
    draft_id: str,
    fmt: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_dashboard_user),
):
    draft = _draft_or_redirect(db, incident_id, draft_id)
    if isinstance(draft, RedirectResponse):
        return draft
    incident = draft.incident
    try:
        data = draft_service.export_draft(
            db, draft, incident, incident_service.latest_confirmed_run(incident), fmt=fmt, actor=user
        )
    except (draft_service.DraftNotAllowedError, ValueError) as exc:
        return _redirect(f"/incidents/{incident_id}", err=str(exc))
    return Response(
        content=data,
        media_type=draft_service.MEDIA_TYPES[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{draft_service.export_filename(draft, fmt)}"'
        },
    )
