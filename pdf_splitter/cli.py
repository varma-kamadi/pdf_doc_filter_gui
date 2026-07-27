"""Command-line interface for the PDF splitter."""

from __future__ import annotations

import argparse
import json
import sys

from .boundary import apply_manual_boundaries, detect_boundaries
from .diagnostics import environment_report, write_debug_report
from .extraction import extract_pages
from .splitter import split_pdf


def _parse_boundaries(raw: str):
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf_splitter",
        description="Split a merged PDF (native or scanned) into separate documents "
                    "using page-number series, titles/headings, and header/footer detection.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser):
        p.add_argument("input_pdf", help="Path to the merged input PDF")
        p.add_argument("--header-frac", type=float, default=0.12,
                        help="Fraction of page height treated as the header zone (default 0.12)")
        p.add_argument("--footer-frac", type=float, default=0.12,
                        help="Fraction of page height treated as the footer zone (default 0.12)")
        p.add_argument("--min-score", type=int, default=6,
                        help="Minimum evidence score to declare a new document boundary (default 6). "
                             "A single weak signal (e.g. just a header/footer change) scores 1-2 and is "
                             "common noise in dense/table-heavy layouts; real boundaries usually combine "
                             "signals and score 7-8. Lower to 2-4 only for simple/clean merged PDFs if the "
                             "default under-splits.")
        p.add_argument("--min-text-chars", type=int, default=20,
                        help="Pages with less extracted text than this are treated as scanned and OCR'd")
        p.add_argument("--dpi", type=int, default=200, help="Rasterization DPI for OCR (default 200)")
        p.add_argument("--lang", default="eng", help="Tesseract OCR language code (default eng)")
        p.add_argument("--force-ocr", action="store_true",
                        help="Run OCR on every page instead of only pages lacking a text layer")
        p.add_argument("--boundaries", default=None,
                        help="Comma-separated 1-based page numbers where new documents start; "
                             "bypasses automatic detection entirely")
        p.add_argument("--json-report", default=None, help="Write the detection/manifest report to this JSON path")

    p_analyze = sub.add_parser("analyze", help="Detect document boundaries without writing any files (dry run)")
    add_common(p_analyze)

    p_split = sub.add_parser("split", help="Detect boundaries and write each document to its own PDF")
    add_common(p_split)
    p_split.add_argument("--outdir", required=True, help="Directory to write split PDFs and manifest.json into")

    sub.add_parser("envreport", help="Write a report of this machine's Python/package/OCR-binary versions "
                                       "to a text file, e.g. to compare setups across Windows/macOS/Linux")

    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "envreport":
        path = write_debug_report()
        print(environment_report())
        print(f"\nSaved to: {path}")
        return 0

    try:
        return _run(args)
    except Exception as e:
        report_path = write_debug_report(e, outdir=getattr(args, "outdir", None))
        print(f"\nError: {e}", file=sys.stderr)
        print(f"A debug report (environment + full traceback) was saved to:\n  {report_path}", file=sys.stderr)
        print("Share that file if you need help troubleshooting this.", file=sys.stderr)
        return 1


def _run(args) -> int:
    print(f"Reading {args.input_pdf} ...")

    def progress(done, total, was_scanned):
        tag = "OCR" if was_scanned else "text"
        print(f"  page {done}/{total} [{tag}]", end="\r")

    pages = extract_pages(
        args.input_pdf,
        header_frac=args.header_frac,
        footer_frac=args.footer_frac,
        ocr_lang=args.lang,
        dpi=args.dpi,
        min_text_chars=args.min_text_chars,
        force_ocr=args.force_ocr,
        progress_callback=progress,
    )
    print()

    ocr_count = sum(1 for p in pages if p.is_scanned)

    if args.boundaries:
        decisions = apply_manual_boundaries(pages, _parse_boundaries(args.boundaries))
    else:
        decisions = detect_boundaries(pages, min_score=args.min_score)

    report_lines = []
    report_lines.append(f"Detected {len(decisions)} document(s) across {len(pages)} page(s) "
                         f"({ocr_count} page(s) required OCR).")
    for i, d in enumerate(decisions, start=1):
        title = d.title or "(no title detected)"
        report_lines.append(f"[{i:02d}] pages {d.start_page_1based}-{d.end_page_1based} "
                             f"({d.page_count} pg, score {d.score}) - {title}")
        for reason in d.reasons:
            report_lines.append(f"       reason: {reason}")
    print("\n".join(report_lines))

    manifest = None
    if args.command == "split":
        manifest = split_pdf(args.input_pdf, decisions, args.outdir)
        print(f"\nWrote {len(manifest)} file(s) to {args.outdir}")

    if args.json_report:
        payload = {
            "input_pdf": args.input_pdf,
            "total_pages": len(pages),
            "ocr_pages": ocr_count,
            "documents": manifest if manifest is not None else [
                {
                    "index": i,
                    "title": d.title,
                    "start_page": d.start_page_1based,
                    "end_page": d.end_page_1based,
                    "page_count": d.page_count,
                    "detection_score": d.score,
                    "reasons": d.reasons,
                }
                for i, d in enumerate(decisions, start=1)
            ],
        }
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Wrote report to {args.json_report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
