# PDF Splitter

Splits a merged PDF — one file containing several original documents back to
back, possibly including scanned/OCR pages — back into individual PDFs. It
figures out where one document ends and the next begins by combining three
signals:

1. **Page-number series resets** — e.g. footer/header text like
   `Page 3 of 5`, `12 / 40`, or a standalone `- 1 -` restarting or jumping
   backward signals a new document.
2. **Title / heading detection** — a line near the top of the page rendered
   in a noticeably larger font (or short ALL-CAPS text) that doesn't appear
   on the previous page is treated as a new document's title.
3. **Header/footer fingerprinting** — the running header and footer text
   (with page numbers stripped out) is fingerprinted per page; a change in
   fingerprint between consecutive pages is strong evidence of a new source
   document, since headers/footers are normally consistent within one
   document.

Pages with no usable embedded text layer (scanned images) are automatically
OCR'd (Tesseract) so the same three signals can be extracted from them.

## Installation

```bash
pip install -r requirements.txt
```

OCR also needs two external binaries on PATH (only required if your PDFs
contain scanned pages):

- **macOS** (Homebrew): `brew install poppler tesseract`
- **Linux** (Debian/Ubuntu): `sudo apt install poppler-utils tesseract-ocr`
- **Windows**:
  - Tesseract OCR installer: https://github.com/UB-Mannheim/tesseract/wiki
  - Poppler binaries: https://github.com/oschwartz10612/poppler-windows/releases
    (add the extracted `Library/bin` folder to PATH)

The GUI (`gui.py`) uses Tkinter, which ships with Python on Windows and macOS.
On Linux it's sometimes a separate package:

```bash
sudo apt install python3-tk       # Debian/Ubuntu
sudo dnf install python3-tkinter  # Fedora
```

## GUI

```bash
python gui.py
```

Pick the merged PDF, pick (or type) an output directory, set the min score,
and click **Split PDF**. This just runs `main.py split <pdf> --outdir <dir>
--min-score <n>` as a subprocess and streams its output into the log pane —
it's a thin wrapper around the same CLI covered below, not a separate
implementation. There's no "Analyze" button in the GUI; run `python main.py
analyze ...` from a terminal first if you want to check the detected
boundaries before splitting for real.

## Usage (CLI)

On macOS/Linux, use `python3` instead of `python` if your system doesn't alias
`python` to Python 3.

Dry run first — see what it detects without writing any files:

```bash
python main.py analyze merged.pdf
```

Then split for real:

```bash
python main.py split merged.pdf --outdir out/
```

This writes `out/01_<title>_p1-4.pdf`, `out/02_<title>_p5-9.pdf`, ... and
`out/manifest.json` describing every detected document, its page range, the
detected title, and the reasons it was split there.

### Useful options

| Flag | Meaning |
|---|---|
| `--min-score N` | Raise to require stronger evidence before splitting (fewer, more confident splits); lower to split more eagerly. Default `6`. Real boundaries usually combine several signals and score `7-8`; a single weak signal alone (just a header/footer change, or a stray name/signature line) scores `4-5` and is common noise in dense, table-heavy, or report-style documents — the default filters that out. Lower to `2-4` only for very simple/clean merged PDFs if the default is under-splitting. |
| `--header-frac` / `--footer-frac` | Fraction of page height treated as header/footer zone (default `0.12` each). Increase if your headers/footers are tall. |
| `--boundaries "1,6,14"` | Skip detection entirely and split at these 1-based page numbers yourself. |
| `--force-ocr` | OCR every page even if it has an embedded text layer (useful if the text layer is garbled). |
| `--lang deu` | Tesseract language code for non-English scans. |
| `--json-report report.json` | Also write the detection report as JSON. |

Always run `analyze` first on a new batch of documents and check the reasons
listed for each boundary. If it over-splits or under-splits, adjust
`--min-score`, or fall back to `--boundaries` for full manual control.

## How the scoring works

Each page is compared to the page before it and gets points:

- header **and** footer fingerprint both changed: **+3**
- header **or** footer fingerprint changed: **+2**
- page-number series reset to 1: **+3**
- page number decreased (not a reset to 1): **+2**
- page number skipped non-sequentially: **+1**
- page numbering format appeared or disappeared (e.g. "Page X of Y" stops or starts): **+2**
- a distinctively large/bold heading appears that wasn't on the previous page: **+2**

A page becomes a new document's first page once its score reaches
`--min-score` (default `6`). Page 1 of the input is always the start of the
first document.

## Project layout

```
pdf_splitter_app/
├── main.py                 # CLI entry point
├── gui.py                   # Tkinter GUI (file picker, outdir picker, min-score, Split button)
├── requirements.txt
└── pdf_splitter/
    ├── extraction.py        # per-page text/layout extraction + OCR fallback
    ├── boundary.py           # scoring heuristics + boundary grouping
    ├── splitter.py           # writes split PDFs + manifest.json
    └── cli.py                # argparse CLI (analyze / split)
```
