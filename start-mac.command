#!/bin/bash
# Double-click to start InvestTrack on a Mac.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python is not installed. Install it from https://www.python.org/downloads/ and run this again."
  open "https://www.python.org/downloads/"
  read -r -p "Press Enter to close."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First start: setting things up. This takes a few minutes..."
  python3 -m venv .venv || { read -r -p "Setup failed. Press Enter to close."; exit 1; }
fi
echo "Checking for updates to the required packages..."
.venv/bin/python -m pip install --disable-pip-version-check --quiet -r requirements.txt \
  || { read -r -p "Install failed. Press Enter to close."; exit 1; }
.venv/bin/python launch.py
