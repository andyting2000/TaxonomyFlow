from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import FilingJob, FinancialStatementPage, User, get_db
from routers.filings import _build_filing_job_cleanup_plan, _delete_upload_artifacts
from schemas import AdminChangeUserPasswordRequest, AdminCreateUserRequest
from security import get_current_admin_user
from services.auth_service import hash_password, normalize_email


router = APIRouter()


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin_user: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        select(User)
        .where(User.is_deleted.is_(False))
        .where(User.is_admin.is_(False))
        .order_by(User.created_at.asc(), User.id.asc())
    )
    users = list(result.scalars().all())
    user_ids = [user.id for user in users]

    task_counts = {
        user_id: {
            "successful_task_count": 0,
            "processing_task_count": 0,
            "error_task_count": 0,
            "task_count": 0,
        }
        for user_id in user_ids
    }
    if user_ids:
        count_result = await db.execute(
            select(FilingJob.user_id, FilingJob.status, func.count(FilingJob.id))
            .where(FilingJob.user_id.in_(user_ids))
            .group_by(FilingJob.user_id, FilingJob.status)
        )
        for user_id, job_status, task_count in count_result.all():
            if user_id is None or user_id not in task_counts:
                continue
            status_value = getattr(job_status, "value", job_status)
            count = int(task_count)
            task_counts[user_id]["task_count"] += count
            if status_value in {"REVIEW", "COMPLETED"}:
                task_counts[user_id]["successful_task_count"] += count
            elif status_value == "PROCESSING":
                task_counts[user_id]["processing_task_count"] += count
            elif status_value == "ERROR":
                task_counts[user_id]["error_task_count"] += count

    return {
        "users": [
            {
                "user_id": user.id,
                "email": user.email,
                "created_at": user.created_at,
                "registered_at": user.created_at,
                "is_admin": bool(user.is_admin),
                "user_type": "ADMIN" if user.is_admin else "USER",
                **task_counts[user.id],
            }
            for user in users
        ]
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminCreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _admin_user: User = Depends(get_current_admin_user),
):
    if payload.password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password and confirmation do not match",
        )

    email = normalize_email(payload.email)
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        token_version=0,
        is_admin=False,
        is_active=True,
        is_deleted=False,
    )
    db.add(user)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    return {
        "success": True,
        "message": "User created.",
        "user_id": user.id,
        "email": user.email,
        "is_admin": False,
    }


@router.post("/users/{user_id}/change-password")
async def change_user_password(
    user_id: int,
    payload: AdminChangeUserPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _admin_user: User = Depends(get_current_admin_user),
):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirmation do not match",
        )

    target_user = await _get_target_user_or_404(db, user_id)
    _ensure_normal_user_target(target_user, "Cannot change another admin password")

    target_user.password_hash = hash_password(payload.new_password)
    target_user.token_version = (target_user.token_version or 0) + 1
    target_user.updated_at = datetime.utcnow()

    return {
        "success": True,
        "message": "User password changed.",
        "user_id": target_user.id,
    }


@router.post("/users/{user_id}/clear-tasks")
async def clear_user_tasks(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin_user: User = Depends(get_current_admin_user),
):
    target_user = await _get_target_user_or_404(db, user_id)
    _ensure_normal_user_target(target_user, "Cannot clear tasks for an admin user")

    summary = await _delete_user_owned_jobs(db, target_user)
    return {
        "success": True,
        "message": "User tasks cleared.",
        "user_id": target_user.id,
        **summary,
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    if user_id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin users cannot delete their own account.",
        )

    target_user = await _get_target_user_or_404(db, user_id)
    _ensure_normal_user_target(target_user, "Cannot delete an admin user")

    summary = await _delete_user_owned_jobs(db, target_user, delete_user_row=True)
    return {
        "success": True,
        "message": "User deleted.",
        "user_id": target_user.id,
        "deleted_user": True,
        **summary,
    }


async def _get_target_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _ensure_normal_user_target(user: User, detail: str) -> None:
    if user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


async def _load_owned_jobs(db: AsyncSession, user_id: int) -> list[FilingJob]:
    result = await db.execute(
        select(FilingJob)
        .where(FilingJob.user_id == user_id)
        .options(
            selectinload(FilingJob.pages).selectinload(
                FinancialStatementPage.extracted_items
            ),
            selectinload(FilingJob.llm_mapping_suggestions),
        )
    )
    return list(result.scalars().all())


async def _delete_user_owned_jobs(
    db: AsyncSession,
    target_user: User,
    *,
    delete_user_row: bool = False,
) -> dict:
    owned_jobs = await _load_owned_jobs(db, target_user.id)

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
        if delete_user_row:
            await db.delete(target_user)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user data",
        ) from exc

    artifact_cleanup = _delete_upload_artifacts(file_candidates)

    from services.smart_ai_processor import status_tracker

    for job in owned_jobs:
        status_tracker.clear_status(job.id)

    return {
        "deleted_jobs_count": len(owned_jobs),
        "deleted_pages_count": deleted_pages_count,
        "deleted_extracted_items_count": deleted_extracted_items_count,
        "deleted_files_count": artifact_cleanup["deleted_files_count"],
        "skipped_missing_files_count": artifact_cleanup[
            "skipped_missing_files_count"
        ],
    }
