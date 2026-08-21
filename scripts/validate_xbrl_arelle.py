import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.arelle_validator import DEFAULT_TIMEOUT_SECONDS, local_schema_ref_remaps, validate_with_arelle


DEFAULT_TAXONOMY_ENTRYPOINT = (
    ROOT_DIR
    / "taxonomy"
    / "SSMxT_2022v1.0"
    / "rep"
    / "ssm"
    / "ca-2016"
    / "fs"
    / "mpers"
    / "ssmt-fs-mpers_2022-12-31_entry_point.xsd"
)


VALIDATION_MODE_ARGS = {
    "full": [],
    "no_formula": ["--formula", "none"],
    "instance_focused": [
        "--formula",
        "none",
        "--calc",
        "none",
        "--baseTaxonomyValidation",
        "none",
    ],
    "skip_formula_table": [
        "--formula",
        "none",
        "--calc",
        "none",
        "--baseTaxonomyValidation",
        "none",
        "--skipLoading",
        "*formula_ssmt-fs-mpers_2022-12-31.xml|*table_ssmt-fs-mpers_2022-12-31*.xml",
    ],
    "instance_baseline": [
        "--formula",
        "none",
        "--calc",
        "none",
        "--baseTaxonomyValidation",
        "none",
        "--skipLoading",
        "*formula_ssmt-fs-mpers_2022-12-31.xml|*table_ssmt-fs-mpers_2022-12-31*.xml|*existence_function_2022-12-31.xml",
    ],
}


def _error_result(message: str, instance_path: str, taxonomy_entrypoint: str) -> dict:
    return {
        "is_valid": False,
        "errors": [message],
        "warnings": [],
        "raw_output": "",
        "return_code": None,
        "duration_ms": 0,
        "instance_path": instance_path,
        "taxonomy_entrypoint": taxonomy_entrypoint,
        "command_used": "",
        "original_instance_path": instance_path or None,
        "validation_instance_path": instance_path or None,
        "schema_ref_remaps": [],
        "validation_mode": "full",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a generated XBRL instance with Arelle and print structured JSON."
    )
    parser.add_argument("--instance", help="Path to an existing generated XBRL instance.")
    parser.add_argument(
        "--taxonomy-entrypoint",
        default=str(DEFAULT_TAXONOMY_ENTRYPOINT),
        help="Local taxonomy entrypoint XSD path.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Arelle subprocess timeout in seconds.",
    )
    parser.add_argument(
        "--local-schema-ref-copy-dir",
        help="Optional directory for a validation-only copy with the remote FS-MPERS schemaRef remapped to the local taxonomy entrypoint.",
    )
    parser.add_argument(
        "--validation-mode",
        choices=sorted(VALIDATION_MODE_ARGS),
        default="full",
        help="Controlled Arelle validation mode for local experiments.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    taxonomy_entrypoint = str(Path(args.taxonomy_entrypoint))

    if not args.instance:
        result = _error_result("--instance is required", "", taxonomy_entrypoint)
    elif not Path(args.instance).exists():
        result = _error_result(
            f"Instance file does not exist: {args.instance}",
            args.instance,
            taxonomy_entrypoint,
        )
    else:
        result = validate_with_arelle(
            instance_path=args.instance,
            taxonomy_entrypoint=taxonomy_entrypoint,
            timeout_seconds=args.timeout,
            extra_args=VALIDATION_MODE_ARGS[args.validation_mode],
            validation_mode=args.validation_mode,
            schema_ref_remaps=local_schema_ref_remaps(taxonomy_entrypoint)
            if args.local_schema_ref_copy_dir
            else None,
            validation_copy_dir=args.local_schema_ref_copy_dir,
        ).to_dict()

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
