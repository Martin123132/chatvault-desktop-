from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

try:
    from PyPDF2 import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore

from .chatvault_db import add_message, create_conversation

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt"}


@dataclass
class DocumentImportStats:
    files_imported: int = 0
    chunks_imported: int = 0
    skipped_files: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "files_imported": self.files_imported,
            "chunks_imported": self.chunks_imported,
            "skipped_files": self.skipped_files,
        }


def _iter_documents(path: Path, recursive: bool) -> Iterable[Path]:
    if path.is_file():
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path
        return

    pattern = "**/*" if recursive else "*"
    for candidate in sorted(path.glob(pattern)):
        if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield candidate


def _read_pdf(path: Path) -> List[tuple[str, str]]:
    if PdfReader is None:
        raise RuntimeError("PyPDF2 is not installed; PDF import is unavailable.")

    pages: List[tuple[str, str]] = []
    with path.open("rb") as handle:
        reader = PdfReader(handle)
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append((text, f"page {index}"))
    return pages


def _read_text(path: Path) -> List[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []
    return [(text, "full document")]


def _chunk_text(text: str, size: int, overlap: int) -> List[str]:
    words = text.split()
    if not words:
        return []

    chunks: List[str] = []
    start = 0
    step = max(1, size - overlap)
    while start < len(words):
        chunk = " ".join(words[start : start + size]).strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def import_documents(
    con,
    source_path: str,
    recursive: bool = True,
    chunk_size_words: int = 260,
    chunk_overlap_words: int = 40,
    embed: bool = True,
) -> dict[str, int]:
    root = Path(source_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")

    stats = DocumentImportStats()

    for file_path in _iter_documents(root, recursive=recursive):
        loader = _read_pdf if file_path.suffix.lower() == ".pdf" else _read_text
        try:
            sections = loader(file_path)
        except Exception:
            stats.skipped_files += 1
            continue

        if not sections:
            stats.skipped_files += 1
            continue

        conversation_id = create_conversation(
            con,
            source="document_import",
            title=file_path.name,
            external_id=None,
            created_at=None,
            provider="local_docs",
        )

        add_message(
            con=con,
            conversation_id=conversation_id,
            source="document_import",
            role="system",
            content=f"Document imported from {file_path}",
            meta={"document_path": str(file_path)},
            create_embedding=False,
        )

        imported_chunks = 0
        for section_text, section_label in sections:
            chunks = _chunk_text(section_text, size=chunk_size_words, overlap=chunk_overlap_words)
            for chunk_idx, chunk_text in enumerate(chunks, start=1):
                add_message(
                    con=con,
                    conversation_id=conversation_id,
                    source="document_import",
                    role="assistant",
                    content=chunk_text,
                    meta={
                        "document_path": str(file_path),
                        "section": section_label,
                        "chunk_index": chunk_idx,
                        "chunk_size_words": chunk_size_words,
                    },
                    create_embedding=embed,
                )
                imported_chunks += 1

        if imported_chunks == 0:
            stats.skipped_files += 1
            continue

        stats.files_imported += 1
        stats.chunks_imported += imported_chunks

    return stats.as_dict()
