"""Environment/error diagnostics: writes a self-contained debug report file when
something goes wrong (or on request), so a failure on another machine/OS can be
shared as-is for troubleshooting without back-and-forth on what's installed."""

from __future__ import annotations

import datetime
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import traceback
from typing import Optional

_PACKAGES = ("pypdf", "pdfplumber", "pdf2image", "pytesseract", "Pillow")
_BINARIES = {"tesseract": "--version", "pdftoppm": "-v"}


def _package_versions() -> list[str]:
    lines = []
    for pkg in _PACKAGES:
        try:
            version = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            version = "NOT INSTALLED"
        lines.append(f"  {pkg}: {version}")
    return lines


def _binary_versions() -> list[str]:
    lines = []
    for binary, flag in _BINARIES.items():
        path = shutil.which(binary)
        if not path:
            lines.append(f"  {binary}: NOT FOUND on PATH")
            continue
        try:
            result = subprocess.run([binary, flag], capture_output=True, text=True, timeout=5)
            output = (result.stdout or result.stderr or "").strip().splitlines()
            version_line = output[0] if output else "(no version output)"
        except Exception as e:
            version_line = f"found but failed to run: {e}"
        lines.append(f"  {binary}: {path}  [{version_line}]")
    return lines


def environment_report() -> str:
    lines = [
        f"Timestamp: {datetime.datetime.now().isoformat()}",
        f"Command: {' '.join(sys.argv)}",
        f"Platform: {platform.platform()}",
        f"Python: {sys.version.splitlines()[0]}",
        f"Executable: {sys.executable}",
        "",
        "Package versions:",
        *_package_versions(),
        "",
        "External OCR binaries:",
        *_binary_versions(),
    ]
    return "\n".join(lines)


def write_debug_report(error: Optional[BaseException] = None, outdir: Optional[str] = None) -> str:
    """Write environment info (plus a full traceback, if an error is given) to a text
    file next to the output directory (or the current directory) and return its path."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = outdir if outdir and os.path.isdir(outdir) else os.getcwd()
    path = os.path.join(target_dir, f"pdf_splitter_debug_{ts}.txt")

    content = environment_report()
    if error is not None:
        content += "\n\nTraceback:\n"
        content += "".join(traceback.format_exception(type(error), error, error.__traceback__))

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
