"""Writes each detected document group out as its own PDF file plus a manifest."""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from pypdf import PdfReader, PdfWriter

from .boundary import BoundaryDecision

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DATE_PREFIX_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{2})\b")


def slugify(text: str, max_len: int = 60) -> str:
    text = (text or "").lower()
    text = _SLUG_RE.sub("_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text[:max_len].strip("_") or "untitled"


def sanitize_filename_part(text: str, max_len: int = 80) -> str:
    """Make a title safe to use in a Windows filename while keeping it human-readable
    (unlike slugify, this preserves case, spaces, and punctuation)."""
    text = _INVALID_FILENAME_CHARS_RE.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len].strip() or "Untitled"


def _extract_date_prefix(input_path: str) -> Optional[str]:
    """Pull a leading yy.mm.dd date off the source filename, e.g. '25.12.03 - Notice.pdf'."""
    base = os.path.splitext(os.path.basename(input_path))[0]
    m = _DATE_PREFIX_RE.match(base.strip())
    return m.group(1) if m else None


def split_pdf(input_path: str, decisions: List[BoundaryDecision], outdir: str) -> List[dict]:
    os.makedirs(outdir, exist_ok=True)
    reader = PdfReader(input_path)
    date_prefix = _extract_date_prefix(input_path)

    manifest = []
    used_filenames = set()
    for i, d in enumerate(decisions, start=1):
        writer = PdfWriter()
        for p in range(d.start_index, d.end_index + 1):
            writer.add_page(reader.pages[p])

        title = sanitize_filename_part(d.title) if d.title else f"Document {i}"
        page_part = (f"p{d.start_page_1based}"
                     if d.start_page_1based == d.end_page_1based
                     else f"p{d.start_page_1based}-{d.end_page_1based}")
        prefix = f"{date_prefix} - " if date_prefix else ""
        base_filename = f"{prefix}{title} ({page_part})"

        filename = f"{base_filename}.pdf"
        suffix = 2
        while filename in used_filenames:
            filename = f"{base_filename} ({suffix}).pdf"
            suffix += 1
        used_filenames.add(filename)

        out_path = os.path.join(outdir, filename)
        with open(out_path, "wb") as f:
            writer.write(f)

        manifest.append({
            "index": i,
            "output_file": filename,
            "title": d.title,
            "start_page": d.start_page_1based,
            "end_page": d.end_page_1based,
            "page_count": d.page_count,
            "detection_score": d.score,
            "reasons": d.reasons,
        })

    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return manifest
