import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.openai_provider import (
    openai_structured_json_smoke,
    openai_text_smoke,
    openai_vision_smoke,
)


DEFAULT_TEXT_PROMPT = "Reply with one short sentence confirming OpenAI text smoke works."
DEFAULT_STRUCTURED_PROMPT = (
    "Classify this document text for a provider smoke test: unaudited financial statements."
)
DEFAULT_IMAGE_PROMPT = (
    "Summarize this filing page image in one or two sentences for an internal provider smoke test."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenAI provider proof-of-life smoke tests. Does not write to the database."
    )
    parser.add_argument("--text", action="store_true", help="Run a text model smoke request.")
    parser.add_argument(
        "--structured-json",
        action="store_true",
        help="Run a structured JSON model smoke request.",
    )
    parser.add_argument(
        "--image",
        metavar="PATH",
        help="Run a vision smoke request against an existing PNG/JPEG/WEBP/GIF image.",
    )
    parser.add_argument(
        "--text-prompt",
        default=DEFAULT_TEXT_PROMPT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--structured-prompt",
        default=DEFAULT_STRUCTURED_PROMPT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--image-prompt",
        default=DEFAULT_IMAGE_PROMPT,
        help=argparse.SUPPRESS,
    )
    return parser


def _print_result(result: Dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def _exit_code(results: Iterable[Dict[str, Any]]) -> int:
    for result in results:
        if not result.get("ok"):
            error_type = result.get("error_type")
            if error_type in {"configuration", "missing_image"}:
                return 2
            return 1
    return 0


def run_smoke(args: argparse.Namespace) -> int:
    results = []

    if args.text:
        results.append(openai_text_smoke(args.text_prompt))

    if args.structured_json:
        results.append(openai_structured_json_smoke(args.structured_prompt))

    if args.image:
        results.append(openai_vision_smoke(args.image, args.image_prompt))

    if not results:
        print("No smoke test selected. Use --text, --structured-json, or --image PATH.")
        return 2

    for result in results:
        _print_result(result)

    return _exit_code(results)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_smoke(args)


if __name__ == "__main__":
    raise SystemExit(main())
