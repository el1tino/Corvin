"""Server-rendered dashboard: the human-facing half of the MVP.

Deliberately thin: every handler here delegates to the same service layer
(app.services.*) the JSON API uses, so the webhook path and a human
clicking through the UI produce byte-identical audit events and behavior.
No business logic should ever be added directly in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.security import create_access_token, verify_password
from ..database import get_db
from ..models import Incident, IncidentSource, User
from ..models.audit_event import AuditEvent
from ..schemas.facts import IncidentFacts
from ..services import clock_service, draft_service, incident_service
from .deps import get_customer_config

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@dataclass(frozen=True)
class FrameworkBadge:
    result: str
    label: str

FACTS_FIELDS = list(IncidentFacts.model_fields.keys())
_BOOL_FIELDS = {
    "critical_services_affected",
    "data_loss_confidentiality",
    "data_loss_integrity",
    "data_loss_availability",
    "data_loss_authenticity",
    "severe_operational_disruption",
    "significant_financial_loss",
    "affects_other_persons_considerable_damage",
    "personal_data_involved",
    "breach_likely_risk_to_individuals",
    "breach_likely_high_risk_to_individuals",
}


def _redirect(url: str, *, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    if msg:
        url = f"{url}{sep}msg={quote(msg)}"
    elif err:
        url = f"{url}{sep}err={quote(err)}"
    return RedirectResponse(url, status_code=303)


def _get_current_user_optional(request: Request, db: Session) -> User | None:
    from ..auth.security import decode_access_token

    token = request.cookies.get("corvin_session")
    if not token:
        return None
    claims = decode_access_token(token)
    if not claims:
        return None
    return db.get(User, claims.get("sub"))


def _parse_form_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _facts_from_form(form) -> dict:
    facts: dict = {}
    for field in FACTS_FIELDS:
        if field in _BOOL_FIELDS:
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


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == username)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        return _redirect("/login", err="Incorrect email or password")
    token = create_access_token(subject=user.id, extra_claims={"role": user.role.value})
    response = _redirect("/dashboard")
    response.set_cookie("corvin_session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24)
    return response


@router.post("/logout")
def logout_submit():
    response = _redirect("/login")
    response.delete_cookie("corvin_session")
    return response


@router.get("/")
def index():
    return _redirect("/dashboard")


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")

    incidents = list(db.execute(select(Incident).order_by(Incident.created_at.desc())).scalars())
    rows = []
    for incident in incidents:
        confirmed_run = incident_service.latest_confirmed_run(incident)
        latest_run = incident_service.latest_classification_run(incident)
        source_run = confirmed_run or latest_run
        frameworks = {}
        if source_run:
            frameworks = {
                fw: FrameworkBadge(result=r["result"], label=r["label"])
                for fw, r in source_run.results.items()
                if r["result"] != "not_reportable"
            }
        clocks = clock_service.compute_incident_clocks(incident, confirmed_run)
        nearest = clock_service.nearest_deadline(clocks)
        is_overdue = nearest is not None and nearest.due_at < datetime.now(timezone.utc)
        rows.append(
            {
                "incident": incident,
                "frameworks": frameworks,
                "nearest_deadline": nearest,
                "is_overdue": is_overdue,
            }
        )
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "rows": rows})


@router.get("/incidents/new")
def incident_new_page(request: Request, db: Session = Depends(get_db)):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    return templates.TemplateResponse(request, "incident_new.html", {"user": user})


@router.post("/incidents/new")
async def incident_new_submit(request: Request, db: Session = Depends(get_db)):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    form = await request.form()
    facts = IncidentFacts(**_facts_from_form(form)).to_engine_dict()
    incident = incident_service.create_incident(
        db,
        title=form.get("title", "").strip() or "Untitled incident",
        description=form.get("description", ""),
        source=IncidentSource.MANUAL,
        facts=facts,
        detected_at=_parse_form_datetime(form.get("detected_at")),
        awareness_at=_parse_form_datetime(form.get("awareness_at")),
        created_by=user,
    )
    return _redirect(f"/incidents/{incident.id}", msg="Incident created")


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    incident = db.get(Incident, incident_id)
    if incident is None:
        return _redirect("/dashboard", err="Incident not found")

    latest_run = incident_service.latest_classification_run(incident)
    confirmed_run = incident_service.latest_confirmed_run(incident)
    facts_changed_since_run = bool(latest_run and latest_run.facts_snapshot != incident.facts)
    clocks = clock_service.compute_incident_clocks(incident, confirmed_run)

    reportable_frameworks = set()
    if confirmed_run:
        reportable_frameworks = {
            fw for fw, r in confirmed_run.results.items() if r["result"] == "reportable"
        }
    available_stages = {
        fw: stages for fw, stages in draft_service.FRAMEWORK_STAGES.items() if fw in reportable_frameworks
    }

    events = (
        db.execute(select(AuditEvent).where(AuditEvent.incident_id == incident.id).order_by(AuditEvent.seq))
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        request,
        "incident_detail.html",
        {
            "user": user,
            "incident": incident,
            "latest_run": latest_run,
            "confirmed_run": confirmed_run,
            "facts_changed_since_run": facts_changed_since_run,
            "clocks": clocks,
            "available_stages": available_stages,
            "events": events,
            "now": datetime.now(timezone.utc),
        },
    )


@router.post("/incidents/{incident_id}/facts")
async def incident_facts_submit(incident_id: str, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    incident = db.get(Incident, incident_id)
    if incident is None:
        return _redirect("/dashboard", err="Incident not found")
    form = await request.form()
    facts = IncidentFacts(**_facts_from_form(form)).to_engine_dict()
    incident_service.update_facts(
        db,
        incident,
        facts=facts,
        detected_at=_parse_form_datetime(form.get("detected_at")),
        awareness_at=_parse_form_datetime(form.get("awareness_at")),
        actor=user,
    )
    return _redirect(f"/incidents/{incident.id}", msg="Facts updated -- re-run classification")


@router.post("/incidents/{incident_id}/classify")
def incident_classify_submit(request: Request, incident_id: str, db: Session = Depends(get_db)):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    incident = db.get(Incident, incident_id)
    if incident is None:
        return _redirect("/dashboard", err="Incident not found")
    incident_service.run_classification(db, incident, user)
    return _redirect(f"/incidents/{incident.id}", msg="Classification run")


@router.post("/incidents/{incident_id}/confirm")
def incident_confirm_submit(
    request: Request, incident_id: str, run_id: str = Form(...), db: Session = Depends(get_db)
):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    incident = db.get(Incident, incident_id)
    if incident is None:
        return _redirect("/dashboard", err="Incident not found")
    try:
        incident_service.confirm_classification(db, incident, run_id, user)
    except incident_service.StaleClassificationError as exc:
        return _redirect(f"/incidents/{incident.id}", err=str(exc))
    return _redirect(f"/incidents/{incident.id}", msg=f"Classification confirmed by {user.display_label()}")


@router.post("/incidents/{incident_id}/drafts")
def incident_generate_draft_submit(
    request: Request,
    incident_id: str,
    framework: str = Form(...),
    stage: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    incident = db.get(Incident, incident_id)
    if incident is None:
        return _redirect("/dashboard", err="Incident not found")
    confirmed_run = incident_service.latest_confirmed_run(incident)
    customer = get_customer_config(db)
    try:
        draft_service.generate_incident_draft(
            db, incident, confirmed_run, customer, framework=framework, stage=stage, actor=user
        )
    except draft_service.DraftNotAllowedError as exc:
        return _redirect(f"/incidents/{incident.id}", err=str(exc))
    return _redirect(f"/incidents/{incident.id}", msg=f"Draft generated: {stage}")


@router.post("/incidents/{incident_id}/drafts/{draft_id}/edit")
def incident_edit_draft_submit(
    request: Request,
    incident_id: str,
    draft_id: str,
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    from ..models import Draft

    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    draft = db.get(Draft, draft_id)
    if draft is None or draft.incident_id != incident_id:
        return _redirect("/dashboard", err="Draft not found")
    draft_service.edit_draft(db, draft, content=content, actor=user)
    return _redirect(f"/incidents/{incident_id}", msg="Draft updated")


@router.post("/incidents/{incident_id}/drafts/{draft_id}/export")
def incident_export_draft_submit(
    request: Request,
    incident_id: str,
    draft_id: str,
    fmt: str = Form(...),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response

    from ..models import Draft

    user = _get_current_user_optional(request, db)
    if user is None:
        return _redirect("/login")
    incident = db.get(Incident, incident_id)
    draft = db.get(Draft, draft_id)
    if incident is None or draft is None or draft.incident_id != incident_id:
        return _redirect("/dashboard", err="Draft not found")
    confirmed_run = incident_service.latest_confirmed_run(incident)
    try:
        data = draft_service.export_draft(db, draft, incident, confirmed_run, fmt=fmt, actor=user)
    except draft_service.DraftNotAllowedError as exc:
        return _redirect(f"/incidents/{incident_id}", err=str(exc))
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if fmt == "docx"
        else "application/pdf"
    )
    filename = f"{incident.id}-{draft.stage.value}-v{draft.version}.{fmt}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
