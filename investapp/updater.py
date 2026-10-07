"""Keep the app up to date from GitHub, without git and without touching your data.

`python -m investapp.updater` downloads the newest version if there is one. The
launchers (start-windows.bat / start-mac.command) run it on every start.
Only the Python standard library is used, so it works before packages are installed.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = "ggemax55/Social"
ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / ".version"
KEEP = {"data", "reports", ".venv", "venv", ".git", ".version"}  # never replaced
API = f"https://api.github.com/repos/{REPO}"


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "InvestTrack-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def local_version() -> str | None:
    try:
        return VERSION_FILE.read_text().strip() or None
    except OSError:
        return None


def remote_version(timeout: float = 5) -> str:
    """Latest commit id on the repository's default branch."""
    branch = json.loads(_get(API, timeout))["default_branch"]
    return json.loads(_get(f"{API}/commits/{branch}", timeout))["sha"]


def is_git_checkout() -> bool:
    return (ROOT / ".git").exists()


def update_available(timeout: float = 5) -> bool | None:
    """True/False, or None when it can't be checked (offline, or a git checkout)."""
    if is_git_checkout():
        return None
    try:
        return remote_version(timeout) != local_version()
    except (OSError, ValueError, KeyError):
        return None


def apply_update(sha: str, timeout: float = 60) -> int:
    """Download version `sha` and copy it over the app. Returns the number of files changed."""
    archive = zipfile.ZipFile(io.BytesIO(_get(f"https://codeload.github.com/{REPO}/zip/{sha}", timeout)))
    changed = 0
    with tempfile.TemporaryDirectory() as tmp:
        archive.extractall(tmp)
        (top,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
        for src in top.rglob("*"):
            rel = src.relative_to(top)
            if not src.is_file() or rel.parts[0] in KEEP:
                continue
            dst = ROOT / rel
            if dst.exists() and dst.read_bytes() == src.read_bytes():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changed += 1
    VERSION_FILE.write_text(sha)
    return changed


def run(timeout: float = 5) -> bool:
    """Check and install an update. Returns True if files changed."""
    if is_git_checkout():
        print("This folder is a git checkout: use 'git pull' to update.")
        return False
    try:
        sha = remote_version(timeout)
    except (OSError, ValueError, KeyError):
        print("Could not check for updates (no internet?). Starting the current version.")
        return False
    if sha == local_version():
        print("InvestTrack is up to date.")
        return False
    print("Downloading the newest version of InvestTrack...")
    try:
        changed = apply_update(sha)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print(f"Update failed ({e}). Starting the current version.")
        return False
    print(f"Updated ({changed} files changed). Your data was not touched.")
    return changed > 0


if __name__ == "__main__":
    run()
    sys.exit(0)
