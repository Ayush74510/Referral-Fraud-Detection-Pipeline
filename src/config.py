"""
config.py
---------
Central configuration for the referral program data pipeline.

Every constant here was locked in *after* running profiling/profile_tables.py
against the real source CSVs — not guessed from the spec alone. See the
comments below for why each value is what it is.

Keeping these in one place means clean.py / transform.py / fraud_rules.py
never hardcode a magic string — if a status label or file name changes,
it changes here once.
"""

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_DATA_DIR = PROJECT_ROOT / "data" / "output"

# Actual filenames as delivered (NOTE: the business spec calls the table
# "lead_logs", but the real source file is named "lead_log.csv" — singular.
# Referencing filenames here, once, means the mismatch only needs handling
# in this one place.)
RAW_FILES = {
    "lead_logs": RAW_DATA_DIR / "lead_log.csv",
    "user_referrals": RAW_DATA_DIR / "user_referrals.csv",
    "user_referral_logs": RAW_DATA_DIR / "user_referral_logs.csv",
    "user_logs": RAW_DATA_DIR / "user_logs.csv",
    "user_referral_statuses": RAW_DATA_DIR / "user_referral_statuses.csv",
    "referral_rewards": RAW_DATA_DIR / "referral_rewards.csv",
    "paid_transactions": RAW_DATA_DIR / "paid_transactions.csv",
}

FINAL_REPORT_PATH = OUTPUT_DATA_DIR / "referral_fraud_report.csv"

EXPECTED_REPORT_ROW_COUNT = 46  # per spec — used as a sanity-check assertion


# --------------------------------------------------------------------------- #
# Business status / category strings
# --------------------------------------------------------------------------- #
# Confirmed via profiling against user_referral_statuses.csv and
# paid_transactions.csv — exact spelling and casing as they appear in the
# real data. Fraud rule comparisons must use these constants, never
# inline string literals, so a mismatch fails loudly (e.g. NameError)
# rather than silently evaluating every row as invalid.

STATUS_BERHASIL = "Berhasil"            # Successful
STATUS_MENUNGGU = "Menunggu"            # Pending
STATUS_TIDAK_BERHASIL = "Tidak Berhasil"  # Failed

# NOTE ON CASING: raw source data has these as "PAID" / "NEW" / "REJOIN"
# (all caps). clean.py applies Initcap to these columns (per the spec's
# String Adjustment rule), and the spec's own sample output row confirms
# the *expected final report* casing is Title Case ("Paid", "New") — not
# raw all-caps. These constants are therefore defined in POST-CLEANING
# (Title Case) form, since fraud_rules.py runs on the cleaned/joined data,
# not the raw data. Comparisons must use these constants everywhere so the
# whole pipeline stays consistent with one casing convention.
TRANSACTION_STATUS_PAID = "Paid"

# Confirmed via profiling: transaction_type has TWO distinct values in the
# real data — "NEW" and "REJOIN". The fraud rules require "NEW" specifically,
# so REJOIN transactions are a real, non-trivial filter (not a no-op).
TRANSACTION_TYPE_NEW = "New"
TRANSACTION_TYPE_REJOIN = "Rejoin"

REFERRAL_SOURCE_USER_SIGNUP = "User Sign Up"
REFERRAL_SOURCE_DRAFT_TRANSACTION = "Draft Transaction"
REFERRAL_SOURCE_LEAD = "Lead"

REFERRAL_SOURCE_CATEGORY_ONLINE = "Online"
REFERRAL_SOURCE_CATEGORY_OFFLINE = "Offline"
# For "Lead" sources, referral_source_category is instead pulled from
# lead_logs.source_category (already "Online"/"Offline" in the real data —
# confirmed via profiling).


# --------------------------------------------------------------------------- #
# Known data quality issues (handled explicitly in clean.py)
# --------------------------------------------------------------------------- #
# Documented here so the "why" behind clean.py's logic is traceable back to
# a specific profiling finding, not silent guesswork.

# 1. referral_rewards.reward_value is a STRING like "10 days" / "15 days" /
#    "20 days" — not numeric. Must extract the integer day count before any
#    ">0" comparison in fraud_rules.py. Parsed into `num_reward_days` (int)
#    for the final report, per the spec's output column list.
REWARD_VALUE_PATTERN = r"(\d+)"  # regex to extract the leading integer

# 2. user_referrals.referral_reward_id loads as float64 (1.0, 2.0, 3.0)
#    because ~38/46 rows are null, which upcasts the column. Cast to
#    pandas' nullable Int64 dtype in clean.py to avoid "1.0" leaking into
#    the final report.

# 3. user_referral_logs has 96 rows but only 78 distinct user_referral_id
#    values — some referrals have multiple log entries (is_reward_granted
#    likely toggles False -> True over time). transform.py must take the
#    MOST RECENT entry per user_referral_id (max created_at) before joining,
#    or the final report will have duplicate rows for those referrals.
TAKE_LATEST_REFERRAL_LOG_PER_REFERRAL = True

# 5. user_logs has heavy duplication: only 9 distinct user_id values across
#    29 rows. Confirmed via profiling that duplicate rows for the same
#    user_id are byte-for-byte identical except the log's own `id` column —
#    these are repeated snapshots, not evolving history. Safe to dedupe to
#    ONE row per user_id (max `id`) with no risk of picking a stale value.
DEDUPE_USER_LOGS_BY_LATEST_ID = True

# 6. 3 of 11 "Lead"-sourced referrals have a referee_id that does not match
#    ANY lead_id in lead_logs (confirmed via profiling — lead_logs only has
#    8 rows / 6 distinct lead_ids, referenced by 11 Lead-sourced referrals).
#    This means referral_source_category will be genuinely NULL for those
#    3 rows after the join — a real data gap, not a bug. report.py resolves
#    this at output time (see report.py for the fill decision).

# 6b. lead_logs also has duplicate lead_id rows (one lead_id has 4 entries,
#     its current_status progressing Fresh -> Fresh -> Maybe -> Appointment
#     over time — a genuine log/event table, same pattern as
#     user_referral_logs). source_category is identical across the
#     duplicates though, so — unlike the referral_logs dedup, where WHICH
#     row you keep matters for reward_granted_at — here dedup is purely to
#     prevent a fan-out join; any tie-break (latest by id) is safe.
DEDUPE_LEAD_LOGS_BY_LATEST_ID = True

# 7. Timestamp localization: paid_transactions.transaction_at has its own
#    timezone_transaction column and is localized directly. But
#    user_referrals.referral_at / updated_at, and the derived
#    reward_granted_at (from user_referral_logs.created_at), have NO
#    timezone column of their own — per the spec's instruction ("if
#    timezone does not exist, you need to join with another table"), these
#    are localized using the REFERRER's homeclub timezone
#    (user_logs.timezone_homeclub via referrer_id), since a referral event
#    belongs to the referrer's account/location context.

# 4. Timezones are NOT uniform across rows — both Asia/Jakarta and
#    Asia/Makassar appear in user_logs.timezone_homeclub and
#    paid_transactions.timezone_transaction. Time adjustment in
#    transform.py must be done per-row using each row's own timezone
#    column, not a single global tz.


# --------------------------------------------------------------------------- #
# Columns eligible for Initcap formatting
# --------------------------------------------------------------------------- #
# Spec: "Initcap should apply in string value, unless the club name."
#
# Implemented as an ALLOWLIST (not a denylist) — deliberately, because
# profiling showed referee_name/referrer-related name & phone columns are
# already SHA-256-style hashes (e.g. "8ef43a9189c084778dadf266d6ee6071"),
# not real names. Applying .title() to a hash would silently mangle it
# (capitalizing arbitrary hex letters) while looking like valid data — a
# denylist would only catch column names we thought to exclude. An
# allowlist means only columns we've explicitly reviewed via profiling get
# reformatted; anything new added later is safe by default.
#
# homeclub / transaction_location / preferred_location are excluded per
# spec ("unless the club name") — confirmed via profiling these are
# already stored in intentional uppercase (e.g. "ARTERI PONDOK INDAH").
INITCAP_COLUMNS = {
    "lead_logs": ["source_category", "current_status"],
    "user_referrals": ["referral_source"],
    "user_referral_statuses": ["description"],
    "referral_rewards": [],
    "paid_transactions": ["transaction_status", "transaction_type"],
    "user_logs": [],
    "user_referral_logs": [],
}


# --------------------------------------------------------------------------- #
# Final report column order (per spec's output table)
# --------------------------------------------------------------------------- #
FINAL_REPORT_COLUMNS = [
    "referral_details_id",
    "referral_id",
    "referral_source",
    "referral_source_category",
    "referral_at",
    "referrer_id",
    "referrer_name",
    "referrer_phone_number",
    "referrer_homeclub",
    "referee_id",
    "referee_name",
    "referee_phone",
    "referral_status",
    "num_reward_days",
    "transaction_id",
    "transaction_status",
    "transaction_at",
    "transaction_location",
    "transaction_type",
    "updated_at",
    "reward_granted_at",
    "is_business_logic_valid",
]