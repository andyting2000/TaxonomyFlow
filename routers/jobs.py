# routers/jobs.py
"""
Job management and monitoring endpoints
Provides utility functions for job processing, monitoring, and system maintenance
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db, FilingJob, ExtractedDataItem, FinancialStatementPage, User
from schemas import JobStatus
from services.smart_ai_processor import smart_ai_processor, status_tracker, process_pdf_background
from security import get_current_workspace_user, require_admin_route_token
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{job_id}/reprocess", dependencies=[Depends(require_admin_route_token)])
async def reprocess_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Reprocess a filing job - clears existing data and restarts extraction"""

    result = await db.execute(
        select(FilingJob).where(
            FilingJob.id == job_id,
            FilingJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Clear existing data
    await db.execute(
        ExtractedDataItem.delete().where(
            ExtractedDataItem.page_id.in_(
                select(FinancialStatementPage.id).where(
                    FinancialStatementPage.job_id == job_id
                )
            )
        )
    )

    # Reset job status
    job.status = JobStatus.PROCESSING
    job.directors_report_html = None
    await db.commit()

    # Start reprocessing
    background_tasks.add_task(process_pdf_background, job_id, db)

    logger.info(f"Started reprocessing for job {job_id}")

    return {"message": "Reprocessing started", "job_id": job_id}


@router.get("/processing")
async def get_processing_jobs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Get all jobs currently being processed with real-time progress updates"""

    # Get all PROCESSING jobs
    result = await db.execute(
        select(FilingJob).where(
            FilingJob.status == JobStatus.PROCESSING,
            FilingJob.user_id == current_user.id,
        )
    )
    processing_jobs = result.scalars().all()

    processing_info = []

    # Add status info for PROCESSING jobs
    for job in processing_jobs:
        status = await status_tracker.get_status(job.id, db)
        processing_info.append({
            "job_id": job.id,
            "company_name": job.company_name,
            "status": status.status.value if hasattr(status.status, 'value') else status.status,
            "progress": status.progress if status.progress is not None else 0,
            "uploaded_at": job.uploaded_at
        })

    # Check Redis for recently completed jobs to ensure frontend gets the final
    # REVIEW/ERROR/COMPLETED transition even when processing takes more than a minute.
    try:
        from services.redis_status_tracker import redis_status_tracker
        from datetime import datetime, timedelta, timezone

        if redis_status_tracker.initialized:
            recent_threshold = datetime.now(timezone.utc) - timedelta(minutes=30)

            result = await db.execute(
                select(FilingJob).where(
                    and_(
                        FilingJob.status.in_([JobStatus.REVIEW, JobStatus.ERROR, JobStatus.COMPLETED]),
                        FilingJob.uploaded_at >= recent_threshold,
                        FilingJob.user_id == current_user.id,
                    )
                )
            )
            recent_completed = result.scalars().all()

            for job in recent_completed:
                redis_status = await redis_status_tracker.get_status(job.id)
                if redis_status and redis_status.progress is not None:
                    if not any(existing["job_id"] == job.id for existing in processing_info):
                        processing_info.append({
                            "job_id": job.id,
                            "company_name": job.company_name,
                            "status": redis_status.status.value if hasattr(redis_status.status, 'value') else redis_status.status,
                            "progress": redis_status.progress,
                            "uploaded_at": job.uploaded_at
                        })
    except Exception as e:
        logger.debug(f"Could not check Redis for recently completed jobs: {e}")

    return processing_info


@router.post(
    "/maintenance/clear-cache",
    dependencies=[Depends(require_admin_route_token)]
)
async def clear_cache():
    """Clear all caches (admin function)"""
    
    from cache import cache_manager
    
    patterns = ['taxonomy_search_*', 'job_status_*', 'fuzzy_matching*']
    cleared_count = 0
    
    for pattern in patterns:
        count = await cache_manager.delete_pattern(pattern)
        cleared_count += count
    
    logger.info(f"Cleared {cleared_count} cache entries")
    
    return {"message": f"Cleared {cleared_count} cache entries"}


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check for the jobs system"""
    
    try:
        # Test database connection
        await db.execute(select(func.count(FilingJob.id)))
        
        # Test AI service (basic check)
        ai_status = "available" if smart_ai_processor else "unavailable"
        
        return {
            "status": "healthy",
            "database": "connected",
            "ai_service": ai_status,
            "cache": "available"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")
