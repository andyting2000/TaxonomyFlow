# Database Migrations

This directory contains SQL migration files for the XBRL Filing Platform database.

## Overview

Migration files are numbered sequentially and applied in order. Each migration is idempotent (safe to run multiple times) using `IF NOT EXISTS` clauses.

## Migration Files

1. **001_initial_schema.sql** - Initial database schema
   - Creates all core tables
   - Sets up indexes
   - Enables pgvector extension
   - Defines foreign key relationships

2. **002_add_validation_fields.sql** - Validation support
   - Adds `validation_warnings` column to extracted_data_items
   - Adds `has_calculation_warning` flag
   - Creates index for filtering items with warnings

13. **013_add_supervisor_guided_mapping_revisions.sql** - Advisory mapping revisions
   - Stores manual Supervisor-guided mapper corrections separately
   - Enforces bounded attempts per initial suggestion
   - Requires human review and prohibits automatic apply at the schema level

## Running Migrations

### Check Database Status

```bash
python db_init.py
```

This shows:
- Current database status
- Missing tables/columns
- Whether pgvector is installed
- What actions are needed

### Apply Migrations

```bash
# Apply all pending migrations
python db_init.py --apply

# Validate data integrity after migration
python db_init.py --apply --validate
```

### Fresh Installation

For a fresh database (no existing tables):

```bash
python db_init.py --apply
```

This will:
1. Install pgvector extension
2. Create all tables with correct schema
3. Create all indexes

### Force Reset (DANGER!)

To drop all tables and start fresh:

```bash
python db_init.py --force
```

**WARNING:** This destroys all data!

## Adding New Migrations

When you need to modify the database schema:

1. Create a new numbered SQL file: `migrations/00X_description.sql`
2. Use `IF NOT EXISTS` or `ADD COLUMN IF NOT EXISTS` for idempotency
3. Add comments explaining the change
4. Test on a copy of the database first

Example:

```sql
-- Migration: Add new feature
-- Date: 2025-10-16
-- Description: Adds support for XYZ

ALTER TABLE some_table
ADD COLUMN IF NOT EXISTS new_column VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_new_column
ON some_table(new_column);
```

## Database Schema

### Tables (in dependency order)

1. **xml_template_fields** - MPERS template fields with embeddings
2. **mbrs_taxonomy_tags** - XBRL taxonomy tags with embeddings
3. **filing_jobs** - Main filing submissions
4. **financial_statement_pages** - PDF pages (FK: filing_jobs)
5. **extracted_data_items** - Extracted financial data (FK: pages, taxonomy)

### Key Features

- **pgvector Extension**: Required for semantic search (1752-dimensional embeddings)
- **Foreign Keys**: Cascade deletes to maintain referential integrity
- **Indexes**: Optimized for common query patterns
- **Text Fields**: Use TEXT type for unlimited length (values, warnings, HTML)

## Shipping to New Machines

When deploying to a new machine:

1. Install PostgreSQL with pgvector extension
2. Create the database
3. Set DATABASE_URL in .env
4. Run: `python db_init.py --apply`
5. The app will auto-populate template data on first startup

## Troubleshooting

### pgvector Not Found

If you see "extension vector does not exist":

```bash
# Install pgvector extension
# See: https://github.com/pgvector/pgvector

# On Ubuntu/Debian:
sudo apt install postgresql-16-pgvector

# On Windows, use pgvector binaries or Docker
```

### Missing Columns

If the app crashes with "column does not exist":

```bash
python db_init.py          # Check what's missing
python db_init.py --apply  # Apply missing migrations
```

### Data Integrity Issues

```bash
python db_init.py --validate
```

This checks for:
- Orphaned pages (pages without jobs)
- Orphaned items (items without pages)
- Invalid tag references
