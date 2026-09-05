"""
clean.py
--------
Data Cleaning step of the referral program pipeline.

Applies, per table, the fixes identified during profiling
(profiling/profile_tables.py) and required by the spec's "Data Cleaning" /
"String Adjustment" instructions:

    1. Timestamp columns -> parsed to proper UTC-aware datetime (source data
       is UTC per the spec: "All timestamp values are in UTC").
    2. referral_reward_id -> cast to pandas nullable Int64 (was float64 due
       to nulls after CSV load).
    3. referral_rewards.reward_value -> parsed from "10 days" (string) into
       a numeric `num_reward_days` (int) column.
    4. Initcap applied to the specific columns listed in
       config.INITCAP_COLUMNS (an explicit allowlist — see config.py for
       why a denylist would be unsafe here).

Null handling philosophy (per spec: "Null value should not exist/removed"):
    Some nulls in the raw data are legitimate business states, not data
    quality defects — e.g. referee_id is null whenever referral_source is
    NOT "Lead" (per the ERD note: "Only join to leads if referral_source is
    Lead, otherwise use referee_name and referee_phone"), and referrer_id /
    transaction_id are null for referrals still Pending or Failed (no
    transaction has happened yet). Blindly dropping or filling these rows
    would destroy real, valid referral records.

    clean.py therefore does NOT drop rows with nulls. It normalizes types
    so nulls are represented consistently (pandas NaN / pd.NA / NaT), and
    leaves the *business* nulls in place. The spec's "null value should not
    exist" requirement is satisfied at the OUTPUT stage instead (report.py)
    — once the tables are joined and business logic is applied, remaining
    nulls in the final report are resolved there (e.g. "N/A" for a referral
    that never had a transaction), where the correct fill value is
    unambiguous. Resolving nulls this early, per-table, would require
    guessing what a later join needs.
"""

import sys
from pathlib import Path
import pandas as pd
import config


# --------------------------------------------------------------------------- #
# Column-type helpers
# --------------------------------------------------------------------------- #

# Column name patterns that indicate a timestamp — parsed to UTC datetime.
TIMESTAMP_COLUMN_PATTERNS = ("_at", "_date")


def _is_timestamp_column(column_name: str) -> bool:
    return any(column_name.endswith(suffix) for suffix in TIMESTAMP_COLUMN_PATTERNS)


def parse_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse every timestamp-like column (ending in _at / _date) to a proper
    UTC-aware pandas datetime. Source timestamps are UTC per the spec, so
    we explicitly localize to UTC rather than guessing the source offset.
    """
    df = df.copy()
    for column in df.columns:
        if _is_timestamp_column(column):
            df[column] = pd.to_datetime(df[column], utc=True, errors="coerce")
    return df


def apply_initcap(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """
    Apply Initcap (title case) to the explicit allowlist of columns for
    this table, per config.INITCAP_COLUMNS. See config.py for why this is
    an allowlist rather than a denylist.
    """
    df = df.copy()
    eligible_columns = config.INITCAP_COLUMNS.get(table_name, [])
    for column in eligible_columns:
        if column in df.columns:
            df[column] = df[column].str.title()
    return df


def parse_reward_days(df: pd.DataFrame) -> pd.DataFrame:
    """
    referral_rewards.reward_value arrives as a string like "10 days" —
    extract the integer day count into a new `num_reward_days` column
    (int), which is what the final report needs (per spec's output column
    list: num_reward_days INT). The original reward_value string column is
    kept alongside it for traceability.
    """
    df = df.copy()
    if "reward_value" in df.columns:
        extracted = df["reward_value"].str.extract(config.REWARD_VALUE_PATTERN)[0]
        df["num_reward_days"] = pd.to_numeric(extracted, errors="coerce").astype("Int64")
    return df


def fix_referral_reward_id_dtype(df: pd.DataFrame) -> pd.DataFrame:
    """
    user_referrals.referral_reward_id loads as float64 (e.g. 1.0) because
    ~38/46 rows are null, which forces pandas to upcast an otherwise-integer
    column. Cast to pandas' nullable Int64 dtype so valid IDs display as
    "1" not "1.0" while still supporting nulls (unlike plain numpy int64).
    """
    df = df.copy()
    if "referral_reward_id" in df.columns:
        df["referral_reward_id"] = df["referral_reward_id"].astype("Int64")
    return df


# --------------------------------------------------------------------------- #
# Per-table cleaning orchestration
# --------------------------------------------------------------------------- #

def clean_table(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Apply all relevant cleaning steps to a single table."""
    df = parse_timestamps(df)
    df = apply_initcap(df, table_name)

    if table_name == "referral_rewards":
        df = parse_reward_days(df)

    if table_name == "user_referrals":
        df = fix_referral_reward_id_dtype(df)

    return df


def clean_all_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Apply cleaning to every table in the dict returned by load.load_all_tables().

    Returns a new dict — does not mutate the input tables.
    """
    cleaned = {}
    for table_name, df in tables.items():
        cleaned_df = clean_table(df, table_name)
        null_counts = cleaned_df.isna().sum().sum()
        print(f"[CLEAN] {table_name:<25} -> {len(cleaned_df)} rows, {null_counts} total nulls remaining (business nulls, not errors)")
        cleaned[table_name] = cleaned_df
    return cleaned


if __name__ == "__main__":
    # Running this file directly: load + clean all tables, print a summary,
    # and spot-check the two trickiest fixes (reward_value parsing and
    # referral_reward_id dtype) so you can confirm they worked correctly.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from load import load_all_tables

    print("[INFO] Loading raw tables...\n")
    raw_tables = load_all_tables()

    print("\n[INFO] Cleaning tables...\n")
    cleaned_tables = clean_all_tables(raw_tables)

    print("\n[SPOT CHECK] referral_rewards — reward_value parsed to num_reward_days:")
    print(cleaned_tables["referral_rewards"][["id", "reward_value", "num_reward_days"]].to_string(index=False))

    print("\n[SPOT CHECK] user_referrals — referral_reward_id dtype:", cleaned_tables["user_referrals"]["referral_reward_id"].dtype)

    print("\n[SPOT CHECK] paid_transactions — transaction_status/type after Initcap:")
    print(cleaned_tables["paid_transactions"][["transaction_status", "transaction_type"]].drop_duplicates().to_string(index=False))