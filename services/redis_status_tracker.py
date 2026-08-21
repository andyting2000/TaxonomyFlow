# services/redis_status_tracker.py - Redis-based status tracking for cross-process progress updates

import asyncio
import json
import logging
import os
from inspect import isawaitable
from typing import Optional
from datetime import datetime, timezone
from redis import asyncio as aioredis
from schemas import ProcessingStatus, JobStatus, ProgressUpdate
from config import settings

logger = logging.getLogger(__name__)


class RedisStatusTracker:
    """
    Redis-based status tracker that works across Celery and FastAPI processes.
    Replaces the in-memory cache with Redis for persistent, cross-process status tracking.
    """

    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.initialized = False
        self._creation_loop_id = None
        self._creation_process_id = None

    @property
    def creation_loop_id(self):
        return self._creation_loop_id

    async def initialize(self):
        """Initialize Redis connection"""
        current_loop_id = id(asyncio.get_running_loop())
        current_process_id = os.getpid()
        if self.initialized and self.redis_client:
            if (
                self._creation_loop_id == current_loop_id
                and self._creation_process_id == current_process_id
            ):
                return
            logger.warning(
                "Discarding Redis client from incompatible async resource context: "
                "created_process_id=%s created_loop_id=%s current_process_id=%s current_loop_id=%s",
                self._creation_process_id,
                self._creation_loop_id,
                current_process_id,
                current_loop_id,
            )
            self.redis_client = None
            self.initialized = False
            self._creation_loop_id = None
            self._creation_process_id = None

        try:
            self.redis_client = await aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            # Test connection
            await self.redis_client.ping()
            self.initialized = True
            self._creation_loop_id = current_loop_id
            self._creation_process_id = current_process_id
            logger.info(
                "Redis status tracker initialized process_id=%s loop_id=%s client_id=%s",
                current_process_id,
                current_loop_id,
                id(self.redis_client),
            )
            logger.info("✅ Redis status tracker initialized")
        except Exception as e:
            logger.warning(f"⚠️ Redis status tracker failed to initialize: {e}")
            self.redis_client = None
            self.initialized = False
            self._creation_loop_id = None
            self._creation_process_id = None

    async def update_progress(self, progress_update: ProgressUpdate):
        """Store progress update in Redis"""
        if self.initialized and self.redis_client:
            await self.initialize()
        if not self.initialized or not self.redis_client:
            logger.debug("Redis not available, skipping progress update")
            return

        try:
            job_id = progress_update.job_id

            status_data = {
                "job_id": job_id,
                "progress": progress_update.progress,
                "status": progress_update.status.value if isinstance(progress_update.status, JobStatus) else progress_update.status,
                "message": progress_update.message or "",
                "current_page": progress_update.current_page if hasattr(progress_update, 'current_page') else None,
                "total_pages": progress_update.total_pages if hasattr(progress_update, 'total_pages') else None,
                "items_extracted": progress_update.items_extracted if hasattr(progress_update, 'items_extracted') else None,
                "items_matched": progress_update.items_matched if hasattr(progress_update, 'items_matched') else None,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            # Remove None values
            status_data = {k: v for k, v in status_data.items() if v is not None}

            key = f"job_progress:{job_id}"

            # Store in Redis with 10-minute expiration
            await self.redis_client.setex(
                key,
                600,  # 10 minutes
                json.dumps(status_data)
            )

            logger.debug(f"Updated Redis progress for job {job_id}: {progress_update.progress}%")

        except Exception as e:
            logger.warning(f"Failed to update Redis progress: {e}")

    async def get_status(self, job_id: int) -> Optional[ProcessingStatus]:
        """Get progress from Redis"""
        if self.initialized and self.redis_client:
            await self.initialize()
        if not self.initialized or not self.redis_client:
            return None

        try:
            key = f"job_progress:{job_id}"
            data = await self.redis_client.get(key)

            if not data:
                return None

            status_dict = json.loads(data)

            return ProcessingStatus(
                job_id=status_dict["job_id"],
                progress=status_dict.get("progress", 0),
                status=JobStatus(status_dict["status"]),
                message=status_dict.get("message"),
                updated_at=datetime.fromisoformat(status_dict["updated_at"]) if status_dict.get("updated_at") else None
            )

        except Exception as e:
            logger.warning(f"Failed to get Redis status: {e}")
            return None

    async def clear_status(self, job_id: int):
        """Clear status from Redis"""
        if self.initialized and self.redis_client:
            await self.initialize()
        if not self.initialized or not self.redis_client:
            return

        try:
            key = f"job_progress:{job_id}"
            await self.redis_client.delete(key)
            logger.debug(f"Cleared Redis status for job {job_id}")
        except Exception as e:
            logger.warning(f"Failed to clear Redis status: {e}")

    async def get_all_processing_jobs(self):
        """Get all jobs with progress data in Redis"""
        if self.initialized and self.redis_client:
            await self.initialize()
        if not self.initialized or not self.redis_client:
            return []

        try:
            # Find all job progress keys
            keys = await self.redis_client.keys("job_progress:*")

            statuses = []
            for key in keys:
                data = await self.redis_client.get(key)
                if data:
                    status_dict = json.loads(data)
                    if status_dict.get("status") == "PROCESSING":
                        statuses.append(ProcessingStatus(
                            job_id=status_dict["job_id"],
                            progress=status_dict.get("progress", 0),
                            status=JobStatus(status_dict["status"]),
                            message=status_dict.get("message")
                        ))

            return statuses

        except Exception as e:
            logger.warning(f"Failed to get processing jobs from Redis: {e}")
            return []

    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            try:
                close_method = getattr(self.redis_client, "aclose", None)
                if close_method is None:
                    close_method = self.redis_client.close
                close_result = close_method()
                if isawaitable(close_result):
                    await close_result
                logger.info("Redis status tracker closed")
            except Exception as e:
                logger.warning(f"Error closing Redis: {e}")
            finally:
                self.redis_client = None
                self.initialized = False
                self._creation_loop_id = None
                self._creation_process_id = None


# Global instance
redis_status_tracker = RedisStatusTracker()
