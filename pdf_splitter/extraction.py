"""Per-page text/layout extraction, with automatic OCR fallback for scanned pages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pdfplumber


@dataclass
class LineInfo:
    text: str
    size: float  # font size (native) or approximate glyph height in px (OCR)
    top: float   # distance from top of page, same unit as page height


@dataclass
class PageData:
    index: int  # 0-based
    text: str
    header_text: str
    footer_text: str
    is_scanned: bool
    lines: List[LineInfo] = field(default_factory=list)  # lines in top ~35% of page, size desc later
    page_height: float = 0.0
    page_width: float = 0.0

    @property
    def page_number_1based(self) -> int:
        return self.index + 1


_LINE_TOP_TOLERANCE = 3.0  # px/pt tolerance for grouping chars into the same line
_HEADING_ZONE_FRACTION = 0.35  # only consider lines in the top X% of the page as heading candidates


def _group_chars_into_lines(chars: list) -> List[LineInfo]:
    if not chars:
        return []
    chars = sorted(chars, key=lambda c: (round(c["top"] / _LINE_TOP_TOLERANCE), c["x0"]))
    lines: List[LineInfo] = []
    current_top = None
    buf_text: List[str] = []
    buf_sizes: List[float] = []
    for c in chars:
        if current_top is None or abs(c["top"] - current_top) > _LINE_TOP_TOLERANCE:
            if buf_text:
                lines.append(LineInfo("".join(buf_text).strip(), sum(buf_sizes) / len(buf_sizes), current_top))
            current_top = c["top"]
            buf_text = [c["text"]]
            buf_sizes = [c["size"]]
        else:
            buf_text.append(c["text"])
            buf_sizes.append(c["size"])
    if buf_text:
        lines.append(LineInfo("".join(buf_text).strip(), sum(buf_sizes) / len(buf_sizes), current_top))
    return [l for l in lines if l.text]


def _group_ocr_words_into_lines(ocr_data: dict) -> List[LineInfo]:
    groups = {}
    n = len(ocr_data.get("text", []))
    for i in range(n):
        word = ocr_data["text"][i].strip()
        if not word:
            continue
        key = (ocr_data["block_num"][i], ocr_data["par_num"][i], ocr_data["line_num"][i])
        groups.setdefault(key, []).append(i)

    lines: List[LineInfo] = []
    for idxs in groups.values():
        words = [ocr_data["text"][i] for i in idxs]
        tops = [ocr_data["top"][i] for i in idxs]
        heights = [ocr_data["height"][i] for i in idxs]
        lines.append(LineInfo(" ".join(words).strip(), sum(heights) / len(heights), min(tops)))
    lines.sort(key=lambda l: l.top)
    return [l for l in lines if l.text]


def _filter_running_lines(lines: List[LineInfo]) -> List[LineInfo]:
    """Drop outsized lines (e.g. a title bleeding into the header/footer zone) so the
    fingerprint reflects only the small, uniformly-sized running header/footer text."""
    if len(lines) <= 1:
        return lines
    min_size = min(l.size for l in lines)
    return [l for l in lines if l.size <= min_size * 1.3]


def _extract_native_page(page: "pdfplumber.page.Page", header_frac: float, footer_frac: float) -> Tuple[str, str, str, List[LineInfo]]:
    full_text = page.extract_text() or ""
    height = page.height
    width = page.width

    all_lines = sorted(_group_chars_into_lines(page.chars), key=lambda l: l.top)

    header_lines = _filter_running_lines([l for l in all_lines if l.top < height * header_frac])
    footer_lines = _filter_running_lines([l for l in all_lines if l.top > height * (1 - footer_frac)])
    header_text = "\n".join(l.text for l in header_lines).strip()
    footer_text = "\n".join(l.text for l in footer_lines).strip()

    heading_zone_lines = [l for l in all_lines if l.top < height * _HEADING_ZONE_FRACTION]
    heading_zone_lines.sort(key=lambda l: (-l.size, l.top))
    return full_text, header_text, footer_text, heading_zone_lines


def _extract_scanned_page(pdf_path: str, page_number_1based: int, dpi: int, ocr_lang: str,
                           header_frac: float, footer_frac: float) -> Tuple[str, str, str, List[LineInfo], float, float]:
    try:
        from pdf2image import convert_from_path
        import pytesseract
        from pytesseract import Output
    except ImportError as e:
        raise RuntimeError(
            "OCR dependencies missing. Install with: pip install pdf2image pytesseract Pillow "
            "and ensure the Poppler and Tesseract binaries are installed and on PATH."
        ) from e

    try:
        images = convert_from_path(pdf_path, dpi=dpi, first_page=page_number_1based, last_page=page_number_1based)
        image = images[0]
        width, height = image.size

        full_text = pytesseract.image_to_string(image, lang=ocr_lang) or ""
        data = pytesseract.image_to_data(image, lang=ocr_lang, output_type=Output.DICT)
    except Exception as e:
        raise RuntimeError(
            f"Page {page_number_1based} has no embedded text layer and needs OCR, but the "
            "Poppler and/or Tesseract binaries could not be run. Install Poppler "
            "(https://github.com/oschwartz10612/poppler-windows/releases) and Tesseract "
            "(https://github.com/UB-Mannheim/tesseract/wiki) and ensure both are on PATH, "
            f"then retry. Underlying error: {e}"
        ) from e
    lines = _group_ocr_words_into_lines(data)

    header_lines = _filter_running_lines([l for l in lines if l.top < height * header_frac])
    footer_lines = _filter_running_lines([l for l in lines if l.top > height * (1 - footer_frac)])
    header_text = " ".join(l.text for l in header_lines).strip()
    footer_text = " ".join(l.text for l in footer_lines).strip()

    heading_zone_lines = [l for l in lines if l.top < height * _HEADING_ZONE_FRACTION]
    heading_zone_lines.sort(key=lambda l: (-l.size, l.top))
    return full_text, header_text, footer_text, heading_zone_lines, float(width), float(height)


def extract_pages(
    pdf_path: str,
    header_frac: float = 0.12,
    footer_frac: float = 0.12,
    ocr_lang: str = "eng",
    dpi: int = 200,
    min_text_chars: int = 20,
    force_ocr: bool = False,
    progress_callback=None,
) -> List[PageData]:
    """Extract text/layout info for every page, OCR'ing pages with no usable text layer."""
    pages: List[PageData] = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            full_text, header_text, footer_text, lines = _extract_native_page(page, header_frac, footer_frac)
            is_scanned = force_ocr or len(full_text.strip()) < min_text_chars

            if is_scanned:
                full_text, header_text, footer_text, lines, w, h = _extract_scanned_page(
                    pdf_path, i + 1, dpi, ocr_lang, header_frac, footer_frac
                )
            else:
                w, h = page.width, page.height

            pages.append(PageData(
                index=i,
                text=full_text,
                header_text=header_text,
                footer_text=footer_text,
                is_scanned=is_scanned,
                lines=lines,
                page_width=w,
                page_height=h,
            ))
            if progress_callback:
                progress_callback(i + 1, total, is_scanned)
    return pages
