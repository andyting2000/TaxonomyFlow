import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import User, get_db
from services.auth_service import AUTH_SECRET_NOT_CONFIGURED_MESSAGE, verify_access_token


_UNSET_ADMIN_TOKENS = {
    "",
    "replace-with-random-admin-route-token",
    "change-this-admin-route-token",
}


def require_admin_route_token(x_admin_token: str = Header(default="")) -> None:
    """Minimal route gate for dangerous operations until full auth exists."""
    expected_token = settings.admin_route_token.strip()

    if expected_token in _UNSET_ADMIN_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin route token is not configured",
        )

    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin route token required",
        )


async def get_current_user(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return the active user identified by the Bearer token."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_access_token(token)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_SECRET_NOT_CONFIGURED_MESSAGE,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()

    if (
        not user
        or not user.is_active
        or user.is_deleted
        or payload.token_version != (user.token_version or 0)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_workspace_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return an authenticated non-admin user for filing/job workspace routes."""
    if current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts cannot access the filing workspace.",
        )

    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return an authenticated admin user for future admin-only routes."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    return current_user
