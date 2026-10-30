"""GGRap generator v3: one generation = 4 loopable versions of a beat.

Every version is 4 bars in the same style, tempo and key, with its own
melody, instruments and chord loop. The last 2 beats of bar 4 are a
transition (drum fill, stop, riser or roll) that leads into whatever version
plays next, so versions can be chained in any order in the mixer.

    python ggrap/beats/fetch_samples.py           # once
    python ggrap/beats/generate.py boombap out/   # or: trap

Writes out/<style>/<A-D>.wav plus manifest.json for the mixer. Each file is
4 bars plus the reverb tail; the mixer starts the next loop exactly on the
bar line and lets the tail ring over it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import (Compressor, Delay, Distortion, Gain, HighpassFilter, Limiter, LowpassFilter,
                        LowShelfFilter, Pedalboard, Reverb)

SR = 44100
HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
TAIL = 2.5  # seconds of reverb tail kept after bar 4

PC = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
NOTE_RE = re.compile(r"_([A-G]#?)(-?\d)_v(\d)")


# ---------------------------------------------------------------- samples

def load(path: Path) -> np.ndarray:
    y, sr = sf.read(path, always_2d=True, dtype="float32")
    if y.shape[1] == 1:
        y = np.repeat(y, 2, axis=1)
    if sr != SR:
        idx = np.arange(0, len(y) - 1, sr / SR)
        y = np.stack([np.interp(idx, np.arange(len(y)), y[:, c]) for c in range(2)], axis=1).astype(np.float32)
    # Trim silence before the attack so every note starts exactly on time.
    a = np.argmax(np.abs(y).max(1) > 0.02 * np.abs(y).max())
    return y[max(0, a - 32):]


class Sampler:
    """Multi-sampled instrument: picks the nearest recorded note and velocity layer, then repitches it."""

    def __init__(self, zones: dict[tuple[int, int], list[np.ndarray]]):
        self.zones = zones
        self.notes = sorted({n for n, _ in zones})
        self.layers = sorted({v for _, v in zones})
        self.rr = 0

    @classmethod
    def vsco(cls, folder: str):
        zones = {}
        for p in sorted((SAMPLES / "vsco" / folder).glob("*.wav")):
            m = NOTE_RE.search(p.name)
            if m:  # VSCO names notes with middle C = C3
                midi = (int(m.group(2)) + 2) * 12 + PC[m.group(1)]
                zones.setdefault((midi, int(m.group(3))), []).append(load(p))
        return cls(zones)

    @classmethod
    def piano(cls):
        zones = {}
        for p in sorted((SAMPLES / "vsco" / "Keys" / "Upright Piano").glob("Player_dyn*_rr1_*.wav")):
            dyn, idx = re.search(r"dyn(\d)_rr1_(\d+)", p.name).groups()
            midi = 21 + 2 * int(idx) if int(idx) < 44 else 108  # from the library's MappingChart.txt
            zones.setdefault((midi, int(dyn)), []).append(load(p))
        return cls(zones)

    def render(self, midi: int, vel: float, dur: float, release: float = 0.3) -> np.ndarray:
        src = min(self.notes, key=lambda n: (abs(n - midi), n < midi))
        layer = self.layers[min(len(self.layers) - 1, int(vel * len(self.layers)))]
        if (src, layer) not in self.zones:
            layer = min((l for n, l in self.zones if n == src), key=lambda l: abs(l - layer))
        takes = self.zones[(src, layer)]
        self.rr += 1
        y = takes[self.rr % len(takes)]
        ratio = 2 ** ((midi - src) / 12)
        n = int((dur + release) * SR)
        pos = np.arange(n) * ratio
        pos = pos[pos < len(y) - 1]
        out = np.stack([np.interp(pos, np.arange(len(y)), y[:, c]) for c in range(2)], axis=1)
        env = np.ones(len(out), dtype=np.float32)
        r = int(release * SR)
        if len(out) > int(dur * SR):
            env[int(dur * SR):] = np.linspace(1, 0, len(out) - int(dur * SR))
        env[:64] = np.linspace(0, 1, 64)
        return (out * env[:, None] * (0.35 + 0.65 * vel)).astype(np.float32)


def drum(name: str) -> np.ndarray:
    return load(SAMPLES / "drums" / f"{name}.wav")


def eight08(midi: int, dur: float, slide_from: int | None = None, drive: float = 2.5) -> np.ndarray:
    """808 bass: sine with a short pitch drop, optional glide from the previous note, saturated."""
    t = np.arange(int((dur + 0.15) * SR)) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    freq = f * (1 + 0.6 * np.exp(-t * 40))
    if slide_from is not None:
        f0 = 440 * 2 ** ((slide_from - 69) / 12)
        g = np.clip(t / 0.09, 0, 1)
        freq = f0 + (freq - f0) * g
    ph = 2 * np.pi * np.cumsum(freq) / SR
    y = np.sin(ph) + 0.15 * np.sin(2 * ph)
    env = np.minimum(1, t / 0.004) * np.exp(-t * (1.1 / max(dur, 0.2)))
    env[t > dur] *= np.linspace(1, 0, int((t > dur).sum()))
    y = np.tanh(drive * y * env) / np.tanh(drive)
    return np.repeat(y[:, None], 2, axis=1).astype(np.float32)


# ---------------------------------------------------------------- music theory

MINOR = [0, 2, 3, 5, 7, 8, 10]
CHORDS = {  # degree in natural minor -> (semitones from key, intervals)
    "i": (0, [0, 3, 7, 10]), "iv": (5, [0, 3, 7, 10]), "v": (7, [0, 3, 7, 10]), "V": (7, [0, 4, 7, 10]),
    "VI": (8, [0, 4, 7, 11]), "III": (3, [0, 4, 7, 11]), "VII": (10, [0, 4, 7, 10]), "ii0": (2, [0, 3, 6, 10]),
}


def voice(key: int, degree: str, around: float = 62) -> list[int]:
    root, ivs = CHORDS[degree]
    pcs = [(key + root + i) % 12 for i in ivs]
    notes = []
    for pc in pcs:  # place each chord tone as close to the centre as possible
        cands = [pc + 12 * o for o in range(3, 7)]
        notes.append(min(cands, key=lambda n: abs(n - around)))
    return sorted(set(notes))


def bass_root(key: int, degree: str, low: int = 33) -> int:
    pc = (key + CHORDS[degree][0]) % 12
    return low + ((pc - low) % 12)


def melody(rng, key: int, prog: list[str], rhythm: list[list[tuple[float, float]]], lo: int, hi: int):
    """Chord tones on strong beats, scale steps in between, kept inside [lo, hi]."""
    scale = sorted({(key + s) % 12 + 12 * o for s in MINOR for o in range(2, 9)})
    scale = [n for n in scale if lo <= n <= hi]
    cur = scale[len(scale) // 2]
    out = []
    for bar, (deg, pattern) in enumerate(zip(prog, rhythm)):
        tones = [n for n in scale if (n - key - CHORDS[deg][0]) % 12 in [i % 12 for i in CHORDS[deg][1][:3]]]
        for beat, ln in pattern:
            if beat % 1 == 0 or rng.random() < 0.35:
                cur = min(tones, key=lambda n: abs(n - cur) + rng.random() * 3)
            else:
                i = scale.index(cur) + rng.choice([-2, -1, 1, 2])
                cur = scale[int(np.clip(i, 0, len(scale) - 1))]
            out.append((bar * 4 + beat, cur, ln))
    return out


# ---------------------------------------------------------------- arrangement

class Mix:
    def __init__(self, bpm: float, swing: float):
        self.beat = 60 / bpm
        self.swing = swing
        self.len = int((16 * self.beat + TAIL) * SR)
        self.stems: dict[str, np.ndarray] = {}

    def t(self, beat: float) -> float:
        sixteenth = round(beat * 4, 4)
        late = self.swing * self.beat / 4 if sixteenth % 2 == 1 else 0
        return beat * self.beat + late

    def add(self, stem: str, beat: float, sig: np.ndarray, gain: float = 1.0, pan: float = 0.0, jitter: float = 0.004):
        buf = self.stems.setdefault(stem, np.zeros((self.len, 2), dtype=np.float32))
        i = int((self.t(beat) + np.random.normal(0, jitter)) * SR) if jitter else int(self.t(beat) * SR)
        i = max(0, i)
        j = min(self.len, i + len(sig))
        if j <= i:
            return
        lr = np.array([1 - max(0, pan), 1 + min(0, pan)], dtype=np.float32)
        buf[i:j] += sig[: j - i] * gain * lr


FX = {
    "drums": [LowShelfFilter(cutoff_frequency_hz=80, gain_db=3), Compressor(threshold_db=-18, ratio=4, attack_ms=6,
              release_ms=80), Distortion(drive_db=4), Gain(2)],
    "bass": [HighpassFilter(30), Compressor(threshold_db=-20, ratio=4, attack_ms=8, release_ms=120), LowpassFilter(4000)],
    "808": [HighpassFilter(28), Compressor(threshold_db=-14, ratio=3)],
    "keys": [HighpassFilter(120), LowpassFilter(9000), Reverb(room_size=0.3, wet_level=0.12, dry_level=0.9)],
    "pizz": [HighpassFilter(150), Reverb(room_size=0.45, wet_level=0.18, dry_level=0.85)],
    "pad": [HighpassFilter(180), Reverb(room_size=0.85, wet_level=0.35, dry_level=0.65), Gain(-2)],
    "lead": [HighpassFilter(250), Delay(delay_seconds=0.33, feedback=0.22, mix=0.15),
             Reverb(room_size=0.55, wet_level=0.22, dry_level=0.85)],
    "fx": [HighpassFilter(300), Reverb(room_size=0.7, wet_level=0.3, dry_level=0.8)],
}


def finish(mix: Mix, levels: dict, dusty: bool) -> np.ndarray:
    out = np.zeros((mix.len, 2), dtype=np.float32)
    for name, buf in mix.stems.items():
        chain = FX.get(name, [])
        if name in ("keys", "pizz", "lead") and dusty:
            chain = chain + [LowpassFilter(6500), Distortion(drive_db=2)]
        y = Pedalboard(chain)(buf.T.copy(), SR).T if chain else buf
        out += y[: mix.len] * levels.get(name, 0.7)
    if dusty:  # vinyl hiss and crackle
        rng = np.random.default_rng(3)
        n = mix.len
        noise = 0.0022 * rng.standard_normal(n).astype(np.float32)
        pops = np.zeros(n, dtype=np.float32)
        idx = rng.integers(0, n, size=int(n / SR * 12))
        pops[idx] = rng.uniform(-0.06, 0.06, size=len(idx))
        out += np.stack([noise + pops, noise + np.roll(pops, 23)], axis=1)
    master = Pedalboard([HighpassFilter(25), Gain(3), Compressor(threshold_db=-14, ratio=2.5, attack_ms=12,
                                                                   release_ms=150), Gain(5), Limiter(threshold_db=-1)])
    out = master(out.T.copy(), SR).T
    return (0.95 * out / max(1e-6, np.abs(out).max())).astype(np.float32)


# ---------------------------------------------------------------- styles

def boombap(instr) -> dict:
    key, bpm = 2, 90  # D minor
    kick, snare, clap = drum("Rap_Kit_00"), drum("Rap_Kit_02"), drum("TR808_03")
    hat, ohat, ghost = drum("Natural_Kit_06"), drum("Natural_Kit_10"), drum("Natural_Kit_02")
    toms = [drum("Natural_Kit_05"), drum("Natural_Kit_07"), drum("Natural_Kit_09")]
    versions = [
        ("A", "Piano Soul", ["i", "VI", "III", "VII"], "keys", "snare roll"),
        ("B", "Pizz Strings", ["i", "iv", "VI", "V"], "pizz", "tom fill"),
        ("C", "String Drama", ["i", "VI", "iv", "V"], "pad", "stop + riser"),
        ("D", "Flute Dust", ["i", "VII", "VI", "VII"], "lead", "hat roll"),
    ]
    out = []
    for vid, name, prog, feature, transition in versions:
        rng = np.random.default_rng(ord(vid) * 7)
        np.random.seed(ord(vid))
        m = Mix(bpm, swing=0.28)
        fill = 14  # the transition takes beats 15-16 of the loop (0-based beat 14)
        for bar in range(4):
            x = bar * 4
            last = bar == 3
            kicks = [0, 1.75, 2.5] if bar % 2 == 0 else [0, 0.75, 2.5, 3.25]
            for k in kicks:
                if not (last and x + k >= fill):
                    m.add("drums", x + k, kick, 1.0, jitter=0)
            for s in (1, 3):
                if not (last and x + s >= fill and transition != "hat roll"):
                    m.add("drums", x + s, snare, 0.85)
                    m.add("drums", x + s + 0.01, clap, 0.35)
            if bar % 2:
                m.add("drums", x + 3.75, ghost, 0.25)
            for h in np.arange(0, 4, 0.5):
                if last and x + h >= fill:
                    continue
                if h == 3.5 and bar == 1:
                    m.add("drums", x + h, ohat, 0.45, pan=0.25)
                else:
                    m.add("drums", x + h, hat, 0.55 if h % 1 == 0 else 0.35, pan=0.25)
            # bass: contrabass pizz on the root with a pickup into the next chord
            deg, nxt = prog[bar], prog[(bar + 1) % 4]
            root = bass_root(key, deg, 33)
            for b, n, ln in ((0, root, 1.2), (1.75, root, 0.4), (2.5, root + 7, 0.5), (3.5, bass_root(key, nxt, 33), 0.4)):
                if not (last and x + b >= fill and transition == "stop + riser"):
                    m.add("bass", x + b, instr["bass"].render(n, 0.9, ln * m.beat), 1.0)
            chord = voice(key, deg, 63)
            if feature == "keys":  # piano comping on 1, and-of-2, a short stab on 4-and
                for b, ln, v in ((0, 1.4, 0.75), (1.5, 0.9, 0.6), (3.5, 0.3, 0.55)):
                    for n in chord:
                        m.add("keys", x + b, instr["piano"].render(n, v, ln * m.beat), 0.5, pan=-0.15)
            elif feature == "pizz":  # broken-chord pizzicato riff
                arp = [chord[i % len(chord)] + (12 if i >= len(chord) else 0) for i in (0, 2, 1, 3, 2, 4, 3, 1)]
                for i, n in enumerate(arp):
                    m.add("pizz", x + i * 0.5, instr["pizz"].render(n, 0.7, 0.4 * m.beat), 0.7, pan=0.2 * (-1) ** i)
                m.add("keys", x, sum_chord(instr["piano"], chord, 0.45, 3.5 * m.beat), 0.3)
            elif feature == "pad":  # held violins over a low cello line
                for n in chord:
                    m.add("pad", x, instr["violins"].render(n + 12 if n < 60 else n, 0.6, 3.9 * m.beat, 0.6), 0.45)
                m.add("pad", x, instr["cellos"].render(bass_root(key, deg, 45), 0.6, 3.9 * m.beat, 0.6), 0.5)
            else:  # flute over sparse piano
                m.add("keys", x, sum_chord(instr["piano"], chord, 0.5, 1.8 * m.beat), 0.4)
                m.add("keys", x + 2.5, sum_chord(instr["piano"], chord, 0.4, 1.2 * m.beat), 0.3)
        # melody line for every version (different seed and rhythm per version)
        rhythms = {
            "keys": [[(0.5, .5), (1, .5), (2, 1)], [(0, .5), (1.5, .5), (2, 1.5)], [(0.5, .5), (1, .5), (2, 1)], [(0, 1), (2, 1)]],
            "pizz": [[(3, .5)], [(3, .5)], [(3, .5)], [(2, .5)]],
            "pad": [[(0, 1.5), (2, 1.5)], [(0, 2)], [(0, 1.5), (2, 1.5)], [(0, 1.5)]],
            "lead": [[(0, 1), (1.5, .5), (2, 1.5)], [(0.5, .5), (1, 1), (2.5, 1)], [(0, 1), (1.5, .5), (2, 1.5)], [(0, 2)]],
        }[feature]
        lead_inst = {"keys": "piano", "pizz": "pizz", "pad": "piano", "lead": "flute"}[feature]
        lo, hi = {"flute": (72, 88), "piano": (69, 84), "pizz": (67, 84)}[lead_inst]
        for beat, n, ln in melody(rng, key, prog, rhythms, lo, hi):
            if beat < fill or transition == "hat roll":
                m.add("lead", beat, instr[lead_inst].render(n, 0.7, ln * m.beat), 0.55 if lead_inst != "flute" else 0.5)
        transitions(m, transition, fill, snare, toms, hat, ohat, kick)
        out.append((vid, name, prog, transition, m))
    return {"style": "Boom Bap", "bpm": bpm, "key": "D minor", "dusty": True, "versions": out,
            "levels": {"drums": 1.0, "bass": 0.9, "keys": 0.6, "pizz": 0.55, "pad": 0.5, "lead": 0.55, "fx": 0.5}}


def trap(instr) -> dict:
    key, bpm = 5, 140  # F minor, half-time feel
    kick, snare, clap = drum("Rap_Kit_00"), drum("TR808_02"), drum("TR808_03")
    hat, ohat = drum("TR808_07"), drum("TR808_11")
    toms = [drum("TR808_05"), drum("TR808_08"), drum("TR808_10")]
    versions = [
        ("A", "Dark Keys", ["i", "VI", "VII", "i"], "keys", "hat roll"),
        ("B", "Flute Wave", ["i", "iv", "VI", "V"], "lead", "stop + riser"),
        ("C", "Violin Night", ["i", "VI", "III", "VII"], "pad", "snare roll"),
        ("D", "Pizz Bounce", ["i", "VII", "VI", "V"], "pizz", "tom fill"),
    ]
    out = []
    for vid, name, prog, feature, transition in versions:
        rng = np.random.default_rng(ord(vid) * 11)
        np.random.seed(ord(vid) + 50)
        m = Mix(bpm, swing=0.0)
        fill = 14
        prev = None
        for bar in range(4):
            x = bar * 4
            last = bar == 3
            for k in ([0, 2.75] if bar % 2 == 0 else [0, 1.75, 2.5]):
                if not (last and x + k >= fill):
                    m.add("drums", x + k, kick, 0.9, jitter=0)
            if not (last and x + 2 >= fill and transition == "stop + riser"):
                m.add("drums", x + 2, clap, 0.8)
                m.add("drums", x + 2, snare, 0.5)
            # hats: 8ths with 16th and triplet rolls
            hb = 0.0
            while hb < 4:
                if not (last and x + hb >= fill):
                    m.add("drums", x + hb, hat, 0.5 if hb % 1 == 0 else 0.32, pan=0.2, jitter=0.002)
                step = 0.25 if (bar % 2 == 1 and 3 <= hb < 4) else (1 / 6 if (bar == 2 and 1 <= hb < 2) else 0.5)
                hb = round(hb + step, 4)
            if bar == 1:
                m.add("drums", x + 3.5, ohat, 0.4, pan=0.2)
            # 808 follows the chord roots with a glide into bar 3
            deg = prog[bar]
            n808 = bass_root(key, deg, 29)
            if not (last and transition == "stop + riser"):
                m.add("808", x, eight08(n808, 2.6 * m.beat, slide_from=prev if bar == 2 else None), 0.95, jitter=0)
                m.add("808", x + 2.75, eight08(n808, 1.0 * m.beat), 0.8, jitter=0)
            prev = n808
            chord = voice(key, deg, 65)
            if feature == "keys":
                for b, ln in ((0, 1.9), (2, 1.9)):
                    for n in chord:
                        m.add("keys", x + b, instr["piano"].render(n + 12, 0.45, ln * m.beat, 0.8), 0.35)
            elif feature == "pad":
                for n in chord:
                    m.add("pad", x, instr["violins"].render(n + 12 if n < 62 else n, 0.5, 3.9 * m.beat, 0.8), 0.45)
            elif feature == "pizz":
                arp = [chord[i % len(chord)] + 12 * (i // len(chord)) for i in (0, 1, 2, 3, 2, 1, 2, 4)]
                for i, n in enumerate(arp):
                    m.add("pizz", x + i * 0.5, instr["pizz"].render(n, 0.65, 0.35 * m.beat), 0.6, pan=0.25 * (-1) ** i)
            else:
                m.add("pad", x, sum_chord(instr["violins"], [n + 12 for n in chord[:3]], 0.4, 3.9 * m.beat), 0.25)
        rhythms = [[(0, .75), (0.75, .75), (1.5, .5), (2, 1)], [(0, .5), (0.5, .5), (1, 1), (3, .75)],
                   [(0, .75), (0.75, .75), (1.5, .5), (2, 1)], [(0, 1.5), (2, 1)]]
        lead_inst = {"keys": "piano", "lead": "flute", "pad": "piano", "pizz": "pizz"}[feature]
        lo, hi = {"flute": (72, 89), "piano": (72, 89), "pizz": (65, 82)}[lead_inst]
        for beat, n, ln in melody(rng, key, prog, rhythms, lo, hi):
            if beat < fill:
                m.add("lead", beat, instr[lead_inst].render(n, 0.65, ln * m.beat), 0.5)
        transitions(m, transition, fill, snare, toms, hat, ohat, kick)
        out.append((vid, name, prog, transition, m))
    return {"style": "Trap", "bpm": bpm, "key": "F minor", "dusty": False, "versions": out,
            "levels": {"drums": 1.0, "808": 0.95, "keys": 0.55, "pizz": 0.5, "pad": 0.45, "lead": 0.55, "fx": 0.5}}


def sum_chord(inst: Sampler, notes, vel, dur):
    parts = [inst.render(n, vel, dur) for n in notes]
    n = max(len(p) for p in parts)
    out = np.zeros((n, 2), dtype=np.float32)
    for p in parts:
        out[: len(p)] += p
    return out


def transitions(m: Mix, kind: str, fill: float, snare, toms, hat, ohat, kick):
    """The last 2 beats of the loop: a fill that leads into the next version."""
    if kind == "snare roll":
        for i in range(8):
            m.add("drums", fill + i * 0.25, snare, 0.35 + 0.08 * i)
    elif kind == "tom fill":
        for i, t in enumerate([0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75]):
            m.add("drums", fill + t, toms[min(2, i // 3)], 0.4)
        m.add("drums", fill + 1.75, kick, 0.8, jitter=0)
    elif kind == "stop + riser":
        # everything drops out; a reversed cymbal swells into the next downbeat
        rev = ohat[::-1]
        rev = np.concatenate([rev] * max(1, int(2 * m.beat * SR / len(rev)) + 1))[: int(2 * m.beat * SR)]
        swell = np.linspace(0, 1, len(rev)) ** 2
        m.add("fx", fill, (rev * swell[:, None]).astype(np.float32), 0.9, jitter=0)
    elif kind == "hat roll":
        t = 0.0
        while t < 2:
            m.add("drums", fill + t, hat, 0.3 + 0.25 * t, pan=0.2, jitter=0)
            t += 1 / 6 if t < 1 else 1 / 8
        m.add("drums", fill + 1.5, ohat, 0.5, pan=0.2)


def main():
    style = sys.argv[1] if len(sys.argv) > 1 else "boombap"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else HERE / "out") / style
    out.mkdir(parents=True, exist_ok=True)
    instr = {"piano": Sampler.piano(), "pizz": Sampler.vsco("Strings/Violin Section/Pizz"),
             "violins": Sampler.vsco("Strings/Violin Section/susVib"), "cellos": Sampler.vsco("Strings/Cello Section/susvib"),
             "bass": Sampler.vsco("Strings/Solo Contrabass/Pizz"), "flute": Sampler.vsco("Woodwinds/Flute/susvib")}
    gen = {"boombap": boombap, "trap": trap}[style](instr)
    beat = 60 / gen["bpm"]
    manifest = {"style": gen["style"], "bpm": gen["bpm"], "key": gen["key"], "bars": 4,
                "loop_seconds": round(16 * beat, 6), "versions": []}
    for vid, name, prog, transition, m in gen["versions"]:
        audio = finish(m, gen["levels"], gen["dusty"])
        sf.write(out / f"{vid}.wav", audio, SR, subtype="PCM_16")
        manifest["versions"].append({"id": vid, "name": name, "file": f"{vid}.wav",
                                     "chords": prog, "transition": transition})
        print(f"{style} {vid}: {name} ({' - '.join(prog)}), transition: {transition}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
