"""Look up existing measurements for songs in AcousticBrainz (CC0 data, no audio needed).

Reads song_list.csv, finds each song in MusicBrainz, then fetches the
AcousticBrainz measurements (tempo, key, chord key, danceability, energy
bands) for the first matching recording that has them.

    python ggrap/analyzer/acousticbrainz_lookup.py

Writes results/acousticbrainz.json and results/acousticbrainz.csv. MusicBrainz
allows about one request per second, so 180 songs take a few minutes.
AcousticBrainz stopped collecting in 2022; newer songs won't be found.
"""
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "GGRap/0.1 (https://github.com/ggemax55/social)"}
HERE = Path(__file__).parent


def get(url, tries=5):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
        except Exception as e:  # 503 = rate limited; back off and retry
            if i == tries - 1:
                raise
            time.sleep(2 + 2 * i)


def lookup(artist, title):
    q = urllib.parse.quote(f'recording:"{title}" AND artist:"{artist}"')
    recs = get(f"https://musicbrainz.org/ws/2/recording/?query={q}&fmt=json&limit=25")["recordings"]
    time.sleep(1.1)
    ids = [r["id"] for r in recs if r.get("score", 0) >= 90][:25]
    if not ids:
        return None
    low = get("https://acousticbrainz.org/api/v1/low-level?recording_ids=" + ";".join(ids))
    hits = [i for i in ids if i in low]
    if not hits:
        return None
    high = get("https://acousticbrainz.org/api/v1/high-level?recording_ids=" + hits[0])
    ll, hl = low[hits[0]]["0"], high.get(hits[0], {}).get("0", {}).get("highlevel", {})
    t, r, lo = ll["tonal"], ll["rhythm"], ll["lowlevel"]
    pick = lambda k: hl.get(k, {}).get("value")
    return {
        "mbid": hits[0], "versions_measured": len(hits),
        "tempo_bpm": round(r["bpm"], 1), "key": f'{t["key_key"]} {t["key_scale"]}',
        "chord_key": f'{t["chords_key"]} {t["chords_scale"]}', "chord_changes_rate": round(t["chords_changes_rate"], 3),
        "danceability": round(r.get("danceability", 0), 2), "onset_rate": round(r.get("onset_rate", 0), 2),
        "bass_energy": round(lo["spectral_energyband_low"]["mean"], 4),
        "mood_aggressive": pick("mood_aggressive"), "mood_happy": pick("mood_happy"), "mood_sad": pick("mood_sad"),
        "mood_relaxed": pick("mood_relaxed"), "mood_party": pick("mood_party"),
    }


def main():
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    cache_path = out / "acousticbrainz.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    songs = list(csv.DictReader(open(HERE / "song_list.csv", encoding="utf-8-sig")))
    for n, s in enumerate(songs, 1):
        key = f'{s["artist"]} - {s["song"]}'
        if key in cache:
            continue
        artist = s["artist"].replace(" (producer)", "")
        try:
            cache[key] = {**s, "found": (res := lookup(artist, s["song"])) is not None, **(res or {})}
        except Exception as e:
            cache[key] = {**s, "found": False, "error": str(e)}
        print(f'[{n}/{len(songs)}] {key}: ' + (f'{cache[key]["tempo_bpm"]} BPM, {cache[key]["key"]}' if cache[key]["found"] else "not found"))
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
        time.sleep(1.1)
    rows = list(cache.values())
    cols = ["style", "artist", "song", "year", "found", "tempo_bpm", "key", "chord_key", "chord_changes_rate",
            "danceability", "mood_aggressive", "mood_happy", "mood_sad", "mood_relaxed", "mood_party"]
    with open(out / "acousticbrainz.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    found = sum(r["found"] for r in rows)
    print(f"\nFound measurements for {found} of {len(rows)} songs.")


if __name__ == "__main__":
    main()
