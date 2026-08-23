"""
report.py
---------
Output step of the referral program pipeline.

Takes the fraud-flagged flat DataFrame (from fraud_rules.add_fraud_flags)
and produces the final report: selects/renames the 22 columns per the
spec's output table, resolves remaining nulls, generates
referral_details_id, validates the row count, and writes the CSV.

Null resolution policy (the "should not exist" requirement deferred from
clean.py — see clean.py's docstring for why it wasn't resolved earlier):
    Now that every join is complete, each remaining null has an
    unambiguous meaning, so it's safe to fill:
        - ID / name / phone / text columns  -> "N/A" (not applicable to
          this referral — e.g. referee_id for a non-Lead referral)
        - num_reward_days                    -> 0 (no reward was assigned)
        - timestamp columns                  -> "N/A" (no such event
          happened for this referral, e.g. reward_granted_at when the
          reward was never granted) EXCEPT referral_at / updated_at, which
          fall back to the raw UTC timestamp when local time couldn't be
          computed (see config.py note #11) — preserving a correct time
          over showing nothing.
"""

import sys
from pathlib import Path

import pandas as pd

import config


def resolve_final_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the null-resolution policy described in the module docstring."""
    df = df.copy()

    # referral_at / updated_at: fall back to raw UTC timestamp when the
    # localized version is unavailable (no referrer timezone found).
    df["referral_at_final"] = df["referral_at_local"].fillna(df["referral_at"])
    df["updated_at_final"] = df["updated_at_local"].fillna(df["updated_at"])

    # reward_granted_at: no fallback — a null here always means the reward
    # genuinely was never granted, which is real information worth keeping
    # visible as "N/A", not papering over with a fake timestamp.
    df["reward_granted_at_final"] = df["reward_granted_at_local"]

    # num_reward_days: null means no reward was ever assigned to this
    # referral -> 0, consistent with the spec's sample dtype (INT).
    df["num_reward_days"] = df["num_reward_days"].fillna(0).astype(int)

    return df


def build_final_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    Select, rename, and order columns to match the spec's output table,
    generate referral_details_id, resolve remaining nulls, and return the
    report-ready DataFrame (still needs formatting/writing — see
    generate_report()).
    """
    df = resolve_final_nulls(df)

    report = pd.DataFrame({
        "referral_details_id": range(1, len(df) + 1),
        "referral_id": df["referral_id"],
        "referral_source": df["referral_source"],
        "referral_source_category": df["referral_source_category"],
        "referral_at": df["referral_at_final"],
        "referrer_id": df["referrer_id"],
        "referrer_name": df["referrer_name"],
        "referrer_phone_number": df["referrer_phone_number"],
        "referrer_homeclub": df["referrer_homeclub"],
        "referee_id": df["referee_id"],
        "referee_name": df["referee_name"],
        "referee_phone": df["referee_phone"],
        "referral_status": df["referral_status"],
        "num_reward_days": df["num_reward_days"],
        "transaction_id": df["transaction_id"],
        "transaction_status": df["transaction_status"],
        "transaction_at": df["transaction_at_local"],
        "transaction_location": df["transaction_location"],
        "transaction_type": df["transaction_type"],
        "updated_at": df["updated_at_final"],
        "reward_granted_at": df["reward_granted_at_final"],
        "is_business_logic_valid": df["is_business_logic_valid"],
    })

    # Format all datetime columns to a readable, consistent string BEFORE
    # filling remaining nulls with "N/A". Formatted per-element (not via
    # the vectorized .dt accessor) because these columns mix different
    # timezone offsets row-to-row (Asia/Jakarta +07:00 vs Asia/Makassar
    # +08:00) — pandas' .dt accessor requires one unified tz per column,
    # which would force everything back to a single offset and undo the
    # per-row localization from transform.py.
    datetime_columns = ["referral_at", "transaction_at", "updated_at", "reward_granted_at"]
    for col in datetime_columns:
        report[col] = report[col].apply(
            lambda ts: ts.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ts) else ts
        )

    # Now fill all remaining nulls (string/ID/datetime-as-string alike)
    # with "N/A" — satisfies the spec's "null value should not exist"
    # requirement uniformly across the whole report.
    string_like_columns = [c for c in config.FINAL_REPORT_COLUMNS
                            if c not in ("referral_details_id", "num_reward_days", "is_business_logic_valid")]
    for col in string_like_columns:
        report[col] = report[col].fillna("N/A")

    return report[config.FINAL_REPORT_COLUMNS]


def validate_report(report: pd.DataFrame) -> None:
    """Fail loudly if the report doesn't match the spec's expectations."""
    if len(report) != config.EXPECTED_REPORT_ROW_COUNT:
        raise ValueError(
            f"Final report has {len(report)} rows, expected exactly "
            f"{config.EXPECTED_REPORT_ROW_COUNT} per the spec. Check for join fan-out."
        )

    remaining_nulls = report.isna().sum().sum()
    if remaining_nulls > 0:
        raise ValueError(f"Final report still has {remaining_nulls} null value(s) after resolution — investigate.")

    print(f"[VALIDATE] Row count OK: {len(report)} rows")
    print(f"[VALIDATE] No remaining nulls OK")
    print(f"[VALIDATE] Columns: {len(report.columns)} (expected {len(config.FINAL_REPORT_COLUMNS)})")


def generate_report(df: pd.DataFrame, output_path: Path = None) -> pd.DataFrame:
    """Build, validate, and write the final report CSV. Returns the DataFrame."""
    output_path = output_path or config.FINAL_REPORT_PATH
    report = build_final_report(df)
    validate_report(report)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False)
    print(f"[WRITE] Final report written to: {output_path}")

    return report


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from load import load_all_tables
    from clean import clean_all_tables
    from transform import build_flat_referral_table
    from fraud_rules import add_fraud_flags

    print("[INFO] Running full pipeline: load -> clean -> transform -> fraud_rules -> report\n")
    raw_tables = load_all_tables()
    cleaned_tables = clean_all_tables(raw_tables)
    flat_df = build_flat_referral_table(cleaned_tables)
    flagged_df = add_fraud_flags(flat_df)

    print("\n[INFO] Building final report...\n")
    final_report = generate_report(flagged_df)

    print(f"\n[SUMMARY] Valid: {final_report['is_business_logic_valid'].sum()}, "
          f"Invalid: {(~final_report['is_business_logic_valid']).sum()}")
    print("\n[PREVIEW] First 3 rows:")
    print(final_report.head(3).to_string(index=False))