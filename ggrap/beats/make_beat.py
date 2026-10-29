"""GGRap beat maker: renders an original beat from a recipe.

The recipe below comes from analyzing a reference track (tempo, key, groove,
bass weight, vocal space). The parts themselves (bass riff, chords, drums,
horns) are written fresh, so the result shares the style, not the song.

    python ggrap/beats/make_beat.py out.wav
"""
from __future__ import annotations

import sys

import numpy as np
import soundfile as sf

SR = 44100
rng = np.random.default_rng(96)

# Recipe: measured from a 90s East Coast reference (96 BPM, E, one-chord groove,
# heavy bass, 8th hats with extra 16ths, bright, lots of room for vocals).
RECIPE = {
    "name": "Hypno Groove",
    "bpm": 96,
    "swing": 0.14,  # how late every second 16th lands (0 = straight)
    "kick": [0, 7, 10],
    "snare": [4, 12],
    "ghost_snare": [14],
    "hats": [0, 2, 3, 4, 6, 8, 10, 11, 12, 14],
    "open_hat": [15],
    # Bass riff in E (step, MIDI note, length in 16ths). Written for this beat.
    "bass": [(0, 40, 3), (3, 40, 1), (4, 43, 1), (6, 45, 2), (8, 40, 2), (10, 38, 1), (11, 40, 1),
             (13, 43, 1), (14, 46, 1), (15, 47, 1)],
    # Turnaround riff for every 4th bar
    "bass_turn": [(0, 40, 3), (3, 40, 1), (4, 43, 2), (6, 45, 2), (8, 43, 2), (10, 45, 2), (12, 47, 2), (14, 38, 2)],
    "chord": [56, 62, 67, 71],  # E7#9 voicing: G#3 D4 G4 B4
    "chord_steps": [2, 10],
    "horn_turn": [(12, [55, 59, 62]), (14, [57, 61, 64])],  # G and A stabs leading back to E
    # Song map: (section, bars)
    "form": [("intro", 4), ("main", 8), ("main", 8), ("break", 4), ("main", 8)],
}


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def t_(dur):
    return np.arange(int(SR * dur)) / SR


def kick():
    t = t_(0.45)
    f = 45 + 85 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 8) + 0.3 * rng.standard_normal(len(t)) * np.exp(-t * 300)


def snare(level=1.0):
    t = t_(0.25)
    n = rng.standard_normal(len(t))
    n = n - np.convolve(n, np.ones(6) / 6, mode="same")  # crude high-pass
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30)
    return level * (0.7 * n * np.exp(-t * 16) + 0.5 * body)


def hat(open_=False):
    t = t_(0.35 if open_ else 0.06)
    n = np.diff(np.diff(rng.standard_normal(len(t) + 2)))
    return 0.35 * n * np.exp(-t * (11 if open_ else 85))


def bass_note(midi, dur):
    """Additive saw with per-harmonic decay, so it sounds filtered and plucky."""
    t = t_(dur)
    f = mtof(midi)
    out = 0.8 * np.sin(2 * np.pi * f * t)  # sub
    for k in range(2, 9):
        out += (0.55 / k) * np.sin(2 * np.pi * f * k * t) * np.exp(-t * k * 5)
    env = np.minimum(1, t / 0.005) * np.exp(-t * 1.5)
    env[-int(SR * 0.02):] *= np.linspace(1, 0, int(SR * 0.02))
    return out * env


def keys(notes, dur):
    """Electric-piano style chord: sine + fast-fading bell partial, with tremolo."""
    t = t_(dur)
    out = np.zeros(len(t))
    for m in notes:
        f = mtof(m)
        out += np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 6)
        out += 0.12 * np.sin(2 * np.pi * 7 * f * t) * np.exp(-t * 25)
    trem = 1 + 0.18 * np.sin(2 * np.pi * 5.2 * t)
    return 0.16 * out * trem * np.exp(-t * 3) * np.minimum(1, t / 0.004)


def horn(notes, dur):
    t = t_(dur)
    out = np.zeros(len(t))
    for m in notes:
        f = mtof(m) * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))
        ph = 2 * np.pi * np.cumsum(f) / SR
        for k in range(1, 10):
            out += np.sin(k * ph) / k * (0.9 ** k)
    env = np.minimum(1, t / 0.025) * np.exp(-t * 4)
    return 0.12 * out * env


def render(recipe: dict) -> np.ndarray:
    step = 60 / recipe["bpm"] / 4
    bars = sum(b for _, b in recipe["form"])
    L = np.zeros(int(SR * step * 16 * bars) + SR * 2)
    R = np.zeros_like(L)

    def add(sig, at, gain=1.0, pan=0.0):
        i = int(at * SR)
        j = min(len(L), i + len(sig))
        L[i:j] += sig[: j - i] * gain * (1 - max(0, pan))
        R[i:j] += sig[: j - i] * gain * (1 + min(0, pan))

    def when(bar, s):
        return (bar * 16 + s) * step + (step * recipe["swing"] if s % 2 else 0)

    bar = 0
    for section, n in recipe["form"]:
        for b in range(n):
            turn = (b % 4) == 3
            drums = section in ("main",) or (section == "intro" and b >= 2)
            full = section == "main"
            if drums:
                for s in recipe["hats"]:
                    add(hat(), when(bar, s), 0.9 if s % 4 == 0 else 0.6, pan=0.3)
                for s in recipe["open_hat"]:
                    add(hat(True), when(bar, s), 0.5, pan=0.3)
            if full:
                for s in recipe["kick"]:
                    add(kick(), when(bar, s), 1.0)
                for s in recipe["snare"]:
                    add(snare(), when(bar, s), 0.9)
                for s in recipe["ghost_snare"]:
                    add(snare(0.3), when(bar, s), 0.9)
            if section in ("main", "break"):
                for s, m, ln in recipe["bass_turn" if turn else "bass"]:
                    add(bass_note(m, ln * step * 0.95), when(bar, s), 0.85)
            for s in recipe["chord_steps"]:
                add(keys(recipe["chord"], step * 6), when(bar, s), 1.0 if section != "intro" else 0.7, pan=-0.25)
            if turn and section == "main":
                for s, notes in recipe["horn_turn"]:
                    add(horn(notes, step * 2), when(bar, s), 1.0, pan=0.15)
            bar += 1

    # Vinyl texture: soft hiss and random crackles, like a sampled record.
    n = len(L)
    hiss = 0.004 * rng.standard_normal(n)
    pops = np.zeros(n)
    idx = rng.integers(0, n, size=int(n / SR * 18))
    pops[idx] = rng.uniform(-0.12, 0.12, size=len(idx))
    L += hiss + pops
    R += hiss + np.roll(pops, 37)

    mix = np.stack([L, R], axis=1)
    mix = np.tanh(mix * 1.6) / np.tanh(1.6)  # gentle saturation, glues the mix
    fade = int(SR * 1.5)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return 0.9 * mix / np.abs(mix).max()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "beat.wav"
    sf.write(out, render(RECIPE), SR)
    print(f"Wrote {out}: {RECIPE['name']}, {RECIPE['bpm']} BPM")
