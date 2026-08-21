import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import main
from config import settings
from database import User, get_db
from db_init import DatabaseInitializer
from routers import filings
from security import get_current_user, require_admin_route_token


class DummyResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class DummyAsyncSession:
    def __init__(self, scalar_results):
        self._results = list(scalar_results)
        self.execute = AsyncMock(side_effect=self._execute)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.delete = AsyncMock()

    async def _execute(self, _statement):
        if not self._results:
            raise AssertionError("Unexpected database execute call")
        return DummyResult(self._results.pop(0))


def build_filings_test_app(db_session):
    app = FastAPI()
    app.include_router(filings.router, prefix="/api/v1/filings")

    async def override_db():
        yield db_session

    async def override_current_user():
        return User(id=1, email="unit@example.com", is_active=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    return app


@contextmanager
def patched_debug(value: bool):
    with patch.object(settings, "debug", value):
        yield


class DatabaseInitializerStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_split_sql_statements_preserves_commented_sql(self):
        sql = """
-- install extension first
CREATE EXTENSION IF NOT EXISTS vector;

-- create table next
CREATE TABLE example_table (
    id INTEGER PRIMARY KEY,
    note TEXT DEFAULT 'semi;colon'
);
"""

        statements = DatabaseInitializer()._split_sql_statements(sql)

        self.assertEqual(len(statements), 2)
        self.assertEqual(
            statements[0],
            "CREATE EXTENSION IF NOT EXISTS vector",
        )
        self.assertIn("CREATE TABLE example_table", statements[1])
        self.assertIn("semi;colon", statements[1])

    async def test_check_database_status_reports_missing_schema(self):
        class FakeInitializer(DatabaseInitializer):
            async def check_pgvector_extension(self):
                return False

            async def get_existing_tables(self):
                return ["filing_jobs"]

            async def get_table_columns(self, table_name: str):
                if table_name == "filing_jobs":
                    return ["id", "company_name"]
                return []

        status = await FakeInitializer().check_database_status()

        self.assertFalse(status["pgvector_installed"])
        self.assertFalse(status["is_fresh_install"])
        self.assertTrue(status["needs_migration"])
        self.assertIn("xml_template_fields", status["missing_tables"])
        self.assertIn("filing_jobs", status["tables_with_missing_columns"])
        self.assertIn(
            "source_pdf_path",
            status["tables_with_missing_columns"]["filing_jobs"],
        )


class LifespanBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_uses_migration_status_path_when_schema_is_current(self):
        fake_initializer = SimpleNamespace(
            check_database_status=AsyncMock(
                return_value={
                    "is_fresh_install": False,
                    "needs_migration": False,
                }
            ),
            initialize_fresh_database=AsyncMock(),
            migrate_existing_database=AsyncMock(),
        )
        fake_template_service = SimpleNamespace(
            templates={"020000": {"description": "Scope of Filing"}},
            get_statistics=lambda: {
                "total_templates": 1,
                "total_concepts": 3,
                "total_required": 2,
                "total_optional": 1,
            },
            get_template_codes=lambda: ["020000"],
        )
        fake_engine = SimpleNamespace(dispose=AsyncMock())

        with (
            patch("main.os.makedirs"),
            patch("db_init.DatabaseInitializer", return_value=fake_initializer),
            patch("cache.cache_manager.initialize", new=AsyncMock()) as cache_init,
            patch("cache.cache_manager.close", new=AsyncMock()) as cache_close,
            patch(
                "services.redis_status_tracker.redis_status_tracker.initialize",
                new=AsyncMock(),
            ) as redis_init,
            patch(
                "services.redis_status_tracker.redis_status_tracker.close",
                new=AsyncMock(),
            ) as redis_close,
            patch(
                "services.xbrl_template_service.get_xbrl_template_service",
                return_value=fake_template_service,
            ),
            patch(
                "services.bootstrap_admin.bootstrap_admin_account",
                new=AsyncMock(),
            ) as bootstrap_admin,
            patch("main.engine", fake_engine),
        ):
            async with main.lifespan(main.app):
                pass

        fake_initializer.check_database_status.assert_awaited_once()
        fake_initializer.initialize_fresh_database.assert_not_awaited()
        fake_initializer.migrate_existing_database.assert_not_awaited()
        cache_init.assert_awaited_once()
        cache_close.assert_awaited_once()
        redis_init.assert_awaited_once()
        redis_close.assert_awaited_once()
        fake_engine.dispose.assert_awaited_once()
        bootstrap_admin.assert_awaited_once()

    async def test_lifespan_uses_sqlalchemy_fallback_only_in_debug_mode(self):
        fake_initializer = SimpleNamespace(
            check_database_status=AsyncMock(side_effect=RuntimeError("db bootstrap failed")),
        )
        fake_template_service = SimpleNamespace(
            templates={"020000": {"description": "Scope of Filing"}},
            get_statistics=lambda: {
                "total_templates": 1,
                "total_concepts": 1,
                "total_required": 1,
                "total_optional": 0,
            },
            get_template_codes=lambda: ["020000"],
        )

        class FakeConnection:
            def __init__(self):
                self.run_sync = AsyncMock()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        fake_connection = FakeConnection()
        fake_engine = SimpleNamespace(
            begin=lambda: fake_connection,
            dispose=AsyncMock(),
        )

        with (
            patched_debug(True),
            patch("main.os.makedirs"),
            patch("db_init.DatabaseInitializer", return_value=fake_initializer),
            patch("main.engine", fake_engine),
            patch("cache.cache_manager.initialize", new=AsyncMock()),
            patch("cache.cache_manager.close", new=AsyncMock()),
            patch(
                "services.redis_status_tracker.redis_status_tracker.initialize",
                new=AsyncMock(),
            ),
            patch(
                "services.redis_status_tracker.redis_status_tracker.close",
                new=AsyncMock(),
            ),
            patch(
                "services.xbrl_template_service.get_xbrl_template_service",
                return_value=fake_template_service,
            ),
            patch(
                "services.bootstrap_admin.bootstrap_admin_account",
                new=AsyncMock(),
            ) as bootstrap_admin,
        ):
            async with main.lifespan(main.app):
                pass

        fake_connection.run_sync.assert_awaited_once_with(main.Base.metadata.create_all)
        bootstrap_admin.assert_awaited_once()

    async def test_lifespan_raises_bootstrap_failure_when_debug_is_false(self):
        fake_initializer = SimpleNamespace(
            check_database_status=AsyncMock(side_effect=RuntimeError("db bootstrap failed")),
        )

        with (
            patched_debug(False),
            patch("main.os.makedirs"),
            patch("db_init.DatabaseInitializer", return_value=fake_initializer),
        ):
            with self.assertRaises(RuntimeError):
                async with main.lifespan(main.app):
                    pass


class RouteHardeningTests(unittest.TestCase):
    def test_expected_dangerous_routes_use_admin_token_dependency(self):
        expected_paths = {
            "/api/v1/filings/extracted-data/{item_id}",
            "/api/v1/filings/jobs/{job_id}/generate-xbrl",
            "/api/v1/jobs/{job_id}/reprocess",
            "/api/v1/jobs/maintenance/clear-cache",
            "/api/v1/taxonomy/debug/sample",
            "/api/v1/taxonomy/debug/search-raw",
            "/api/v1/taxonomy/tags",
            "/api/v1/xbrl-templates/export/csv",
        }

        protected_paths = set()

        for route in main.app.routes:
            if not isinstance(route, APIRoute):
                continue

            dependency_calls = {
                dependency.call
                for dependency in route.dependant.dependencies
            }
            if require_admin_route_token in dependency_calls:
                protected_paths.add(route.path)

        self.assertEqual(protected_paths, expected_paths)

    def test_download_xbrl_route_is_not_admin_token_protected(self):
        download_route = next(
            route
            for route in main.app.routes
            if isinstance(route, APIRoute)
            and route.path == "/api/v1/filings/jobs/{job_id}/download-xbrl"
        )

        dependency_calls = {
            dependency.call
            for dependency in download_route.dependant.dependencies
        }

        self.assertNotIn(require_admin_route_token, dependency_calls)

    def test_delete_job_route_is_not_admin_token_protected(self):
        delete_route = next(
            route
            for route in main.app.routes
            if isinstance(route, APIRoute)
            and route.path == "/api/v1/filings/jobs/{job_id}"
            and "DELETE" in route.methods
        )

        dependency_calls = {
            dependency.call
            for dependency in delete_route.dependant.dependencies
        }

        self.assertNotIn(require_admin_route_token, dependency_calls)

    def test_delete_job_route_reaches_route_logic_without_admin_token(self):
        app = build_filings_test_app(DummyAsyncSession([None]))

        with patch.object(settings, "admin_route_token", "unit-test-token"):
            with TestClient(app) as client:
                response = client.delete("/api/v1/filings/jobs/999999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Filing job not found")

    def test_page_image_route_rejects_artifact_outside_upload_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploads = root / "uploads"
            inside_pdf_dir = uploads / "pdfs"
            inside_pdf_dir.mkdir(parents=True)
            source_pdf = inside_pdf_dir / "source.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")

            outside_image = root / "outside.png"
            outside_image.write_bytes(b"not really a png")

            page = SimpleNamespace(page_number=1, image_path=str(outside_image))
            job = SimpleNamespace(source_pdf_path=str(source_pdf))
            app = build_filings_test_app(DummyAsyncSession([job, page]))

            with (
                patch.object(settings, "upload_directory", str(uploads)),
                TestClient(app) as client,
            ):
                response = client.get("/api/v1/filings/jobs/7/pages/1/image")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "File not found")


if __name__ == "__main__":
    unittest.main()
