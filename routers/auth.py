from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import FilingJob, FinancialStatementPage, User, get_db
from routers.filings import _build_filing_job_cleanup_plan, _delete_upload_artifacts
from schemas import (
    AuthTokenResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    DeleteAccountRequest,
    DeleteAccountResponse,
    LoginRequest,
    LogoutResponse,
    RegisterRequest,
    UserResponse,
)
from security import get_current_user
from services.auth_service import (
    AUTH_SECRET_NOT_CONFIGURED_MESSAGE,
    create_access_token,
    hash_password,
    normalize_email,
    verify_password,
)


router = APIRouter()


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    _payload: RegisterRequest,
    _db: AsyncSession = Depends(get_db),
):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Public registration is disabled. Please contact an administrator.",
    )


@router.post("/login", response_model=AuthTokenResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_by_email(db, normalize_email(payload.email))
    if (
        not user
        or not user.is_active
        or user.is_deleted
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.last_login_at = datetime.utcnow()
    return _build_auth_response(user)


@router.post("/logout", response_model=LogoutResponse)
async def logout(_current_user: User = Depends(get_current_user)):
    return {
        "success": True,
        "message": "Logged out. Discard the bearer token on the client.",
    }


@router.get("/current-user", response_model=UserResponse)
async def current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.new_password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirmation do not match",
        )

    if verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from your current password.",
        )

    current_user.password_hash = hash_password(payload.new_password)
    current_user.token_version = (current_user.token_version or 0) + 1
    current_user.updated_at = datetime.utcnow()

    return {
        "success": True,
        "message": "Password changed successfully.",
    }


@router.post("/delete-account", response_model=DeleteAccountResponse)
async def delete_account(
    payload: DeleteAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.email_confirmation != current_user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email confirmation does not match",
        )

    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.current_password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password confirmation does not match",
        )

    result = await db.execute(
        select(FilingJob)
        .where(FilingJob.user_id == current_user.id)
        .options(
            selectinload(FilingJob.pages).selectinload(
                FinancialStatementPage.extracted_items
            )
        )
    )
    owned_jobs = list(result.scalars().all())

    deleted_pages_count = 0
    deleted_extracted_items_count = 0
    file_candidates = []

    for job in owned_jobs:
        cleanup_plan = _build_filing_job_cleanup_plan(job)
        deleted_pages_count += cleanup_plan["deleted_pages_count"]
        deleted_extracted_items_count += cleanup_plan[
            "deleted_extracted_items_count"
        ]
        file_candidates.extend(cleanup_plan["file_candidates"])

    try:
        for job in owned_jobs:
            await db.delete(job)
        await db.delete(current_user)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete account",
        ) from exc

    artifact_cleanup = _delete_upload_artifacts(file_candidates)
    from services.smart_ai_processor import status_tracker

    for job in owned_jobs:
        status_tracker.clear_status(job.id)

    return {
        "success": True,
        "message": "Your account and all filing data have been permanently deleted.",
        "deleted_user": True,
        "deleted_jobs_count": len(owned_jobs),
        "deleted_pages_count": deleted_pages_count,
        "deleted_extracted_items_count": deleted_extracted_items_count,
        "deleted_files_count": artifact_cleanup["deleted_files_count"],
        "skipped_missing_files_count": artifact_cleanup[
            "skipped_missing_files_count"
        ],
    }


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


def _build_auth_response(user: User) -> dict:
    try:
        access_token = create_access_token(
            user.id,
            user.email,
            token_version=user.token_version or 0,
        )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AUTH_SECRET_NOT_CONFIGURED_MESSAGE,
        )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }
