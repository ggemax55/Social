# GGRap style analyzer

Measures what a beat or song is made of, so the beat engine can build new beats in the same style:

- tempo, including half-time feel (trap and drill)
- key and its relative key
- the most common 4-chord loops, as chord names and as numerals (i – bVI – bIII – bVII)
- hi-hat density, bass weight, and how much room the midrange leaves for a voice

## Setup

```bash
pip install -r ggrap/analyzer/requirements.txt
```

## Use

Analyze single tracks:

```bash
python ggrap/analyzer/analyze.py path/to/beat.mp3
```

Build a profile for an artist or style from a folder of reference tracks (about 20 is a good start):

```bash
python ggrap/analyzer/analyze.py ggrap/analyzer/tracks/metro-boomin --profile "Metro Boomin"
```

Results are saved as JSON in `ggrap/analyzer/results/`. Audio files in `tracks/` are never committed.

## Accuracy

Checked on test beats with known answers (Am–F–C–G at 90 BPM, a 140 BPM trap beat): tempo, half-time feel and chord loops came out right. Two things need a human eye:
- Major keys and their relative minor share the same notes (C major and A minor, for example). The analyzer uses the bass line to decide and always reports the other one as `key_relative`.
- A producer should review every profile before it goes into the app.
