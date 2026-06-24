#!/usr/bin/env python3
"""Runnable entry point for the ncrypted CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ncrypted_cli.cli import run  # noqa: E402

if __name__ == "__main__":
    run()
