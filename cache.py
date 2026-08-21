# cache.py
import json
import hashlib
import asyncio
from typing import Any, Optional, Dict, List
from datetime import datetime, timedelta
from redis import asyncio as aioredis
import pickle
import logging
from config import settings

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Async cache manager using Redis with fallback to in-memory cache
    """
    
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.memory_cache: Dict[str, Dict] = {}
        self.use_redis = True
        
    async def initialize(self): 
        """Initialize cache connections"""
        try:
            self.redis = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                retry_on_timeout=True
            )
            
            # Test connection
            await self.redis.ping()
            logger.info("✅ Redis cache initialized")
            
        except Exception as e:
            logger.warning(f"Redis unavailable, using memory cache: {e}")
            self.use_redis = False
    
    async def close(self):
        """Close cache connections"""
        if self.redis:
            await self.redis.close()
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from prefix and arguments"""
        key_parts = [str(arg) for arg in args]
        key_parts.extend([f"{k}:{v}" for k, v in sorted(kwargs.items())])
        key_string = ":".join(key_parts)
        
        # Hash long keys
        if len(key_string) > 100:
            key_string = hashlib.md5(key_string.encode()).hexdigest()
        
        return f"{prefix}:{key_string}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            if self.use_redis and self.redis:
                value = await self.redis.get(key)
                if value:
                    return json.loads(value) if value.startswith(('{', '[', '"')) else value
            else:
                # Memory cache with TTL check
                if key in self.memory_cache:
                    cache_entry = self.memory_cache[key]
                    if cache_entry['expires'] > datetime.utcnow():
                        return cache_entry['value']
                    else:
                        del self.memory_cache[key]
            
            return None
            
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """Set value in cache"""
        try:
            if ttl is None:
                ttl = settings.cache_ttl
            
            if self.use_redis and self.redis:
                serialized_value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                await self.redis.setex(key, ttl, serialized_value)
                return True
            else:
                # Memory cache with TTL
                self.memory_cache[key] = {
                    'value': value,
                    'expires': datetime.utcnow() + timedelta(seconds=ttl)
                }
                
                # Clean expired entries periodically
                if len(self.memory_cache) % 100 == 0:
                    await self._cleanup_memory_cache()
                
                return True
                
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        try:
            if self.use_redis and self.redis:
                await self.redis.delete(key)
            else:
                self.memory_cache.pop(key, None)
            return True
            
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern"""
        try:
            if self.use_redis and self.redis:
                keys = await self.redis.keys(pattern)
                if keys:
                    return await self.redis.delete(*keys)
                return 0
            else:
                # Memory cache pattern matching
                matching_keys = [key for key in self.memory_cache.keys() 
                               if self._pattern_match(pattern, key)]
                for key in matching_keys:
                    del self.memory_cache[key]
                return len(matching_keys)
                
        except Exception as e:
            logger.error(f"Cache delete pattern error for {pattern}: {e}")
            return 0
    
    def _pattern_match(self, pattern: str, key: str) -> bool:
        """Simple pattern matching for memory cache"""
        # Convert Redis pattern to simple matching
        pattern = pattern.replace('*', '')
        return key.startswith(pattern)
    
    async def _cleanup_memory_cache(self):
        """Clean expired entries from memory cache"""
        current_time = datetime.utcnow()
        expired_keys = [
            key for key, entry in self.memory_cache.items()
            if entry['expires'] <= current_time
        ]
        
        for key in expired_keys:
            del self.memory_cache[key]
        
        logger.debug(f"Cleaned {len(expired_keys)} expired cache entries")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            if self.use_redis and self.redis:
                info = await self.redis.info()
                return {
                    'type': 'redis',
                    'hits': info.get('keyspace_hits', 0),
                    'misses': info.get('keyspace_misses', 0),
                    'keys': info.get('db0', {}).get('keys', 0),
                    'memory_usage': info.get('used_memory_human', '0B'),
                }
            else:
                return {
                    'type': 'memory',
                    'keys': len(self.memory_cache),
                    'hits': 0,  # Would need to track separately
                    'misses': 0,
                    'memory_usage': 'N/A',
                }
                
        except Exception as e:
            logger.error(f"Cache stats error: {e}")
            return {'type': 'error', 'error': str(e)}


# Global cache manager instance
cache_manager = CacheManager()


# Cache decorators and utilities
def cache_key(*args, **kwargs) -> str:
    """Generate cache key"""
    return cache_manager._generate_key('general', *args, **kwargs)


async def cached_function(key_prefix: str, ttl: int = None):
    """Decorator for caching function results"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = cache_manager._generate_key(key_prefix, *args, **kwargs)
            
            # Try to get from cache
            cached_result = await cache_manager.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            await cache_manager.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


# Specific cache functions for the application
class TaxonomyCache:
    """Cache for taxonomy-related operations"""
    
    @staticmethod
    async def get_search_results(query: str) -> Optional[List[Dict]]:
        """Get cached taxonomy search results"""
        key = cache_manager._generate_key('taxonomy_search', query.lower())
        return await cache_manager.get(key)
    
    @staticmethod
    async def set_search_results(query: str, results: List[Dict], ttl: int = None) -> bool:
        """Cache taxonomy search results"""
        if ttl is None:
            ttl = settings.search_cache_ttl
        
        key = cache_manager._generate_key('taxonomy_search', query.lower())
        return await cache_manager.set(key, results, ttl)
    
    @staticmethod
    async def get_fuzzy_matching_data() -> Optional[Dict]:
        """Get cached taxonomy data for fuzzy matching"""
        key = 'taxonomy_fuzzy_matching'
        return await cache_manager.get(key)
    
    @staticmethod
    async def set_fuzzy_matching_data(data: Dict, ttl: int = 21600) -> bool:
        """Cache taxonomy data for fuzzy matching (6 hours)"""
        key = 'taxonomy_fuzzy_matching'
        return await cache_manager.set(key, data, ttl)


class JobCache:
    """Cache for job-related operations"""
    
    @staticmethod
    async def get_job_status(job_id: int) -> Optional[Dict]:
        """Get cached job status"""
        key = cache_manager._generate_key('job_status', job_id)
        return await cache_manager.get(key)
    
    @staticmethod
    async def set_job_status(job_id: int, status_data: Dict, ttl: int = 300) -> bool:
        """Cache job status (5 minutes)"""
        key = cache_manager._generate_key('job_status', job_id)
        return await cache_manager.set(key, status_data, ttl)
    
    @staticmethod
    async def invalidate_job_cache(job_id: int) -> bool:
        """Invalidate all cache entries for a job"""
        pattern = f"*job*{job_id}*"
        return await cache_manager.delete_pattern(pattern) > 0


# Cache warming functions
async def warm_cache():
    """Warm up cache with frequently accessed data"""
    logger.info("🔥 Starting cache warmup")
    
    try:
        # Import here to avoid circular imports
        from database import AsyncSessionLocal
        from database import MBRSTaxonomyTag
        from sqlalchemy import select
        
        async with AsyncSessionLocal() as session:
            # Load taxonomy data for fuzzy matching
            result = await session.execute(
                select(MBRSTaxonomyTag).where(
                    ~MBRSTaxonomyTag.label.contains('[abstract]')
                )
            )
            tags = result.scalars().all()
            
            taxonomy_data = {tag.label: {
                'id': tag.id,
                'label': tag.label,
                'namespace': tag.namespace,
                'period_type': tag.period_type
            } for tag in tags}
            
            await TaxonomyCache.set_fuzzy_matching_data(taxonomy_data)
            logger.info(f"✅ Cached {len(taxonomy_data)} taxonomy tags for fuzzy matching")
        
        # Pre-cache common search terms
        common_terms = [
            'revenue', 'profit', 'loss', 'asset', 'liability', 'equity', 
            'cash', 'debt', 'share', 'dividend', 'tax', 'property'
        ]
        
        # This would normally trigger actual searches to populate cache
        logger.info(f"✅ Cache warmup completed")
        
    except Exception as e:
        logger.error(f"Cache warmup failed: {e}")


# Performance monitoring
async def get_cache_performance_metrics() -> Dict[str, Any]:
    """Get cache performance metrics"""
    stats = await cache_manager.get_stats()
    
    # Calculate additional metrics
    if stats.get('hits', 0) + stats.get('misses', 0) > 0:
        hit_rate = stats.get('hits', 0) / (stats.get('hits', 0) + stats.get('misses', 0))
    else:
        hit_rate = 0.0
    
    return {
        **stats,
        'hit_rate': hit_rate,
        'performance': 'good' if hit_rate > 0.7 else 'needs_improvement',
        'recommendations': get_cache_recommendations(hit_rate, stats.get('keys', 0))
    }


def get_cache_recommendations(hit_rate: float, key_count: int) -> List[str]:
    """Get cache performance recommendations"""
    recommendations = []
    
    if hit_rate < 0.5:
        recommendations.append("Cache hit rate is very low - review caching strategy")
    elif hit_rate < 0.7:
        recommendations.append("Cache hit rate could be improved - consider longer TTL for stable data")
    
    if key_count > 10000:
        recommendations.append("High number of cache keys - consider implementing cache cleanup")
    
    if not recommendations:
        recommendations.append("Cache performance is good!")
    
    return recommendations
