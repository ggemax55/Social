"""Build the GGRap studio app.

    python ggrap/beats/generate.py boombap <beats> 80 85 90 95 100
    python ggrap/beats/generate.py trap <beats> 130 135 140 145 150
    python ggrap/app/build.py <beats> <out_dir>

Writes <out_dir>/GGRap.html: one file with the app and every beat loop inside
(as Opus audio). Double-click it and it opens in Chrome, where the Record
button can use the microphone. No server or install needed.
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


def main():
    beats, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    data = {}
    for gen in ("boombap", "trap"):
        man = json.loads((beats / gen / "manifest.json").read_text())
        man["ext"] = "ogg"
        files = {}
        for t in man["tempos"]:
            for v in man["versions"]:
                files[f"{t}/{v['id']}"] = base64.b64encode(opus(beats / gen / str(t) / f"{v['id']}.flac")).decode()
        data[gen] = {"manifest": man, "files": files}
        print(gen, len(files), "loops")
    app = (HERE / "app.html").read_text().replace("/*STUDIO*/", (HERE / "studio.js").read_text())
    embed = "<script>window.GGRAP_BEATS=" + json.dumps(data, separators=(",", ":")) + "</script>\n"
    html = HEAD + embed + app + "\n</body></html>\n"
    (out / "GGRap.html").write_text(html)
    print("GGRap.html", round(len(html) / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
