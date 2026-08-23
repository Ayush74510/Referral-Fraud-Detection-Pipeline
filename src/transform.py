"""
transform.py
------------
Data Processing step of the referral program pipeline.

Takes the cleaned tables (from clean.clean_all_tables) and produces ONE
flat DataFrame — one row per referral — by joining all 7 sources together,
localizing timestamps, and deriving referral_source_category.

Join plan (spine = user_referrals, 46 rows):
    1. + user_referral_statuses  (user_referral_status_id = id)   -> status text
    2. + user_logs AS referrer   (referrer_id = user_id)          -> referrer info
    3. + user_logs AS referee    (referee_id = user_id)           -> referee info (Lead source only)
    4. + lead_logs               (referee_id = lead_id, Lead only)-> source_category for CASE logic
    5. + user_referral_logs      (referral_id = user_referral_id, latest entry only) -> reward_granted_at
    6. + paid_transactions       (transaction_id = transaction_id)-> transaction details
    7. + referral_rewards        (referral_reward_id = id)        -> num_reward_days

Deduplication (both confirmed safe via profiling — see config.py):
    - user_logs: collapse to 1 row per user_id (duplicates are identical
      snapshots; keep the row with the max `id`).
    - user_referral_logs: collapse to 1 row per user_referral_id (the
      latest by created_at) — referrals with a granted reward only ever
      have one log entry anyway, so this is safe.

Timestamp localization:
    - transaction_at uses its own timezone_transaction column.
    - referral_at / updated_at / reward_granted_at have no timezone column
      of their own, so they're localized using the REFERRER's homeclub
      timezone (see config.py comment for the reasoning).
"""

import sys
from pathlib import Path

import pandas as pd

import config


# --------------------------------------------------------------------------- #
# Deduplication helpers
# --------------------------------------------------------------------------- #

def dedupe_user_logs(user_logs: pd.DataFrame) -> pd.DataFrame:
    """One row per user_id — keep the row with the max `id` (duplicates are
    confirmed-identical snapshots, so any tie-break is safe)."""
    return (
        user_logs.sort_values("id")
        .drop_duplicates(subset="user_id", keep="last")
        .reset_index(drop=True)
    )


def dedupe_lead_logs(lead_logs: pd.DataFrame) -> pd.DataFrame:
    """One row per lead_id — keep the row with the max `id`. Confirmed via
    profiling that source_category is identical across duplicate lead_id
    rows (only current_status progresses), so this dedup only prevents a
    join fan-out and cannot pick a wrong source_category."""
    return (
        lead_logs.sort_values("id")
        .drop_duplicates(subset="lead_id", keep="last")
        .reset_index(drop=True)
    )


def dedupe_referral_logs(referral_logs: pd.DataFrame) -> pd.DataFrame:
    """One row per user_referral_id — keep the row with the latest created_at.
    Referrals with a granted reward only ever have a single log entry, so
    this cannot accidentally discard a True in favor of a later False."""
    return (
        referral_logs.sort_values("created_at")
        .drop_duplicates(subset="user_referral_id", keep="last")
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------- #
# Timezone localization
# --------------------------------------------------------------------------- #

def localize_to_timezone(utc_series: pd.Series, timezone_series: pd.Series) -> pd.Series:
    """
    Convert a UTC-aware datetime Series to local time, using a *per-row*
    IANA timezone name given in timezone_series. Rows with a missing
    timestamp or missing timezone are left as NaT rather than guessing.
    """
    def _convert(utc_value, tz_name):
        if pd.isna(utc_value) or pd.isna(tz_name):
            return pd.NaT
        return utc_value.tz_convert(tz_name)

    return pd.Series(
        [_convert(ts, tz) for ts, tz in zip(utc_series, timezone_series)],
        index=utc_series.index,
    )


# --------------------------------------------------------------------------- #
# referral_source_category derivation
# --------------------------------------------------------------------------- #

def derive_referral_source_category(row: pd.Series) -> str | None:
    """
    Implements the spec's CASE logic:
        WHEN referral_source = 'User Sign Up'    THEN 'Online'
        WHEN referral_source = 'Draft Transaction' THEN 'Offline'
        WHEN referral_source = 'Lead'            THEN leads.source_category
    """
    source = row["referral_source"]
    if source == config.REFERRAL_SOURCE_USER_SIGNUP:
        return config.REFERRAL_SOURCE_CATEGORY_ONLINE
    if source == config.REFERRAL_SOURCE_DRAFT_TRANSACTION:
        return config.REFERRAL_SOURCE_CATEGORY_OFFLINE
    if source == config.REFERRAL_SOURCE_LEAD:
        return row.get("lead_source_category")  # may be NaN — see config.py note
    return None


# --------------------------------------------------------------------------- #
# Main join orchestration
# --------------------------------------------------------------------------- #

def build_flat_referral_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Join all 7 cleaned tables into one flat DataFrame, one row per referral.
    """
    referrals = tables["user_referrals"].copy()
    statuses = tables["user_referral_statuses"]
    user_logs = dedupe_user_logs(tables["user_logs"])
    leads = dedupe_lead_logs(tables["lead_logs"])
    referral_logs = dedupe_referral_logs(tables["user_referral_logs"])
    transactions = tables["paid_transactions"]
    rewards = tables["referral_rewards"]

    print(f"[TRANSFORM] Starting from user_referrals: {len(referrals)} rows")

    # 1. Status text
    df = referrals.merge(
        statuses.rename(columns={"id": "user_referral_status_id", "description": "referral_status"}),
        on="user_referral_status_id",
        how="left",
    )
    print(f"[TRANSFORM]   + status                -> {len(df)} rows")

    # 2. Referrer info (name, phone, homeclub, timezone, membership, is_deleted)
    referrer_cols = user_logs.rename(columns={
        "user_id": "referrer_id",
        "name": "referrer_name",
        "phone_number": "referrer_phone_number",
        "homeclub": "referrer_homeclub",
        "timezone_homeclub": "referrer_timezone",
        "membership_expired_date": "referrer_membership_expired_date",
        "is_deleted": "referrer_is_deleted",
    })[["referrer_id", "referrer_name", "referrer_phone_number", "referrer_homeclub",
        "referrer_timezone", "referrer_membership_expired_date", "referrer_is_deleted"]]
    df = df.merge(referrer_cols, on="referrer_id", how="left")
    print(f"[TRANSFORM]   + referrer info          -> {len(df)} rows")

    # 3. Lead source_category (only meaningfully joins for Lead-sourced referrals;
    #    referee_id -> lead_id per the ERD note "Only join to leads if
    #    referral_source is Lead")
    lead_cols = leads.rename(columns={
        "lead_id": "referee_id",
        "source_category": "lead_source_category",
    })[["referee_id", "lead_source_category"]]
    df = df.merge(lead_cols, on="referee_id", how="left")
    print(f"[TRANSFORM]   + lead source_category   -> {len(df)} rows")

    # 4. Latest referral log entry -> reward_granted_at
    log_cols = referral_logs.rename(columns={
        "user_referral_id": "referral_id",
        "created_at": "reward_granted_at_raw",
    })[["referral_id", "reward_granted_at_raw", "is_reward_granted"]]
    df = df.merge(log_cols, on="referral_id", how="left")
    # Only a real "granted at" timestamp when the reward was actually granted.
    df["reward_granted_at_utc"] = df["reward_granted_at_raw"].where(df["is_reward_granted"] == True)
    print(f"[TRANSFORM]   + referral log (dedup'd) -> {len(df)} rows")

    # 5. Transaction details
    df = df.merge(transactions, on="transaction_id", how="left")
    print(f"[TRANSFORM]   + transaction details    -> {len(df)} rows")

    # 6. Reward day count
    reward_cols = rewards.rename(columns={"id": "referral_reward_id"})[
        ["referral_reward_id", "num_reward_days"]
    ]
    df = df.merge(reward_cols, on="referral_reward_id", how="left")
    print(f"[TRANSFORM]   + reward days             -> {len(df)} rows")

    if len(df) != config.EXPECTED_REPORT_ROW_COUNT:
        print(f"[WARN] Row count after joins ({len(df)}) does not match expected "
              f"{config.EXPECTED_REPORT_ROW_COUNT} — a join likely fanned out. Investigate before proceeding.")

    # ---- referral_source_category ----
    df["referral_source_category"] = df.apply(derive_referral_source_category, axis=1)

    # ---- Timestamp localization ----
    # transaction_at: has its own timezone column directly.
    df["transaction_at_local"] = localize_to_timezone(df["transaction_at"], df["timezone_transaction"])

    # referral_at / updated_at / reward_granted_at: no own timezone column,
    # localized using the referrer's homeclub timezone (see config.py).
    df["referral_at_local"] = localize_to_timezone(df["referral_at"], df["referrer_timezone"])
    df["updated_at_local"] = localize_to_timezone(df["updated_at"], df["referrer_timezone"])
    df["reward_granted_at_local"] = localize_to_timezone(df["reward_granted_at_utc"], df["referrer_timezone"])

    return df


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from load import load_all_tables
    from clean import clean_all_tables

    print("[INFO] Loading raw tables...\n")
    raw_tables = load_all_tables()

    print("\n[INFO] Cleaning tables...\n")
    cleaned_tables = clean_all_tables(raw_tables)

    print("\n[INFO] Transforming (joining) tables...\n")
    flat_df = build_flat_referral_table(cleaned_tables)

    print(f"\n[RESULT] Flat table: {len(flat_df)} rows, {len(flat_df.columns)} columns")
    print(f"[RESULT] referral_source_category nulls: {flat_df['referral_source_category'].isna().sum()} "
          f"(expected: 3, from the known Lead/lead_logs data gap)")

    print("\n[SPOT CHECK] Local timestamp conversion sample:")
    print(flat_df[["referral_id", "referral_at", "referral_at_local", "referrer_timezone"]].head(5).to_string(index=False))