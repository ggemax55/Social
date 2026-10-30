"""Build the GGRap studio app.

    python ggrap/beats/fetch_samples.py                 # once
    python ggrap/app/build_samples.py <samples.json>
    python ggrap/beats/generate.py boombap <beats> 80 85 90 95 100
    python ggrap/beats/generate.py trap <beats> 130 135 140 145 150
    python ggrap/app/build.py <samples.json> <beats> <out_dir>

Writes <out_dir>/GGRap.html: one file with the app, the beat maker with its
instrument samples, and the ready-made Boom Bap and Trap beat sets (all Opus
audio). Each session can use a beat made for it or one of the ready-made sets.
Double-click it and it opens in Chrome, where the Record button can use the
microphone. No server or install needed.
"""
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
body{margin:0;font-size:14px;font-family:system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>
</head><body>
"""


def opus(path: Path) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "x.ogg"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-c:a", "libopus", "-b:a", "128k",
                        "-vbr", "on", str(out)], check=True)
        return out.read_bytes()


def ready_made(beats: Path) -> dict:
    """The ready-made beat sets (Boom Bap, Trap) rendered by ggrap/beats/generate.py at 5 tempos."""
    data = {}
    for gen in ("boombap", "trap"):
        man = json.loads((beats / gen / "manifest.json").read_text())
        man["ext"] = "ogg"
        files = {f"{t}/{v['id']}": base64.b64encode(opus(beats / gen / str(t) / f"{v['id']}.flac")).decode()
                 for t in man["tempos"] for v in man["versions"]}
        data[gen] = {"manifest": man, "files": files}
    return data


def main():
    samples, beats, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    code = (HERE / "studio.js").read_text() + "\n" + (HERE / "beatmaker.js").read_text()
    app = (HERE / "app.html").read_text().replace("/*STUDIO*/", code)
    embed = ("<script>window.GGRAP_SAMPLES=" + samples.read_text() + "</script>\n" +
             "<script>window.GGRAP_BEATS=" + json.dumps(ready_made(beats), separators=(",", ":")) + "</script>\n")
    html = HEAD + embed + app + "\n</body></html>\n"
    (out / "GGRap.html").write_text(html)
    print("GGRap.html", round(len(html) / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
