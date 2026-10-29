"""Sort analyzed songs into categories.

Reads the JSON results written by analyze.py and produces:

- catalog.csv      one row per song: style guess, mood guess, sound group,
                   tempo, key, main chord loop. Opens in Numbers or Excel.
                   The empty "your_label" column is for corrections.
- categories.md    counts and a short description of every category.
- profile-*.json   one profile per folder (artist or style) with 3+ songs,
                   and one per guessed style, ready for the beat engine.

    python ggrap/analyzer/categorize.py ggrap/analyzer/results

Style and mood are guesses from measurements. Folder names (your labels)
always win over guesses, so organise songs in folders when you know them.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from analyze import build_profile

# tempo range, half-time feel, and optional feature ranges per style
STYLE_RULES = {
    "Trap": dict(tempo=(130, 155), half=True, hats=(3, 99), bass=(0.35, 1)),
    "Drill": dict(tempo=(138, 146), half=True, hats=(2.5, 99), bass=(0.35, 1), minor=True),
    "Rage / Melodic": dict(tempo=(150, 170), half=True),
    "Boom Bap": dict(tempo=(82, 98), half=False, hats=(1, 3.2)),
    "Lo-fi / Jazz": dict(tempo=(68, 92), half=False, bright=(0, 1700)),
    "Old School": dict(tempo=(95, 112), half=False, hats=(1, 2.5)),
    "G-Funk": dict(tempo=(88, 100), half=False, bass=(0.3, 1), minor=False),
    "Reggaeton / Dancehall": dict(tempo=(86, 102), half=False, bass=(0.3, 1)),
    "Afro / Amapiano": dict(tempo=(100, 116), half=False),
    "Club / House": dict(tempo=(116, 130), half=False, drum=(0.3, 1)),
    "Phonk": dict(tempo=(120, 145), bright=(2500, 99999), bass=(0.35, 1)),
    "Grime": dict(tempo=(136, 144), hats=(0, 2.5), bass=(0.35, 1)),
}
# style name in this file -> style id in the app's vibe builder
APP_STYLE = {"Trap": "trap", "Drill": "drill", "Rage / Melodic": "rage", "Boom Bap": "boombap", "Lo-fi / Jazz": "lofi",
             "Old School": "oldschool", "G-Funk": "gfunk", "Reggaeton / Dancehall": "reggaeton",
             "Afro / Amapiano": "afro", "Club / House": "club", "Phonk": "phonk", "Grime": "grime"}


def in_range(v, lo_hi, soft):
    lo, hi = lo_hi
    if lo <= v <= hi:
        return 1.0
    d = lo - v if v < lo else v - hi
    return math.exp(-d / soft)


def style_scores(r: dict) -> list[tuple[str, float]]:
    minor = r["key"].endswith("minor")
    out = []
    for name, rule in STYLE_RULES.items():
        s = in_range(r["tempo_bpm"], rule["tempo"], 6)
        if "half" in rule:
            s *= 1.0 if r["half_time_feel"] == rule["half"] else 0.35
        if "hats" in rule:
            s *= in_range(r["hats_per_beat"], rule["hats"], 0.8)
        if "bass" in rule:
            s *= in_range(r["bass_share"], rule["bass"], 0.15)
        if "drum" in rule:
            s *= in_range(r["drum_share"], rule["drum"], 0.15)
        if "bright" in rule:
            s *= in_range(r["brightness_hz"], rule["bright"], 500)
        if "minor" in rule:
            s *= 1.0 if minor == rule["minor"] else 0.6
        out.append((name, s))
    return sorted(out, key=lambda x: -x[1])


def mood(r: dict) -> str:
    minor = r["key"].endswith("minor")
    loop = r["chord_loops"][0]["roman"] if r["chord_loops"] else []
    if "bII" in loop:
        return "Dark"
    if minor and "V" in loop:  # major V in a minor key = harmonic minor colour
        return "Mysterious"
    if minor:
        if r["brightness_hz"] < 1800:
            return "Dark"
        if r["hats_per_beat"] >= 3 and r["bass_share"] >= 0.4:
            return "Aggressive / Hype"
        return "Sad / Emotional"
    if loop in (["I", "V", "vi", "IV"], ["vi", "IV", "I", "V"], ["I", "IV", "V", "IV"], ["IV", "V", "iii", "vi"]):
        return "Motivational / Hopeful"
    if r["tempo_bpm"] >= 115 or r["brightness_hz"] > 2600:
        return "Upbeat"
    return "Chill / Romantic"


def kmeans(X: np.ndarray, k: int, seed: int = 7, iters: int = 60):
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), axis=1)
        newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        if np.allclose(newC, C):
            break
        C = newC
    return lab


def sound_groups(rows: list[dict]) -> list[str]:
    """Group songs that sound alike, without using any labels."""
    n = len(rows)
    if n < 6:
        return ["-"] * n
    X = np.array([[r["tempo_bpm"] / 30, 2 * r["half_time_feel"], r["hats_per_beat"], 4 * r["bass_share"],
                   3 * r["drum_share"], 3 * r["vocal_range_share"], r["brightness_hz"] / 600,
                   1.5 * r["key"].endswith("minor")] for r in rows], dtype=float)
    X = (X - X.mean(0)) / (X.std(0) + 1e-9)
    k = int(min(8, max(2, round(math.sqrt(n / 2)))))
    lab = kmeans(X, k)
    names = {}
    for j in range(k):
        members = [rows[i] for i in range(n) if lab[i] == j]
        if not members:
            continue
        t = int(np.median([m["tempo_bpm"] for m in members]))
        ht = sum(m["half_time_feel"] for m in members) > len(members) / 2
        mn = sum(m["key"].endswith("minor") for m in members) > len(members) / 2
        bass = np.median([m["bass_share"] for m in members])
        top = Counter(m["_style"] for m in members).most_common(1)[0][0]
        names[j] = (f"{chr(65 + j)}: ~{t} BPM{' half-time' if ht else ''}, {'minor' if mn else 'major'}, "
                    f"{'heavy' if bass >= 0.4 else 'light'} bass (mostly {top})")
    return [names[l] for l in lab]


def categorize_folder(folder: Path):
    folder = Path(folder)
    rows = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json")) if not p.name.startswith("profile-")
            and p.name != "app_profiles.json"]
    if not rows:
        print("No results to categorize yet.")
        return
    for r in rows:
        sc = style_scores(r)
        total = sum(s for _, s in sc[:3]) or 1
        r["_style"], r["_style2"] = sc[0][0], sc[1][0]
        r["_conf"] = round(sc[0][1] / total, 2)
        r["_mood"] = mood(r)
    groups = sound_groups(rows)

    with open(folder / "catalog.csv", "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads Armenian
        w = csv.writer(fh)
        w.writerow(["folder", "file", "style_guess", "second_guess", "confidence", "mood_guess", "sound_group",
                    "tempo_bpm", "half_time", "key", "main_loop", "main_loop_roman", "hats_per_beat", "bass_share",
                    "vocal_space", "brightness_hz", "first_beat_s", "length_s", "your_label"])
        for r, g in zip(rows, groups):
            loop = r["chord_loops"][0] if r["chord_loops"] else {"chords": [], "roman": []}
            w.writerow([r.get("group", ""), r["file"], r["_style"], r["_style2"], r["_conf"], r["_mood"], g,
                        r["tempo_bpm"], "yes" if r["half_time_feel"] else "no", r["key"], " - ".join(loop["chords"]),
                        " - ".join(loop["roman"]), r["hats_per_beat"], r["bass_share"],
                        round(1 - r["vocal_range_share"], 2), r["brightness_hz"], r["first_beat_s"], r["duration_s"], ""])

    # Profiles: one per folder (your labels), one per guessed style.
    by_folder, by_style = defaultdict(list), defaultdict(list)
    for r in rows:
        by_folder[r.get("group", "")].append(r)
        by_style[r["_style"]].append(r)
    app = {"folders": {}, "styles": {}}
    for kind, buckets in (("folders", by_folder), ("styles", by_style)):
        for name, members in buckets.items():
            if len(members) < 3 or not name:
                continue
            prof = build_profile(name, members)
            prof["moods"] = dict(Counter(m["_mood"] for m in members).most_common())
            if kind == "styles":
                prof["app_style_id"] = APP_STYLE.get(name)
            app[kind][name] = prof
            slug = "".join(c if c.isalnum() else "-" for c in f"{kind[:-1]}-{name}".lower()).strip("-")
            (folder / f"profile-{slug}.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2))
    (folder / "app_profiles.json").write_text(json.dumps(app, ensure_ascii=False, indent=2))

    # Human-readable summary
    lines = [f"# Library categories", "", f"{len(rows)} songs analyzed.", ""]
    for title, key in (("Styles (guessed)", "_style"), ("Moods (guessed)", "_mood")):
        lines += [f"## {title}", "", "| Category | Songs | Median BPM | Minor keys |", "|---|---|---|---|"]
        for name, cnt in Counter(r[key] for r in rows).most_common():
            m = [r for r in rows if r[key] == name]
            lines.append(f"| {name} | {cnt} | {int(np.median([x['tempo_bpm'] for x in m]))} | "
                         f"{round(100 * sum(x['key'].endswith('minor') for x in m) / cnt)}% |")
        lines.append("")
    if any(g != "-" for g in groups):
        lines += ["## Sound groups (found automatically)", ""]
        for g, cnt in Counter(groups).most_common():
            lines.append(f"- **{g}**: {cnt} songs")
        lines.append("")
    if len(by_folder) > 1 or "" not in by_folder:
        lines += ["## Your folders", "", "| Folder | Songs | Tempo range | Top loop | Mostly guessed as |", "|---|---|---|---|---|"]
        for name, members in sorted(by_folder.items()):
            prof = app["folders"].get(name)
            top_loop = prof["top_loops_roman"][0] if prof and prof["top_loops_roman"] else "-"
            rng = f"{prof['tempo_range_bpm'][0]}-{prof['tempo_range_bpm'][1]}" if prof else "-"
            lines.append(f"| {name or '(no folder)'} | {len(members)} | {rng} | {top_loop} | "
                         f"{Counter(m['_style'] for m in members).most_common(1)[0][0]} |")
        lines.append("")
    low = [r["file"] for r in rows if r["_conf"] < 0.4]
    if low:
        lines += [f"## Check by ear ({len(low)} songs with an unsure style guess)", ""] + [f"- {f}" for f in low[:40]] + [""]
    (folder / "categories.md").write_text("\n".join(lines))
    print(f"\nCategorized {len(rows)} songs -> {folder / 'catalog.csv'} and {folder / 'categories.md'}")
    for name, cnt in Counter(r["_style"] for r in rows).most_common():
        print(f"  {name}: {cnt}")


if __name__ == "__main__":
    categorize_folder(Path(sys.argv[1] if len(sys.argv) > 1 else "ggrap/analyzer/results"))
