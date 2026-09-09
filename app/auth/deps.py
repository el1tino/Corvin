from __future__ import annotations

from collections.abc import Callable, Iterable

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, User
from .security import decode_access_token

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def _extract_token(
    bearer_token: str | None = Depends(_oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias="corvin_session"),
) -> str | None:
    # Supports both an API bearer token (webhook/API clients) and a browser
    # session cookie (the server-rendered dashboard), issued by the same
    # /auth/token endpoint.
    return bearer_token or session_cookie


def get_current_user(
    token: str | None = Depends(_extract_token),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise unauthorized
    claims = decode_access_token(token)
    if claims is None or "sub" not in claims:
        raise unauthorized
    user = db.execute(select(User).where(User.id == claims["sub"])).scalar_one_or_none()
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    """Dependency factory enforcing role separation (build spec: analyst,
    compliance, admin).
    """
    allowed: Iterable[Role] = roles

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' is not permitted to perform this action",
            )
        return user

    return _checker


require_admin = require_roles(Role.ADMIN)
require_compliance = require_roles(Role.COMPLIANCE, Role.ADMIN)
require_analyst = require_roles(Role.ANALYST, Role.COMPLIANCE, Role.ADMIN)
