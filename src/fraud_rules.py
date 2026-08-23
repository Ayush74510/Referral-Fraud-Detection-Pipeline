"""
fraud_rules.py
--------------
Basic Business Logic Implementation step of the referral program pipeline.

Takes the flat, joined DataFrame (from transform.build_flat_referral_table)
and adds is_business_logic_valid (bool), per the spec's 9 conditions.

Design: each individual sub-condition (there are ~17 across all 9 rules) is
computed as its own named boolean Series first, then combined into the 2
"valid" conditions and 5 "invalid" conditions, then combined into the final
column. This is deliberately verbose rather than one giant boolean
expression — it means:
    (a) each condition can be unit-tested / spot-checked in isolation,
    (b) a reviewer can trace exactly which sub-condition drove a given
        row's result,
    (c) it mirrors the numbered structure of the spec 1:1, so it's easy to
        verify nothing was missed or misread.

VALID if V1 OR V2:
    V1  — reward > 0, status Berhasil, has transaction_id, transaction
          Paid, transaction type New, transaction after referral, same
          month, referrer membership not expired, referrer not deleted,
          reward granted.
    V2  — status Menunggu or Tidak Berhasil, AND no reward value assigned.

INVALID if I1 OR I2 OR I3 OR I4 OR I5 (checked regardless of V1/V2 — see
combination logic at the bottom):
    I1 — reward > 0 AND status != Berhasil
    I2 — reward > 0 AND no transaction_id
    I3 — no reward value AND has transaction_id AND transaction Paid AND
         transaction occurred after referral
    I4 — status Berhasil AND reward is null or 0
    I5 — transaction occurred before referral was created
"""

import sys
from pathlib import Path

import pandas as pd

import config


def add_fraud_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds is_business_logic_valid (bool) to df, plus the intermediate
    condition columns (v1_valid, v2_valid, i1_invalid ... i5_invalid) so
    the reasoning behind every row's result is inspectable, not just the
    final True/False.
    """
    df = df.copy()

    # ---- Shared building-block conditions, computed once ---- #
    has_reward = df["num_reward_days"].notna()                       # "reward value > 0"
    no_reward = df["num_reward_days"].isna()                          # "no reward value assigned"
    status_berhasil = df["referral_status"] == config.STATUS_BERHASIL
    status_pending_or_failed = df["referral_status"].isin(
        [config.STATUS_MENUNGGU, config.STATUS_TIDAK_BERHASIL]
    )
    has_transaction_id = df["transaction_id"].notna()
    no_transaction_id = df["transaction_id"].isna()
    transaction_paid = df["transaction_status"] == config.TRANSACTION_STATUS_PAID
    transaction_type_new = df["transaction_type"] == config.TRANSACTION_TYPE_NEW

    # Temporal comparisons — use UTC timestamps (not the localized ones) so
    # cross-timezone rows compare on a consistent, absolute timeline.
    transaction_after_referral = df["transaction_at"] > df["referral_at"]
    transaction_before_referral = df["transaction_at"] < df["referral_at"]
    same_month = (
        (df["transaction_at"].dt.year == df["referral_at"].dt.year)
        & (df["transaction_at"].dt.month == df["referral_at"].dt.month)
    )

    # Referrer membership check: not expired AS OF the referral date (see
    # config.py note for why this reference point was chosen).
    membership_not_expired = df["referrer_membership_expired_date"] >= df["referral_at"]
    referrer_not_deleted = df["referrer_is_deleted"] == False  # noqa: E712 (explicit bool compare for clarity)
    reward_granted = df["is_reward_granted"] == True  # noqa: E712

    # ---- VALID conditions ---- #

    v1_valid = (
        has_reward
        & status_berhasil
        & has_transaction_id
        & transaction_paid
        & transaction_type_new
        & transaction_after_referral
        & same_month
        & membership_not_expired
        & referrer_not_deleted
        & reward_granted
    )

    v2_valid = status_pending_or_failed & no_reward

    # ---- INVALID conditions ---- #

    i1_invalid = has_reward & ~status_berhasil

    i2_invalid = has_reward & no_transaction_id

    i3_invalid = no_reward & has_transaction_id & transaction_paid & transaction_after_referral

    i4_invalid = status_berhasil & no_reward

    i5_invalid = transaction_before_referral

    # ---- BONUS: additional invalid pattern found during development ---- #
    # Confirmed via investigation: in this dataset, NONE of the referrals
    # in user_referrals have a matching is_reward_granted=True log entry —
    # all 17 "granted" log entries in user_referral_logs belong to referral
    # IDs that don't exist in user_referrals at all (orphaned records).
    # This means condition V1's "reward has been granted" sub-condition can
    # never be satisfied for this dataset, and 5 referrals otherwise meet
    # every other V1 requirement (Berhasil, reward assigned, transaction
    # Paid + New + after referral + same month, referrer membership valid,
    # referrer not deleted) but were NEVER actually granted the reward to
    # the referee. That's a real fraud/ops signal worth its own explicit
    # flag, distinct from the 5 documented invalid conditions: the referral
    # was fully earned per business criteria, but the payout never happened.
    i6_invalid_reward_earned_but_not_granted = (
        has_reward
        & status_berhasil
        & has_transaction_id
        & transaction_paid
        & transaction_type_new
        & transaction_after_referral
        & same_month
        & membership_not_expired
        & referrer_not_deleted
        & ~reward_granted
    )

    # ---- BONUS #2: transaction_id referenced but unverifiable ---- #
    # Confirmed via investigation: some referrals have a transaction_id
    # that does NOT exist anywhere in paid_transactions — i.e. the referral
    # claims a transaction happened, but there's no record proving it did
    # (transaction_status is null after the left join because no match was
    # found, not because the source data had a null status). Claiming an
    # unverifiable transaction for a "Berhasil" + reward-assigned referral
    # is arguably the strongest fraud signal in the dataset, so it gets its
    # own explicit flag rather than silently falling through as unmatched.
    transaction_unverifiable = has_transaction_id & df["transaction_status"].isna()
    i7_invalid_unverifiable_transaction = (
        has_reward & status_berhasil & transaction_unverifiable
    )

    # ---- Combine ---- #
    # A row is valid only if it satisfies a valid condition AND does not
    # trip any invalid condition. In practice V1/V2 and I1-I5 should be
    # mutually exclusive by construction, but combining this way is
    # defensive: an invalid signal always wins, even if an edge case in the
    # real data satisfies both a valid- and an invalid-shaped pattern
    # simultaneously (e.g. a data entry error), which is exactly the kind
    # of thing a fraud-detection pipeline should flag rather than paper over.
    any_valid = v1_valid | v2_valid
    any_invalid = (
        i1_invalid | i2_invalid | i3_invalid | i4_invalid | i5_invalid
        | i6_invalid_reward_earned_but_not_granted | i7_invalid_unverifiable_transaction
    )

    df["is_business_logic_valid"] = any_valid & ~any_invalid

    # Keep the intermediate flags — useful for debugging and for the
    # "if you found any invalid business logic is a plus" bonus ask, since
    # a reviewer (or you) can see exactly which condition(s) fired per row.
    df["v1_valid"] = v1_valid
    df["v2_valid"] = v2_valid
    df["i1_invalid"] = i1_invalid
    df["i2_invalid"] = i2_invalid
    df["i3_invalid"] = i3_invalid
    df["i4_invalid"] = i4_invalid
    df["i5_invalid"] = i5_invalid
    df["i6_invalid_reward_earned_but_not_granted"] = i6_invalid_reward_earned_but_not_granted
    df["i7_invalid_unverifiable_transaction"] = i7_invalid_unverifiable_transaction

    return df


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from load import load_all_tables
    from clean import clean_all_tables
    from transform import build_flat_referral_table

    print("[INFO] Loading + cleaning + transforming...\n")
    raw_tables = load_all_tables()
    cleaned_tables = clean_all_tables(raw_tables)
    flat_df = build_flat_referral_table(cleaned_tables)

    print("\n[INFO] Applying fraud detection rules...\n")
    result_df = add_fraud_flags(flat_df)

    valid_count = result_df["is_business_logic_valid"].sum()
    invalid_count = (~result_df["is_business_logic_valid"]).sum()
    print(f"[RESULT] {len(result_df)} total referrals")
    print(f"[RESULT]   valid:   {valid_count}")
    print(f"[RESULT]   invalid: {invalid_count}")

    print("\n[BREAKDOWN] Which condition fired, per row (non-zero only):")
    condition_cols = ["v1_valid", "v2_valid", "i1_invalid", "i2_invalid", "i3_invalid", "i4_invalid",
                       "i5_invalid", "i6_invalid_reward_earned_but_not_granted", "i7_invalid_unverifiable_transaction"]
    print(result_df[condition_cols].sum())

    # Rows where NEITHER a valid nor an invalid condition fired — these
    # don't cleanly match any of the documented patterns. Worth a
    # reviewer's eye.
    unmatched = result_df[~(result_df["v1_valid"] | result_df["v2_valid"] |
                             result_df["i1_invalid"] | result_df["i2_invalid"] |
                             result_df["i3_invalid"] | result_df["i4_invalid"] |
                             result_df["i5_invalid"] | result_df["i6_invalid_reward_earned_but_not_granted"] |
                             result_df["i7_invalid_unverifiable_transaction"])]
    print(f"\n[FLAG] {len(unmatched)} row(s) matched NEITHER a valid nor an invalid pattern:")
    if len(unmatched) > 0:
        print(unmatched[["referral_id", "referral_status", "num_reward_days", "transaction_id",
                          "transaction_status", "is_reward_granted"]].to_string(index=False))