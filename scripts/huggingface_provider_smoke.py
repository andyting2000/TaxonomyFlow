import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path
from typing import Optional

from huggingface_hub import AsyncInferenceClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from scripts.generate_huggingface_embeddings import huggingface_embeddings


PLACEHOLDER_TOKENS = {"", "replace-with-your-model-provider-token", "YOUR_MODEL_API_TOKEN_HERE"}


def configured_token() -> str:
    return (settings.model_api_token or settings.hugging_face_token or "").strip()


async def text_smoke() -> dict:
    token = configured_token()
    if token in PLACEHOLDER_TOKENS:
        return {"ok": False, "provider": "huggingface", "operation": "text", "error": "MODEL_API_TOKEN is not configured.", "model": settings.ai_text_model_id}
    client = AsyncInferenceClient(model=settings.ai_text_model_id, token=token)
    response = await client.chat_completion(
        messages=[{"role": "user", "content": "Reply with a short JSON object: {\"ok\": true}"}],
        max_tokens=120,
        temperature=0.1,
    )
    return {"ok": True, "provider": "huggingface", "operation": "text", "model": settings.ai_text_model_id, "output_text": response.choices[0].message.content}


async def vision_smoke(image_path: str) -> dict:
    token = configured_token()
    path = Path(image_path)
    if not path.exists():
        return {"ok": False, "provider": "huggingface", "operation": "vision", "error": f"Image file does not exist: {image_path}", "model": settings.ai_vlm_model_id}
    if token in PLACEHOLDER_TOKENS:
        return {"ok": False, "provider": "huggingface", "operation": "vision", "error": "MODEL_API_TOKEN is not configured.", "model": settings.ai_vlm_model_id}
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    client = AsyncInferenceClient(model=settings.ai_vlm_model_id, token=token)
    response = await client.chat_completion(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Return a short JSON description of this financial statement page."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ],
            }
        ],
        max_tokens=240,
        temperature=0.1,
    )
    return {"ok": True, "provider": "huggingface", "operation": "vision", "model": settings.ai_vlm_model_id, "output_text": response.choices[0].message.content}


async def embedding_smoke(text: str) -> dict:
    result = await huggingface_embeddings(text)
    return {key: value for key, value in result.items() if key != "embeddings"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run optional live Hugging Face provider smokes.")
    parser.add_argument("--text", action="store_true")
    parser.add_argument("--vision")
    parser.add_argument("--embedding")
    return parser


async def async_main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    selected = bool(args.text or args.vision or args.embedding)
    if not selected:
        print("Select at least one smoke: --text, --vision <image_path>, or --embedding \"text\"")
        return 2

    results = []
    if args.text:
        results.append(await text_smoke())
    if args.vision:
        results.append(await vision_smoke(args.vision))
    if args.embedding:
        results.append(await embedding_smoke(args.embedding))
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if all(result.get("ok") for result in results) else 1


def main(argv: Optional[list[str]] = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
