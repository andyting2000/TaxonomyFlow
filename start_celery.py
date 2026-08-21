# start_celery_windows.py - Windows-optimized Celery startup
import os
import sys
import subprocess

def start_celery_worker():
    """Start Celery worker with Windows-optimized settings"""
    
    print("🚀 Starting Celery worker for Windows...")
    
    # Windows-optimized Celery command
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "tasks",
        "worker",
        "--loglevel=info",
        "--pool=threads",          # Use thread pool instead of prefork
        "--concurrency=4",         # Limit to 4 concurrent tasks
        "--without-gossip",        # Disable gossip for Windows
        "--without-mingle",        # Disable mingle for Windows
        "--without-heartbeat",     # Disable heartbeat for Windows
    ]
    
    print(f"Command: {' '.join(cmd)}")
    print("=" * 50)
    
    try:
        # Start the worker
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n🛑 Celery worker stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"❌ Celery worker failed to start: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False
    
    return True


def start_celery_beat():
    """Start Celery beat scheduler (optional)"""
    
    print("📅 Starting Celery beat scheduler...")
    
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "tasks",
        "beat",
        "--loglevel=info"
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n🛑 Celery beat stopped by user")
    except Exception as e:
        print(f"❌ Celery beat error: {e}")


def check_redis_connection():
    """Check if Redis is running and accessible"""
    try:
        import redis
        from config import settings
        
        # Parse Redis URL
        if settings.redis_url.startswith('redis://localhost:6380'):
            host, port = 'localhost', 6380
        else:
            # Default Redis port
            host, port = 'localhost', 6379
        
        r = redis.Redis(host=host, port=port, db=0)
        r.ping()
        print(f"✅ Redis is running on {host}:{port}")
        return True
        
    except ImportError:
        print("❌ Redis package not installed. Run: pip install redis")
        return False
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("   Make sure Redis server is running on port 6380 (or 6379)")
        return False


def main():
    """Main startup function"""
    print("🔧 XBRL Celery Worker for Windows")
    print("=" * 40)
    
    # Check Redis connection first
    if not check_redis_connection():
        print("\n💡 To fix Redis issues:")
        print("   1. Install Redis for Windows")
        print("   2. Start Redis server: redis-server")
        print("   3. Or use Docker: docker run -p 6380:6379 redis")
        return
    
    # Check required packages
    try:
        import celery
        print(f"✅ Celery version: {celery.__version__}")
    except ImportError:
        print("❌ Celery not installed. Run: pip install celery")
        return
    
    # Start worker
    if len(sys.argv) > 1 and sys.argv[1] == 'beat':
        start_celery_beat()
    else:
        start_celery_worker()


if __name__ == "__main__":
    main()