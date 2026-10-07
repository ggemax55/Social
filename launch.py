"""Start InvestTrack: update it, install what it needs, and open it in your browser.

Used by start-windows.bat and start-mac.command; you can also run `python launch.py`.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8501
URL = f"http://localhost:{PORT}"
HERE = Path(__file__).resolve().parent


def update() -> None:
    """Install the newest version, then restart this launcher so new code runs."""
    sys.path.insert(0, str(HERE))
    from investapp import updater

    if updater.run():
        sys.exit(subprocess.call([sys.executable, str(HERE / "launch.py"), "--no-update"]))


def install_requirements() -> None:
    """pip install, skipped when requirements.txt hasn't changed since the last success."""
    req = HERE / "requirements.txt"
    stamp = Path(sys.prefix) / ".investtrack-requirements"
    digest = hashlib.sha256(req.read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text() == digest:
        return
    print("Installing the packages InvestTrack needs (first start takes a few minutes)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                           "--quiet", "-r", str(req)])
    try:
        stamp.write_text(digest)
    except OSError:
        pass  # not in a virtual environment we can write to; just install again next time


def server_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=1) as resp:
            return resp.status == 200
    except OSError:
        return False


def main() -> int:
    if "--no-update" not in sys.argv:
        update()
    install_requirements()
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(HERE / "app.py"),
         "--server.port", str(PORT), "--server.headless", "true"],
        cwd=HERE,
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
