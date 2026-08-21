from pathlib import Path
import re
from typing import BinaryIO
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from config import settings

PDF_MAGIC = b"%PDF-"
READ_CHUNK_SIZE = 1024 * 1024
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def uploads_root() -> Path:
    return Path(settings.upload_directory).resolve()


def resolve_upload_path(path: str, subdirectory: str) -> Path:
    """Resolve a runtime artifact path under an expected uploads subdirectory."""
    allowed_root = (uploads_root() / subdirectory).resolve()
    requested_path = Path(path).resolve()

    if allowed_root != requested_path and allowed_root not in requested_path.parents:
        raise HTTPException(status_code=404, detail="File not found")

    if not requested_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return requested_path


def assert_upload_child(path: str, subdirectory: str) -> Path:
    """Resolve a path under uploads without requiring it to exist."""
    allowed_root = (uploads_root() / subdirectory).resolve()
    requested_path = Path(path).resolve()

    if allowed_root != requested_path and allowed_root not in requested_path.parents:
        raise ValueError("Path is outside the expected uploads directory")

    return requested_path


def build_upload_pdf_path() -> Path:
    upload_dir = (uploads_root() / "pdfs").resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"{uuid4().hex}.pdf"


def safe_filename_component(value: object, fallback: str = "file") -> str:
    cleaned = SAFE_FILENAME_RE.sub("_", str(value or "").strip()).strip("._")
    return cleaned or fallback


def validate_pdf_upload_metadata(file: UploadFile) -> None:
    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    content_type = (file.content_type or "").lower()
    if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")


def _read_initial_pdf_bytes(source: BinaryIO) -> bytes:
    position = source.tell() if source.seekable() else None
    header = source.read(len(PDF_MAGIC))
    if position is not None:
        source.seek(position)
    return header


def save_bounded_pdf_upload(file: UploadFile, destination: Path) -> int:
    source = file.file
    header = _read_initial_pdf_bytes(source)
    if header != PDF_MAGIC:
        raise HTTPException(status_code=400, detail="Invalid PDF file")

    max_size = settings.max_file_size
    total_size = 0

    try:
        source.seek(0)
    except Exception:
        pass

    with destination.open("wb") as buffer:
        while True:
            chunk = source.read(READ_CHUNK_SIZE)
            if not chunk:
                break

            total_size += len(chunk)
            if total_size > max_size:
                raise HTTPException(status_code=400, detail="File size exceeds maximum limit")

            buffer.write(chunk)

    return total_size
