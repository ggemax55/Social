"""Download the free sample libraries the GGRap engine uses (all CC0 / public domain).

    python ggrap/beats/fetch_samples.py

- Drumatic 3 drum kits (CC0) from the Internet Archive: kicks, snares, claps,
  hats and toms from 5 kits, sliced into single hits.
- VS Chamber Orchestra Community Edition (CC0) by Versilian Studios: upright
  piano, violin and cello sections, pizzicato strings, contrabass, flute.

Files land in ggrap/beats/samples/ (not committed to git).
"""
import io
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

ROOT = Path(__file__).parent / "samples"
DRUMATIC = "https://archive.org/download/drumatic-samples/Drumatic%20Samples.zip"
VSCO = "https://github.com/sgossner/VSCO-2-CE.git"
VSCO_PARTS = ["/Keys/Upright Piano/*", "/Strings/Violin Section/susVib/*", "/Strings/Violin Section/Pizz/*",
              "/Strings/Cello Section/susvib/*", "/Strings/Solo Contrabass/Pizz/*", "/Woodwinds/Flute/susvib/*"]


def drumatic():
    out = ROOT / "drums"
    if out.exists():
        return
    print("Downloading Drumatic kits (14 MB)...")
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(DRUMATIC, timeout=120).read()))
    out.mkdir(parents=True)
    for name in z.namelist():
        if not name.endswith(".wav"):
            continue
        kit = Path(name).stem.replace("Drumatic ", "").replace(" ", "_")
        y, sr = sf.read(io.BytesIO(z.read(name)), always_2d=True)
        # Each kit is one recording of every hit in a row: cut at the silences.
        for i, (a, b) in enumerate(librosa.effects.split(y.mean(1), top_db=45, frame_length=1024, hop_length=256)):
            if b - a > sr * 0.03:
                sf.write(out / f"{kit}_{i:02d}.wav", y[a:b], sr)


def vsco():
    out = ROOT / "vsco"
    if out.exists():
        return
    print("Downloading VS Chamber Orchestra CE instruments (about 750 MB)...")
    subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", "--depth", "1", VSCO, str(out)], check=True)
    subprocess.run(["git", "-C", str(out), "sparse-checkout", "init", "--no-cone"], check=True)
    subprocess.run(["git", "-C", str(out), "sparse-checkout", "set", *VSCO_PARTS], check=True)
    subprocess.run(["git", "-C", str(out), "checkout", "-q", "HEAD"], check=True)


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    drumatic()
    vsco()
    print("Samples ready in", ROOT)
