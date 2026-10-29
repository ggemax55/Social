#!/bin/bash
# One-time setup of the GGRap analyzer on a Mac.
#   bash ggrap/analyzer/setup_mac.sh
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  echo "Python 3.9+ is needed. macOS will offer to install the developer tools now; accept, then run this script again."
  xcode-select --install 2>/dev/null || true
  exit 1
fi

# ffmpeg lets the analyzer read .m4a and .aac files (mp3, wav and flac work without it).
if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
  else
    echo "Note: ffmpeg not found. mp3, wav and flac will work; for m4a/aac install Homebrew (https://brew.sh), then: brew install ffmpeg"
  fi
fi

echo "Creating a private Python environment in ggrap/analyzer/.venv ..."
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

mkdir -p "$HOME/Music/GGRap-library"
echo
echo "Done. Put songs in ~/Music/GGRap-library, one folder per artist or style, then run:"
echo "  ggrap/analyzer/.venv/bin/python ggrap/analyzer/analyze.py ~/Music/GGRap-library"
