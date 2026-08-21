import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from config import settings
from database import FilingJob, User, get_db
from routers import admin, auth
from services.auth_service import create_access_token, hash_password, verify_password


class DummyScalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class DummyResult:
    def __init__(self, *, one=None, many=None, rows=None):
        self._one = one
        self._many = many or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return DummyScalars(self._many)

    def all(self):
        return self._rows


class FakeAdminSession:
    def __init__(self):
        self.users_by_email = {}
        self.users_by_id = {}
        self.jobs_by_id = {}
        self.suggestions_by_id = {}
        self.pending_user = None
        self.next_user_id = 1
        self.deleted_objects = []

    def add_existing_user(
        self,
        email,
        password,
        *,
        is_admin=False,
        is_deleted=False,
        token_version=0,
    ):
        user = User(
            id=self.next_user_id,
            email=email.lower(),
            password_hash=hash_password(password, iterations=1_000),
            token_version=token_version,
            is_admin=is_admin,
            is_active=True,
            is_deleted=is_deleted,
            created_at=datetime(2026, 1, self.next_user_id),
            updated_at=datetime(2026, 1, self.next_user_id),
            deleted_at=datetime(2026, 1, self.next_user_id) if is_deleted else None,
        )
        self.next_user_id += 1
        self.users_by_email[user.email] = user
        self.users_by_id[user.id] = user
        return user

    def add_existing_job(
        self,
        *,
        job_id,
        user_id,
        source_pdf_path,
        pages=None,
        registration_number="REG/123",
        status="REVIEW",
    ):
        job = SimpleNamespace(
            id=job_id,
            user_id=user_id,
            status=status,
            source_pdf_path=str(source_pdf_path) if source_pdf_path is not None else None,
            pages=list(pages or []),
            llm_mapping_suggestions=[],
            registration_number=registration_number,
            financial_year_end=datetime(2026, 12, 31),
        )
        self.jobs_by_id[job_id] = job
        return job

    def add_suggestion(self, suggestion_id, job_id):
        suggestion = SimpleNamespace(id=suggestion_id, job_id=job_id)
        self.suggestions_by_id[suggestion_id] = suggestion
        self.jobs_by_id[job_id].llm_mapping_suggestions.append(suggestion)
        return suggestion

    def add(self, user):
        self.pending_user = user

    async def flush(self):
        if self.pending_user.email in self.users_by_email:
            raise IntegrityError("duplicate email", {}, None)
        self.pending_user.id = self.next_user_id
        self.next_user_id += 1
        self.pending_user.email = self.pending_user.email.lower()
        self.pending_user.is_admin = bool(getattr(self.pending_user, "is_admin", False))
        self.pending_user.is_active = True
        self.pending_user.is_deleted = False
        self.pending_user.token_version = 0
        self.pending_user.created_at = datetime.utcnow()
        self.pending_user.updated_at = datetime.utcnow()
        self.users_by_email[self.pending_user.email] = self.pending_user
        self.users_by_id[self.pending_user.id] = self.pending_user
        self.pending_user = None

    async def commit(self):
        return None

    async def rollback(self):
        self.pending_user = None

    async def delete(self, obj):
        self.deleted_objects.append(obj)
        if isinstance(obj, User):
            self.users_by_id.pop(obj.id, None)
            self.users_by_email.pop(obj.email, None)
            return
        if hasattr(obj, "source_pdf_path") and hasattr(obj, "user_id"):
            self.jobs_by_id.pop(obj.id, None)
            for suggestion_id, suggestion in list(self.suggestions_by_id.items()):
                if suggestion.job_id == obj.id:
                    self.suggestions_by_id.pop(suggestion_id, None)
            return
        raise AssertionError(f"Unexpected delete object: {obj!r}")

    async def execute(self, statement):
        sql = str(statement)
        params = statement.compile().params

        if "FROM filing_jobs" in sql and "count(" in sql:
            rows = []
            counts = {}
            for job in self.jobs_by_id.values():
                if job.user_id is None:
                    continue
                key = (job.user_id, job.status)
                counts[key] = counts.get(key, 0) + 1
            for (user_id, status), count in counts.items():
                rows.append((user_id, status, count))
            return DummyResult(rows=rows)

        entity = None
        column_descriptions = getattr(statement, "column_descriptions", [])
        if column_descriptions:
            entity = column_descriptions[0].get("entity")

        if entity is FilingJob:
            user_id = self._param(params, "user_id")
            return DummyResult(
                many=[job for job in self.jobs_by_id.values() if job.user_id == user_id]
            )

        if entity is User or "FROM users" in sql:
            email = next(
                (
                    value.lower()
                    for value in params.values()
                    if isinstance(value, str) and "@" in value
                ),
                None,
            )
            if email:
                return DummyResult(one=self.users_by_email.get(email))

            user_id = self._param(params, "id")
            if user_id is not None:
                return DummyResult(one=self.users_by_id.get(user_id))

            users = [
                user
                for user in self.users_by_id.values()
                if not user.is_deleted
                and ("users.is_admin IS false" not in sql or not user.is_admin)
            ]
            users.sort(key=lambda user: (user.created_at, user.id))
            return DummyResult(many=users)

        raise AssertionError(f"Unexpected query: {sql} params={params}")

    def _param(self, params, prefix):
        for key, value in params.items():
            if key.startswith(prefix):
                return value
        return None


def make_page(page_id, image_path=None, item_count=0):
    return SimpleNamespace(
        id=page_id,
        image_path=str(image_path) if image_path is not None else None,
        extracted_items=[
            SimpleNamespace(id=f"{page_id}-item-{index}") for index in range(item_count)
        ],
    )


def build_admin_test_app(session):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(admin.router, prefix="/api/v1/admin")

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    return app


def bearer_for(user):
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, user.email, token_version=user.token_version)}"
        )
    }


class AdminUserManagementTests(unittest.TestCase):
    def setUp(self):
        self.secret_patch = patch.object(settings, "secret_key", "unit-test-admin-secret")
        self.secret_patch.start()
        self.addCleanup(self.secret_patch.stop)

    def test_admin_can_list_users_with_task_status_counts(self):
        session = FakeAdminSession()
        admin_user = session.add_existing_user("admin@example.com", "password-123", is_admin=True)
        other_admin = session.add_existing_user("other-admin@example.com", "password-123", is_admin=True)
        normal_user = session.add_existing_user("user@example.com", "password-123")
        other_user = session.add_existing_user("other@example.com", "password-123")
        deleted_user = session.add_existing_user(
            "deleted@example.com",
            "password-123",
            is_deleted=True,
        )
        session.add_existing_job(job_id=1, user_id=normal_user.id, source_pdf_path=None, status="REVIEW")
        session.add_existing_job(job_id=2, user_id=normal_user.id, source_pdf_path=None, status="COMPLETED")
        session.add_existing_job(job_id=3, user_id=normal_user.id, source_pdf_path=None, status="PROCESSING")
        session.add_existing_job(job_id=4, user_id=normal_user.id, source_pdf_path=None, status="ERROR")
        session.add_existing_job(job_id=5, user_id=other_user.id, source_pdf_path=None, status="ERROR")
        session.add_existing_job(job_id=6, user_id=None, source_pdf_path=None, status="REVIEW")
        session.add_existing_job(job_id=7, user_id=deleted_user.id, source_pdf_path=None, status="REVIEW")
        app = build_admin_test_app(session)

        with TestClient(app) as client:
            response = client.get("/api/v1/admin/users", headers=bearer_for(admin_user))

        self.assertEqual(response.status_code, 200)
        users = response.json()["users"]
        emails = [user["email"] for user in users]
        self.assertEqual(emails, ["user@example.com", "other@example.com"])
        self.assertNotIn(admin_user.email, emails)
        self.assertNotIn(other_admin.email, emails)
        normal_row = next(user for user in users if user["email"] == "user@example.com")
        self.assertEqual(normal_row["user_id"], normal_user.id)
        self.assertEqual(normal_row["user_type"], "USER")
        self.assertEqual(normal_row["task_count"], 4)
        self.assertEqual(normal_row["successful_task_count"], 2)
        self.assertEqual(normal_row["processing_task_count"], 1)
        self.assertEqual(normal_row["error_task_count"], 1)
        self.assertFalse(normal_row["is_admin"])
        self.assertIn("created_at", normal_row)
        self.assertIn("registered_at", normal_row)
        other_row = next(user for user in users if user["email"] == "other@example.com")
        self.assertEqual(other_row["successful_task_count"], 0)
        self.assertEqual(other_row["processing_task_count"], 0)
        self.assertEqual(other_row["error_task_count"], 1)

    def test_normal_user_cannot_list_users(self):
        session = FakeAdminSession()
        normal_user = session.add_existing_user("user@example.com", "password-123")
        app = build_admin_test_app(session)

        with TestClient(app) as client:
            response = client.get("/api/v1/admin/users", headers=bearer_for(normal_user))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin access required.")

    def test_admin_can_create_normal_user_and_public_registration_stays_disabled(self):
        session = FakeAdminSession()
        admin_user = session.add_existing_user("admin@example.com", "password-123", is_admin=True)
        app = build_admin_test_app(session)

        with TestClient(app) as client:
            create_response = client.post(
                "/api/v1/admin/users",
                headers=bearer_for(admin_user),
                json={
                    "email": " New.User@Example.COM ",
                    "password": "created-password",
                    "confirm_password": "created-password",
                },
            )
            register_response = client.post(
                "/api/v1/auth/register",
                json={"email": "public@example.com", "password": "public-password"},
            )

        self.assertEqual(create_response.status_code, 201)
        created_user = session.users_by_email["new.user@example.com"]
        self.assertFalse(created_user.is_admin)
        self.assertTrue(verify_password("created-password", created_user.password_hash))
        self.assertNotIn("created-password", created_user.password_hash)
        self.assertEqual(register_response.status_code, 403)
        self.assertEqual(
            register_response.json()["detail"],
            "Public registration is disabled. Please contact an administrator.",
        )

    def test_admin_change_normal_user_password_revokes_old_token(self):
        session = FakeAdminSession()
        admin_user = session.add_existing_user("admin@example.com", "password-123", is_admin=True)
        target_user = session.add_existing_user(
            "user@example.com",
            "old-password",
            token_version=4,
        )
        app = build_admin_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/admin/users/{target_user.id}/change-password",
                headers=bearer_for(admin_user),
                json={
                    "new_password": "new-password",
                    "confirm_password": "new-password",
                },
            )
            old_login = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "old-password"},
            )
            new_login = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "new-password"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(target_user.token_version, 5)
        self.assertFalse(verify_password("old-password", target_user.password_hash))
        self.assertTrue(verify_password("new-password", target_user.password_hash))
        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)

    def test_normal_user_cannot_call_admin_change_password(self):
        session = FakeAdminSession()
        normal_user = session.add_existing_user("user@example.com", "password-123")
        target_user = session.add_existing_user("target@example.com", "password-123")
        app = build_admin_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/admin/users/{target_user.id}/change-password",
                headers=bearer_for(normal_user),
                json={
                    "new_password": "new-password",
                    "confirm_password": "new-password",
                },
            )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(verify_password("password-123", target_user.password_hash))

    def test_admin_cannot_change_another_admin_password(self):
        session = FakeAdminSession()
        admin_user = session.add_existing_user("admin@example.com", "password-123", is_admin=True)
        other_admin = session.add_existing_user(
            "other-admin@example.com",
            "password-123",
            is_admin=True,
        )
        app = build_admin_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/admin/users/{other_admin.id}/change-password",
                headers=bearer_for(admin_user),
                json={
                    "new_password": "new-password",
                    "confirm_password": "new-password",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Cannot change another admin password")
        self.assertTrue(verify_password("password-123", other_admin.password_hash))

    def test_admin_can_clear_normal_user_tasks_and_files_without_deleting_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            page_dir = uploads / "pages"
            xbrl_dir = uploads / "xbrl"
            pdf_dir.mkdir(parents=True)
            page_dir.mkdir(parents=True)
            xbrl_dir.mkdir(parents=True)

            target_pdf = pdf_dir / "target.pdf"
            target_page = page_dir / "target-page.png"
            target_xbrl = xbrl_dir / "SSM_FS-MPERS_REG_123_20261231.xbrl"
            target_xml = xbrl_dir / "SSM_FS-MPERS_REG_123_20261231.xml"
            other_pdf = pdf_dir / "other.pdf"
            legacy_pdf = pdf_dir / "legacy.pdf"
            for path in (target_pdf, target_page, target_xbrl, target_xml, other_pdf, legacy_pdf):
                path.write_bytes(b"artifact")

            session = FakeAdminSession()
            admin_user = session.add_existing_user(
                "admin@example.com",
                "password-123",
                is_admin=True,
            )
            target_user = session.add_existing_user("user@example.com", "password-123")
            other_user = session.add_existing_user("other@example.com", "password-123")
            target_job = session.add_existing_job(
                job_id=10,
                user_id=target_user.id,
                source_pdf_path=target_pdf,
                pages=[make_page("page-target", target_page, item_count=2)],
            )
            session.add_suggestion("suggestion-target", target_job.id)
            session.add_existing_job(job_id=20, user_id=other_user.id, source_pdf_path=other_pdf)
            session.add_existing_job(job_id=30, user_id=None, source_pdf_path=legacy_pdf)
            app = build_admin_test_app(session)

            with patch.object(settings, "upload_directory", str(uploads)), TestClient(app) as client:
                response = client.post(
                    f"/api/v1/admin/users/{target_user.id}/clear-tasks",
                    headers=bearer_for(admin_user),
                )

            file_state = {
                "target_pdf": target_pdf.exists(),
                "target_page": target_page.exists(),
                "target_xbrl": target_xbrl.exists(),
                "target_xml": target_xml.exists(),
                "other_pdf": other_pdf.exists(),
                "legacy_pdf": legacy_pdf.exists(),
            }

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["deleted_jobs_count"], 1)
        self.assertEqual(response.json()["deleted_files_count"], 4)
        self.assertIn(target_user.id, session.users_by_id)
        self.assertNotIn(10, session.jobs_by_id)
        self.assertNotIn("suggestion-target", session.suggestions_by_id)
        self.assertIn(20, session.jobs_by_id)
        self.assertIn(30, session.jobs_by_id)
        self.assertFalse(file_state["target_pdf"])
        self.assertFalse(file_state["target_page"])
        self.assertFalse(file_state["target_xbrl"])
        self.assertFalse(file_state["target_xml"])
        self.assertTrue(file_state["other_pdf"])
        self.assertTrue(file_state["legacy_pdf"])

    def test_admin_can_delete_normal_user_and_owned_data_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            xbrl_dir = uploads / "xbrl"
            pdf_dir.mkdir(parents=True)
            xbrl_dir.mkdir(parents=True)

            target_pdf = pdf_dir / "target.pdf"
            target_xbrl = xbrl_dir / "SSM_FS-MPERS_DEL_123_20261231.xbrl"
            target_xml = xbrl_dir / "SSM_FS-MPERS_DEL_123_20261231.xml"
            other_pdf = pdf_dir / "other.pdf"
            legacy_pdf = pdf_dir / "legacy.pdf"
            for path in (target_pdf, target_xbrl, target_xml, other_pdf, legacy_pdf):
                path.write_bytes(b"artifact")

            session = FakeAdminSession()
            admin_user = session.add_existing_user(
                "admin@example.com",
                "password-123",
                is_admin=True,
            )
            target_user = session.add_existing_user("delete@example.com", "password-123")
            other_user = session.add_existing_user("other@example.com", "password-123")
            target_job = session.add_existing_job(
                job_id=40,
                user_id=target_user.id,
                source_pdf_path=target_pdf,
                pages=[],
                registration_number="DEL/123",
            )
            session.add_suggestion("suggestion-delete", target_job.id)
            session.add_existing_job(job_id=50, user_id=other_user.id, source_pdf_path=other_pdf)
            session.add_existing_job(job_id=60, user_id=None, source_pdf_path=legacy_pdf)
            app = build_admin_test_app(session)

            with patch.object(settings, "upload_directory", str(uploads)), TestClient(app) as client:
                response = client.delete(
                    f"/api/v1/admin/users/{target_user.id}",
                    headers=bearer_for(admin_user),
                )
                login_after_delete = client.post(
                    "/api/v1/auth/login",
                    json={"email": "delete@example.com", "password": "password-123"},
                )

            file_state = {
                "target_pdf": target_pdf.exists(),
                "target_xbrl": target_xbrl.exists(),
                "target_xml": target_xml.exists(),
                "other_pdf": other_pdf.exists(),
                "legacy_pdf": legacy_pdf.exists(),
            }

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertTrue(response.json()["deleted_user"])
        self.assertEqual(response.json()["deleted_jobs_count"], 1)
        self.assertEqual(response.json()["deleted_files_count"], 3)
        self.assertEqual(login_after_delete.status_code, 401)
        self.assertNotIn(target_user.id, session.users_by_id)
        self.assertNotIn(40, session.jobs_by_id)
        self.assertNotIn("suggestion-delete", session.suggestions_by_id)
        self.assertIn(other_user.id, session.users_by_id)
        self.assertIn(50, session.jobs_by_id)
        self.assertIn(60, session.jobs_by_id)
        self.assertFalse(file_state["target_pdf"])
        self.assertFalse(file_state["target_xbrl"])
        self.assertFalse(file_state["target_xml"])
        self.assertTrue(file_state["other_pdf"])
        self.assertTrue(file_state["legacy_pdf"])

    def test_admin_cannot_delete_self_or_another_admin(self):
        session = FakeAdminSession()
        admin_user = session.add_existing_user("admin@example.com", "password-123", is_admin=True)
        other_admin = session.add_existing_user(
            "other-admin@example.com",
            "password-123",
            is_admin=True,
        )
        app = build_admin_test_app(session)

        with TestClient(app) as client:
            self_response = client.delete(
                f"/api/v1/admin/users/{admin_user.id}",
                headers=bearer_for(admin_user),
            )
            other_admin_response = client.delete(
                f"/api/v1/admin/users/{other_admin.id}",
                headers=bearer_for(admin_user),
            )

        self.assertEqual(self_response.status_code, 400)
        self.assertEqual(
            self_response.json()["detail"],
            "Admin users cannot delete their own account.",
        )
        self.assertEqual(other_admin_response.status_code, 400)
        self.assertEqual(other_admin_response.json()["detail"], "Cannot delete an admin user")
        self.assertIn(admin_user.id, session.users_by_id)
        self.assertIn(other_admin.id, session.users_by_id)


if __name__ == "__main__":
    unittest.main()
