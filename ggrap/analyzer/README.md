# GGRap style analyzer

Measures what a beat or song is made of, so the beat engine can build new beats in the same style:

- tempo, including half-time feel (trap and drill)
- key and its relative key
- the most common 4-chord loops, as chord names and as numerals (i – bVI – bIII – bVII)
- hi-hat density, bass weight, and how much room the midrange leaves for a voice

## Setup on a Mac (one time)

Open Terminal and run, from the `Social` repository folder:

```bash
bash ggrap/analyzer/setup_mac.sh
```

It creates a private Python environment, installs the tools, installs ffmpeg if Homebrew is present, and creates `~/Music/GGRap-library`.

## Analyze a library (100+ songs)

1. Put songs in `~/Music/GGRap-library`, **one folder per artist or style**. The folder name becomes the label:

   ```
   GGRap-library/
     metro-boomin/   20 songs
     central-cee/    20 songs
     kochari/        15 songs
     my-suno-beats/  30 songs
   ```

2. Run:

   ```bash
   ggrap/analyzer/.venv/bin/python ggrap/analyzer/analyze.py ~/Music/GGRap-library
   ```

   - Several songs run at once (`--workers`, defaults to your CPU cores minus one).
   - Only the middle 2 minutes of each song are measured (`--clip 0` for whole songs).
   - Stop any time. Running again skips songs that are already measured (`--redo` to measure again).

3. Open the results in `ggrap/analyzer/results/`:
   - `catalog.csv`: one row per song, opens in Numbers or Excel. Style guess, mood guess, sound group, tempo, key, chord loop. Fill in `your_label` where a guess is wrong.
   - `categories.md`: counts per style, mood, sound group and folder, plus songs to check by ear.
   - `profile-folder-*.json` and `profile-style-*.json`: profiles for the beat engine. `app_profiles.json` has all of them in one file.

Re-sort without measuring again: `ggrap/analyzer/.venv/bin/python ggrap/analyzer/categorize.py ggrap/analyzer/results`

## How categories are made

- **Your folders** are the most reliable labels. Every folder with 3+ songs gets its own profile.
- **Style guess**: tempo, half-time feel, hi-hat density, bass weight and brightness compared with 12 style rules (Trap, Drill, Boom Bap, Lo-fi, Old School, G-Funk, Reggaeton/Dancehall, Afro/Amapiano, Club/House, Phonk, Grime, Rage). Styles with similar tempos (Boom Bap, G-Funk, Lo-fi, Reggaeton) are hard to tell apart from these measurements, so check low-confidence rows by ear.
- **Mood guess**: major or minor, the chord loop, brightness and energy.
- **Sound groups**: songs clustered by how they sound, with no labels. Useful for finding styles you didn't name.

## Accuracy

Checked on 14 test beats with known answers (boom bap 90, trap 136–152 half-time, club 123–126): every tempo, half-time feel, chord loop and style guess came out right, and the automatic sound groups matched the three test folders. Also checked on a real song (Hypnotize: 95.7 BPM, E, one-chord groove) and on a swung boom bap beat, which first fooled the tempo reading into 120 and then 136 BPM. Tempo is now chosen by laying a beat grid over the song and keeping the one where the drum hits land hardest. Chord names for jazz chords (9ths, rootless voicings) are approximate, since the analyzer matches plain major and minor chords. Real songs are messier than test beats, so expect some misses. Two things need a human eye:
- Major keys and their relative minor share the same notes (C major and A minor, for example). The analyzer uses the bass line to decide and always reports the other one as `key_relative`.
- A producer should review every profile before it goes into the app.
