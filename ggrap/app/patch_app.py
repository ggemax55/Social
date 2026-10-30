"""One-off: turn the GGRap 2.0 prototype page into the studio app source (app/app.html)."""
from pathlib import Path
src = Path(__file__).parent.parent / "app_base.html"
s = src.read_text()
def rep(a, b, n=1):
    global s
    assert s.count(a) == n, (s.count(a), a[:80]); s = s.replace(a, b)

# ---------- CSS
rep(".toast{position:fixed;", r""".lp-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px}
.lp-now{display:grid;min-width:0;flex:1 1 140px;line-height:1.2}
.lp-now .k{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--deck-muted)}
.lp-now b{font-family:var(--display);font-size:24px;font-weight:900;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rec{border:0;border-radius:999px;padding:10px 16px;background:var(--deck-line);color:var(--deck-fg);font-weight:600;display:inline-flex;align-items:center;gap:8px;font-family:var(--mono)}
.rec::before{content:"";width:12px;height:12px;border-radius:50%;background:#E5484D}
.rec.on{background:#E5484D;color:#fff}
.rec.on::before{background:#fff;animation:recpulse .8s ease-in-out infinite alternate}
@keyframes recpulse{from{opacity:.35}to{opacity:1}}
.lp-bars{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}
.lp-bars span{height:6px;border-radius:3px;background:var(--deck-line);overflow:hidden;position:relative}
.lp-bars span:last-child::after{content:"";position:absolute;right:0;top:0;bottom:0;width:50%;background:repeating-linear-gradient(135deg,transparent 0 4px,rgba(255,255,255,.2) 4px 8px)}
.lp-bars i{display:block;height:100%;width:0;background:var(--apricot)}
.mixer{display:grid;gap:12px}
.pads{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
@media (max-width:700px){.pads{grid-template-columns:repeat(2,minmax(0,1fr))}}
.pad{--c:var(--r1);position:relative;border:1px solid var(--line);background:var(--surface);border-radius:12px;padding:12px;text-align:left;display:grid;gap:4px;align-content:start;min-width:0}
.pad .pid{font-family:var(--display);font-weight:900;font-size:44px;line-height:.8;color:var(--c)}
.pad .pnm{font-weight:600}
.pad .ptr{font-size:12px;color:var(--muted)}
.pad .badge{position:absolute;top:10px;right:10px;font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;padding:2px 7px;border-radius:999px}
.pad.playing{border-color:var(--c);box-shadow:inset 0 0 0 3px var(--c)}
.pad.playing .badge{background:var(--c);color:var(--on-accent)}
.pad.next{border-style:dashed;border-color:var(--c)}
.pad.next .badge{border:1px solid var(--c);color:var(--c)}
.mnotice{display:flex;align-items:center;gap:10px;border-radius:10px;padding:10px 14px;background:var(--surface-2);font-weight:600;min-height:44px}
.mnotice .dot{width:10px;height:10px;border-radius:50%;background:var(--muted);flex:none}
.mnotice.hot{background:color-mix(in srgb,var(--nxt,var(--apricot)) 22%,var(--surface))}
.mnotice.hot .dot{background:var(--nxt,var(--apricot));animation:recpulse .5s ease-in-out infinite alternate}
.lseg{display:inline-flex;background:var(--surface-2);border-radius:999px;padding:3px}
.lseg button{border:0;background:none;border-radius:999px;padding:5px 12px;font-weight:600;color:var(--muted)}
.lseg button[aria-pressed="true"]{background:var(--fg);color:var(--bg)}
.cchip{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:7px;color:var(--on-accent);font-family:var(--display);font-weight:900;font-size:18px;margin-right:4px}
.cchip.at{outline:3px solid var(--fg);outline-offset:1px}
.take{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 14px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}
.take:first-child{border-top:0}
.tk-main{display:grid;min-width:0}
@media (max-width:620px){.take{grid-template-columns:minmax(0,1fr)}}
.daw-transport{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
#dawWork{display:grid;gap:14px}
.recpanel .rec{background:var(--surface-2);color:var(--fg)}
.recpanel .rec.on{background:#E5484D;color:#fff}
.recpick button:disabled{opacity:.5}
.daw-transport .pos{font-family:var(--mono);font-size:20px;margin-left:auto}
.track{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:grid;gap:10px}
.track-head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.track-head h3{font-size:22px}
.track-head .muted{flex:1 1 200px;font-size:13px;min-width:0}
.wave{position:relative;height:84px;border-radius:8px;background:var(--surface-2);overflow:hidden;cursor:pointer}
.wave canvas{width:100%;height:100%;display:block}
#beatWave canvas{color:var(--blue)}
#vocalWave canvas{color:var(--apricot)}
.wave .head{position:absolute;top:0;bottom:0;width:2px;background:var(--fg);left:0}
.fxrow{display:flex;flex-wrap:wrap;gap:8px}
.fx{display:flex;flex-wrap:wrap;gap:8px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:6px}
.fx button{border:0;border-radius:7px;padding:5px 10px;font-weight:600;background:var(--surface-2);color:var(--muted)}
.fx.on{border-color:var(--apricot)}
.fx.on button{background:var(--apricot);color:var(--on-accent)}
.fxs{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.fxs input{width:90px;accent-color:var(--apricot)}
.vctl{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center}
.vctl label{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.vctl input[type=range]{accent-color:var(--apricot);width:130px}
.meter{height:8px;border-radius:4px;background:var(--surface-2);overflow:hidden;flex:1 1 160px}
.meter i{display:block;height:100%;width:0;background:var(--green, #23825A)}
.meter.clip i{background:#E5484D}
.filebtn{position:relative;overflow:hidden}
.filebtn input{position:absolute;inset:0;opacity:0;cursor:pointer}
.toast{position:fixed;""")

# ---------- deck: loop player for sessions, the old synth controls only on training tool pages
rep("""    <div class="deck-row">
      <button class="play" id="playBtn" aria-label="Play beat">""", """    <div class="lp-row" id="loopDeck">
      <button class="play" id="lpPlay" aria-label="Play beat"><svg viewBox="0 0 20 20" id="lpIcon"><path d="M5 3l12 7-12 7z"/></svg></button>
      <div class="lp-now"><span class="k" id="lpGen">Beat</span><b id="lpNow">Open a session</b></div>
      <label for="lpBpm">BPM <select id="lpBpm"></select></label>
      <label for="lpVol">Volume <input type="range" id="lpVol" min="0" max="1" step="0.01" value="0.85" style="accent-color:var(--apricot);width:110px"></label>
    </div>
    <div class="lp-bars" id="lpBars" aria-hidden="true"><span><i></i></span><span><i></i></span><span><i></i></span><span><i></i></span></div>
    <div id="synthDeck" hidden>
    <div class="deck-row">
      <button class="play" id="playBtn" aria-label="Play beat">""")
rep("""    <div class="lights" id="lights" aria-hidden="true"></div>
    <div class="styleinfo" id="styleInfo"></div>
  </div>
</div>""", """    <div class="lights" id="lights" aria-hidden="true"></div>
    <div class="styleinfo" id="styleInfo"></div>
    </div>
  </div>
</div>""")

# ---------- session: mixer + takes under the session header
rep("""  <div class="sdetail" id="sessHead"></div>
</section>""", """  <div class="sdetail" id="sessHead"></div>
  <div class="panel mixer">
    <div class="row" style="justify-content:space-between">
      <div><h3>Beat versions</h3><span class="label" id="mixKey"></span></div>
      <div class="lseg" role="group" aria-label="How versions change">
        <button data-lmode="manual" aria-pressed="true">Tap to queue</button><button data-lmode="random" aria-pressed="false">Random</button><button data-lmode="chain" aria-pressed="false">Chain</button>
      </div>
    </div>
    <div class="pads" id="pads"></div>
    <div class="mnotice" id="mixNotice" role="status" aria-live="polite"><span class="dot"></span><span>Tap a version to start with it.</span></div>
    <div class="row" id="chainRow" hidden><span class="label">Chain</span><span id="chain"></span><button class="btn small" id="chainClear">Clear</button></div>
  </div>
  <div class="panel recpanel">
    <div class="row" style="justify-content:space-between"><h3>Record</h3><span class="muted" style="font-size:13px">Wear headphones so the beat doesn't leak into the mic.</span></div>
    <div class="row">
      <div class="recpick lseg" role="group" aria-label="What to record"><button id="recBeat" aria-pressed="true">Beat</button><button id="recVocal" aria-pressed="true">Vocal</button></div>
      <button class="rec" id="recBtn" aria-label="Record"><span id="recTxt">Record</span></button>
      <span class="muted" style="font-size:13px">Pick Beat, Vocal or both. The beat plays either way.</span>
    </div>
    <h3 style="font-size:18px">Takes</h3>
    <div id="takes"></div>
  </div>
</section>

<!-- DAW -->
<section class="mod" id="daw" role="tabpanel" hidden>
  <div class="intro"><span class="label">Studio</span><h2>DAW</h2><p>Open a take from any session, record over it, polish the lines with effects, then export or save it to your history.</p></div>
  <div class="panel" id="dawEmpty">
    <b>No recording open</b>
    <span class="muted">Go to a session, record a take, then press <b>Open in DAW</b>. Or open something you saved below.</span>
    <div class="row"><button class="btn small primary" data-goto="sessions">Go to Sessions</button></div>
  </div>
  <div id="dawWork" hidden>
  <div class="daw-transport">
    <span class="label" id="dawSource"></span>
    <button class="btn" id="dawToStart" aria-label="Back to start">⏮</button>
    <button class="btn primary" id="dawPlay">▶ Play</button>
    <button class="btn rec" id="dawRec" style="background:var(--surface);color:var(--fg);border:1px solid var(--line)">Record vocal</button>
    <span class="pos" id="dawPos">0:00 / 0:00</span>
  </div>
  <div class="track">
    <div class="track-head"><h3>Beat</h3><span class="muted" id="beatLabel"></span>
      <div class="vctl"><label for="beatVol">Vol <input type="range" id="beatVol" min="0" max="1.2" step="0.01"></label><button class="btn small" data-mute="beat" id="beatMute" aria-pressed="false">Mute</button></div></div>
    <div class="wave" id="beatWave"><canvas data-track="beat"></canvas><span class="head"></span></div>
    <div id="beatFx"></div>
  </div>
  <div class="track">
    <div class="track-head"><h3>Vocal</h3><span class="muted" id="vocalLabel"></span>
      <div class="vctl"><label for="vocalVol">Vol <input type="range" id="vocalVol" min="0" max="1.5" step="0.01"></label><button class="btn small" data-mute="vocal" id="vocalMute" aria-pressed="false">Mute</button></div></div>
    <div class="wave" id="vocalWave"><canvas data-track="vocal"></canvas><span class="head"></span></div>
    <div class="vctl"><label for="dawOffset">Sync <input type="range" id="dawOffset" min="-400" max="400" step="5" value="0"></label><output id="dawOffsetOut" class="label">0 ms</output><span class="muted" style="font-size:12.5px">Slide left if your voice sounds late.</span></div>
    <div id="vocalFx"></div>
  </div>
  <div class="track">
    <div class="track-head"><h3>Master</h3><span class="muted">Both tracks together, with a limiter so the export never clips.</span></div>
    <div class="vctl"><label for="masterVol">Vol <input type="range" id="masterVol" min="0" max="1.2" step="0.01"></label><div class="meter" id="dawMeter"><i></i></div></div>
    <div class="row"><button class="btn primary" id="dawSave">Save to history</button><button class="btn" data-export="wav">Export WAV</button><button class="btn" data-export="mp3">Export MP3</button></div>
  </div>
  </div>
  <div class="panel">
    <h3>History</h3>
    <div id="history"></div>
  </div>
</section>""")

# ---------- tabs and page routing
rep("const TABS=[['styles','','Start'],['plan','','Daily plan'],['sessions','','Sessions']];",
    "const TABS=[['styles','','Start'],['plan','','Daily plan'],['sessions','','Sessions'],['daw','','DAW']];")
rep("PAGES=['styles','plan','sessions','session',", "PAGES=['styles','plan','sessions','daw','session',")
rep("  if(id==='session')renderSessHead();if(id==='sessions')renderSessions();if(id==='plan')renderPlan();\n}",
    "  if(id==='session')renderSessHead();if(id==='sessions')renderSessions();if(id==='plan')renderPlan();\n"
    "  $('#synthDeck').hidden=!tool||id==='saved';$('#loopDeck').hidden=tool&&id!=='saved';$('#lpBars').hidden=tool&&id!=='saved';\n"
    "  if(tool&&LE&&LE.playing)LE.stop();if(!tool&&state.playing)stop();\n"
    "  if(id==='session'){const s=curSess();const g=genFor(s.style);if(LE.gen!==g)LE.setGen(g,s.loopTempo||s.bpm).catch(()=>toast('Beats could not load'));else{renderPads();announceMix()}renderTakes()}\n"
    "  if(id==='daw')dawUI();\n}")

# ---------- engines: synth (training tools) and loops (sessions) never play at once
rep("""function start(){
  if(!ensureCtx()){toast('Audio is not available in this browser');return}""", """function start(){
  if(!ensureCtx()){toast('Audio is not available in this browser');return}
  if(LE&&LE.playing)LE.stop();""")
rep("""function fsStart(){
  if(!state.playing){const cs=curSess();if(cs)playSession(cs);else start()}
  if(!state.playing)return;""", """async function fsStart(){
  if(!LE.playing)await LE.play();
  if(!LE.playing)return;""")
rep("function playSession(s){const keep=vibe;vibe=s.vibe;const R=recipe();vibe=keep;setStyle(s.preset,s.bpm);state.vibe={prog:R.E.prog,key:s.vibe.key,sample:s.vibe.sample};start()}",
    "async function playSession(s){await LE.setGen(genFor(s.style),s.loopTempo||s.bpm);LE.play()}")
rep("if(t.closest('[data-vibeplay]')){applyVibe();start();toast(STYLES[state.style].label+' · '+state.bpm+' BPM · '+NOTES[vibe.key]);return}",
    "if(t.closest('[data-vibeplay]')){const R=recipe();LE.setGen(genFor(R.S.id),R.bpm).then(()=>LE.play());return}")
rep("<span style=\"flex:1\"></span><button class=\"btn primary\" id=\"sessPlay\">▶ Play beat</button></div>'+",
    "</div>'+")

# ---------- studio code goes in before boot
rep("/* ---------------- Boot ---------------- */", "/*STUDIO*/\n\n/* ---------------- Boot ---------------- */")
Path(__file__).with_name("app.html").write_text(s)
print("app.html written", len(s))
