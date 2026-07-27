"""Simple cross-platform GUI for the PDF splitter (Tkinter, ships with Python
on Windows/macOS and most Linux distros). Lets you pick the merged PDF, pick
an output directory, set --min-score, and runs main.py split as a subprocess."""

from __future__ import annotations

import os
import queue
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_PY = os.path.join(SCRIPT_DIR, "main.py")


class PdfSplitterGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Splitter")
        self.geometry("720x520")
        self.minsize(560, 380)

        self.pdf_path = tk.StringVar()
        self.outdir_path = tk.StringVar()
        self.min_score = tk.StringVar(value="6")

        self._log_queue: "queue.Queue[str | None]" = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_widgets()
        self.after(100, self._poll_log_queue)

    def _build_widgets(self):
        form = ttk.Frame(self, padding=10)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="PDF file:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.pdf_path).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="Browse...", command=self._choose_pdf).grid(row=0, column=2)

        ttk.Label(form, text="Output directory:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.outdir_path).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="Browse...", command=self._choose_outdir).grid(row=1, column=2)

        ttk.Label(form, text="Min score:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=0, to=20, textvariable=self.min_score, width=8).grid(row=2, column=1, sticky="w", padx=6)

        self.run_button = ttk.Button(self, text="Split PDF", command=self._on_run_clicked)
        self.run_button.pack(pady=8)

        self.log = scrolledtext.ScrolledText(self, state="disabled", height=20, wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _choose_pdf(self):
        path = filedialog.askopenfilename(
            title="Select merged PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.pdf_path.set(path)
            if not self.outdir_path.get():
                self.outdir_path.set(os.path.join(os.path.dirname(path), "out"))

    def _choose_outdir(self):
        path = filedialog.askdirectory(title="Select output directory")
        if path:
            self.outdir_path.set(path)

    def _append_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                line = self._log_queue.get_nowait()
                if line is None:
                    self.run_button.configure(state="normal")
                else:
                    self._append_log(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _on_run_clicked(self):
        pdf_path = self.pdf_path.get().strip()
        outdir = self.outdir_path.get().strip()
        min_score = self.min_score.get().strip()

        if not pdf_path:
            messagebox.showerror("Missing input", "Please select a PDF file.")
            return
        if not os.path.isfile(pdf_path):
            messagebox.showerror("Invalid input", f"PDF file not found:\n{pdf_path}")
            return
        if not outdir:
            messagebox.showerror("Missing input", "Please choose an output directory.")
            return
        if not min_score.isdigit():
            messagebox.showerror("Invalid input", "Min score must be a whole number.")
            return

        cmd = [sys.executable, MAIN_PY, "split", pdf_path, "--outdir", outdir, "--min-score", min_score]

        self._append_log(f"$ {shlex.join(cmd)}\n\n")
        self.run_button.configure(state="disabled")
        self._worker = threading.Thread(target=self._run_command, args=(cmd,), daemon=True)
        self._worker.start()

    def _run_command(self, cmd: list[str]):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            for line in process.stdout:
                self._log_queue.put(line)
            process.wait()
            self._log_queue.put(f"\nExit code: {process.returncode}\n")
        except Exception as e:
            self._log_queue.put(f"\nError launching process: {e}\n")
        finally:
            self._log_queue.put(None)


def main():
    app = PdfSplitterGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
