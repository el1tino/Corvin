from __future__ import annotations

from collections.abc import Callable

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, User
from .security import SESSION_COOKIE, decode_access_token

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


class LoginRequired(Exception):
    """Raised by dashboard routes when no valid session cookie is present.

    Handled app-wide (see app.main) by redirecting to the login page, so
    HTML routes get a redirect while JSON routes keep their 401: one auth
    implementation, two presentations.
    """


def _resolve_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    claims = decode_access_token(token)
    if not claims or "sub" not in claims:
        return None
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(
    bearer_token: str | None = Depends(_oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> User:
    """Auth for JSON routes: accepts an API bearer token or the dashboard's
    session cookie, both issued by the same /auth/token endpoint."""
    user = _resolve_user(db, bearer_token or session_cookie)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_dashboard_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Auth for HTML routes: same resolution, but a missing session becomes
    a redirect to /login instead of a JSON 401."""
    user = _resolve_user(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise LoginRequired
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """Dependency factory enforcing role separation (analyst, compliance, admin)."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' is not permitted to perform this action",
            )
        return user

    return _checker


require_admin = require_roles(Role.ADMIN)
require_compliance = require_roles(Role.COMPLIANCE, Role.ADMIN)
require_analyst = require_roles(Role.ANALYST, Role.COMPLIANCE, Role.ADMIN)
