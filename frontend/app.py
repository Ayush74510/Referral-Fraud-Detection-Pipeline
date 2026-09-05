"""
app.py
------
Flask API server for the Referral Fraud Detection Pipeline dashboard.

Endpoints:
    GET  /                  — serve the dashboard HTML
    POST /api/run           — accept 7 CSV uploads, run the pipeline, return results
    GET  /api/results       — return the last pipeline result as JSON
    GET  /api/download      — stream the referral_fraud_report.csv
    GET  /api/health        — liveness check

Usage:
    python frontend/run_dashboard.py
    # or directly:
    python frontend/app.py
"""

import json
import os
import sys
import time
import traceback
from io import StringIO
from pathlib import Path

# pyrefly: ignore [missing-import]
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Path setup — allow importing src/ from the project root
# ---------------------------------------------------------------------------
from pathlib import Path
import sys

FRONTEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

import src.config
from src.load import load_all_tables
from src.clean import clean_all_tables
from src.transform import build_flat_referral_table
from src.fraud_rules import add_fraud_flags
from src.report import generate_report

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
STATIC_DIR = FRONTEND_DIR / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
CORS(app)

# In-memory store for the last pipeline result
_last_result: dict | None = None
_pipeline_running: bool = False

# ---------------------------------------------------------------------------
# Expected upload file keys → destination filenames in data/raw/
# ---------------------------------------------------------------------------
EXPECTED_FILES = {
    "lead_log":                "lead_log.csv",
    "user_referrals":          "user_referrals.csv",
    "user_referral_logs":      "user_referral_logs.csv",
    "user_logs":               "user_logs.csv",
    "user_referral_statuses":  "user_referral_statuses.csv",
    "referral_rewards":        "referral_rewards.csv",
    "paid_transactions":       "paid_transactions.csv",
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the dashboard."""
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/api/run", methods=["POST"])
def run_pipeline():
    """
    Accept 7 CSV uploads (multipart/form-data), save to data/raw/,
    run the full pipeline, and return the results as JSON.

    If some files are missing from the upload but already exist on disk
    (e.g. a re-run), they are reused. Missing files that don't exist at
    all will cause a clear error response.
    """
    global _last_result, _pipeline_running

    if _pipeline_running:
        return jsonify({"error": "Pipeline is already running."}), 409

    _pipeline_running = True
    start_time = time.time()

    try:
        # ---- Save uploaded files ----
        raw_dir = src.config.RAW_DATA_DIR
        raw_dir.mkdir(parents=True, exist_ok=True)

        uploaded = []
        skipped = []

        for field_name, dest_filename in EXPECTED_FILES.items():
            dest_path = raw_dir / dest_filename
            if field_name in request.files and request.files[field_name].filename:
                f = request.files[field_name]
                f.save(str(dest_path))
                uploaded.append(dest_filename)
            elif dest_path.exists():
                skipped.append(dest_filename)  # reuse existing
            else:
                return jsonify({
                    "error": f"Missing required file: '{dest_filename}'. "
                             f"Please upload it (field name: '{field_name}')."
                }), 400

        # ---- Capture stdout from the pipeline steps ----
        log_buffer = []

        def logged_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            log_buffer.append(msg)
            print(msg)  # still emit to server console

        # ---- Run pipeline ----
        log_buffer.append("Starting pipeline...")

        raw_tables = load_all_tables()
        log_buffer.append("✓ Step 1/5 — Tables loaded")

        cleaned_tables = clean_all_tables(raw_tables)
        log_buffer.append("✓ Step 2/5 — Tables cleaned")

        flat_df = build_flat_referral_table(cleaned_tables)
        log_buffer.append("✓ Step 3/5 — Transformed & joined")

        flagged_df = add_fraud_flags(flat_df)
        log_buffer.append("✓ Step 4/5 — Fraud rules applied")

        final_report = generate_report(flagged_df)
        log_buffer.append("✓ Step 5/5 — Report generated")

        elapsed = time.time() - start_time

        # ---- Build stats ----
        total = len(final_report)
        valid_count = int(final_report["is_business_logic_valid"].sum())
        invalid_count = total - valid_count

        # Per-condition counts (from flagged_df, before report columns are dropped)
        condition_cols = {
            "V1 — Fully earned reward":        "v1_valid",
            "V2 — Pending/failed, no reward":  "v2_valid",
            "I1 — Reward without completion":  "i1_invalid",
            "I2 — Reward without transaction": "i2_invalid",
            "I3 — Transaction without reward": "i3_invalid",
            "I4 — Completed without reward":   "i4_invalid",
            "I5 — Backdated transaction":      "i5_invalid",
            "I6 — Earned but never disbursed": "i6_invalid_reward_earned_but_not_granted",
            "I7 — Orphaned transaction ref":   "i7_invalid_unverifiable_transaction",
        }
        conditions = {}
        for label, col in condition_cols.items():
            if col in flagged_df.columns:
                conditions[label] = int(flagged_df[col].sum())

        # ---- Serialize report rows ----
        # Convert timestamps/booleans to JSON-safe types
        report_json = final_report.copy()
        for col in report_json.columns:
            if report_json[col].dtype == "bool" or str(report_json[col].dtype) == "boolean":
                report_json[col] = report_json[col].astype(bool)

        # Map condition flags per row (from flagged_df)
        per_row_conditions = []
        for _, row in flagged_df.iterrows():
            fired = []
            for label, col in condition_cols.items():
                if col in flagged_df.columns and bool(row[col]):
                    fired.append(label)
            per_row_conditions.append(fired)

        rows = []
        for i, (_, row) in enumerate(report_json.iterrows()):
            record = {}
            for col in report_json.columns:
                val = row[col]
                if hasattr(val, "item"):          # numpy scalar → python
                    val = val.item()
                elif val is True or val is False:
                    pass
                record[col] = val
            record["_conditions_fired"] = per_row_conditions[i]
            rows.append(record)

        result = {
            "status": "success",
            "elapsed_seconds": round(elapsed, 2),
            "uploaded_files": uploaded,
            "reused_files": skipped,
            "stats": {
                "total": total,
                "valid": valid_count,
                "invalid": invalid_count,
                "validity_rate": round(valid_count / total * 100, 1) if total else 0,
            },
            "conditions": conditions,
            "columns": list(report_json.columns),
            "rows": rows,
            "log": log_buffer,
        }

        _last_result = result
        return jsonify(result)

    except Exception as exc:
        tb = traceback.format_exc()
        print(tb)
        return jsonify({
            "error": str(exc),
            "traceback": tb,
        }), 500

    finally:
        _pipeline_running = False


@app.route("/api/results")
def get_results():
    """Return the last pipeline result, if any."""
    if _last_result is None:
        # Try to load an existing report from disk
        report_path = src.config.FINAL_REPORT_PATH
        if report_path.exists():
            try:
                import pandas as pd
                df = pd.read_csv(report_path)
                total = len(df)
                valid_count = int(df["is_business_logic_valid"].sum())
                invalid_count = total - valid_count
                rows = []
                for _, row in df.iterrows():
                    record = {}
                    for col in df.columns:
                        val = row[col]
                        if hasattr(val, "item"):
                            val = val.item()
                        record[col] = val
                    record["_conditions_fired"] = []
                    rows.append(record)
                return jsonify({
                    "status": "success",
                    "elapsed_seconds": None,
                    "stats": {
                        "total": total,
                        "valid": valid_count,
                        "invalid": invalid_count,
                        "validity_rate": round(valid_count / total * 100, 1) if total else 0,
                    },
                    "conditions": {},
                    "columns": list(df.columns),
                    "rows": rows,
                    "log": ["Loaded from existing report on disk."],
                    "source": "disk",
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500
        return jsonify({"status": "no_results"}), 404

    return jsonify(_last_result)


@app.route("/api/download")
def download():
    """Stream the final report CSV."""
    report_path = src.config.FINAL_REPORT_PATH
    if not report_path.exists():
        return jsonify({"error": "No report found. Run the pipeline first."}), 404
    return send_file(
        str(report_path),
        as_attachment=True,
        download_name="referral_fraud_report.csv",
        mimetype="text/csv",
    )


@app.route("/api/status")
def pipeline_status():
    return jsonify({"running": _pipeline_running})


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Referral Fraud Detection — Dashboard")
    print("=" * 60)
    print(f"  Dashboard:  http://localhost:5000")
    print(f"  Project:    {PROJECT_ROOT}")
    print("=" * 60)
    app.run(debug=True, port=5000, use_reloader=False)
