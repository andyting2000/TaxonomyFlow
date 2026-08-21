"""Smoke-test Azure Document Intelligence prebuilt-layout against one PDF."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.azure_document_intelligence_provider import (  # noqa: E402
    AzureDocumentIntelligenceConfigError,
    AzureDocumentIntelligenceProvider,
    format_smoke_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test Azure Document Intelligence layout extraction.")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", help="Optional Azure DI page range, for example 1-2 or 1,3.")
    parser.add_argument("--first-lines", type=int, default=8)
    parser.add_argument("--first-table-rows", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = AzureDocumentIntelligenceProvider().analyze_pdf_path(args.pdf, pages=args.pages)
    except AzureDocumentIntelligenceConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(format_smoke_summary(result, first_lines=args.first_lines, first_table_rows=args.first_table_rows))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
