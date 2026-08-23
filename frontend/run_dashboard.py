"""
run_dashboard.py
----------------
Entrypoint for the Referral Fraud Detection dashboard.

Usage:
    python frontend/run_dashboard.py

Then open http://localhost:5000 in your browser.
"""

import subprocess
import sys
import webbrowser
from pathlib import Path


def main():
    frontend_dir = Path(__file__).resolve().parent

    # Auto-install frontend dependencies if not present
    try:
        # pyrefly: ignore [missing-import]
        import flask
        import flask_cors
    except ImportError:
        print("[INFO] Installing frontend dependencies...")
        req_file = frontend_dir / "requirements_frontend.txt"
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
        )

    # Open the browser after a short delay
    import threading
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://localhost:5000")

    threading.Thread(target=open_browser, daemon=True).start()

    # Launch the app
    from app import app
    print("=" * 60)
    print("Referral Fraud Detection — Dashboard")
    print("=" * 60)
    print("  Dashboard:  http://localhost:5000")
    print("=" * 60)
    app.run(debug=False, port=5000)


if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).resolve().parent)
    main()
