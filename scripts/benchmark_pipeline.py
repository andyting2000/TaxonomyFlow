import argparse
import asyncio
import json
import time
from pathlib import Path
from statistics import mean
from typing import Dict, List

import fitz

from config import settings
from services.smart_ai_processor import SmartAIProcessor


async def benchmark_pdf(processor: SmartAIProcessor, pdf_path: Path) -> Dict:
    started = time.perf_counter()
    doc = fitz.open(pdf_path)
    page_results: List[Dict] = []

    try:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            native_text = processor._extract_page_text(page)

            quality = processor._score_page_quality(
                native_text=native_text
            )
            extraction_text = native_text
            extraction_source = "native_pdf"

            if (
                len(extraction_text) >= settings.extraction_text_min_chars
                and quality['text_route_score'] >= settings.page_quality_min_text_score
                and not quality['force_vlm']
            ):
                recommended_route = 'text_llm'
            elif settings.region_vlm_enabled:
                recommended_route = 'region_vlm'
            else:
                recommended_route = 'whole_page_vlm'

            page_results.append({
                'page_number': page_num + 1,
                'native_chars': len(native_text),
                'text_route_score': round(float(quality['text_route_score']), 4),
                'native_text_score': round(float(quality['native_text_score']), 4),
                'force_vlm': bool(quality['force_vlm']),
                'extraction_source': extraction_source,
                'recommended_route': recommended_route,
            })
    finally:
        doc.close()

    elapsed = time.perf_counter() - started
    text_pages = sum(1 for item in page_results if item['recommended_route'] == 'text_llm')
    region_pages = sum(1 for item in page_results if item['recommended_route'] == 'region_vlm')
    whole_pages = sum(1 for item in page_results if item['recommended_route'] == 'whole_page_vlm')

    return {
        'pdf': str(pdf_path),
        'pages': len(page_results),
        'elapsed_seconds': round(elapsed, 2),
        'avg_text_route_score': round(mean(item['text_route_score'] for item in page_results), 4) if page_results else 0.0,
        'recommended_text_pages': text_pages,
        'recommended_region_vlm_pages': region_pages,
        'recommended_whole_page_vlm_pages': whole_pages,
        'page_results': page_results,
    }


async def main():
    parser = argparse.ArgumentParser(description="Benchmark native-text/VLM routing for a folder of PDFs.")
    parser.add_argument("pdf_dir", help="Directory containing benchmark PDFs")
    parser.add_argument("--limit", type=int, default=20, help="Max PDFs to benchmark")
    parser.add_argument("--output", default="uploads/benchmark_pipeline.json", help="Output JSON file")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))[:args.limit]
    if not pdf_paths:
        raise SystemExit(f"No PDFs found in {pdf_dir}")

    processor = SmartAIProcessor()

    results = []
    for pdf_path in pdf_paths:
        print(f"Benchmarking {pdf_path.name}...")
        results.append(await benchmark_pdf(processor, pdf_path))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    avg_text_score = mean(result['avg_text_route_score'] for result in results)
    print(f"Benchmarked {len(results)} PDFs")
    print(f"Average text-route score: {avg_text_score:.4f}")
    print(f"Saved detailed results to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
