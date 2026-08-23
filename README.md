<div align="center">

# 🔍 Referral Fraud Detection Pipeline

### *Springer Capital · Internship Project*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Pandas](https://img.shields.io/badge/Pandas-2.3.3-150458?style=for-the-badge&logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![NumPy](https://img.shields.io/badge/NumPy-2.2.6-013243?style=for-the-badge&logo=numpy&logoColor=white)](https://numpy.org/)

> **An end-to-end data pipeline** that ingests 7 raw source tables, applies 9 business-logic rules, and surfaces potentially fraudulent referral rewards in a clean 46-row audit report.

</div>

---

## 📌 Table of Contents

- [Overview](#-overview)
- [Pipeline Architecture](#-pipeline-architecture)
- [Project Structure](#-project-structure)
- [Fraud Detection Rules](#-fraud-detection-rules)
- [Notable Data Findings](#-notable-data-findings)
- [Setup & Usage](#%EF%B8%8F-setup--usage)
  - [Docker (Recommended)](#-docker-recommended)
  - [Local (Python venv)](#-local-python-venv)
- [Data Profiling](#-data-profiling)
- [Output](#-output)
- [Tech Stack](#%EF%B8%8F-tech-stack)

---

## 🧠 Overview

Springer Capital's referral program rewards **existing users (referrers)** for bringing in **new users (referees)**. This pipeline processes 7 raw CSV tables, joins them into a single referral-level view, and evaluates each referral reward against fraud-detection business rules.

```
7 raw CSV tables  →  Clean & Join  →  Apply 9 Fraud Rules  →  46-row Audit Report
```

**Key outputs:**
- `is_business_logic_valid` flag per referral row
- Full intermediate condition columns for auditability (`v1_valid`, `i1_invalid`, etc.)
- A `referral_fraud_report.csv` matching the spec's 22-column output exactly

---

## 🏗 Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       REFERRAL FRAUD PIPELINE                           │
├─────────────┬──────────────┬───────────────┬─────────────┬─────────────┤
│  STEP 1     │   STEP 2     │   STEP 3      │   STEP 4    │   STEP 5    │
│  load.py    │  clean.py    │ transform.py  │fraud_rules  │  report.py  │
│             │              │               │    .py      │             │
│  Read 7     │  Parse UTC   │  Join all 7   │  Apply 9    │  Select 22  │
│  raw CSVs   │  timestamps  │  tables into  │  business   │  columns,   │
│  into       │  Fix dtypes  │  flat 46-row  │  rules →    │  resolve    │
│  DataFrames │  Initcap     │  table        │  is_valid   │  nulls, CSV │
│             │  Parse       │  Dedup logs   │  flag       │  output     │
│             │  reward_val  │  TZ localize  │             │             │
└─────────────┴──────────────┴───────────────┴─────────────┴─────────────┘
```

**Data sources ingested:**

| Table | Description |
|---|---|
| `lead_log.csv` | Lead acquisition events |
| `user_referrals.csv` | Referral linkage records |
| `user_referral_logs.csv` | Referral status change history |
| `user_logs.csv` | User account event history |
| `user_referral_statuses.csv` | Status dimension table |
| `referral_rewards.csv` | Reward assignments per referral |
| `paid_transactions.csv` | Payment transaction records |

---

## 📁 Project Structure

```
.
├── script.py                    # 🚀 Entrypoint — run this
├── requirements.txt
├── Dockerfile
├── .dockerignore
│
├── data/
│   ├── raw/                     # 📥 Input CSVs go here
│   └── output/
│       └── referral_fraud_report.csv   # 📤 Generated report
│
├── src/
│   ├── config.py                # Paths, constants, documented data-quality findings
│   ├── load.py                  # Step 1 — load all 7 CSVs
│   ├── clean.py                 # Step 2 — dtype fixes, Initcap, null handling
│   ├── transform.py             # Step 3 — joins, TZ localization, source category
│   ├── fraud_rules.py           # Step 4 — 9 business rules → is_business_logic_valid
│   ├── report.py                # Step 5 — final columns, null resolution, CSV output
│   └── main.py                  # Orchestrates steps 1–5
│
├── profiling/
│   ├── profile_tables.py        # Standalone profiling script (run independently)
│   └── output/                  # Per-table profile CSVs + summary
│
├── docs/
│   └── data_dictionary.xlsx     # Column-by-column guide for non-technical readers
│
├── notebooks/                   # Exploratory analysis notebooks
└── tests/                       # Unit tests
```

---

## 🚨 Fraud Detection Rules

The pipeline evaluates each referral against **9 conditions** (2 valid, 7 invalid). The final `is_business_logic_valid` column reflects the combined result.

### ✅ Valid Conditions

| ID | Condition | Description |
|---|---|---|
| **V1** | Fully earned reward | `reward > 0`, status `Berhasil`, linked paid transaction exists, transaction is `New` type, occurs after referral in the same month, referrer active & not deleted, reward was granted |
| **V2** | Pending / failed — no reward | Status is `Menunggu` or `Tidak Berhasil` AND no reward value was assigned |

### ❌ Invalid Conditions

| ID | Condition | Description |
|---|---|---|
| **I1** | Reward without completion | `reward > 0` AND status ≠ `Berhasil` |
| **I2** | Reward without transaction | `reward > 0` AND no `transaction_id` linked |
| **I3** | Transaction without reward | No reward value, but has a paid transaction occurring after referral |
| **I4** | Completed without reward | Status `Berhasil` AND reward is null or 0 |
| **I5** | Backdated transaction | Transaction occurred *before* the referral was created |
| **I6** | *(Discovered)* Earned but never disbursed | Meets all V1 criteria except the reward grant log is missing |
| **I7** | *(Discovered)* Orphaned transaction reference | `transaction_id` referenced but does not exist in `paid_transactions` |

> **Note:** I6 and I7 were discovered during development by inspecting the actual data — they are not in the original spec.

---

## 🔬 Notable Data Findings

These were uncovered via `profiling/profile_tables.py` and follow-up investigation, not assumed from the spec. All are documented as inline comments in `src/config.py`.

| Finding | Detail |
|---|---|
| 📝 **`reward_value` is a string** | Stored as `"10 days"` — parsed into `num_reward_days` before any numeric comparison |
| 🔁 **Duplicate rows** | `user_logs`, `lead_logs`, `user_referral_logs` all have repeated entries per entity; deduped before joining to prevent row fan-out |
| 👻 **Orphaned references** | 3 Lead-sourced referrals → missing `referee_id` in `lead_logs`; 4 referrals → missing `referrer_id` in `user_logs`; 2 referrals → missing `transaction_id` in `paid_transactions` (flagged as I7) |
| ⏰ **V1 never fires on this dataset** | None of the 46 referrals have a matching `is_reward_granted = True` log; the 3 rows closest to qualifying are captured under I6 |
| 🌏 **Mixed timezones** | Timestamps use both `Asia/Jakarta` and `Asia/Makassar` — localization is applied per-row, not globally |

---

## ⚙️ Setup & Usage

### Input files required

Place these **7 files** in `data/raw/` before running:

```
data/raw/lead_log.csv
data/raw/user_referrals.csv
data/raw/user_referral_logs.csv
data/raw/user_logs.csv
data/raw/user_referral_statuses.csv
data/raw/referral_rewards.csv
data/raw/paid_transactions.csv
```

> If filenames differ, update `RAW_FILES` in `src/config.py`.

---

### 🐳 Docker (Recommended)

No local Python environment needed.

```bash
# 1. Build the image
docker build -t referral-pipeline .

# 2. Run — mounts output dir so the report lands on your host machine
docker run -v "$(pwd)/data/output:/app/data/output" referral-pipeline
```

The report will be at `data/output/referral_fraud_report.csv` on your machine.

---

### 🐍 Local (Python venv)

```bash
# 1. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the pipeline
python script.py
```

---

## 📊 Data Profiling

Profiling is a **standalone step** — it inspects raw tables before any cleaning and produces null counts, distinct value counts, min/max values, etc.

```bash
python profiling/profile_tables.py
```

**Output** (written to `profiling/output/`):
- One `<table_name>_profile.csv` per input table
- `_profiling_summary.csv` — aggregated view across all tables

---

## 📤 Output

| Property | Value |
|---|---|
| **File** | `data/output/referral_fraud_report.csv` |
| **Rows** | 46 (validated at runtime — pipeline fails if count is wrong) |
| **Columns** | 22 (spec-defined) |
| **Nulls** | 0 (validated at runtime — all nulls resolved before output) |
| **Data Dictionary** | `docs/data_dictionary.xlsx` |

---

## 🛠️ Tech Stack

| Library | Version | Purpose |
|---|---|---|
| `pandas` | 2.3.3 | Core data manipulation and joining |
| `numpy` | 2.2.6 | Numeric operations and null handling |
| `pytz` | 2026.3 | Per-row timezone localization |
| `openpyxl` | 3.1.5 | Reading `data_dictionary.xlsx` |
| `tzdata` | 2026.3 | Timezone database |
| Python | 3.11+ | Runtime |
| Docker | — | Containerized execution |

---

<div align="center">

*Built as part of an internship at Springer Capital · 2026*

</div>
