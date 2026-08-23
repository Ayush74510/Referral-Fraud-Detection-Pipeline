"""
main.py
-------
Pipeline orchestrator for the referral program data pipeline.

Wires together every stage in order:
    load -> clean -> transform -> fraud_rules -> report

This is the single function the root-level your_script.py calls. Kept
separate from your_script.py itself so the actual logic lives in the
`src/` package (importable, testable) while your_script.py stays a thin,
literal entrypoint matching the spec's submission requirement.
"""

import sys
import time
from pathlib import Path

# Allow running this file directly (python src/main.py) as well as via
# the root your_script.py wrapper, regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from load import load_all_tables
from clean import clean_all_tables
from transform import build_flat_referral_table
from fraud_rules import add_fraud_flags
from report import generate_report


def run() -> None:
    """
    Run the full referral program data pipeline end-to-end:
      1. Load all 7 raw source CSVs.
      2. Clean each table (dtypes, nulls, Initcap).
      3. Transform: join all sources into one flat, deduplicated table;
         localize timestamps; derive referral_source_category.
      4. Apply the 9 fraud-detection business rules to flag
         is_business_logic_valid.
      5. Assemble, validate, and write the final report CSV.
    """
    start_time = time.time()

    print("=" * 70)
    print("Springer Capital — Referral Program Fraud Detection Pipeline")
    print("=" * 70)

    print("\n[STEP 1/5] Loading raw source tables...")
    raw_tables = load_all_tables()

    print("\n[STEP 2/5] Cleaning tables...")
    cleaned_tables = clean_all_tables(raw_tables)

    print("\n[STEP 3/5] Transforming (joining, localizing, categorizing)...")
    flat_df = build_flat_referral_table(cleaned_tables)

    print("\n[STEP 4/5] Applying fraud detection business logic...")
    flagged_df = add_fraud_flags(flat_df)

    print("\n[STEP 5/5] Generating final report...")
    final_report = generate_report(flagged_df)

    elapsed = time.time() - start_time
    valid_count = int(final_report["is_business_logic_valid"].sum())
    invalid_count = len(final_report) - valid_count

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print(f"  Total referrals processed : {len(final_report)}")
    print(f"  Valid                     : {valid_count}")
    print(f"  Invalid                   : {invalid_count}")
    print(f"  Report written to         : {config.FINAL_REPORT_PATH}")
    print(f"  Elapsed time               : {elapsed:.2f}s")
    print("=" * 70)


if __name__ == "__main__":
    run()