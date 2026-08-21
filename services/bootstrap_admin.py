import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal, User
from services.auth_service import hash_password, normalize_email


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootstrapAdminResult:
    enabled: bool
    created: bool
    email: str | None = None
    reason: str | None = None


async def bootstrap_admin_account(
    db: AsyncSession | None = None,
) -> BootstrapAdminResult:
    """Create the optional environment-driven bootstrap account if enabled."""
    if not settings.bootstrap_admin_enabled:
        return BootstrapAdminResult(enabled=False, created=False, reason="disabled")

    email = normalize_email(settings.bootstrap_admin_email)
    password = settings.bootstrap_admin_password

    if not email or not password:
        raise RuntimeError(
            "Bootstrap admin account is enabled but BOOTSTRAP_ADMIN_EMAIL "
            "or BOOTSTRAP_ADMIN_PASSWORD is missing"
        )

    if db is not None:
        return await _bootstrap_admin_with_session(db, email, password, commit=False)

    async with AsyncSessionLocal() as session:
        try:
            result = await _bootstrap_admin_with_session(
                session,
                email,
                password,
                commit=True,
            )
            return result
        except Exception:
            await session.rollback()
            raise


async def _bootstrap_admin_with_session(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    commit: bool,
) -> BootstrapAdminResult:
    existing = await db.execute(select(User).where(User.email == email))
    existing_user = existing.scalar_one_or_none()
    if existing_user:
        if not existing_user.is_admin:
            existing_user.is_admin = True
            if commit:
                await db.commit()
        logger.info(
            "Bootstrap account already exists for %s; password unchanged",
            email,
        )
        return BootstrapAdminResult(
            enabled=True,
            created=False,
            email=email,
            reason="already_exists",
        )

    user = User(
        email=email,
        password_hash=hash_password(password),
        token_version=0,
        is_admin=True,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    if commit:
        await db.commit()

    logger.info("Created bootstrap account for %s", email)
    return BootstrapAdminResult(
        enabled=True,
        created=True,
        email=email,
        reason="created",
    )
