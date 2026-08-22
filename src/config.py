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

TRANSACTION_STATUS_PAID = "PAID"

# Confirmed via profiling: transaction_type has TWO distinct values in the
# real data — "NEW" and "REJOIN". The fraud rules require "NEW" specifically,
# so REJOIN transactions are a real, non-trivial filter (not a no-op).
TRANSACTION_TYPE_NEW = "NEW"
TRANSACTION_TYPE_REJOIN = "REJOIN"

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

# 4. Timezones are NOT uniform across rows — both Asia/Jakarta and
#    Asia/Makassar appear in user_logs.timezone_homeclub and
#    paid_transactions.timezone_transaction. Time adjustment in
#    transform.py must be done per-row using each row's own timezone
#    column, not a single global tz.


# --------------------------------------------------------------------------- #
# Columns that should NOT be Initcap-formatted
# --------------------------------------------------------------------------- #
# Spec: "Initcap should apply in string value, unless the club name."
# Club/location names (homeclub, transaction_location, preferred_location)
# are already stored in intentional uppercase (e.g. "ARTERI PONDOK INDAH")
# and must be left as-is.
NO_INITCAP_COLUMNS = {
    "homeclub",
    "transaction_location",
    "preferred_location",
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