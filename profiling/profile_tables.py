"""
profile_tables.py
------------------
Data Profiling script for the Referral Program data sources.

Purpose:
    Before any cleaning / joining / fraud-detection logic is written, we need
    to understand the shape and quality of each raw source table. This script
    scans every CSV in `data/raw/` and produces one profile CSV per table
    (written to `profiling/output/`) containing, per column:

        - data_type            : pandas-inferred dtype
        - null_count            : number of missing values
        - null_percentage       : % of rows that are null
        - populated_percentage  : % of rows that are populated (non-null)
        - distinct_value_count  : number of unique values
        - min_value              : minimum value (numeric/date) or None
        - max_value              : maximum value (numeric/date) or None
        - max_actual_length      : longest string length seen in the column
        - sample_values          : a few example values, for a quick eyeball check

    This mirrors the "Example Document" format shown in the take-home spec
    (Column Name, Data Type, Nulls Allowed, Null Count, % Populated,
    Distinct Value Count, Min/Max Value, Max Actual Length).

Usage:
    python profile_tables.py
    python profile_tables.py --raw-dir ../data/raw --out-dir output

Expected source tables (from the business flow spec):
    lead_logs, user_referrals, user_referral_logs, user_logs,
    user_referral_statuses, referral_rewards, paid_transactions

Note:
    The script does NOT assume exact filenames beyond "<table_name>.csv" —
    it will profile *every* CSV found in the raw data directory, so it keeps
    working even if extra/renamed source files show up.
"""

import argparse
from pathlib import Path
import pandas as pd


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

# Expected tables per the business flow spec — used only to warn if any are
# missing from the raw data directory. Profiling itself is fully dynamic.
EXPECTED_TABLES = [
    "lead_log",
    "user_referrals",
    "user_referral_logs",
    "user_logs",
    "user_referral_statuses",
    "referral_rewards",
    "paid_transactions",
]

SAMPLE_VALUES_COUNT = 5  # how many example values to show per column


# --------------------------------------------------------------------------- #
# Core profiling logic
# --------------------------------------------------------------------------- #

def profile_column(series: pd.Series) -> dict:
    """
    Compute profiling stats for a single column (pandas Series).

    Handles numeric, datetime-like, and string/object columns differently
    for min/max, since a string column's "min/max" is alphabetical while a
    numeric/date column's is a true range.
    """
    total_rows = len(series)
    null_count = int(series.isna().sum())
    non_null = series.dropna()

    # Distinct values (excluding nulls, matching the spec's "Distinct Value Count")
    distinct_value_count = int(non_null.nunique())

    # Try to compute min/max sensibly based on dtype.
    min_value = None
    max_value = None
    if not non_null.empty:
        if pd.api.types.is_numeric_dtype(series):
            min_value = non_null.min()
            max_value = non_null.max()
        else:
            # Try datetime parsing first (many "timestamp" columns arrive as
            # strings from CSV) — falls back to plain string min/max if it
            # doesn't look like a date.
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                parsed = pd.to_datetime(non_null, errors="coerce", utc=False)
            if parsed.notna().mean() > 0.9:  # mostly parseable as dates
                min_value = parsed.min()
                max_value = parsed.max()
            else:
                min_value = non_null.astype(str).min()
                max_value = non_null.astype(str).max()

    # Max actual string length (relevant for varchar-like fields; spec asks
    # for this explicitly). Non-string values are cast to str first.
    if not non_null.empty:
        max_actual_length = int(non_null.astype(str).map(len).max())
    else:
        max_actual_length = 0

    # A few sample values for a quick human sanity check.
    sample_values = (
        non_null.astype(str).unique()[:SAMPLE_VALUES_COUNT].tolist()
        if not non_null.empty
        else []
    )

    return {
        "data_type": str(series.dtype),
        "row_count": total_rows,
        "null_count": null_count,
        "null_percentage": round((null_count / total_rows) * 100, 2) if total_rows else 0.0,
        "populated_percentage": round(((total_rows - null_count) / total_rows) * 100, 2) if total_rows else 0.0,
        "distinct_value_count": distinct_value_count,
        "min_value": min_value,
        "max_value": max_value,
        "max_actual_length": max_actual_length,
        "sample_values": "; ".join(sample_values),
    }


def profile_table(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """
    Build a profile DataFrame (one row per column) for a single source table.
    """
    rows = []
    for column_name in df.columns:
        stats = profile_column(df[column_name])
        rows.append({"table_name": table_name, "column_name": column_name, **stats})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# I/O orchestration
# --------------------------------------------------------------------------- #

def discover_csv_files(raw_dir: Path) -> list[Path]:
    """Find all CSV files in the raw data directory."""
    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        print(f"[WARN] No CSV files found in {raw_dir.resolve()}")
    return csv_files


def warn_missing_expected_tables(found_table_names: list[str]) -> None:
    """Flag any table from the business spec that wasn't found, so nothing
    is silently skipped."""
    missing = [t for t in EXPECTED_TABLES if t not in found_table_names]
    if missing:
        print(f"[WARN] Expected tables not found in raw data dir: {missing}")


def run_profiling(raw_dir: str, out_dir: str) -> None:
    raw_path = Path(raw_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    csv_files = discover_csv_files(raw_path)
    found_table_names = [f.stem for f in csv_files]
    warn_missing_expected_tables(found_table_names)

    summary_rows = []

    for csv_file in csv_files:
        table_name = csv_file.stem
        print(f"[INFO] Profiling table: {table_name}")

        try:
            df = pd.read_csv(csv_file)
        except Exception as exc:
            print(f"[ERROR] Failed to read {csv_file.name}: {exc}")
            continue

        profile_df = profile_table(df, table_name)

        # Write per-table profile CSV
        output_file = out_path / f"{table_name}_profile.csv"
        profile_df.to_csv(output_file, index=False)
        print(f"[INFO]   -> wrote {output_file}")

        summary_rows.append(
            {
                "table_name": table_name,
                "row_count": len(df),
                "column_count": len(df.columns),
                "columns_with_nulls": int((profile_df["null_count"] > 0).sum()),
            }
        )

    # Write a top-level summary across all tables — useful as a quick index.
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_file = out_path / "_profiling_summary.csv"
        summary_df.to_csv(summary_file, index=False)
        print(f"[INFO] Wrote overall summary -> {summary_file}")

    print("[INFO] Profiling complete.")


# --------------------------------------------------------------------------- #
# CLI entrypoint
# --------------------------------------------------------------------------- #

def parse_args():
    parser = argparse.ArgumentParser(
        description="Profile all raw CSV source tables for the referral program pipeline."
    )
    parser.add_argument(
        "--raw-dir",
        default=str(Path(__file__).resolve().parent.parent / "data" / "raw"),
        help="Directory containing the raw source CSVs (default: ../data/raw)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parent / "output"),
        help="Directory to write profile CSVs to (default: ./output)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_profiling(args.raw_dir, args.out_dir)