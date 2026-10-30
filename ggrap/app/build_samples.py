"""Pack the instrument samples the in-app beat maker uses into one JSON blob (Opus, base64).

    python ggrap/app/build_samples.py out.json

Instruments (all CC0): Drumatic drum hits, and from VS Chamber Orchestra CE the
upright piano, violin and cello sections, pizzicato violins, contrabass and
flute. Each multisampled instrument keeps one velocity layer, trimmed to a
few seconds, which is plenty for loops and keeps the app small.
"""
import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLES = Path(__file__).parent.parent / "beats" / "samples"
PC = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
NOTE_RE = re.compile(r"_([A-G]#?)(-?\d)_v(\d)")

DRUMS = {  # name in the app -> Drumatic hit
    "kick": "Rap_Kit_00", "kick2": "Natural_Kit_00", "kick3": "Brutal_Kit_00",
    "snare": "Rap_Kit_02", "snare2": "Natural_Kit_02", "snare808": "TR808_02", "clap": "TR808_03",
    "hat": "Natural_Kit_06", "ohat": "Natural_Kit_10", "hat808": "TR808_07", "ohat808": "TR808_11",
    "rim": "Natural_Kit_01", "tomL": "Natural_Kit_05", "tomM": "Natural_Kit_07", "tomH": "Natural_Kit_09",
    "tom808L": "TR808_05", "tom808M": "TR808_08", "tom808H": "TR808_10",
}
INSTRUMENTS = {  # name -> (folder, file filter, seconds kept)
    "piano": ("Keys/Upright Piano", "Player_dyn2_rr1_*.wav", 3.5),
    "pizz": ("Strings/Violin Section/Pizz", "*_v1_rr1.wav", 1.2),
    "violins": ("Strings/Violin Section/susVib", "*_v1.wav", 4.0),
    "cellos": ("Strings/Cello Section/susvib", "*_v1_1.wav", 4.0),
    "bass": ("Strings/Solo Contrabass/Pizz", "*_v1_rr1.wav", 1.6),
    "flute": ("Woodwinds/Flute/susvib", "*_v1_1.wav", 3.0),
}


def encode(y: np.ndarray, sr: int, keep: float | None = None) -> str:
    if y.ndim == 1:
        y = y[:, None]
    a = int(np.argmax(np.abs(y).max(1) > 0.02 * np.abs(y).max()))  # start right at the attack
    y = y[max(0, a - 32):]
    if keep:
        n = int(keep * sr)
        if len(y) > n:
            y = y[:n].copy()
            f = int(0.25 * sr)
            y[-f:] *= np.linspace(1, 0, f)[:, None]
    with tempfile.TemporaryDirectory() as d:
        w, o = Path(d) / "x.wav", Path(d) / "x.ogg"
        sf.write(w, y, sr)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(w), "-c:a", "libopus", "-b:a", "96k", str(o)], check=True)
        return base64.b64encode(o.read_bytes()).decode()


def midi_of(path: Path, folder: str) -> int | None:
    if folder.startswith("Keys/Upright"):
        idx = int(re.search(r"_(\d+)\.wav$", path.name).group(1))
        return 21 + 2 * idx if idx < 44 else 108
    m = NOTE_RE.search(path.name)
    return (int(m.group(2)) + 2) * 12 + PC[m.group(1)] if m else None  # VSCO: middle C = C3


def main():
    out = {"drums": {}, "inst": {}}
    for name, hit in DRUMS.items():
        y, sr = sf.read(SAMPLES / "drums" / f"{hit}.wav")
        out["drums"][name] = encode(y, sr)
    for name, (folder, pattern, keep) in INSTRUMENTS.items():
        zones = {}
        for p in sorted((SAMPLES / "vsco" / folder).glob(pattern)):
            midi = midi_of(p, folder)
            if midi is None or midi in zones:
                continue
            y, sr = sf.read(p)
            zones[midi] = encode(y, sr, keep)
        out["inst"][name] = {str(k): v for k, v in sorted(zones.items())}
        print(name, len(zones), "notes", min(zones), "-", max(zones))
    Path(sys.argv[1]).write_text(json.dumps(out, separators=(",", ":")))
    print("samples", round(Path(sys.argv[1]).stat().st_size / 1e6, 2), "MB")


if __name__ == "__main__":
    main()
