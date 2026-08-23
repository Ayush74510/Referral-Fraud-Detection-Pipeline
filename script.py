#!/usr/bin/env python3
"""
your_script.py
--------------
Entrypoint for the Springer Capital referral program data pipeline.

This file exists at the project root to satisfy the take-home's literal
submission requirement ("The Python script file (your_script.py) should
exist"). The actual pipeline logic lives in src/ as a set of focused,
importable modules (load, clean, transform, fraud_rules, report) — see
each file's docstring for what it does — orchestrated by src/main.py.

Usage:
    python your_script.py

Expects raw CSVs in data/raw/ (see src/config.py for exact filenames).
Writes the final fraud report to data/output/referral_fraud_report.csv.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from src.main import run

if __name__ == "__main__":
    run()