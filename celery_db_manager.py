# celery_db_manager.py - IMPROVED VERSION with better session recovery
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import PendingRollbackError, InvalidRequestError
from config import settings

logger = logging.getLogger(__name__)

class CeleryDatabaseManager:
    """
    Enhanced database manager for Celery tasks with better error recovery
    """
    
    def __init__(self):
        self.engine = None
        self.session_factory = None
        self._initialized = False
        self._creation_loop_id = None
        self._creation_process_id = None

    @property
    def creation_loop_id(self):
        return self._creation_loop_id
    
    async def initialize(self):
        """Initialize database connections for Celery worker"""
        current_loop_id = id(asyncio.get_running_loop())
        current_process_id = os.getpid()
        if self._initialized:
            if (
                self._creation_loop_id == current_loop_id
                and self._creation_process_id == current_process_id
            ):
                return
            raise RuntimeError(
                "Celery database engine belongs to an incompatible async resource context: "
                f"created_process_id={self._creation_process_id} "
                f"created_loop_id={self._creation_loop_id} "
                f"current_process_id={current_process_id} current_loop_id={current_loop_id}"
            )
        
        try:
            # Create engine with enhanced settings for Celery
            self.engine = create_async_engine(
                settings.database_url,
                echo=False,  # Disable echo in Celery for performance
                pool_pre_ping=True,
                pool_recycle=300,  # Recycle connections every 5 minutes
                pool_timeout=30,
                max_overflow=20,  # Allow more overflow connections
                pool_size=10,     # Larger pool for Celery workers
                # Enhanced isolation and connection handling
                isolation_level="READ_COMMITTED",
                connect_args={
                    "server_settings": {
                        "application_name": "celery_worker",
                    }
                }
            )
            
            # Create session factory with enhanced configuration
            self.session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=True,
                autocommit=False,
                # Better handling of concurrent operations
                twophase=False,
            )
            
            self._initialized = True
            self._creation_loop_id = current_loop_id
            self._creation_process_id = current_process_id
            logger.info(
                "Celery database manager initialized process_id=%s loop_id=%s engine_id=%s",
                current_process_id,
                current_loop_id,
                id(self.engine),
            )
            logger.info("✅ Enhanced Celery database manager initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Celery database manager: {e}")
            raise
    
    @asynccontextmanager
    async def get_session(self):
        """
        Get database session with enhanced error handling and recovery
        
        This context manager provides:
        - Automatic retry on transient errors
        - Proper cleanup on failures
        - Session recovery after rollback errors
        """
        await self.initialize()
        
        session = None
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Create fresh session for each attempt
                session = self.session_factory()
                
                # Ensure we start with a clean session state
                if session.in_transaction():
                    await session.rollback()
                
                yield session
                
                # If we get here, the operation was successful
                if session.in_transaction():
                    await session.commit()
                
                break  # Success, exit retry loop
                
            except (PendingRollbackError, InvalidRequestError) as rollback_error:
                logger.warning(f"Session rollback error (attempt {retry_count + 1}/{max_retries}): {rollback_error}")
                
                # Handle session rollback errors
                if session:
                    try:
                        await session.rollback()
                        await session.close()
                    except Exception as cleanup_error:
                        logger.error(f"Error during rollback cleanup: {cleanup_error}")
                
                # Retry with a fresh session if we have retries left
                if retry_count < max_retries - 1:
                    retry_count += 1
                    session = None
                    # Small delay before retry
                    await asyncio.sleep(0.5)
                    continue
                else:
                    # Max retries reached, raise the original error
                    raise
                    
            except Exception as e:
                error_msg = str(e).lower()
                
                # Check if this is a transient database error that we can retry
                transient_errors = [
                    'transaction is aborted',
                    'current transaction is aborted',
                    'connection',
                    'timeout',
                    'greenlet_spawn has not been called',
                    'was io attempted in an unexpected place'
                ]
                
                is_transient = any(phrase in error_msg for phrase in transient_errors)
                
                if is_transient and retry_count < max_retries - 1:
                    logger.warning(f"Transient database error (attempt {retry_count + 1}/{max_retries}): {e}")
                    
                    # Clean up current session
                    if session:
                        try:
                            await session.rollback()
                            await session.close()
                        except Exception as cleanup_error:
                            logger.error(f"Error during error cleanup: {cleanup_error}")
                    
                    # Retry with fresh session
                    retry_count += 1
                    session = None
                    # Exponential backoff
                    await asyncio.sleep(2 ** retry_count)
                    continue
                else:
                    # Non-transient error or max retries reached
                    if session:
                        try:
                            await session.rollback()
                        except Exception as rollback_error:
                            logger.error(f"Error during final rollback: {rollback_error}")
                    raise
                    
            finally:
                # Always close the session
                if session:
                    try:
                        await session.close()
                    except Exception as close_error:
                        logger.error(f"Error closing session: {close_error}")
    
    @asynccontextmanager
    async def get_fresh_session(self):
        """
        Get a completely fresh session - useful for recovery scenarios
        """
        await self.initialize()
        
        session = None
        try:
            # Create new session
            session = self.session_factory()
            
            yield session
            
            # Commit if in transaction
            if session.in_transaction():
                await session.commit()
                
        except Exception as e:
            logger.error(f"Fresh session error: {e}")
            if session:
                try:
                    await session.rollback()
                except Exception as rollback_error:
                    logger.error(f"Error during fresh session rollback: {rollback_error}")
            raise
        finally:
            if session:
                try:
                    await session.close()
                except Exception as close_error:
                    logger.error(f"Error closing fresh session: {close_error}")
    
    async def test_connection(self) -> bool:
        """Test database connection health"""
        try:
            async with self.get_session() as session:
                # Simple query to test connection
                await session.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    async def recover_session(self):
        """
        Attempt to recover from session errors by recreating the session factory
        """
        try:
            logger.info("Attempting session recovery...")
            
            # Close existing engine
            if self.engine:
                await self.engine.dispose()
            
            # Reinitialize
            self._initialized = False
            await self.initialize()
            
            logger.info("✅ Session recovery completed")
            return True
            
        except Exception as e:
            logger.error(f"Session recovery failed: {e}")
            return False
    
    async def close(self):
        """Close database connections"""
        if self.engine:
            try:
                await self.engine.dispose()
                logger.info(
                    "Celery database connections closed process_id=%s loop_id=%s engine_id=%s",
                    os.getpid(),
                    id(asyncio.get_running_loop()),
                    id(self.engine),
                )
                logger.info("✅ Celery database connections closed")
            except Exception as e:
                logger.error(f"Error closing database connections: {e}")
        
        self.engine = None
        self.session_factory = None
        self._initialized = False
        self._creation_loop_id = None
        self._creation_process_id = None

# Global instance for Celery workers
celery_db_manager = CeleryDatabaseManager()

# Enhanced convenience function for use in tasks
@asynccontextmanager
async def get_celery_db_session():
    """
    Get database session for Celery tasks with automatic error handling
    """
    try:
        async with celery_db_manager.get_session() as session:
            yield session
    except Exception as e:
        # Log the error and attempt recovery
        logger.error(f"Celery database session error: {e}")
        
        # Attempt recovery for certain types of errors
        error_msg = str(e).lower()
        if any(phrase in error_msg for phrase in ['greenlet', 'connection', 'session']):
            logger.info("Attempting session recovery...")
            recovery_success = await celery_db_manager.recover_session()
            
            if recovery_success:
                # Try one more time with fresh session
                async with celery_db_manager.get_fresh_session() as fresh_session:
                    yield fresh_session
            else:
                raise
        else:
            raise


# Utility functions for monitoring and debugging
async def get_db_health_status():
    """Get database health status for monitoring"""
    try:
        connection_ok = await celery_db_manager.test_connection()
        
        return {
            'status': 'healthy' if connection_ok else 'unhealthy',
            'connection_test': connection_ok,
            'initialized': celery_db_manager._initialized,
            'timestamp': asyncio.get_event_loop().time()
        }
    except Exception as e:
        return {
            'status': 'error',
            'connection_test': False,
            'initialized': False,
            'error': str(e),
            'timestamp': asyncio.get_event_loop().time()
        }


async def force_db_recovery():
    """Force database recovery - useful for debugging"""
    try:
        logger.info("Forcing database recovery...")
        success = await celery_db_manager.recover_session()
        
        if success:
            # Test the recovered connection
            health = await get_db_health_status()
            return {
                'recovery_success': True,
                'health_after_recovery': health
            }
        else:
            return {
                'recovery_success': False,
                'error': 'Recovery failed'
            }
    except Exception as e:
        return {
            'recovery_success': False,
            'error': str(e)
        }
