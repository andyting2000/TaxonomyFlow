import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from config import settings
from database import FilingJob, User, get_db
from routers import auth, filings
from services.auth_service import (
    AUTH_SECRET_NOT_CONFIGURED_MESSAGE,
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from services.bootstrap_admin import bootstrap_admin_account


class DummyResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self._value, list):
            return self._value
        if self._value is None:
            return []
        return [self._value]


class FakeAuthSession:
    def __init__(self):
        self.users_by_email = {}
        self.users_by_id = {}
        self.jobs_by_id = {}
        self.pending_user = None
        self.next_id = 1

    def add_existing_user(
        self,
        email: str,
        password: str,
        *,
        is_active: bool = True,
        is_deleted: bool = False,
        token_version: int = 0,
        is_admin: bool = False,
    ):
        user = User(
            id=self.next_id,
            email=email.lower(),
            password_hash=hash_password(password, iterations=1_000),
            token_version=token_version,
            is_admin=is_admin,
            is_active=is_active,
            is_deleted=is_deleted,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            deleted_at=datetime.utcnow() if is_deleted else None,
        )
        self.next_id += 1
        self.users_by_email[user.email] = user
        self.users_by_id[user.id] = user
        return user

    def add_existing_job(
        self,
        *,
        job_id: int,
        user_id: int | None,
        source_pdf_path: str | None,
        pages=None,
        registration_number: str = "REG/123",
    ):
        job = SimpleNamespace(
            id=job_id,
            user_id=user_id,
            source_pdf_path=source_pdf_path,
            pages=list(pages or []),
            registration_number=registration_number,
            financial_year_end=datetime(2026, 12, 31),
        )
        self.jobs_by_id[job_id] = job
        return job

    def add(self, user):
        self.pending_user = user

    async def flush(self):
        if self.pending_user.email in self.users_by_email:
            raise IntegrityError("duplicate email", {}, None)

        self.pending_user.id = self.next_id
        self.next_id += 1
        self.pending_user.email = self.pending_user.email.lower()
        self.pending_user.token_version = 0
        self.pending_user.is_admin = bool(getattr(self.pending_user, "is_admin", False))
        self.pending_user.is_active = True
        self.pending_user.is_deleted = False
        self.pending_user.created_at = datetime.utcnow()
        self.pending_user.updated_at = datetime.utcnow()
        self.pending_user.deleted_at = None
        self.users_by_email[self.pending_user.email] = self.pending_user
        self.users_by_id[self.pending_user.id] = self.pending_user
        self.pending_user = None

    async def rollback(self):
        self.pending_user = None

    async def commit(self):
        return None

    async def delete(self, obj):
        if isinstance(obj, User):
            self.users_by_id.pop(obj.id, None)
            self.users_by_email.pop(obj.email, None)
            return

        if hasattr(obj, "source_pdf_path") and hasattr(obj, "user_id"):
            self.jobs_by_id.pop(obj.id, None)
            return

        raise AssertionError(f"Unexpected delete object: {obj!r}")

    async def execute(self, statement):
        entity = None
        column_descriptions = getattr(statement, "column_descriptions", [])
        if column_descriptions:
            entity = column_descriptions[0].get("entity")

        params = statement.compile().params
        if entity is FilingJob:
            user_id = next((value for value in params.values() if isinstance(value, int)), None)
            return DummyResult(
                [job for job in self.jobs_by_id.values() if job.user_id == user_id]
            )

        email = next(
            (value.lower() for value in params.values() if isinstance(value, str) and "@" in value),
            None,
        )
        if email:
            return DummyResult(self.users_by_email.get(email))

        user_id = next((value for value in params.values() if isinstance(value, int)), None)
        if user_id is not None:
            return DummyResult(self.users_by_id.get(user_id))

        raise AssertionError(f"Unexpected auth query params: {params}")


def build_auth_test_app(db_session):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return app


def build_auth_and_filings_test_app(db_session):
    app = build_auth_test_app(db_session)
    app.include_router(filings.router, prefix="/api/v1/filings")
    return app


def make_page(page_id, image_path=None, item_count=0):
    return SimpleNamespace(
        id=page_id,
        image_path=str(image_path) if image_path is not None else None,
        extracted_items=[
            SimpleNamespace(id=f"{page_id}-item-{index}") for index in range(item_count)
        ],
    )


class PasswordHashingTests(unittest.TestCase):
    def test_password_hash_round_trip_and_wrong_password_rejection(self):
        password_hash = hash_password("correct horse battery staple", iterations=1_000)

        self.assertNotIn("correct horse battery staple", password_hash)
        self.assertTrue(verify_password("correct horse battery staple", password_hash))
        self.assertFalse(verify_password("incorrect password", password_hash))

    def test_invalid_password_hash_rejected(self):
        self.assertFalse(verify_password("password", "not-a-valid-hash"))


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.secret_patch = patch.object(settings, "secret_key", "unit-test-secret-key-15a")
        self.secret_patch.start()
        self.addCleanup(self.secret_patch.stop)

    def test_public_registration_is_disabled(self):
        session = FakeAuthSession()
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/register",
                json={"email": " Test@Example.COM ", "password": "long-enough-password"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Public registration is disabled. Please contact an administrator.",
        )
        self.assertEqual(session.users_by_email, {})

    def test_login_returns_token_for_valid_password(self):
        session = FakeAuthSession()
        session.add_existing_user("user@example.com", "long-enough-password")
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "long-enough-password"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token_type"], "bearer")
        self.assertEqual(body["user"]["email"], "user@example.com")
        self.assertFalse(body["user"]["is_admin"])
        payload = verify_access_token(body["access_token"])
        self.assertEqual(payload.token_version, 0)
        self.assertIsNotNone(session.users_by_email["user@example.com"].last_login_at)

    def test_login_response_includes_admin_role(self):
        session = FakeAuthSession()
        session.add_existing_user(
            "admin@example.com",
            "long-enough-password",
            is_admin=True,
        )
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "admin@example.com", "password": "long-enough-password"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["is_admin"])

    def test_login_rejects_invalid_password(self):
        session = FakeAuthSession()
        session.add_existing_user("user@example.com", "long-enough-password")
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "wrong-password"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password")

    def test_deleted_user_cannot_log_in(self):
        session = FakeAuthSession()
        session.add_existing_user(
            "user@example.com",
            "long-enough-password",
            is_active=False,
            is_deleted=True,
        )
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "long-enough-password"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid email or password")

    def test_current_user_requires_valid_bearer_token(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "long-enough-password")
        token = create_access_token(
            user.id,
            user.email,
            token_version=user.token_version,
            now=1_900_000_000,
        )
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            unauthorized = client.get("/api/v1/auth/current-user")
            authorized = client.get(
                "/api/v1/auth/current-user",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["email"], "user@example.com")
        self.assertFalse(authorized.json()["is_admin"])

    def test_current_user_returns_admin_role(self):
        session = FakeAuthSession()
        user = session.add_existing_user(
            "admin@example.com",
            "long-enough-password",
            is_admin=True,
        )
        token = create_access_token(
            user.id,
            user.email,
            token_version=user.token_version,
            now=1_900_000_000,
        )
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/auth/current-user",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_admin"])

    def test_current_user_rejects_stale_token_version(self):
        session = FakeAuthSession()
        user = session.add_existing_user(
            "user@example.com",
            "long-enough-password",
            token_version=2,
        )
        stale_token = create_access_token(
            user.id,
            user.email,
            token_version=1,
            now=1_900_000_000,
        )
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/auth/current-user",
                headers={"Authorization": f"Bearer {stale_token}"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid bearer token")

    def test_current_user_reports_server_auth_secret_configuration_problem(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "long-enough-password")
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with patch.object(settings, "secret_key", ""), TestClient(app) as client:
            response = client.get(
                "/api/v1/auth/current-user",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], AUTH_SECRET_NOT_CONFIGURED_MESSAGE)

    def test_logout_requires_auth_and_returns_token_discard_contract(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "long-enough-password")
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertIn("Discard the bearer token", response.json()["message"])

    def test_change_password_updates_hash_and_allows_new_password_login(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "old-password")
        session.add_existing_job(
            job_id=44,
            user_id=user.id,
            source_pdf_path=None,
            pages=[],
        )
        old_hash = user.password_hash
        old_token_version = user.token_version
        token = create_access_token(
            user.id,
            user.email,
            token_version=user.token_version,
            now=1_900_000_000,
        )
        app = build_auth_and_filings_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "current_password": "old-password",
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
            same_token_current_user = client.get(
                "/api/v1/auth/current-user",
                headers={"Authorization": f"Bearer {token}"},
            )
            stale_token_filings = client.get(
                "/api/v1/filings/jobs",
                headers={"Authorization": f"Bearer {token}"},
            )
            new_token_current_user = client.get(
                "/api/v1/auth/current-user",
                headers={"Authorization": f"Bearer {new_login.json()['access_token']}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["message"], "Password changed successfully.")
        self.assertNotEqual(user.password_hash, old_hash)
        self.assertEqual(user.token_version, old_token_version + 1)
        self.assertNotIn("new-password", user.password_hash)
        self.assertFalse(verify_password("old-password", user.password_hash))
        self.assertTrue(verify_password("new-password", user.password_hash))
        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)
        self.assertEqual(same_token_current_user.status_code, 401)
        self.assertEqual(stale_token_filings.status_code, 401)
        self.assertEqual(new_token_current_user.status_code, 200)
        new_token_payload = verify_access_token(new_login.json()["access_token"])
        self.assertEqual(new_token_payload.token_version, user.token_version)

    def test_change_password_rejects_wrong_current_password(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "old-password")
        original_hash = user.password_hash
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "current_password": "wrong-password",
                    "new_password": "new-password",
                    "confirm_password": "new-password",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Current password is incorrect")
        self.assertEqual(user.password_hash, original_hash)

    def test_change_password_rejects_same_password_without_updating_hash(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "old-password")
        original_hash = user.password_hash
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "current_password": "old-password",
                    "new_password": "old-password",
                    "confirm_password": "old-password",
                },
            )
            old_login = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "old-password"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "New password must be different from your current password.",
        )
        self.assertEqual(user.password_hash, original_hash)
        self.assertTrue(verify_password("old-password", user.password_hash))
        self.assertEqual(old_login.status_code, 200)

    def test_change_password_rejects_weak_new_password(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "old-password")
        original_hash = user.password_hash
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "current_password": "old-password",
                    "new_password": "short",
                    "confirm_password": "short",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(user.password_hash, original_hash)

    def test_change_password_rejects_mismatched_confirmation(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "old-password")
        original_hash = user.password_hash
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "current_password": "old-password",
                    "new_password": "new-password",
                    "confirm_password": "other-password",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "New password and confirmation do not match",
        )
        self.assertEqual(user.password_hash, original_hash)

    def test_delete_account_hard_deletes_user_owned_jobs_records_files_and_blocks_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            page_dir = uploads / "pages"
            xbrl_dir = uploads / "xbrl"
            structure_dir = uploads / "document-structures" / "job_7"
            pdf_dir.mkdir(parents=True)
            page_dir.mkdir(parents=True)
            xbrl_dir.mkdir(parents=True)
            structure_dir.mkdir(parents=True)

            source_pdf = pdf_dir / "source.pdf"
            page_image = page_dir / "job-7-page-1.png"
            generated_xbrl = xbrl_dir / "SSM_FS-MPERS_REG_123_20261231.xbrl"
            generated_xml = xbrl_dir / "SSM_FS-MPERS_REG_123_20261231.xml"
            document_structure = structure_dir / "structure_19a_v4.json"
            template_classification = (
                structure_dir / "template_classification_19b_v2.json"
            )
            initial_mapping = structure_dir / "initial_mapping_19c_v2.json"
            stale_initial_mapping = structure_dir / "initial_mapping_19c_v1.json"
            pipeline_execution_status = structure_dir / "pipeline_execution_status.json"
            missing_page_image = page_dir / "missing.png"
            for path in (
                source_pdf,
                page_image,
                generated_xbrl,
                generated_xml,
                document_structure,
                template_classification,
                initial_mapping,
                stale_initial_mapping,
                pipeline_execution_status,
            ):
                path.write_bytes(b"artifact")

            session = FakeAuthSession()
            user = session.add_existing_user("user@example.com", "current-password")
            session.add_existing_job(
                job_id=7,
                user_id=user.id,
                source_pdf_path=str(source_pdf),
                pages=[
                    make_page("page-1", page_image, item_count=2),
                    make_page("page-2", missing_page_image, item_count=1),
                ],
            )
            token = create_access_token(user.id, user.email, now=1_900_000_000)
            app = build_auth_and_filings_test_app(session)

            with patch.object(settings, "upload_directory", str(uploads)), TestClient(app) as client:
                response = client.post(
                    "/api/v1/auth/delete-account",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "email_confirmation": " user@example.com ",
                        "current_password": "current-password",
                        "confirm_password": "current-password",
                    },
                )
                login_after_delete = client.post(
                    "/api/v1/auth/login",
                    json={"email": "user@example.com", "password": "current-password"},
                )
                current_user_after_delete = client.get(
                    "/api/v1/auth/current-user",
                    headers={"Authorization": f"Bearer {token}"},
                )
                filings_after_delete = client.get(
                    "/api/v1/filings/jobs",
                    headers={"Authorization": f"Bearer {token}"},
                )

            file_cleanup_state = {
                "source_pdf_exists": source_pdf.exists(),
                "page_image_exists": page_image.exists(),
                "generated_xbrl_exists": generated_xbrl.exists(),
                "generated_xml_exists": generated_xml.exists(),
                "document_structure_exists": document_structure.exists(),
                "template_classification_exists": template_classification.exists(),
                "initial_mapping_exists": initial_mapping.exists(),
                "stale_initial_mapping_exists": stale_initial_mapping.exists(),
                "pipeline_execution_status_exists": pipeline_execution_status.exists(),
            }

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "success": True,
            "message": "Your account and all filing data have been permanently deleted.",
            "deleted_user": True,
            "deleted_jobs_count": 1,
            "deleted_pages_count": 2,
            "deleted_extracted_items_count": 3,
            "deleted_files_count": 9,
            "skipped_missing_files_count": 1,
        })
        self.assertNotIn(user.email, session.users_by_email)
        self.assertNotIn(user.id, session.users_by_id)
        self.assertEqual(session.jobs_by_id, {})
        self.assertFalse(file_cleanup_state["source_pdf_exists"])
        self.assertFalse(file_cleanup_state["page_image_exists"])
        self.assertFalse(file_cleanup_state["generated_xbrl_exists"])
        self.assertFalse(file_cleanup_state["generated_xml_exists"])
        self.assertFalse(file_cleanup_state["document_structure_exists"])
        self.assertFalse(file_cleanup_state["template_classification_exists"])
        self.assertFalse(file_cleanup_state["initial_mapping_exists"])
        self.assertFalse(file_cleanup_state["stale_initial_mapping_exists"])
        self.assertFalse(file_cleanup_state["pipeline_execution_status_exists"])
        self.assertNotIn("password_hash", response.text)
        self.assertNotIn("current-password", response.text)
        self.assertEqual(login_after_delete.status_code, 401)
        self.assertEqual(current_user_after_delete.status_code, 401)
        self.assertEqual(filings_after_delete.status_code, 401)

    def test_deleted_email_still_cannot_self_register_after_hard_deletion(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "current-password")
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            delete_response = client.post(
                "/api/v1/auth/delete-account",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email_confirmation": "user@example.com",
                    "current_password": "current-password",
                    "confirm_password": "current-password",
                },
            )
            register_response = client.post(
                "/api/v1/auth/register",
                json={"email": "user@example.com", "password": "new-password"},
            )

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(register_response.status_code, 403)
        self.assertNotIn("user@example.com", session.users_by_email)

    def test_delete_account_rejects_wrong_password(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "current-password")
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/delete-account",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email_confirmation": "user@example.com",
                    "current_password": "wrong-password",
                    "confirm_password": "wrong-password",
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Current password is incorrect")
        self.assertIn(user.email, session.users_by_email)
        self.assertIn(user.id, session.users_by_id)

    def test_delete_account_rejects_password_confirmation_mismatch(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "current-password")
        session.add_existing_job(
            job_id=9,
            user_id=user.id,
            source_pdf_path=None,
            pages=[make_page("page-1", None, item_count=1)],
        )
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/delete-account",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email_confirmation": "user@example.com",
                    "current_password": "current-password",
                    "confirm_password": "other-password",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Password confirmation does not match")
        self.assertIn(user.email, session.users_by_email)
        self.assertIn(9, session.jobs_by_id)

    def test_delete_account_rejects_email_confirmation_mismatch(self):
        session = FakeAuthSession()
        user = session.add_existing_user("user@example.com", "current-password")
        token = create_access_token(user.id, user.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/delete-account",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email_confirmation": "other@example.com",
                    "current_password": "current-password",
                    "confirm_password": "current-password",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Email confirmation does not match")
        self.assertIn(user.email, session.users_by_email)
        self.assertIn(user.id, session.users_by_id)

    def test_deleting_user_a_does_not_affect_user_b_or_legacy_jobs(self):
        session = FakeAuthSession()
        user_a = session.add_existing_user("a@example.com", "current-password")
        user_b = session.add_existing_user("b@example.com", "other-password")
        owned_job = session.add_existing_job(
            job_id=100,
            user_id=user_a.id,
            source_pdf_path=None,
            pages=[make_page("a-page", None, item_count=1)],
        )
        other_job = session.add_existing_job(
            job_id=200,
            user_id=user_b.id,
            source_pdf_path=None,
            pages=[make_page("b-page", None, item_count=1)],
        )
        legacy_job = session.add_existing_job(
            job_id=300,
            user_id=None,
            source_pdf_path=None,
            pages=[make_page("legacy-page", None, item_count=1)],
        )
        token = create_access_token(user_a.id, user_a.email, now=1_900_000_000)
        app = build_auth_test_app(session)

        with TestClient(app) as client:
            delete_response = client.post(
                "/api/v1/auth/delete-account",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "email_confirmation": "a@example.com",
                    "current_password": "current-password",
                    "confirm_password": "current-password",
                },
            )
            user_b_login = client.post(
                "/api/v1/auth/login",
                json={"email": "b@example.com", "password": "other-password"},
            )

        self.assertEqual(delete_response.status_code, 200)
        self.assertNotIn(user_a.email, session.users_by_email)
        self.assertIn(user_b.email, session.users_by_email)
        self.assertNotIn(owned_job.id, session.jobs_by_id)
        self.assertIs(session.jobs_by_id[other_job.id], other_job)
        self.assertIs(session.jobs_by_id[legacy_job.id], legacy_job)
        self.assertEqual(user_b_login.status_code, 200)


class AuthSecretConfigTests(unittest.TestCase):
    def test_token_signing_requires_configured_secret(self):
        with patch.object(settings, "secret_key", ""):
            with self.assertRaisesRegex(RuntimeError, "Server auth secret is not configured"):
                create_access_token(1, "user@example.com", now=1_900_000_000)

    def test_token_signing_uses_configured_secret(self):
        with patch.object(settings, "secret_key", "configured-secret-one"):
            token = create_access_token(1, "user@example.com", now=1_900_000_000)
            payload = verify_access_token(token, now=1_900_000_001)

        self.assertEqual(payload.user_id, 1)
        self.assertEqual(payload.email, "user@example.com")
        self.assertEqual(payload.token_version, 0)

        versioned_token = create_access_token(
            1,
            "user@example.com",
            token_version=7,
            now=1_900_000_000,
        )
        versioned_payload = verify_access_token(versioned_token, now=1_900_000_001)
        self.assertEqual(versioned_payload.token_version, 7)

        with patch.object(settings, "secret_key", "configured-secret-two"):
            with self.assertRaisesRegex(ValueError, "Invalid access token"):
                verify_access_token(token, now=1_900_000_001)


class BootstrapAdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_admin_creates_account_when_enabled(self):
        session = FakeAuthSession()

        with (
            patch.object(settings, "bootstrap_admin_enabled", True),
            patch.object(settings, "bootstrap_admin_email", "Admin@Example.COM "),
            patch.object(settings, "bootstrap_admin_password", "bootstrap-password"),
        ):
            result = await bootstrap_admin_account(session)

        self.assertTrue(result.enabled)
        self.assertTrue(result.created)
        self.assertIn("admin@example.com", session.users_by_email)
        user = session.users_by_email["admin@example.com"]
        self.assertTrue(user.is_admin)
        self.assertNotIn("bootstrap-password", user.password_hash)
        self.assertTrue(verify_password("bootstrap-password", user.password_hash))

    async def test_bootstrap_admin_promotes_existing_account_without_overwriting_password(self):
        session = FakeAuthSession()
        existing = session.add_existing_user("admin@example.com", "original-password")
        original_hash = existing.password_hash

        with (
            patch.object(settings, "bootstrap_admin_enabled", True),
            patch.object(settings, "bootstrap_admin_email", "admin@example.com"),
            patch.object(settings, "bootstrap_admin_password", "new-password"),
        ):
            result = await bootstrap_admin_account(session)

        self.assertTrue(result.enabled)
        self.assertFalse(result.created)
        self.assertEqual(len(session.users_by_email), 1)
        self.assertEqual(session.users_by_email["admin@example.com"].password_hash, original_hash)
        self.assertTrue(session.users_by_email["admin@example.com"].is_admin)
        self.assertTrue(verify_password("original-password", original_hash))
        self.assertFalse(verify_password("new-password", original_hash))

    async def test_bootstrap_admin_disabled_does_nothing(self):
        session = FakeAuthSession()

        with (
            patch.object(settings, "bootstrap_admin_enabled", False),
            patch.object(settings, "bootstrap_admin_email", "admin@example.com"),
            patch.object(settings, "bootstrap_admin_password", "bootstrap-password"),
        ):
            result = await bootstrap_admin_account(session)

        self.assertFalse(result.enabled)
        self.assertFalse(result.created)
        self.assertEqual(session.users_by_email, {})


class AuthMigrationTests(unittest.TestCase):
    def test_users_migration_and_db_init_registration_exist(self):
        migration = Path("migrations/004_add_users.sql").read_text(encoding="utf-8")
        soft_delete_migration = Path("migrations/006_add_user_soft_delete.sql").read_text(
            encoding="utf-8"
        )
        token_version_migration = Path("migrations/007_add_user_token_version.sql").read_text(
            encoding="utf-8"
        )
        admin_role_migration = Path("migrations/010_add_user_admin_role.sql").read_text(
            encoding="utf-8"
        )
        db_init_source = Path("db_init.py").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS users", migration)
        self.assertIn("password_hash TEXT NOT NULL", migration)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email", migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS is_deleted", soft_delete_migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS deleted_at", soft_delete_migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS token_version", token_version_migration)
        self.assertIn("DEFAULT 0", token_version_migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS is_admin", admin_role_migration)
        self.assertIn("DEFAULT FALSE", admin_role_migration)
        self.assertIn('"users"', db_init_source)
        self.assertIn('"password_hash"', db_init_source)
        self.assertIn('"token_version"', db_init_source)
        self.assertIn('"is_admin"', db_init_source)
        self.assertIn('"is_deleted"', db_init_source)
        self.assertIn('"deleted_at"', db_init_source)

    def test_auth_secret_and_bootstrap_env_templates_are_documented(self):
        env_example = Path(".env.example").read_text(encoding="utf-8")
        docker_env_example = Path(".env.docker.example").read_text(encoding="utf-8")
        db_init_source = Path("db_init.py").read_text(encoding="utf-8")

        for source in (env_example, docker_env_example):
            self.assertIn("SECRET_KEY=generate-with-openssl-rand-hex-32", source)
            self.assertIn("BOOTSTRAP_ADMIN_ENABLED=false", source)
            self.assertIn("BOOTSTRAP_ADMIN_EMAIL=admin@example.com", source)
            self.assertIn("BOOTSTRAP_ADMIN_PASSWORD=replace-with-bootstrap-password", source)

        self.assertIn("bootstrap_admin_account", db_init_source)


if __name__ == "__main__":
    unittest.main()
