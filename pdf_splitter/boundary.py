"""Heuristics to detect where one source document ends and the next begins
inside a merged PDF: page-number series resets, distinctive titles/headings,
and header/footer fingerprint changes."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

from .extraction import PageData, LineInfo

_DIGITS_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")

_PAGE_OF_RE = re.compile(r"page\s+(\d+)\s+of\s+(\d+)", re.I)
_SLASH_RE = re.compile(r"\b(\d{1,4})\s*/\s*(\d{1,4})\b")
_STANDALONE_RE = re.compile(r"^-?\s*(\d{1,4})\s*-?$")


@dataclass
class BoundaryDecision:
    start_index: int  # 0-based first page of this document
    end_index: int  # 0-based last page (inclusive)
    title: Optional[str]
    reasons: List[str] = field(default_factory=list)
    score: int = 0

    @property
    def start_page_1based(self) -> int:
        return self.start_index + 1

    @property
    def end_page_1based(self) -> int:
        return self.end_index + 1

    @property
    def page_count(self) -> int:
        return self.end_index - self.start_index + 1


def normalize_fingerprint(text: str) -> str:
    t = (text or "").lower()
    t = _DIGITS_RE.sub("#", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def extract_page_number(text: str) -> Optional[int]:
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _PAGE_OF_RE.search(line)
        if m:
            return int(m.group(1))
        m = _SLASH_RE.search(line)
        if m:
            return int(m.group(1))
        m = _STANDALONE_RE.match(line)
        if m:
            return int(m.group(1))
    return None


def _best_heading(page: PageData) -> Optional[LineInfo]:
    for line in page.lines:
        text = line.text.strip()
        if len(text) < 3:
            continue
        if text.strip().lower() in (page.header_text.strip().lower(), page.footer_text.strip().lower()):
            continue
        return line
    return None


def _is_distinctive_heading(page: PageData, heading: LineInfo) -> bool:
    sizes = [l.size for l in page.lines if l.size > 0]
    if len(sizes) >= 2:
        median = statistics.median(sizes)
        if heading.size >= median * 1.15:
            return True
    words = heading.text.strip().split()
    if 1 <= len(words) <= 8 and heading.text.strip().isupper():
        return True
    return len(sizes) < 2


_BOILERPLATE_TITLES = {"confidential", "confidential report", "draft", "privileged and confidential"}


def _is_boilerplate_title(text: str) -> bool:
    normalized = re.sub(r"[\*\s]+", " ", text).strip().lower()
    return normalized in _BOILERPLATE_TITLES


def _next_line_after(page: PageData, heading: LineInfo) -> Optional[str]:
    """Find the next line below `heading` at a similar font size — the real subtitle
    when the heading itself turned out to be generic boilerplate (e.g. 'CONFIDENTIAL REPORT')."""
    candidates = sorted((l for l in page.lines if l.top > heading.top), key=lambda l: l.top)
    for line in candidates:
        if line.size >= heading.size * 0.6 and len(line.text.strip()) >= 3:
            return line.text.strip()
    return None


def compute_title(page: PageData) -> Optional[str]:
    heading = _best_heading(page)
    if heading:
        text = heading.text.strip()
        if len(text) >= 3:
            if _is_boilerplate_title(text):
                specific = _next_line_after(page, heading)
                if specific:
                    return specific
            return text
    for raw_line in (page.text or "").splitlines():
        line = raw_line.strip()
        if len(line) >= 3 and not line.isdigit():
            return line
    return None


def _page_score(prev: PageData, cur: PageData) -> tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    fp_cur_header = normalize_fingerprint(cur.header_text)
    fp_prev_header = normalize_fingerprint(prev.header_text)
    fp_cur_footer = normalize_fingerprint(cur.footer_text)
    fp_prev_footer = normalize_fingerprint(prev.footer_text)

    header_changed = bool(fp_cur_header or fp_prev_header) and fp_cur_header != fp_prev_header
    footer_changed = bool(fp_cur_footer or fp_prev_footer) and fp_cur_footer != fp_prev_footer

    if header_changed and footer_changed:
        score += 3
        reasons.append("header and footer both changed")
    elif header_changed or footer_changed:
        score += 2
        reasons.append("header or footer changed")

    cur_num = extract_page_number(cur.header_text + "\n" + cur.footer_text)
    prev_num = extract_page_number(prev.header_text + "\n" + prev.footer_text)
    if cur_num is not None and prev_num is not None:
        if cur_num == 1 and prev_num != 1:
            score += 3
            reasons.append(f"page-number series reset to 1 (was {prev_num})")
        elif cur_num < prev_num:
            score += 2
            reasons.append(f"page number decreased ({prev_num} -> {cur_num})")
        elif cur_num != prev_num + 1:
            score += 1
            reasons.append(f"page number non-sequential ({prev_num} -> {cur_num})")
    elif (cur_num is None) != (prev_num is None):
        score += 2
        reasons.append(f"page-number format changed (numbering {'disappeared' if cur_num is None else 'appeared'})")

    heading = _best_heading(cur)
    if heading and _is_distinctive_heading(cur, heading):
        heading_text = heading.text.strip()
        if heading_text and heading_text.lower() not in (prev.text or "").lower():
            score += 2
            reasons.append(f"distinctive heading: '{heading_text[:60]}'")

    return score, reasons


def detect_boundaries(pages: List[PageData], min_score: int = 2) -> List[BoundaryDecision]:
    """Score every page against its predecessor and group pages into documents."""
    if not pages:
        return []

    boundary_indices = [0]
    boundary_reasons = {0: ["first page of file"]}
    boundary_scores = {0: 99}

    for i in range(1, len(pages)):
        score, reasons = _page_score(pages[i - 1], pages[i])
        if score >= min_score:
            boundary_indices.append(i)
            boundary_reasons[i] = reasons
            boundary_scores[i] = score

    decisions: List[BoundaryDecision] = []
    for idx, start in enumerate(boundary_indices):
        end = (boundary_indices[idx + 1] - 1) if idx + 1 < len(boundary_indices) else len(pages) - 1
        title = compute_title(pages[start])
        decisions.append(BoundaryDecision(
            start_index=start,
            end_index=end,
            title=title,
            reasons=boundary_reasons[start],
            score=boundary_scores[start],
        ))
    return decisions


def apply_manual_boundaries(pages: List[PageData], start_pages_1based: List[int]) -> List[BoundaryDecision]:
    """Bypass heuristics: caller supplies the 1-based page numbers where each document starts."""
    starts = sorted(set(p - 1 for p in start_pages_1based))
    if not starts or starts[0] != 0:
        starts = [0] + starts
    decisions: List[BoundaryDecision] = []
    for idx, start in enumerate(starts):
        end = (starts[idx + 1] - 1) if idx + 1 < len(starts) else len(pages) - 1
        title = compute_title(pages[start])
        decisions.append(BoundaryDecision(
            start_index=start, end_index=end, title=title,
            reasons=["manual override"], score=99,
        ))
    return decisions
