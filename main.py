#!/usr/bin/env python
"""Standalone entry point: python main.py {analyze|split} input.pdf [options]"""

import sys

from pdf_splitter.cli import main

if __name__ == "__main__":
    sys.exit(main())
