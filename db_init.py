"""
Database Initialization and Migration Script

This script handles:
1. Fresh database initialization (creates all tables, indexes, extensions)
2. Existing database migration (applies missing columns, indexes)
3. Data validation and consistency checks

Run this script to ensure your database is properly initialized for shipping.

Usage:
    python db_init.py              # Check status and show what would be done
    python db_init.py --apply      # Apply all migrations
    python db_init.py --force      # Drop and recreate all tables (DANGER!)
"""

import asyncio
import sys
import argparse
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from database import engine, Base
from config import settings
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """Handles database initialization and migrations"""

    MIGRATIONS_DIR = Path(__file__).parent / "migrations"

    # Required tables in order of creation (respects foreign keys)
    REQUIRED_TABLES = [
        "users",
        "xml_template_fields",
        "semantic_embeddings",
        "mbrs_taxonomy_tags",
        "filing_jobs",
        "financial_statement_pages",
        "extracted_data_items",
        "llm_mapping_suggestions",
        "mapping_supervisor_reviews",
        "supervisor_guided_mapping_revisions"
    ]

    # Required columns for each table
    REQUIRED_COLUMNS = {
        "users": [
            "id", "email", "password_hash", "token_version", "is_admin",
            "is_active", "is_deleted", "created_at", "updated_at",
            "last_login_at", "deleted_at"
        ],
        "xml_template_fields": [
            "id", "field_id", "statement_code", "statement_type", "label",
            "xbrl_tag", "data_type", "required", "position", "level",
            "path", "embedding", "created_at", "updated_at"
        ],
        "semantic_embeddings": [
            "id", "source_type", "source_id", "source_label", "source_text",
            "provider", "model", "dimension", "embedding", "source_text_hash",
            "embedding_hash", "is_active", "created_at", "updated_at"
        ],
        "mbrs_taxonomy_tags": [
            "id", "label", "xbrl_tag", "namespace", "period_type", "embedding"
        ],
        "filing_jobs": [
            "id", "user_id", "company_name", "registration_number",
            "financial_year_end", "source_pdf_path", "status", "uploaded_at",
            "progress", "error_message", "ai_mapping_status",
            "ai_mapping_last_error_message", "directors_report_html"
        ],
        "financial_statement_pages": [
            "id", "job_id", "page_number", "image_path"
        ],
        "extracted_data_items": [
            "id", "page_id", "extracted_label", "extracted_value", "financial_year",
            "value_previous_year", "financial_year_previous", "statement_type",
            "template_field_id", "template_position", "is_required_field",
            "is_reviewed", "confirmed_tag_id", "validation_warnings",
            "has_calculation_warning"
        ],
        "llm_mapping_suggestions": [
            "id", "job_id", "extracted_data_item_id", "suggested_template_field_id",
            "confidence", "reason", "ranked_candidates_json", "status", "model_id",
            "created_at", "raw_response_preview", "diagnostic_json"
        ],
        "mapping_supervisor_reviews": [
            "id", "user_id", "job_id", "extracted_data_item_id",
            "llm_mapping_suggestion_id", "mapper_selected_template_field_id",
            "mapper_selected_qname", "mapper_confidence", "mapper_status",
            "review_status", "supervisor_decision", "supervisor_risk_level",
            "supervisor_recommended_action", "supervisor_safe_to_accept",
            "calibrated_safe_to_accept", "supervisor_confidence_adjustment",
            "supervisor_issues_json", "supervisor_reason",
            "supervisor_model_provider", "supervisor_model_id",
            "supervisor_prompt_version", "supervisor_schema_version",
            "supervisor_payload_hash", "supervisor_response_hash",
            "error_type", "error_message_sanitized", "started_at",
            "completed_at", "review_attempt", "source", "is_latest",
            "created_at", "updated_at"
        ],
        "supervisor_guided_mapping_revisions": [
            "id", "job_id", "parent_suggestion_id", "supervisor_review_id",
            "correction_attempt", "correction_source", "original_suggested_qname",
            "revised_suggested_qname", "revised_confidence", "supervisor_decision",
            "reason", "addressed_supervisor_issues_json", "remaining_ambiguities_json",
            "status", "model_id", "requires_human_review", "safe_for_auto_apply",
            "created_at", "completed_at"
        ]
    }

    async def check_pgvector_extension(self) -> bool:
        """Check if pgvector extension is installed"""
        async with engine.begin() as conn:
            try:
                result = await conn.execute(text(
                    "SELECT extname FROM pg_extension WHERE extname = 'vector'"
                ))
                exists = result.fetchone() is not None
                return exists
            except Exception as e:
                logger.error(f"Error checking pgvector extension: {e}")
                return False

    async def install_pgvector_extension(self):
        """Install pgvector extension"""
        async with engine.begin() as conn:
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                logger.info("[OK] pgvector extension installed")
            except Exception as e:
                logger.error(f"[ERROR] Failed to install pgvector extension: {e}")
                logger.error("Please install pgvector manually: https://github.com/pgvector/pgvector")
                raise

    async def get_existing_tables(self) -> list:
        """Get list of existing tables in the database"""
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ))
            return [row[0] for row in result.fetchall()]

    async def get_table_columns(self, table_name: str) -> list:
        """Get columns for a specific table"""
        async with engine.begin() as conn:
            try:
                result = await conn.execute(text(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = '{table_name}'
                    ORDER BY ordinal_position
                """))
                return [row[0] for row in result.fetchall()]
            except Exception as e:
                logger.error(f"Error getting columns for {table_name}: {e}")
                return []

    async def check_database_status(self) -> dict:
        """Check current database status and return diagnostics"""
        status = {
            "pgvector_installed": False,
            "existing_tables": [],
            "missing_tables": [],
            "tables_with_missing_columns": {},
            "is_fresh_install": False,
            "needs_migration": False
        }

        # Check pgvector
        status["pgvector_installed"] = await self.check_pgvector_extension()

        # Check tables
        status["existing_tables"] = await self.get_existing_tables()
        status["missing_tables"] = [
            t for t in self.REQUIRED_TABLES
            if t not in status["existing_tables"]
        ]

        # Check columns for existing tables
        for table in self.REQUIRED_TABLES:
            if table in status["existing_tables"]:
                existing_cols = await self.get_table_columns(table)
                required_cols = self.REQUIRED_COLUMNS[table]
                missing_cols = [c for c in required_cols if c not in existing_cols]

                if missing_cols:
                    status["tables_with_missing_columns"][table] = missing_cols

        # Determine status
        status["is_fresh_install"] = len(status["existing_tables"]) == 0
        status["needs_migration"] = (
            len(status["missing_tables"]) > 0 or
            len(status["tables_with_missing_columns"]) > 0 or
            not status["pgvector_installed"]
        )

        return status

    async def run_sql_file(self, filepath: Path):
        """Execute a SQL file"""
        if not filepath.exists():
            logger.warning(f"SQL file not found: {filepath}")
            return False

        logger.info(f"Executing SQL file: {filepath.name}")

        sql_content = filepath.read_text(encoding='utf-8')
        statements = self._split_sql_statements(sql_content)

        if not statements:
            logger.warning(f"No executable SQL statements found in {filepath.name}")
            return False

        async with engine.begin() as conn:
            for stmt in statements:
                if stmt:
                    try:
                        await conn.execute(text(stmt))
                    except ProgrammingError as e:
                        # Ignore "already exists" errors
                        if "already exists" in str(e):
                            logger.debug(f"Skipping: {str(e)[:100]}")
                        else:
                            raise

        logger.info(f"[OK] Completed: {filepath.name}")
        return True

    def _split_sql_statements(self, sql_content: str) -> list[str]:
        """Split migration SQL while preserving statements preceded by comments."""
        sql_without_comments = []

        for line in sql_content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            sql_without_comments.append(line)

        statements = []
        current_statement = []
        in_single_quote = False
        in_double_quote = False

        cleaned_sql = "\n".join(sql_without_comments)
        index = 0

        while index < len(cleaned_sql):
            char = cleaned_sql[index]

            if char == "'" and in_single_quote and index + 1 < len(cleaned_sql) and cleaned_sql[index + 1] == "'":
                current_statement.append(char)
                current_statement.append(cleaned_sql[index + 1])
                index += 2
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote

            if char == ";" and not in_single_quote and not in_double_quote:
                statement = "".join(current_statement).strip()
                if statement:
                    statements.append(statement)
                current_statement = []
            else:
                current_statement.append(char)

            index += 1

        statement = "".join(current_statement).strip()
        if statement:
            statements.append(statement)

        return statements

    async def initialize_fresh_database(self):
        """Initialize a fresh database from scratch"""
        logger.info("[INIT] Initializing fresh database...")

        # Install pgvector
        await self.install_pgvector_extension()

        # Run all idempotent migrations so fresh installs include later tables.
        migration_files = sorted(self.MIGRATIONS_DIR.glob("*.sql"))
        for migration_file in migration_files:
            await self.run_sql_file(migration_file)

        logger.info("[OK] Fresh database initialized successfully")

    async def migrate_existing_database(self):
        """Apply migrations to existing database"""
        logger.info("[MIGRATE] Migrating existing database...")

        # Ensure pgvector is installed
        if not await self.check_pgvector_extension():
            await self.install_pgvector_extension()

        # Run all migration files in order
        migration_files = sorted(self.MIGRATIONS_DIR.glob("*.sql"))

        for migration_file in migration_files:
            await self.run_sql_file(migration_file)

        logger.info("[OK] Database migration completed")

    async def drop_all_tables(self):
        """Drop all tables (DANGEROUS - only for force reset)"""
        logger.warning("[WARNING] DROPPING ALL TABLES...")

        async with engine.begin() as conn:
            # Drop tables in reverse order to respect foreign keys
            for table in reversed(self.REQUIRED_TABLES):
                try:
                    await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                    logger.info(f"Dropped table: {table}")
                except Exception as e:
                    logger.error(f"Error dropping {table}: {e}")

        logger.warning("[WARNING] All tables dropped")

    async def print_status_report(self, status: dict):
        """Print a detailed status report"""
        print("\n" + "="*70)
        print("DATABASE STATUS REPORT")
        print("="*70)

        db_url = settings.database_url.split('@')[1] if '@' in settings.database_url else settings.database_url
        print(f"\n[DATABASE] Database URL: {db_url}")

        # pgvector
        print(f"\n[PGVECTOR] pgvector Extension:")
        print(f"   {'[OK] Installed' if status['pgvector_installed'] else '[ERROR] NOT INSTALLED'}")

        # Tables
        print(f"\n[TABLES] Tables:")
        print(f"   Existing: {len(status['existing_tables'])}/{len(self.REQUIRED_TABLES)}")

        if status['missing_tables']:
            print(f"\n   [ERROR] Missing tables:")
            for table in status['missing_tables']:
                print(f"      - {table}")

        if status['tables_with_missing_columns']:
            print(f"\n   [WARNING] Tables with missing columns:")
            for table, cols in status['tables_with_missing_columns'].items():
                print(f"      - {table}: {', '.join(cols)}")

        if status['existing_tables'] and not status['missing_tables'] and not status['tables_with_missing_columns']:
            print(f"   [OK] All tables present with correct schema")

        # Overall status
        print(f"\n[STATUS] Overall Status:")
        if status['is_fresh_install']:
            print(f"   [INFO] Fresh installation needed")
        elif status['needs_migration']:
            print(f"   [INFO] Migration needed")
        else:
            print(f"   [OK] Database is up to date")

        print("\n" + "="*70 + "\n")

    async def validate_data_integrity(self):
        """Run basic data integrity checks"""
        logger.info("[VALIDATE] Validating data integrity...")

        checks_passed = True

        async with engine.begin() as conn:
            # Check for orphaned pages
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM financial_statement_pages
                WHERE job_id NOT IN (SELECT id FROM filing_jobs)
            """))
            orphaned_pages = result.scalar()
            if orphaned_pages > 0:
                logger.warning(f"[WARNING] Found {orphaned_pages} orphaned pages")
                checks_passed = False

            # Check for orphaned items
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM extracted_data_items
                WHERE page_id NOT IN (SELECT id FROM financial_statement_pages)
            """))
            orphaned_items = result.scalar()
            if orphaned_items > 0:
                logger.warning(f"[WARNING] Found {orphaned_items} orphaned data items")
                checks_passed = False

            result = await conn.execute(text("""
                SELECT COUNT(*) FROM llm_mapping_suggestions
                WHERE job_id NOT IN (SELECT id FROM filing_jobs)
                   OR extracted_data_item_id NOT IN (SELECT id FROM extracted_data_items)
            """))
            orphaned_suggestions = result.scalar()
            if orphaned_suggestions > 0:
                logger.warning(f"[WARNING] Found {orphaned_suggestions} orphaned LLM mapping suggestions")
                checks_passed = False

            # Check for invalid tag references
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM extracted_data_items
                WHERE confirmed_tag_id IS NOT NULL
                AND confirmed_tag_id NOT IN (SELECT id FROM mbrs_taxonomy_tags)
            """))
            invalid_tags = result.scalar()
            if invalid_tags > 0:
                logger.warning(f"[WARNING] Found {invalid_tags} items with invalid tag references")
                checks_passed = False

        if checks_passed:
            logger.info("[OK] Data integrity checks passed")
        else:
            logger.warning("[WARNING] Some data integrity issues found")

        return checks_passed


async def main():
    parser = argparse.ArgumentParser(
        description="Initialize or migrate XBRL Filing Platform database"
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply migrations/initialization (default: dry-run only)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force drop all tables and reinitialize (DANGER: destroys all data!)'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Run data integrity validation checks'
    )

    args = parser.parse_args()

    initializer = DatabaseInitializer()

    try:
        # Check current status
        status = await initializer.check_database_status()
        await initializer.print_status_report(status)

        # Handle force reset
        if args.force:
            confirm = input("\n[WARNING] This will DELETE ALL DATA. Type 'YES' to confirm: ")
            if confirm == "YES":
                await initializer.drop_all_tables()
                await initializer.initialize_fresh_database()
                logger.info("[OK] Database reset and reinitialized")
            else:
                logger.info("Cancelled.")
            return

        # Handle apply
        if args.apply:
            if status['is_fresh_install']:
                await initializer.initialize_fresh_database()
            elif status['needs_migration']:
                await initializer.migrate_existing_database()
            else:
                logger.info("[OK] Database is already up to date. No action needed.")

            from services.bootstrap_admin import bootstrap_admin_account

            await bootstrap_admin_account()
        else:
            # Dry run
            if status['is_fresh_install']:
                print("[ACTION NEEDED] Run with --apply to initialize fresh database")
            elif status['needs_migration']:
                print("[ACTION NEEDED] Run with --apply to migrate existing database")
            else:
                print("[OK] No action needed. Database is up to date.")

        # Validate if requested
        if args.validate:
            await initializer.validate_data_integrity()

    except Exception as e:
        logger.error(f"[ERROR] {e}", exc_info=True)
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
