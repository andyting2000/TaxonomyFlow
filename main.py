import logging
import mimetypes
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from database import Base, engine
from middleware import CacheMiddleware, PerformanceMiddleware
from routers import admin, auth, filings, jobs, taxonomy, xbrl_templates

mimetypes.init()
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

APP_RUNTIME_REVISION = "18F-G-D-hotfix-1+"


def get_runtime_provenance() -> dict[str, str | int]:
    """Return non-secret source provenance for startup diagnostics."""

    from services import suggestion_actionability, supervisor_mapping_orchestrator

    return {
        "runtime_revision": APP_RUNTIME_REVISION,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "python_executable": sys.executable,
        "main_module_path": str(Path(__file__).resolve()),
        "filings_module_path": str(Path(filings.__file__).resolve()),
        "actionability_module_path": str(
            Path(suggestion_actionability.__file__).resolve()
        ),
        "orchestrator_module_path": str(
            Path(supervisor_mapping_orchestrator.__file__).resolve()
        ),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    print("Starting XBRL FastAPI Application")
    provenance = get_runtime_provenance()
    logger.info(
        "Runtime provenance: revision=%s pid=%s cwd=%s python=%s main=%s "
        "filings=%s actionability=%s orchestrator=%s",
        provenance["runtime_revision"],
        provenance["pid"],
        provenance["cwd"],
        provenance["python_executable"],
        provenance["main_module_path"],
        provenance["filings_module_path"],
        provenance["actionability_module_path"],
        provenance["orchestrator_module_path"],
    )

    os.makedirs("static", exist_ok=True)
    os.makedirs("static/js", exist_ok=True)
    os.makedirs("uploads/pdfs", exist_ok=True)
    os.makedirs("uploads/pages", exist_ok=True)
    os.makedirs("uploads/xbrl", exist_ok=True)

    logger.info("Initializing database...")
    try:
        from db_init import DatabaseInitializer

        db_init = DatabaseInitializer()
        status = await db_init.check_database_status()

        if status["is_fresh_install"]:
            logger.info("Fresh database detected - initializing schema...")
            await db_init.initialize_fresh_database()
        elif status["needs_migration"]:
            logger.info("Database migration needed - applying updates...")
            await db_init.migrate_existing_database()
        else:
            logger.info("Database schema is up to date")

    except Exception as db_error:
        logger.error("Database initialization error: %s", db_error, exc_info=True)
        if not settings.debug:
            logger.critical(
                "Database bootstrap failed; SQL migrations are required when DEBUG is false."
            )
            raise

        logger.warning(
            "Development mode database fallback enabled: using SQLAlchemy auto-create. "
            "Run `python db_init.py --apply` to use the migration source of truth."
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    from services.bootstrap_admin import bootstrap_admin_account

    await bootstrap_admin_account()

    from cache import cache_manager

    await cache_manager.initialize()

    try:
        from services.redis_status_tracker import redis_status_tracker

        await redis_status_tracker.initialize()
    except Exception as exc:
        logger.warning(
            f"Redis status tracker initialization failed (non-critical): {exc}"
        )

    logger.info("Loading XBRL templates from SSMxT taxonomy...")
    from services.xbrl_template_service import get_xbrl_template_service

    xbrl_service = get_xbrl_template_service()

    if xbrl_service.templates:
        stats = xbrl_service.get_statistics()
        logger.info(
            "XBRL templates loaded: %s templates, %s concepts",
            stats["total_templates"],
            stats["total_concepts"],
        )
        logger.info(
            "Required concepts: %s, Optional: %s",
            stats["total_required"],
            stats["total_optional"],
        )
        template_codes = ", ".join(sorted(xbrl_service.get_template_codes()))
        logger.info("Available templates: %s", template_codes)
    else:
        logger.error("XBRL templates not loaded")
        logger.info(
            "Please run: python scripts/extract_xbrl_templates.py SSMxT_2022v1.zip"
        )
        logger.warning(
            "Template-based extraction will not work without XBRL templates"
        )

    print("Application startup complete")

    yield

    print("Shutting down XBRL Application")
    await cache_manager.close()

    try:
        from services.redis_status_tracker import redis_status_tracker

        await redis_status_tracker.close()
    except Exception as exc:
        logger.warning(f"Redis status tracker shutdown warning: {exc}")

    await engine.dispose()


app = FastAPI(
    title="XBRL Filing Platform",
    description="FastAPI-based XBRL converter for Malaysian MBRS taxonomy",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PerformanceMiddleware)
app.add_middleware(CacheMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")
react_assets_dir = Path("frontend/dist/assets")
app.mount(
    "/app/assets",
    StaticFiles(directory=str(react_assets_dir), check_dir=False),
    name="react-app-assets",
)

templates = Jinja2Templates(directory="templates")

app.include_router(filings.router, prefix="/api/v1/filings", tags=["filings"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(taxonomy.router, prefix="/api/v1/taxonomy", tags=["taxonomy"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(
    xbrl_templates.router,
    prefix="/api/v1/xbrl-templates",
    tags=["XBRL Templates"],
)


@app.get("/")
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request, "title": "XBRL Filing Platform"},
    )


@app.get("/app")
@app.get("/app/")
@app.get("/app/login")
@app.get("/app/register")
@app.get("/app/admin")
async def react_dashboard(request: Request):
    """React application shell entrypoint."""
    built_js = react_assets_dir / "app.js"
    built_css = react_assets_dir / "app.css"

    return templates.TemplateResponse(
        request=request,
        name="react_app.html",
        context={
            "request": request,
            "app_js_url": "/app/assets/app.js" if built_js.exists() else None,
            "app_css_url": "/app/assets/app.css" if built_css.exists() else None,
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "runtime_revision": APP_RUNTIME_REVISION,
        "database": "connected",
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        reload=False,
        access_log=True,
        log_level="info" if not settings.debug else "debug",
    )
