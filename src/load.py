"""
load.py
-------
Data Loading step of the referral program pipeline.

Reads all 7 raw source CSVs (paths defined in config.RAW_FILES) into
pandas DataFrames and returns them as a single dict, keyed by table name,
so downstream steps (clean.py, transform.py) can iterate over sources
generically instead of importing each DataFrame individually.

Kept deliberately simple per the spec's own skeleton ("# Data Loading:
Load all CSV files into DataFrames.") — no cleaning or transformation
logic lives here. This step's only job is: does every expected file
exist, and can it be read.
"""

import sys
from pathlib import Path
import pandas as pd
import config


def load_all_tables() -> dict[str, pd.DataFrame]:
    """
    Load every raw source CSV listed in config.RAW_FILES into a DataFrame.

    Returns:
        dict mapping table_name -> DataFrame, e.g.
        {
            "lead_logs": <DataFrame>,
            "user_referrals": <DataFrame>,
            ...
        }

    Raises:
        FileNotFoundError: if any expected raw file is missing, with a
            clear message naming which table/file is missing (fail fast,
            rather than letting a later join silently produce wrong results).
    """
    tables: dict[str, pd.DataFrame] = {}
    missing_files = []

    for table_name, file_path in config.RAW_FILES.items():
        if not file_path.exists():
            missing_files.append((table_name, file_path))
            continue

        df = pd.read_csv(file_path)
        tables[table_name] = df
        print(f"[LOAD] {table_name:<25} <- {file_path.name:<30} ({len(df)} rows, {len(df.columns)} cols)")

    if missing_files:
        details = "\n".join(f"  - {name}: expected at {path}" for name, path in missing_files)
        raise FileNotFoundError(
            f"Missing {len(missing_files)} raw source file(s):\n{details}\n"
            f"Check config.RAW_FILES and confirm the CSVs are in {config.RAW_DATA_DIR}"
        )

    return tables


if __name__ == "__main__":
    # Running this file directly loads all tables and prints a summary —
    # useful as a quick smoke test that every source file is present and
    # readable before moving on to clean.py.
    print(f"[INFO] Loading raw tables from: {config.RAW_DATA_DIR}\n")

    tables = load_all_tables()

    print(f"\n[INFO] Successfully loaded {len(tables)}/{len(config.RAW_FILES)} tables.")
    total_rows = sum(len(df) for df in tables.values())
    print(f"[INFO] Total rows across all tables: {total_rows}")