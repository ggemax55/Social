"""GGRap beat maker v2: real sampled instruments.

Writes each part as MIDI, plays it through FluidSynth with the FluidR3 General
MIDI instrument library (recorded drums, Rhodes, upright bass, vibraphone,
strings, brass), then mixes the stems with studio effects (compression,
chorus, reverb, delay, saturation) using pedalboard.

    python ggrap/beats/make_beat_real.py out.wav

Needs: fluidsynth + a .sf2 sound font (apt: fluidsynth fluid-soundfont-gm,
mac: brew install fluid-synth + any GM .sf2), and pip: mido pedalboard soundfile.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import mido
import numpy as np
import soundfile as sf
from pedalboard import (Chorus, Compressor, Delay, Distortion, Gain, HighpassFilter, Limiter, LowpassFilter,
                        LowShelfFilter, Pedalboard, Reverb)

SR = 44100
SF2 = next((p for p in ["/usr/share/sounds/sf2/FluidR3_GM.sf2", "/opt/homebrew/share/soundfonts/default.sf2",
                        str(Path.home() / "soundfonts/FluidR3_GM.sf2")] if Path(p).exists()), None)
rng = np.random.default_rng(90)

BPM = 90
SWING = 0.30          # late 16ths, as a share of a 16th note
TPB = 480             # MIDI ticks per beat
BAR = 4 * TPB

# Song map: section name, bars
FORM = [("intro", 4), ("verse", 16), ("hook", 8), ("verse", 8), ("hook", 8), ("outro", 4)]

# 4-bar loop in D minor: Dm9 | Gm9 | Bbmaj9 | A7(b9). Rootless Rhodes voicings, upright bass roots.
CHORDS = [[53, 57, 60, 64], [53, 57, 58, 62], [53, 57, 60, 62], [55, 58, 61, 64]]
ROOTS = [38, 31, 34, 33]
# Vibraphone hook (beat offset, MIDI, length in beats): an original 2-bar motif, answered on bars 3-4.
HOOK = [(0, 69, .5), (.75, 72, .25), (1.5, 74, .5), (2.5, 77, 1), (4, 76, .5), (4.5, 74, .5), (5.5, 72, .5),
        (6.5, 69, 1.5), (8, 69, .5), (8.75, 72, .25), (9.5, 74, .5), (10.5, 77, .75), (11.5, 79, .5),
        (12, 76, .5), (12.5, 74, .5), (13, 73, .5), (13.5, 72, .5), (14.5, 69, 1.5)]

# GM drum notes
KICK, RIM, SNARE, HAT, OPEN_HAT, CRASH, SHAKER = 36, 37, 38, 42, 46, 49, 70


def tick(beat: float) -> int:
    """Beat position to ticks, pushing every second 16th late for swing."""
    sixteenth = round(beat * 4, 6)
    t = beat * TPB
    if abs(sixteenth - round(sixteenth)) < 1e-6 and int(round(sixteenth)) % 2 == 1:
        t += SWING * TPB / 4
    return int(round(t))


class Part:
    def __init__(self, program: int, channel: int = 0, bank: int | None = None):
        self.events = []  # (tick, on/off, note, velocity)
        self.program, self.channel, self.bank = program, channel, bank

    def note(self, beat: float, note: int, length: float, vel: int, humanize: float = 6):
        jitter = int(rng.normal(0, humanize / 1000 * BPM / 60 * TPB)) if humanize else 0
        start = max(0, tick(beat) + jitter)
        end = max(start + 10, tick(beat + length) + jitter - 5)
        v = int(np.clip(vel + rng.normal(0, 6), 20, 127))
        self.events += [(start, 1, note, v), (end, 0, note, 0)]

    def save(self, path: Path):
        mid = mido.MidiFile(ticks_per_beat=TPB)
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))
        if self.bank is not None:
            tr.append(mido.Message("control_change", channel=self.channel, control=0, value=self.bank))
        tr.append(mido.Message("program_change", channel=self.channel, program=self.program))
        now = 0
        for t, on, n, v in sorted(self.events, key=lambda e: (e[0], e[1])):
            tr.append(mido.Message("note_on" if on else "note_off", channel=self.channel, note=n, velocity=v,
                                   time=t - now))
            now = t
        tr.append(mido.MetaMessage("end_of_track", time=TPB * 8))
        mid.save(path)


def compose():
    drums = Part(16, channel=9)                  # Power kit (drum channel picks the kit bank)
    bass = Part(32)                              # Acoustic (upright) bass
    keys = Part(4)                               # Electric Piano 1 (Rhodes)
    vibes = Part(11)                             # Vibraphone
    strings = Part(49)                           # Slow strings
    brass = Part(61)                             # Brass section
    kicks = []

    bar = 0
    for section, n in FORM:
        for b in range(n):
            x = bar * 4                          # beat where this bar starts
            c = b % 4
            drums_on = section in ("verse", "hook")
            if b == 0 and section in ("verse", "hook"):
                drums.note(x, CRASH, 2, 90)
            if drums_on:
                for s in (0, 7, 10) + ((15,) if c == 3 else ()):
                    drums.note(x + s / 4, KICK, .25, 112 if s == 0 else 98, humanize=0)
                    kicks.append(x + s / 4)
                for s in (4, 12):
                    drums.note(x + s / 4, SNARE, .25, 115, humanize=3)
                for s in (6, 14) if c % 2 else (14,):
                    drums.note(x + s / 4, RIM, .25, 45)
                for s in range(0, 16, 2):
                    if c == 3 and s == 14:
                        drums.note(x + s / 4, OPEN_HAT, .5, 80)
                    else:
                        drums.note(x + s / 4, HAT, .25, 92 if s % 4 == 0 else 68)
                if c in (1, 3):
                    drums.note(x + 11 / 4, HAT, .25, 55)
                if section == "hook":
                    for s in range(16):
                        drums.note(x + s / 4, SHAKER, .25, 60 if s % 2 else 40)

            # Upright bass: root, octave answer, root, chromatic walk into the next chord
            if section not in ("intro", "outro"):
                root, nxt = ROOTS[c], ROOTS[(c + 1) % 4]
                bass.note(x, root, 1.4, 100)
                bass.note(x + 1.75, root + 12, .4, 80)
                bass.note(x + 2.5, root + 7, .5, 88)
                bass.note(x + 3, root, .6, 92)
                bass.note(x + 3.5, nxt + (1 if nxt < root else -1), .45, 85)

            # Rhodes comping: on 1, anticipate the "and" of 2, short stab on the "and" of 4
            vel = 70 if section in ("intro", "outro") else 82
            for beat, ln in ((0, 1.4), (2.5, 1.0), (3.5, .4)):
                for m in CHORDS[c]:
                    keys.note(x + beat, m, ln, vel - (8 if beat == 3.5 else 0))

            if section in ("hook", "outro"):
                for beat, m, ln in HOOK:
                    if c * 4 <= beat < c * 4 + 4:
                        vibes.note(x + beat - c * 4, m, ln, 88)
            if section == "hook":
                for m in CHORDS[c]:
                    strings.note(x, m - 12 if m > 60 else m, 4, 58, humanize=0)
                if c == 3:
                    for beat in (2, 2.75):
                        for m in (61, 64, 67, 70):
                            brass.note(x + beat, m, .35, 96)
            bar += 1
    total_beats = bar * 4
    return {"drums": drums, "bass": bass, "keys": keys, "vibes": vibes, "strings": strings, "brass": brass}, kicks, total_beats


def render_stem(part: Part, tmp: Path, name: str, length: int) -> np.ndarray:
    mid, wav = tmp / f"{name}.mid", tmp / f"{name}.wav"
    part.save(mid)
    subprocess.run(["fluidsynth", "-ni", "-q", "-R", "0", "-C", "0", "-g", "0.7", "-r", str(SR), "-F", str(wav),
                    SF2, str(mid)], check=True, capture_output=True)
    y, _ = sf.read(wav, dtype="float32", always_2d=True)
    out = np.zeros((length, 2), dtype=np.float32)
    out[:min(length, len(y))] = y[:length]
    return out


FX = {
    "drums": Pedalboard([LowShelfFilter(cutoff_frequency_hz=90, gain_db=4), Compressor(threshold_db=-20, ratio=4,
                         attack_ms=8, release_ms=90), Distortion(drive_db=5), LowpassFilter(11000), Gain(3)]),
    "bass": Pedalboard([HighpassFilter(35), Compressor(threshold_db=-22, ratio=5, attack_ms=10, release_ms=120),
                        LowpassFilter(3000), Gain(6)]),
    "keys": Pedalboard([HighpassFilter(140), Chorus(rate_hz=0.7, depth=0.25, mix=0.35), LowpassFilter(7500),
                        Reverb(room_size=0.35, wet_level=0.14, dry_level=0.9), Gain(1)]),
    "vibes": Pedalboard([HighpassFilter(250), Delay(delay_seconds=60 / BPM * 0.75, feedback=0.25, mix=0.18),
                         Reverb(room_size=0.5, wet_level=0.22, dry_level=0.85), Gain(0)]),
    "strings": Pedalboard([HighpassFilter(220), Reverb(room_size=0.8, wet_level=0.4, dry_level=0.6), Gain(-5)]),
    "brass": Pedalboard([HighpassFilter(180), Compressor(threshold_db=-16, ratio=3), Reverb(room_size=0.3,
                         wet_level=0.15, dry_level=0.9), Gain(-3)]),
}
LEVELS = {"drums": 1.0, "bass": 0.9, "keys": 0.55, "vibes": 0.5, "strings": 0.35, "brass": 0.45}


def main(out_path: str):
    if not SF2:
        sys.exit("No General MIDI sound font found. Install fluid-soundfont-gm (Linux) or put FluidR3_GM.sf2 in ~/soundfonts.")
    parts, kicks, total_beats = compose()
    length = int(SR * (total_beats * 60 / BPM + 3))
    mix = np.zeros((length, 2), dtype=np.float32)
    with tempfile.TemporaryDirectory() as d:
        for name, part in parts.items():
            stem = render_stem(part, Path(d), name, length)
            stem = FX[name](stem.T.copy(), SR).T[:length]
            if name in ("bass", "keys"):
                # Duck under each kick so the low end stays clean (sidechain feel)
                duck = np.ones(length, dtype=np.float32)
                for k in kicks:
                    i = int((k * 60 / BPM) * SR)
                    seg = np.linspace(0.6 if name == "bass" else 0.8, 1, int(SR * 0.14))
                    duck[i:i + len(seg)] = np.minimum(duck[i:i + len(seg)], seg[:max(0, length - i)])
                stem *= duck[:, None]
            mix[:len(stem)] += stem * LEVELS[name]

    # Intro and outro through a low-pass, like the record is playing in another room
    bar_s = 4 * 60 / BPM
    intro_end = int(SR * bar_s * FORM[0][1])
    outro_start = int(SR * bar_s * (sum(n for _, n in FORM) - FORM[-1][1]))
    muffled = Pedalboard([LowpassFilter(1500), Gain(7)])(mix.T.copy(), SR).T
    ramp = int(SR * 0.6)
    w = np.ones(length, dtype=np.float32)
    w[:intro_end] = 0
    w[intro_end:intro_end + ramp] = np.linspace(0, 1, ramp)
    w[outro_start:outro_start + ramp] = np.linspace(1, 0, ramp)
    w[outro_start + ramp:] = 0
    mix = mix * w[:, None] + muffled * (1 - w[:, None])

    # Vinyl: soft hiss and crackle
    hiss = 0.0025 * rng.standard_normal(length).astype(np.float32)
    pops = np.zeros(length, dtype=np.float32)
    idx = rng.integers(0, length, size=int(length / SR * 14))
    pops[idx] = rng.uniform(-0.08, 0.08, size=len(idx))
    mix += np.stack([hiss + pops, hiss + np.roll(pops, 29)], axis=1)

    master = Pedalboard([HighpassFilter(28), Gain(4), Compressor(threshold_db=-16, ratio=3, attack_ms=15, release_ms=150),
                         Gain(6), Limiter(threshold_db=-1.0, release_ms=120)])
    mix = master(mix.T.copy(), SR).T
    mix *= 0.95 / max(1e-6, np.abs(mix).max())
    fade = int(SR * 2)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    sf.write(out_path, mix, SR)
    print(f"Wrote {out_path}: {BPM} BPM, D minor, {sum(n for _, n in FORM)} bars")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "beat_real.wav")
