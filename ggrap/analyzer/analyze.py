"""GGRap style analyzer.

Measures what a beat or song is made of: tempo, key, chord loop, drum
density, bass weight and how much room it leaves for a rapper. Run it on a
folder of reference tracks for one artist or style to build a profile the
beat engine can use.

    python ggrap/analyzer/analyze.py tracks/drake/*.mp3 --profile "Drake" --out ggrap/analyzer/results

For big libraries (100+ songs) point it at a folder. It runs several songs at
once, skips songs it already measured, and sorts everything into categories:

    python ggrap/analyzer/analyze.py ~/Music/GGRap-library --workers 6

Put songs in one subfolder per artist or style (the folder name becomes the
label). Only measurements are stored, never the audio itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import tempfile

# librosa compiles parts of itself with numba and caches the result on disk.
# Parallel workers writing that cache at the same moment can corrupt it, which
# crashes Python later. Use our own cache folder and fill it once up front.
os.environ.setdefault("NUMBA_CACHE_DIR", str(Path(tempfile.gettempdir()) / f"ggrap-numba-{os.getpid()}"))

import librosa  # noqa: E402
import numpy as np  # noqa: E402

NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
# Krumhansl-Kessler key profiles
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
ROMAN_MAJOR = ["I", "bII", "II", "bIII", "III", "IV", "#IV", "V", "bVI", "VI", "bVII", "VII"]
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}


def chord_templates():
    names, temps = [], []
    for root in range(12):
        for quality, intervals in (("", (0, 4, 7)), ("m", (0, 3, 7))):
            t = np.zeros(12)
            t[[(root + i) % 12 for i in intervals]] = 1
            names.append((root, quality))
            temps.append(t / np.linalg.norm(t))
    return names, np.array(temps)


CHORD_NAMES, CHORD_TEMPLATES = chord_templates()


def detect_key(chroma_mean: np.ndarray):
    best = (-2.0, 0, "major")
    for root in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            r = np.corrcoef(chroma_mean, np.roll(profile, root))[0, 1]
            if r > best[0]:
                best = (r, root, mode)
    return best[1], best[2], float(best[0])


def roman(root: int, quality: str, key_root: int, key_mode: str) -> str:
    # Numerals are relative to the major scale of the tonic; for minor keys
    # this reads like "i - bVI - bIII - bVII", which producers recognise.
    interval = (root - key_root) % 12
    numeral = ROMAN_MAJOR[interval]
    return numeral.lower() if quality == "m" else numeral


def band_share(S: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    band = S[(freqs >= lo) & (freqs < hi)].sum()
    return float(band / (S.sum() + 1e-9))


def analyze(path: Path, clip: float | None = 120) -> dict:
    """Measure one track. By default only the middle `clip` seconds are used:
    intros and outros are often drumless, and it keeps big batches fast."""
    full = librosa.get_duration(path=str(path))
    offset = max(0.0, (full - clip) / 2) if clip and full > clip else 0.0
    y, sr = librosa.load(path, sr=22050, mono=True, offset=offset, duration=clip or None)
    duration = len(y) / sr
    y_harm, y_perc = librosa.effects.hpss(y)

    S = np.abs(librosa.stft(y, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    P = S ** 2

    # Tempo from kick and snare only (below 2 kHz), so 16th hi-hats can't
    # fool the tracker into odd tempos. Fold into the 60-180 range.
    low_env = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs < 2000]), sr=sr)
    tg = librosa.feature.tempogram(onset_envelope=low_env, sr=sr).mean(axis=1)
    bpms = librosa.tempo_frequencies(len(tg), sr=sr)
    cands = set()
    for i in np.argsort(-tg)[:12]:
        t = bpms[i]
        if not 40 < t < 400:
            continue
        while t < 60:
            t *= 2
        while t > 180:
            t /= 2
        cands.add(round(float(t), 1))

    # Swing and syncopated keys can fake a strong pulse at 2/3 or 3/2 speed.
    # So for each candidate we lay a beat grid over the song and keep the one
    # where the drum hits land on the grid the hardest.
    def alignment(t):
        _, b = librosa.beat.beat_track(onset_envelope=low_env, sr=sr, bpm=t, tightness=400)
        return low_env[b].mean() / (low_env.mean() + 1e-9) if len(b) > 3 else 0

    tempo = max(cands, key=alignment) if cands else 120.0
    # The tempogram is coarse (89.1 for a 90 BPM beat); refine from the tracked beats.
    _, beats = librosa.beat.beat_track(onset_envelope=low_env, sr=sr, start_bpm=tempo, tightness=200)
    beat_times = librosa.frames_to_time(beats, sr=sr)
    if len(beat_times) > 8:
        refined = 60 / float(np.median(np.diff(beat_times)))
        for k in (0.5, 1, 2):
            if abs(refined * k - tempo) / tempo < 0.06:
                tempo = refined * k
                break

    # Drums: how busy the top end is (hi-hats).
    high_env = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs > 5000]), sr=sr)
    hat_onsets = librosa.onset.onset_detect(onset_envelope=high_env, sr=sr)
    hats_per_beat = len(hat_onsets) / max(1, len(beats))

    # Kick and snare can land only every other beat (house kicks on 1 and 3,
    # trap snare on 3 only), so the low drums alone can read as half tempo.
    # Dense hi-hats at a slow tempo tell us to double it. If the hats are
    # still 16ths after doubling, the beat has a half-time feel (trap, drill).
    doubled = (tempo < 80 and hats_per_beat >= 3.5) or (tempo <= 90 and hats_per_beat >= 6)
    if doubled and tempo * 2 <= 200:
        tempo, hats_per_beat = tempo * 2, hats_per_beat / 2
    half_time = doubled and hats_per_beat >= 2.5
    alt = tempo / 2 if half_time or tempo >= 120 else tempo * 2

    # Key from the harmonic part only, so drums don't pull it around. Major
    # and its relative minor share notes, so the bass line breaks the tie.
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr)
    key_root, key_mode, key_conf = detect_key(chroma.mean(axis=1))
    bass = librosa.feature.chroma_cqt(y=y_harm, sr=sr, fmin=librosa.note_to_hz("C1"), n_octaves=2).mean(axis=1)
    rel_root, rel_mode = ((key_root + 9) % 12, "minor") if key_mode == "major" else ((key_root + 3) % 12, "major")
    if bass[rel_root] > bass[key_root] * 1.1:
        key_root, key_mode, rel_root, rel_mode = rel_root, rel_mode, key_root, key_mode

    # Chords: one per bar of 4 beats on a fixed time grid. We don't know
    # where bar 1 starts, so we try every half-beat offset and keep the grid
    # where chords fit most cleanly (changes usually land on the downbeat).
    bar_len = 4 * 60 / tempo
    frame_t = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr)
    frame_energy = chroma.sum() / max(1, chroma.shape[1])
    first = float(beat_times[0]) % (60 / tempo) if len(beat_times) else 0.0

    def bars_from(t0):
        names, fit, t = [], [], t0
        while t + bar_len * 0.5 < duration:
            sl = (frame_t >= t) & (frame_t < t + bar_len)
            v = np.median(chroma[:, sl], axis=1) if sl.any() else np.zeros(12)
            sc = CHORD_TEMPLATES @ (v / (np.linalg.norm(v) + 1e-9))
            if v.sum() < 0.1 * frame_energy or sc.max() < 0.6:
                names.append("N")
            else:
                r, q = CHORD_NAMES[int(sc.argmax())]
                names.append(NOTES[r] + q)
                fit.append(sc.max())
            t += bar_len
        return names, (np.mean(fit) if fit else 0)

    # Harmonic change curve: how different the chroma is just before and
    # just after each moment. Pick the grid whose bar lines hit the changes.
    w = max(2, int(0.3 * sr / 512))
    sm = np.cumsum(np.pad(chroma, ((0, 0), (1, 0))), axis=1)
    n_frames = chroma.shape[1]
    idx = np.arange(w, n_frames - w)
    before = (sm[:, idx] - sm[:, idx - w]) / w
    after = (sm[:, idx + w] - sm[:, idx]) / w
    cos = (before * after).sum(0) / (np.linalg.norm(before, axis=0) * np.linalg.norm(after, axis=0) + 1e-9)
    change = np.zeros(n_frames)
    change[idx] = 1 - cos

    def grid_score(t0):
        marks = np.arange(t0, duration, bar_len)
        frames = librosa.time_to_frames(marks, sr=sr)
        frames = frames[(frames > 0) & (frames < n_frames)]
        return change[frames].mean() if len(frames) else 0

    offsets = [first + k * 30 / tempo for k in range(8)]
    bar_chords = bars_from(max(offsets, key=grid_score))[0]
    # A loop is a cycle, so "F C G Am" and "Am F C G" are the same loop.
    # Merge rotations and start each one on the home chord when it has one.
    home = NOTES[key_root] + ("m" if key_mode == "minor" else "")
    merged = Counter()
    raw = Counter(
        tuple(bar_chords[i:i + 4]) for i in range(0, max(0, len(bar_chords) - 3)) if "N" not in bar_chords[i:i + 4]
    )
    for loop, n in raw.items():
        rots = [loop[i:] + loop[:i] for i in range(4)]
        merged[next((r for r in rots if r[0] == home), min(rots))] += n
    loops = merged.most_common(3)

    def to_roman(name: str) -> str:
        q = "m" if name.endswith("m") else ""
        return roman(NOTES.index(name[:-1] if q else name), q, key_root, key_mode)

    perc_share = float(np.sum(y_perc ** 2) / (np.sum(y ** 2) + 1e-9))

    rms = librosa.feature.rms(y=y)[0]
    centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())

    return {
        "file": path.name,
        "group": path.parent.name,
        "duration_s": round(full, 1),
        "measured_from_s": round(offset, 1),
        "tempo_bpm": round(tempo, 1),
        "tempo_alt_bpm": round(alt, 1),
        "half_time_feel": half_time,
        "first_beat_s": round(float(beat_times[0]) + offset, 3) if len(beat_times) else None,
        "key": f"{NOTES[key_root]} {key_mode}",
        "key_relative": f"{NOTES[rel_root]} {rel_mode}",
        "key_confidence": round(key_conf, 2),
        "chord_loops": [
            {"chords": list(loop), "roman": [to_roman(c) for c in loop], "times": n} for loop, n in loops
        ],
        "chords_per_bar": bar_chords,
        "hats_per_beat": round(hats_per_beat, 2),
        "drum_share": round(perc_share, 2),
        "bass_share": round(band_share(P, freqs, 20, 150), 2),
        "vocal_range_share": round(band_share(P, freqs, 300, 3000), 2),
        "brightness_hz": round(centroid),
        "loudness_db": round(float(librosa.amplitude_to_db(rms.mean())), 1),
    }


def describe(r: dict) -> list[str]:
    """Plain-language read of the numbers, for people who aren't producers."""
    out = []
    hp = r["hats_per_beat"]
    out.append("busy hi-hats (16ths or rolls)" if hp >= 3 else "steady hi-hats (8ths)" if hp >= 1.5 else "sparse top end")
    if r["half_time_feel"]:
        out.insert(0, "half-time feel (trap/drill style)")
    if r["chord_loops"] and len(set(r["chord_loops"][0]["chords"])) == 1:
        out.append("one-chord groove (the bass riff and drums carry the song)")
    out.append("heavy bass / 808" if r["bass_share"] >= 0.4 else "medium bass" if r["bass_share"] >= 0.2 else "light bass")
    out.append("drum-led" if r["drum_share"] >= 0.45 else "melody-led")
    out.append("lots of room for vocals" if r["vocal_range_share"] < 0.3 else "busy midrange, keep the melody simple under verses")
    return out


def build_profile(name: str, results: list[dict]) -> dict:
    tempos = []
    for r in results:
        # Fold every tempo into the 60-180 window the beat engine uses.
        t = r["tempo_bpm"]
        while t < 60:
            t *= 2
        while t > 180:
            t /= 2
        tempos.append(t)
    modes = Counter(r["key"].split()[1] for r in results)
    loops = Counter()
    for r in results:
        for loop in r["chord_loops"]:
            loops[" - ".join(loop["roman"])] += loop["times"]
    avg = lambda k: round(float(np.mean([r[k] for r in results])), 2)
    return {
        "profile": name,
        "tracks": len(results),
        "tempo_range_bpm": [round(min(tempos)), round(max(tempos))],
        "tempo_median_bpm": round(float(np.median(tempos))),
        "minor_share": round(modes.get("minor", 0) / len(results), 2),
        "top_loops_roman": [loop for loop, _ in loops.most_common(5)],
        "hats_per_beat": avg("hats_per_beat"),
        "drum_share": avg("drum_share"),
        "bass_share": avg("bass_share"),
        "vocal_range_share": avg("vocal_range_share"),
        "brightness_hz": round(avg("brightness_hz")),
    }


def result_name(f: Path) -> str:
    # Folder + file name, so two "intro.mp3" files from different artists don't collide.
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in f"{f.parent.name}__{f.stem}") + ".json"


def _work(path_str: str, clip):
    warnings.filterwarnings("ignore")
    f = Path(path_str)
    r = analyze(f, clip)
    r["summary"] = describe(r)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="audio files or folders")
    ap.add_argument("--profile", help="name for a combined profile of all inputs (an artist or style)")
    ap.add_argument("--out", default="ggrap/analyzer/results", help="folder for JSON results")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="songs analyzed at the same time")
    ap.add_argument("--clip", type=float, default=120, help="seconds from the middle of each song to measure; 0 = whole song")
    ap.add_argument("--redo", action="store_true", help="measure again even if a result already exists")
    ap.add_argument("--no-categories", action="store_true", help="skip sorting into categories at the end")
    args = ap.parse_args(argv)

    files = []
    for item in map(Path, args.inputs):
        item = item.expanduser()
        files += sorted(p for p in item.rglob("*") if p.suffix.lower() in AUDIO_EXT and not p.name.startswith(".")) if item.is_dir() else [item]
    if not files:
        sys.exit("No audio files found. Supported: " + ", ".join(sorted(AUDIO_EXT)))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = [f for f in files if args.redo or not (out / result_name(f)).exists()]
    print(f"{len(files)} songs found, {len(files) - len(todo)} already measured, {len(todo)} to go "
          f"({args.workers} at a time)")

    results, failed = [], []
    clip = args.clip or None
    def first_then_pool():
        # The first song runs here, so every compiled part of librosa is built
        # once before the workers start (they inherit it instead of racing).
        if todo:
            try:
                yield todo[0], _work(str(todo[0]), clip), None
            except Exception as e:
                yield todo[0], None, e
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            jobs = {pool.submit(_work, str(f), clip): f for f in todo[1:]}
            for job in as_completed(jobs):
                try:
                    yield jobs[job], job.result(), None
                except Exception as e:
                    yield jobs[job], None, e

    for n, (f, r, err) in enumerate(first_then_pool(), 1):
            try:
                if err:
                    raise err
            except Exception as e:  # one broken file shouldn't stop a batch
                failed.append(f.name)
                print(f"[{n}/{len(todo)}] !! {f.name}: {e}")
                continue
            (out / result_name(f)).write_text(json.dumps(r, ensure_ascii=False, indent=2))
            results.append(r)
            loop = r["chord_loops"][0] if r["chord_loops"] else None
            print(f"[{n}/{len(todo)}] {f.name}: {r['tempo_bpm']} BPM, {r['key']}, "
                  f"loop {' - '.join(loop['chords']) if loop else 'unclear'}; " + ", ".join(r["summary"]))

    if failed:
        print(f"\n{len(failed)} files could not be read: " + ", ".join(failed[:10]) + (" ..." if len(failed) > 10 else ""))

    if args.profile:
        everything = [json.loads((out / result_name(f)).read_text()) for f in files if (out / result_name(f)).exists()]
        if everything:
            prof = build_profile(args.profile, everything)
            slug = "".join(c if c.isalnum() else "-" for c in args.profile.lower()).strip("-")
            (out / f"profile-{slug}.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2))
            print(f"\nProfile {args.profile}: {json.dumps(prof, ensure_ascii=False)}")

    if not args.no_categories:
        from categorize import categorize_folder
        categorize_folder(out)


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    main()
