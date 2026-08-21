# middleware.py
import time
import json
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from config import settings

# Set up loggers
performance_logger = logging.getLogger('performance')
security_logger = logging.getLogger('security')


class PerformanceMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log performance metrics and detect slow requests
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Get client info
        client_ip = self.get_client_ip(request)
        user_agent = request.headers.get('user-agent', '')[:100]
        
        # Process request
        response = await call_next(request)
        
        # Calculate metrics
        process_time = time.time() - start_time
        response_size = int(response.headers.get('content-length', 0))
        
        # Performance metrics
        metrics = {
            'path': str(request.url.path),
            'method': request.method,
            'status_code': response.status_code,
            'process_time': round(process_time, 3),
            'response_size': response_size,
            'client_ip': client_ip,
            'user_agent': user_agent,
            'query_params': str(request.query_params) if request.query_params else None
        }
        
        # Add debug headers in development
        if settings.debug:
            response.headers['X-Process-Time'] = str(process_time)
            response.headers['X-Response-Size'] = str(response_size)
        
        # Log slow requests
        if process_time > settings.slow_query_threshold:
            performance_logger.warning(
                f"SLOW REQUEST: {json.dumps(metrics, indent=2)}"
            )
        elif settings.debug:
            performance_logger.info(f"REQUEST: {json.dumps(metrics)}")
        
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """Get the client's IP address"""
        forwarded_for = request.headers.get('x-forwarded-for')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.client.host if request.client else "unknown"


class CacheMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add cache headers and track cache performance
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Record cache operations during request
        request.state.cache_operations = []
        
        response = await call_next(request)
        
        # Add cache headers for static content
        if any(request.url.path.endswith(ext) for ext in ['.css', '.js', '.png', '.jpg', '.ico']):
            response.headers['Cache-Control'] = 'public, max-age=3600'
        
        # Add no-cache headers for API endpoints
        elif request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        
        # Log cache performance if we have operations recorded
        if hasattr(request.state, 'cache_operations') and request.state.cache_operations:
            cache_hits = sum(1 for op in request.state.cache_operations if op.get('result') == 'hit')
            cache_misses = sum(1 for op in request.state.cache_operations if op.get('result') == 'miss')
             
            if cache_misses > cache_hits and len(request.state.cache_operations) > 3:
                performance_logger.info(
                    f"LOW CACHE HIT RATIO for {request.url.path}: "
                    f"{cache_hits} hits, {cache_misses} misses"
                )
        
        return response


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Basic security middleware
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Log suspicious activity
        if self.is_suspicious_request(request):
            security_logger.warning(
                f"Suspicious request from {self.get_client_ip(request)}: "
                f"{request.method} {request.url.path}"
            )
        
        response = await call_next(request)
        
        # Add security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Add HSTS in production
        if not settings.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response
    
    def get_client_ip(self, request: Request) -> str:
        """Get the client's IP address"""
        forwarded_for = request.headers.get('x-forwarded-for')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.client.host if request.client else "unknown"
    
    def is_suspicious_request(self, request: Request) -> bool:
        """Basic suspicious request detection"""
        suspicious_patterns = [
            'admin', 'wp-admin', 'phpmyadmin', '.env', 'config',
            'sql', 'union', 'select', 'script', 'alert('
        ]
        
        path_lower = str(request.url.path).lower()
        query_lower = str(request.query_params).lower()
        
        return any(pattern in path_lower or pattern in query_lower 
                  for pattern in suspicious_patterns)


class CompressionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to monitor compression effectiveness
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Check if response should be compressed
        content_length = int(response.headers.get('content-length', 0))
        content_encoding = response.headers.get('content-encoding', '')
        content_type = response.headers.get('content-type', '')
        
        # Log large uncompressed responses
        if (content_length > 1024 * 1024 and  # > 1MB
            not content_encoding and 
            any(ct in content_type for ct in ['text/', 'application/json', 'application/xml'])):
            
            performance_logger.info(
                f"LARGE UNCOMPRESSED RESPONSE: {request.url.path} "
                f"returned {content_length / 1024 / 1024:.1f}MB uncompressed {content_type}"
            )
        
        return response


# Memory monitoring (optional, requires psutil)
class MemoryMiddleware(BaseHTTPMiddleware):
    """
    Middleware to monitor memory usage
    """
    
    def __init__(self, app):
        super().__init__(app)
        try:
            import psutil
            self.psutil_available = True
        except ImportError:
            self.psutil_available = False
            performance_logger.warning("psutil not available - memory monitoring disabled")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_memory = 0
        
        if self.psutil_available:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            start_memory = process.memory_info().rss
        
        response = await call_next(request)
        
        if self.psutil_available and start_memory > 0:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            end_memory = process.memory_info().rss
            memory_delta = end_memory - start_memory
            
            # Log significant memory usage (> 50MB)
            if memory_delta > 50 * 1024 * 1024:
                performance_logger.warning(
                    f"HIGH MEMORY USAGE: {request.url.path} used "
                    f"{memory_delta / 1024 / 1024:.1f}MB additional memory"
                )
        
        return response


# Utility functions for performance reporting
def get_performance_metrics():
    """Get current performance metrics"""
    # This would typically read from logs or monitoring system
    return {
        'request_count': 0,
        'avg_response_time': 0.0,
        'slow_requests': 0,
        'cache_hit_rate': 0.0,
        'database_queries': 0,
        'memory_usage_mb': 0.0,
        'active_connections': 0
    }


async def log_performance_summary():
    """Log daily performance summary"""
    metrics = get_performance_metrics()
    performance_logger.info(f"DAILY SUMMARY: {json.dumps(metrics, indent=2)}")