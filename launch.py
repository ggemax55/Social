"""Start InvestTrack and open it in your web browser.

Used by start-windows.bat and start-mac.command; you can also run `python launch.py`.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8501
URL = f"http://localhost:{PORT}"


def server_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=1) as resp:
            return resp.status == 200
    except OSError:
        return False


def main() -> int:
    here = Path(__file__).resolve().parent
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(here / "app.py"),
         "--server.port", str(PORT), "--server.headless", "true"],
        cwd=here,
    )
    for _ in range(240):  # wait up to about 2 minutes
        if server.poll() is not None:
            print(f"\nInvestTrack stopped. If it says port {PORT} is already in use, "
                  f"the app is probably open already: {URL}")
            return server.returncode or 1
        if server_is_up():
            break
        time.sleep(0.5)
    webbrowser.open(URL)
    print(f"\nInvestTrack is running at {URL}")
    print("Keep this window open while you use the app. Close it (or press Ctrl+C) to stop.\n")
    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
