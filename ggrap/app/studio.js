/* ================= Studio: sample-loop beat player, mixer, recorder, takes, DAW =================
   Inlined into the app's main script by build.py, so it shares ctx, state, toast, sessions and the rest. */
var LE = null;
const TRAPISH = new Set(['trap', 'drill', 'melodic', 'cloud', 'rage', 'phonk', 'grime', 'oriental', 'jersey', 'club']);
const genFor = style => TRAPISH.has(style) ? 'trap' : 'boombap';
const nearest = (list, v) => list.reduce((a, b) => Math.abs(b - v) < Math.abs(a - v) ? b : a);
const PADC = ['var(--r1)', 'var(--r2)', 'var(--r3)', 'var(--r4)'];
function b64ToBuf(b64) { const bin = atob(b64), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u.buffer }
async function beatManifest(gen) {
  if (window.GGRAP_BEATS) return window.GGRAP_BEATS[gen].manifest;
  const r = await fetch('beats/' + gen + '/manifest.json'); if (!r.ok) throw new Error('missing'); return r.json();
}
async function beatBytes(gen, tempo, id, ext) {
  if (window.GGRAP_BEATS) return b64ToBuf(window.GGRAP_BEATS[gen].files[tempo + '/' + id]);
  return (await fetch('beats/' + gen + '/' + tempo + '/' + id + '.' + ext)).arrayBuffer();
}
function decode(ab) { return new Promise((res, rej) => ctx.decodeAudioData(ab, res, rej)) }
function fmtTime(s) { s = Math.max(0, s); return Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0') }

LE = {
  gen: null, man: {}, tempo: null, curTempo: null, bufs: {}, playing: false, cur: 'A', curStart: 0, nextStart: 0,
  nextId: null, locked: false, queue: null, mode: 'manual', chain: [], chainAt: 0, srcs: [], bars: [], barNo: 0,
  out: null, recDest: null, pendingTempo: null, tk: null,
  init() {
    ensureCtx();
    if (!this.out) {
      this.out = ctx.createGain(); this.out.gain.value = +$('#lpVol').value; this.out.connect(ctx.destination);
      this.recDest = ctx.createMediaStreamDestination(); this.out.connect(this.recDest);
    }
  },
  async setGen(gen, tempo) {
    this.init();
    if (!this.man[gen]) this.man[gen] = await beatManifest(gen);
    const m = this.man[gen], t = nearest(m.tempos, tempo || m.default_bpm);
    $('#lpNow').textContent = 'Loading beat…';
    await this.loadTempo(gen, t);
    if (this.gen !== gen && this.playing) this.stop();
    this.gen = gen; this.tempo = t; this.pendingTempo = null;
    renderLoopDeck(); renderPads(); announceMix();
  },
  async loadTempo(gen, t) {
    const m = this.man[gen];
    await Promise.all(m.versions.map(async v => {
      const k = gen + '/' + t + '/' + v.id;
      if (!this.bufs[k]) this.bufs[k] = await decode(await beatBytes(gen, t, v.id, m.ext || 'flac'));
    }));
  },
  async setTempo(t) {
    await this.loadTempo(this.gen, t);
    if (this.playing) { this.pendingTempo = t; toast('Tempo ' + t + ' BPM from the next loop') } else this.tempo = t;
    const s = curSess(); if (s) { s.loopTempo = t; saveSessions() }
    renderLoopDeck();
  },
  loopSec(t) { return 16 * 60 / t },
  startLoop(id, when, t) {
    const buf = this.bufs[this.gen + '/' + t + '/' + id], s = ctx.createBufferSource(), g = ctx.createGain();
    s.buffer = buf; s.connect(g).connect(this.out); s.start(when);
    this.srcs.push({ s, g, end: when + buf.duration });
    this.srcs = this.srcs.filter(x => x.end > ctx.currentTime - 0.1);
    for (let i = 0; i < 4; i++) this.bars.push(when + i * 240 / t);
  },
  async play() {
    if (!this.gen) { const s = curSess(); await this.setGen(s ? genFor(s.style) : 'boombap', s ? (s.loopTempo || s.bpm) : null) }
    if (state.playing) stop();
    if (DAW.playing) dawStop();
    this.init(); if (ctx.state === 'suspended') await ctx.resume();
    this.cur = this.mode === 'chain' && this.chain.length ? this.chain[this.chainAt = 0] : (this.queue || this.cur || 'A');
    this.queue = null; this.curTempo = this.tempo;
    this.curStart = ctx.currentTime + 0.08; this.nextStart = this.curStart + this.loopSec(this.curTempo);
    this.locked = false; this.playing = true; this.bars = []; this.barNo = 0;
    this.startLoop(this.cur, this.curStart, this.curTempo);
    clearInterval(this.tk); this.tk = setInterval(() => this.tick(), 25);
    renderLoopDeck(); announceMix();
  },
  stop() {
    this.playing = false; clearInterval(this.tk);
    if (ctx) { const t = ctx.currentTime; this.srcs.forEach(x => { try { x.g.gain.setTargetAtTime(0, t, 0.03); x.s.stop(t + 0.25) } catch (e) { } }) }
    this.srcs = []; this.locked = false; this.nextId = null; this.bars = [];
    if (REC.on) recStop();
    renderLoopDeck(); announceMix();
  },
  pick() {
    const ids = this.man[this.gen].versions.map(v => v.id);
    if (this.mode === 'random') { const o = ids.filter(x => x !== this.cur); return o[Math.floor(Math.random() * o.length)] }
    if (this.mode === 'chain' && this.chain.length) { this.chainAt = (this.chainAt + 1) % this.chain.length; return this.chain[this.chainAt] }
    if (this.queue) { const q = this.queue; this.queue = null; return q }
    return this.cur;
  },
  tick() {
    const now = ctx.currentTime, beat = 60 / this.curTempo;
    if (!this.locked && now >= this.nextStart - 2 * beat - 0.05) {
      if (this.pendingTempo) { this.tempo = this.pendingTempo; this.pendingTempo = null }
      this.nextId = this.pick(); this.nextTempo = this.tempo; this.locked = true;
      this.startLoop(this.nextId, this.nextStart, this.nextTempo); announceMix();
    }
    if (now >= this.nextStart) {
      this.cur = this.nextId; this.curStart = this.nextStart; this.curTempo = this.nextTempo;
      this.nextStart = this.curStart + this.loopSec(this.curTempo); this.locked = false; this.nextId = null; announceMix();
    }
    while (this.bars.length && this.bars[0] <= now) { this.bars.shift(); this.barNo++; barListeners.forEach(f => f(this.barNo)) }
  },
  vname(id) { const v = this.gen && this.man[this.gen].versions.find(x => x.id === id); return v ? v.id + ' · ' + v.name : id }
};

function renderLoopDeck() {
  const m = LE.gen && LE.man[LE.gen];
  $('#lpIcon').innerHTML = LE.playing ? '<path d="M5 3h4v14H5zM11 3h4v14h-4z"/>' : '<path d="M5 3l12 7-12 7z"/>';
  $('#lpPlay').setAttribute('aria-label', LE.playing ? 'Stop beat' : 'Play beat');
  $('#lpGen').textContent = m ? m.style + ' · ' + m.key : 'Beat';
  $('#lpNow').textContent = LE.playing ? LE.vname(LE.cur) : (m ? 'Press play' : 'Open a session');
  const sel = $('#lpBpm');
  if (m) { const want = String(LE.pendingTempo || LE.tempo); if (sel.dataset.gen !== LE.gen) { sel.innerHTML = m.tempos.map(t => '<option value="' + t + '">' + t + '</option>').join(''); sel.dataset.gen = LE.gen } sel.value = want }
}
function renderPads() {
  const m = LE.gen && LE.man[LE.gen]; if (!m) return;
  $('#pads').innerHTML = m.versions.map((v, i) => '<button class="pad" data-pad="' + v.id + '" style="--c:' + PADC[i] + '"><span class="badge" id="pb-' + v.id + '"></span><span class="pid">' + v.id + '</span><span class="pnm">' + esc(v.name) + '</span><span class="ptr">Ends with: ' + esc(v.transition) + '</span></button>').join('');
  $('#mixKey').textContent = m.style + ' · ' + m.key + ' · ' + m.tempos[0] + '–' + m.tempos[m.tempos.length - 1] + ' BPM';
}
function announceMix() {
  if (!$('#pads')) return;
  const n = $('#mixNotice');
  if (LE.locked && LE.nextId) {
    n.classList.add('hot'); n.style.setProperty('--nxt', PADC[LE.man[LE.gen].versions.findIndex(v => v.id === LE.nextId)]);
    n.lastChild.textContent = LE.nextId === LE.cur ? 'Repeating ' + LE.vname(LE.cur) + '. Fill now…' : 'Next up: ' + LE.vname(LE.nextId) + ' · in 2 beats';
  } else {
    n.classList.remove('hot');
    n.lastChild.textContent = LE.mode === 'random' ? 'Random is on. The next version shows here 2 beats before it starts.' :
      LE.mode === 'chain' ? (LE.chain.length ? 'Chain: ' + LE.chain.join(' ') + '. Tap pads to add more.' : 'Tap pads in order to build a chain.') :
        LE.queue ? 'Queued: ' + LE.vname(LE.queue) + '. It starts on the next loop.' : (LE.playing ? 'Tap a version to switch on the next loop.' : 'Tap a version to start with it.');
  }
  $$('.pad').forEach(p => {
    const id = p.dataset.pad, now = LE.playing && id === LE.cur, next = (LE.locked && id === LE.nextId && id !== LE.cur) || (!LE.locked && id === LE.queue);
    p.classList.toggle('playing', now); p.classList.toggle('next', next);
    $('#pb-' + id).textContent = now ? 'Now' : next ? 'Next' : '';
  });
  $$('[data-lmode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lmode === LE.mode)));
  $('#chainRow').hidden = LE.mode !== 'chain';
  $('#chain').innerHTML = LE.chain.map((id, i) => '<span class="cchip' + (LE.playing && i === LE.chainAt ? ' at' : '') + '" style="background:' + PADC[LE.man[LE.gen].versions.findIndex(v => v.id === id)] + '">' + id + '</span>').join('');
}
function drawLoopBars() {
  if (LE.playing && ctx) {
    const p = Math.max(0, ctx.currentTime - LE.curStart), bl = 240 / LE.curTempo;
    $$('#lpBars i').forEach((el, i) => { el.style.width = Math.max(0, Math.min(1, (p - i * bl) / bl)) * 100 + '%' });
  } else $$('#lpBars i').forEach(el => { el.style.width = '0' });
  if (REC.on) $('#recTxt').textContent = fmtTime((performance.now() - REC.t0) / 1000);
  if (DAW.playing) dawDrawHead();
  requestAnimationFrame(drawLoopBars);
}

/* ---------------- recording ---------------- */
const REC = { on: false, mic: null, mr: [], t0: 0 };
const MIME = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find(m => window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) || '';
async function getMic() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('nomic');
  if (!REC.mic || REC.mic.getTracks().every(t => t.readyState === 'ended'))
    REC.mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  return REC.mic;
}
function micError(e) {
  if (!window.isSecureContext) return 'Recording needs the GGRap.html file opened in Chrome, or the website.';
  if (e && e.name === 'NotAllowedError') return 'Microphone is blocked. Click the icon at the left of the address bar, allow Microphone, then press Rec again.';
  if (e && e.name === 'NotFoundError') return 'No microphone found. Plug one in or check your sound settings.';
  return 'The microphone could not start in this view. Open GGRap.html in Chrome to record.';
}
const recWant = k => $('#rec' + k).getAttribute('aria-pressed') === 'true';
async function recToggle() {
  if (REC.on) return recStop();
  const s = curSess();
  if (!s) { toast('Open a session first, then press Record'); return }
  const wantBeat = recWant('Beat'), wantVocal = recWant('Vocal');
  if (!wantBeat && !wantVocal) { toast('Choose what to record: Beat, Vocal, or both'); return }
  let mic = null;
  if (wantVocal) { try { mic = await getMic() } catch (e) { toast(micError(e)); return } }
  if (!LE.playing) await LE.play(); // the beat always plays so you can rap to it, even when it isn't recorded
  const opts = MIME ? { mimeType: MIME } : {}, parts = {}, startedAt = Date.now(), recs = [];
  const add = (key, stream) => { const mr = new MediaRecorder(stream, opts), chunks = []; mr.ondataavailable = e => e.data.size && chunks.push(e.data); parts[key] = { mr, chunks }; recs.push(mr) };
  if (wantVocal) add('vocal', mic);
  if (wantBeat) add('beat', LE.recDest.stream);
  let stopped = 0;
  const done = async () => {
    if (++stopped < recs.length) return;
    const all = await takesFor(s.id), dur = (Date.now() - startedAt) / 1000, blob = k => parts[k] ? new Blob(parts[k].chunks, { type: parts[k].mr.mimeType }) : null;
    const take = { id: 't' + Date.now(), sessionId: s.id, sessionName: s.name, created: startedAt, dur, name: 'Take ' + (all.length + 1), mode: s.mode,
      vocal: blob('vocal'), beat: blob('beat'), bpm: LE.tempo, offset: wantBeat && wantVocal ? -((ctx.outputLatency || 0) + (ctx.baseLatency || 0) + 0.015) : 0 };
    await IDB.put(take); renderTakes(); toast('Saved ' + take.name + ' · ' + fmtTime(dur));
  };
  recs.forEach(mr => { mr.onstop = done; mr.start(250) });
  REC.mr = recs; REC.on = true; REC.t0 = performance.now();
  renderRec();
}
function recStop() { REC.mr.forEach(m => m.state !== 'inactive' && m.stop()); REC.on = false; renderRec() }
function renderRec() {
  const b = $('#recBtn'); if (!b) return;
  b.classList.toggle('on', REC.on); b.setAttribute('aria-label', REC.on ? 'Stop recording' : 'Record');
  if (!REC.on) $('#recTxt').textContent = 'Record';
  $$('.recpick button').forEach(x => x.disabled = REC.on);
}

/* ---------------- takes: saved on this device (IndexedDB) ---------------- */
const IDB = {
  db: null, mem: { takes: new Map(), projects: new Map() },
  async open() {
    if (this.db !== null) return this.db;
    try {
      this.db = await new Promise((res, rej) => {
        const r = indexedDB.open('ggrap', 2);
        r.onupgradeneeded = () => { for (const n of ['takes', 'projects']) if (!r.result.objectStoreNames.contains(n)) r.result.createObjectStore(n, { keyPath: 'id' }) };
        r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
      });
    } catch (e) { this.db = false }
    return this.db;
  },
  async run(store, mode, fn) {
    const db = await this.open();
    if (!db) { const r = fn(null, this.mem[store]); return r && r.result }
    return new Promise((res, rej) => { const t = db.transaction(store, mode), r = fn(t.objectStore(store)); t.oncomplete = () => res(r && r.result); t.onerror = () => rej(t.error) });
  },
  put(x, store = 'takes') { return this.run(store, 'readwrite', (st, m) => st ? st.put(x) : (m.set(x.id, x), null)) },
  del(id, store = 'takes') { return this.run(store, 'readwrite', (st, m) => st ? st.delete(id) : (m.delete(id), null)) },
  async all(store = 'takes') { return (await this.run(store, 'readonly', (st, m) => st ? st.getAll() : { result: [...m.values()] })) || [] },
  async get(id, store = 'takes') { return this.run(store, 'readonly', (st, m) => st ? st.get(id) : { result: m.get(id) }) }
};
async function takesFor(sid) { return (await IDB.all()).filter(t => t.sessionId === sid).sort((a, b) => b.created - a.created) }
let takePlay = null, takeDelArm = null;
async function renderTakes() {
  const s = curSess(), box = $('#takes'); if (!s || !box) return;
  const list = await takesFor(s.id);
  box.innerHTML = list.length ? list.map(t => '<div class="take"><div class="tk-main"><b>' + esc(t.name) + '</b><span class="muted">' + (t.beat && t.vocal ? 'Beat + vocal' : t.vocal ? 'Vocal only' : 'Beat only') + ' · ' + fmtTime(t.dur) + ' · ' + new Date(t.created).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' · ' + sessDate(t.created) + '</span></div><div class="row"><button class="btn small" data-tplay="' + t.id + '">' + (takePlay && takePlay.id === t.id ? '■ Stop' : '▶ Play') + '</button><button class="btn small primary" data-tdaw="' + t.id + '">Open in DAW</button><button class="btn small" data-tdel="' + t.id + '">' + (takeDelArm === t.id ? 'Tap again to delete' : 'Delete') + '</button></div></div>').join('')
    : '<p class="muted">No takes yet. Choose Beat, Vocal or both above, press <b>Record</b> and rap. Takes are saved on this computer.</p>';
}
async function playTake(id) {
  if (takePlay) { const was = takePlay.id; takePlay.srcs.forEach(s => { try { s.stop() } catch (e) { } }); takePlay = null; renderTakes(); if (was === id) return }
  const t = await IDB.get(id); if (!t) return;
  if (LE.playing) LE.stop(); if (DAW.playing) dawStop();
  ensureCtx(); if (ctx.state === 'suspended') await ctx.resume();
  const dec = async b => b ? decode(await b.arrayBuffer()) : null;
  const [vb, bb] = await Promise.all([dec(t.vocal), dec(t.beat)]);
  const at = ctx.currentTime + 0.1, srcs = [];
  for (const [buf, pos] of [[bb, 0], [vb, t.offset || 0]]) {
    if (!buf) continue;
    const s = ctx.createBufferSource(); s.buffer = buf; s.connect(ctx.destination);
    if (pos >= 0) s.start(at + pos); else s.start(at, -pos); srcs.push(s);
  }
  srcs.reduce((a, b) => a.buffer.duration >= b.buffer.duration ? a : b).onended = () => { if (takePlay && takePlay.id === id) { takePlay = null; renderTakes() } };
  takePlay = { id, srcs }; renderTakes();
}

/* ---------------- DAW ---------------- */
const fxDefaults = () => ({ eq: { on: false, low: 0, high: 0 }, comp: { on: false, amt: 0.5 }, delay: { on: false, mix: 0.25, time: '1/8' }, reverb: { on: false, mix: 0.25 } });
const DAW = {
  beat: null, vocal: null, offset: 0, bpm: 90, name: 'GGRap', playing: false, srcs: [], t0: 0, from: 0, pos: 0, recording: false,
  tr: { beat: { vol: 0.85, mute: false, fx: fxDefaults() }, vocal: { vol: 1, mute: false, fx: Object.assign(fxDefaults(), { comp: { on: true, amt: 0.5 } }) } },
  master: { vol: 0.9 }
};
function dawLen() { return Math.max(DAW.beat ? DAW.beat.duration : 0, DAW.vocal ? DAW.vocal.duration + DAW.offset : 0) }
function irBuffer(c) { const n = Math.floor(c.sampleRate * 2.2), b = c.createBuffer(2, n, c.sampleRate); for (let ch = 0; ch < 2; ch++) { const d = b.getChannelData(ch); for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 3) } return b }
function buildTrack(c, src, cfg, dest) {
  let node = src; const fx = cfg.fx;
  if (fx.eq.on) { const lo = c.createBiquadFilter(); lo.type = 'lowshelf'; lo.frequency.value = 150; lo.gain.value = fx.eq.low; const hi = c.createBiquadFilter(); hi.type = 'highshelf'; hi.frequency.value = 5000; hi.gain.value = fx.eq.high; node.connect(lo); lo.connect(hi); node = hi }
  if (fx.comp.on) { const k = c.createDynamicsCompressor(); k.threshold.value = -10 - 30 * fx.comp.amt; k.ratio.value = 2 + 6 * fx.comp.amt; k.attack.value = 0.005; k.release.value = 0.15; const mk = c.createGain(); mk.gain.value = Math.pow(10, 8 * fx.comp.amt / 20); node.connect(k); k.connect(mk); node = mk }
  const out = c.createGain(); out.gain.value = cfg.mute ? 0 : cfg.vol; node.connect(out);
  if (fx.delay.on) { const d = c.createDelay(2); d.delayTime.value = 60 / DAW.bpm * ({ '1/8': 0.5, '1/4': 1, '1/8.': 0.75 }[fx.delay.time]); const fb = c.createGain(); fb.gain.value = 0.35; const w = c.createGain(); w.gain.value = fx.delay.mix; node.connect(d); d.connect(fb); fb.connect(d); d.connect(w); w.connect(out) }
  if (fx.reverb.on) { const cv = c.createConvolver(); cv.buffer = irBuffer(c); const w = c.createGain(); w.gain.value = fx.reverb.mix; node.connect(cv); cv.connect(w); w.connect(out) }
  out.connect(dest);
}
function buildGraph(c, at, from) {
  const mg = c.createGain(); mg.gain.value = DAW.master.vol;
  const lim = c.createDynamicsCompressor(); lim.threshold.value = -1; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.002; lim.release.value = 0.08;
  mg.connect(lim); const srcs = [];
  for (const [key, buf, pos] of [['beat', DAW.beat, 0], ['vocal', DAW.vocal, DAW.offset]]) {
    if (!buf) continue;
    const s = c.createBufferSource(); s.buffer = buf; buildTrack(c, s, DAW.tr[key], mg);
    const rel = pos - from;
    if (rel >= 0) s.start(at + rel); else if (-rel < buf.duration) s.start(at, -rel); else continue;
    srcs.push(s);
  }
  return { lim, srcs };
}
let dawMeter = null;
async function dawPlay(from) {
  if (!DAW.beat && !DAW.vocal) { toast('Open a take from a session first'); return }
  if (LE.playing) LE.stop(); if (state.playing) stop();
  ensureCtx(); if (ctx.state === 'suspended') await ctx.resume();
  dawStop(true);
  DAW.from = from == null ? DAW.pos : from; if (DAW.from >= dawLen()) DAW.from = 0;
  DAW.t0 = ctx.currentTime + 0.06;
  const g = buildGraph(ctx, DAW.t0, DAW.from);
  dawMeter = ctx.createAnalyser(); dawMeter.fftSize = 1024; g.lim.connect(dawMeter); dawMeter.connect(ctx.destination);
  DAW.srcs = g.srcs; DAW.playing = true; dawUI();
}
function dawStop(silent) {
  DAW.srcs.forEach(s => { try { s.stop() } catch (e) { } }); DAW.srcs = [];
  if (DAW.playing && ctx) DAW.pos = Math.min(dawLen(), DAW.from + ctx.currentTime - DAW.t0);
  DAW.playing = false; if (dawMeter) { try { dawMeter.disconnect() } catch (e) { } dawMeter = null }
  if (DAW.recording && !silent) dawRecStop();
  if (!silent) dawUI();
}
function dawDrawHead() {
  const p = DAW.from + ctx.currentTime - DAW.t0, L = dawLen();
  if (p >= L + 0.3 && !DAW.recording) { DAW.pos = 0; dawStop(); return }
  $('#dawPos').textContent = fmtTime(p) + ' / ' + fmtTime(L);
  $$('.wave .head').forEach(h => h.style.left = Math.min(100, p / L * 100) + '%');
  if (dawMeter) { const a = new Float32Array(dawMeter.fftSize); dawMeter.getFloatTimeDomainData(a); let pk = 0; for (const v of a) pk = Math.max(pk, Math.abs(v)); $('#dawMeter i').style.width = Math.min(100, pk * 100) + '%'; $('#dawMeter').classList.toggle('clip', pk > 0.98) }
}
let dawRec = null;
async function dawRecStart() {
  if (!DAW.beat) { toast('Open a take that has the beat in it, then record your vocal over it'); return }
  let mic; try { mic = await getMic() } catch (e) { toast(micError(e)); return }
  const chunks = [], mr = new MediaRecorder(mic, MIME ? { mimeType: MIME } : {});
  mr.ondataavailable = e => e.data.size && chunks.push(e.data);
  mr.onstop = async () => {
    DAW.vocalBlob = new Blob(chunks, { type: mr.mimeType }); DAW.vocal = await decode(await DAW.vocalBlob.arrayBuffer());
    DAW.offset = -((ctx.outputLatency || 0) + (ctx.baseLatency || 0) + 0.015); DAW.vocalLabel = 'Recorded in the DAW';
    dawUI(); toast('Vocal recorded');
  };
  DAW.vocalSave = DAW.vocal; DAW.vocal = null; // the old vocal would play under the new one
  await dawPlay(0); mr.start(250); dawRec = mr; DAW.recording = true; dawUI();
}
function dawRecStop() { if (dawRec && dawRec.state !== 'inactive') dawRec.stop(); dawRec = null; DAW.recording = false; if (DAW.playing) dawStop(true); dawUI() }

async function openTakeInDaw(id) {
  const t = await IDB.get(id); if (!t) return;
  ensureCtx(); if (DAW.playing) dawStop();
  const dec = async b => b ? decode(await b.arrayBuffer()) : null;
  DAW.beat = await dec(t.beat); DAW.vocal = await dec(t.vocal); DAW.beatBlob = t.beat; DAW.vocalBlob = t.vocal;
  DAW.offset = t.offset || 0; DAW.bpm = t.bpm || 90; DAW.pos = 0; DAW.name = 'GGRap-' + (t.sessionName || 'session').replace(/\W+/g, '') + '-' + t.name.replace(/\W+/g, '');
  DAW.source = { sessionId: t.sessionId, sessionName: t.sessionName || (sessions.find(x => x.id === t.sessionId) || {}).name || 'Session', take: t.name };
  DAW.beatLabel = DAW.beat ? 'Beat from ' + t.name : null; DAW.vocalLabel = DAW.vocal ? 'Vocal from ' + t.name : null; DAW.projectId = null;
  location.hash = 'daw'; dawUI(); toast(t.name + ' is open in the DAW');
}
async function dawSave() {
  if (!DAW.beat && !DAW.vocal) return;
  const id = DAW.projectId || 'p' + Date.now(), old = DAW.projectId ? await IDB.get(id, 'projects') : null;
  const proj = { id, created: old ? old.created : Date.now(), saved: Date.now(), name: (DAW.source ? DAW.source.sessionName + ' · ' + DAW.source.take : 'Recording'),
    source: DAW.source || null, beat: DAW.beatBlob || null, vocal: DAW.vocalBlob || null, offset: DAW.offset, bpm: DAW.bpm,
    tr: JSON.parse(JSON.stringify(DAW.tr)), master: { ...DAW.master }, dur: dawLen(), fileName: DAW.name };
  await IDB.put(proj, 'projects'); DAW.projectId = id; dawUI(); toast(old ? 'Saved changes to history' : 'Saved to history');
}
async function openProject(id) {
  const p = await IDB.get(id, 'projects'); if (!p) return;
  ensureCtx(); if (DAW.playing) dawStop();
  const dec = async b => b ? decode(await b.arrayBuffer()) : null;
  DAW.beat = await dec(p.beat); DAW.vocal = await dec(p.vocal); DAW.beatBlob = p.beat; DAW.vocalBlob = p.vocal;
  DAW.offset = p.offset; DAW.bpm = p.bpm; DAW.tr = JSON.parse(JSON.stringify(p.tr)); DAW.master = { ...p.master };
  DAW.source = p.source; DAW.name = p.fileName; DAW.projectId = p.id; DAW.pos = 0;
  DAW.beatLabel = DAW.beat ? 'Beat' : null; DAW.vocalLabel = DAW.vocal ? 'Vocal' : null;
  dawUI(); window.scrollTo({ top: 0 }); toast(p.name + ' opened');
}
let histDelArm = null;
async function renderHistory() {
  const box = $('#history'); if (!box) return;
  const list = (await IDB.all('projects')).sort((a, b) => b.saved - a.saved);
  box.innerHTML = list.length ? list.map(p => '<div class="take"><div class="tk-main"><b>' + esc(p.name) + '</b><span class="muted">' + fmtTime(p.dur) + ' · saved ' + sessDate(p.saved) + ' ' + new Date(p.saved).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + (p.id === DAW.projectId ? ' · open now' : '') + '</span></div><div class="row"><button class="btn small primary" data-hopen="' + p.id + '">Open</button><button class="btn small" data-hdel="' + p.id + '">' + (histDelArm === p.id ? 'Tap again to delete' : 'Delete') + '</button></div></div>').join('')
    : '<p class="muted">Nothing saved yet. Open a take from a session, polish it here, then press <b>Save to history</b>.</p>';
}
function drawWave(canvas, buf) {
  const w = canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1), h = canvas.height = canvas.clientHeight * (window.devicePixelRatio || 1);
  const g = canvas.getContext('2d'); g.clearRect(0, 0, w, h);
  if (!buf) return;
  const L = dawLen() || buf.duration, d = buf.getChannelData(0), x0 = canvas.dataset.track === 'vocal' ? DAW.offset / L * w : 0, ww = buf.duration / L * w;
  g.fillStyle = getComputedStyle(canvas).color; const step = Math.max(1, Math.floor(d.length / ww));
  for (let x = 0; x < ww; x++) { let pk = 0; for (let i = x * step; i < (x + 1) * step && i < d.length; i += 4) pk = Math.max(pk, Math.abs(d[i])); const y = pk * h / 2; g.fillRect(x0 + x, h / 2 - y, 1, Math.max(1, y * 2)) }
}
function fxPanel(key) {
  const f = DAW.tr[key].fx, sl = (path, min, max, step, val, label) => '<label class="fxs">' + label + '<input type="range" data-fx="' + key + '.' + path + '" min="' + min + '" max="' + max + '" step="' + step + '" value="' + val + '"></label>';
  return '<div class="fxrow">' +
    '<div class="fx' + (f.eq.on ? ' on' : '') + '"><button data-fxon="' + key + '.eq">EQ</button>' + (f.eq.on ? sl('eq.low', -12, 12, 1, f.eq.low, 'Low') + sl('eq.high', -12, 12, 1, f.eq.high, 'High') : '') + '</div>' +
    '<div class="fx' + (f.comp.on ? ' on' : '') + '"><button data-fxon="' + key + '.comp">Compressor</button>' + (f.comp.on ? sl('comp.amt', 0, 1, 0.05, f.comp.amt, 'Amount') : '') + '</div>' +
    '<div class="fx' + (f.delay.on ? ' on' : '') + '"><button data-fxon="' + key + '.delay">Delay</button>' + (f.delay.on ? sl('delay.mix', 0, 0.8, 0.05, f.delay.mix, 'Mix') + '<label class="fxs">Time<select data-fx="' + key + '.delay.time"><option' + (f.delay.time === '1/8' ? ' selected' : '') + '>1/8</option><option' + (f.delay.time === '1/8.' ? ' selected' : '') + '>1/8.</option><option' + (f.delay.time === '1/4' ? ' selected' : '') + '>1/4</option></select></label>' : '') + '</div>' +
    '<div class="fx' + (f.reverb.on ? ' on' : '') + '"><button data-fxon="' + key + '.reverb">Reverb</button>' + (f.reverb.on ? sl('reverb.mix', 0, 0.8, 0.05, f.reverb.mix, 'Mix') : '') + '</div></div>';
}
function dawUI() {
  if (!$('#daw')) return;
  const L = dawLen();
  $('#dawPlay').textContent = DAW.playing && !DAW.recording ? '■ Stop' : '▶ Play';
  $('#dawRec').classList.toggle('on', DAW.recording); $('#dawRec').textContent = DAW.recording ? 'Stop recording' : 'Record vocal';
  $('#dawPos').textContent = fmtTime(DAW.pos) + ' / ' + fmtTime(L);
  $('#beatLabel').textContent = DAW.beat ? (DAW.beatLabel || 'Beat') + ' · ' + fmtTime(DAW.beat.duration) : 'No beat in this recording';
  $('#vocalLabel').textContent = DAW.vocal ? (DAW.vocalLabel || 'Vocal') + ' · ' + fmtTime(DAW.vocal.duration) : (DAW.recording ? 'Recording…' : 'No vocal yet. Press Record vocal to rap over the beat');
  const open = !!(DAW.beat || DAW.vocal);
  $('#dawEmpty').hidden = open; $('#dawWork').hidden = !open;
  $('#dawSource').textContent = DAW.source ? DAW.source.sessionName + ' · ' + DAW.source.take : 'Saved recording';
  $('#dawSave').textContent = DAW.projectId ? 'Save changes' : 'Save to history';
  renderHistory();
  for (const k of ['beat', 'vocal']) {
    const tr = DAW.tr[k];
    $('#' + k + 'Vol').value = tr.vol; $('#' + k + 'Mute').setAttribute('aria-pressed', String(tr.mute));
    $('#' + k + 'Fx').innerHTML = fxPanel(k);
    drawWave($('#' + k + 'Wave canvas'), k === 'beat' ? DAW.beat : DAW.vocal);
  }
  $('#dawOffset').value = Math.round(DAW.offset * 1000); $('#dawOffsetOut').textContent = Math.round(DAW.offset * 1000) + ' ms';
  $('#masterVol').value = DAW.master.vol;
  $$('.wave .head').forEach(h => h.style.left = (L ? Math.min(100, DAW.pos / L * 100) : 0) + '%');
  $$('[data-export]').forEach(b => b.disabled = !L);
}
function dawChanged() { if (DAW.playing && !DAW.recording) dawPlay(DAW.from + ctx.currentTime - DAW.t0); else dawUI() }

/* ---------------- export ---------------- */
function wavBlob(ab) {
  const ch = ab.numberOfChannels, len = ab.length, sr = ab.sampleRate, buf = new ArrayBuffer(44 + len * ch * 2), v = new DataView(buf);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)) };
  ws(0, 'RIFF'); v.setUint32(4, 36 + len * ch * 2, true); ws(8, 'WAVE'); ws(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, ch, true);
  v.setUint32(24, sr, true); v.setUint32(28, sr * ch * 2, true); v.setUint16(32, ch * 2, true); v.setUint16(34, 16, true); ws(36, 'data'); v.setUint32(40, len * ch * 2, true);
  const data = Array.from({ length: ch }, (_, c) => ab.getChannelData(c)); let o = 44;
  for (let i = 0; i < len; i++) for (let c = 0; c < ch; c++) { const s = Math.max(-1, Math.min(1, data[c][i])); v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true); o += 2 }
  return new Blob([buf], { type: 'audio/wav' });
}
function loadScript(src) { return new Promise((res, rej) => { if (window.lamejs) return res(); const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('script')); document.head.appendChild(s) }) }
async function mp3Blob(ab) {
  await loadScript('https://cdn.jsdelivr.net/npm/lamejs@1.2.1/lame.min.js');
  const toI16 = f => { const o = new Int16Array(f.length); for (let i = 0; i < f.length; i++) { const s = Math.max(-1, Math.min(1, f[i])); o[i] = s < 0 ? s * 0x8000 : s * 0x7fff } return o };
  const enc = new lamejs.Mp3Encoder(2, ab.sampleRate, 192), L = toI16(ab.getChannelData(0)), R = toI16(ab.getChannelData(ab.numberOfChannels > 1 ? 1 : 0)), out = [];
  for (let i = 0; i < L.length; i += 1152) {
    const b = enc.encodeBuffer(L.subarray(i, i + 1152), R.subarray(i, i + 1152)); if (b.length) out.push(new Uint8Array(b));
    if (i % (1152 * 400) === 0) await new Promise(r => setTimeout(r, 0)); // keep the page responsive
  }
  const e = enc.flush(); if (e.length) out.push(new Uint8Array(e));
  return new Blob(out, { type: 'audio/mpeg' });
}
async function dawExport(kind) {
  const L = dawLen(); if (!L) return;
  const btn = $('[data-export="' + kind + '"]'), label = btn.textContent; btn.disabled = true; btn.textContent = 'Mixing…';
  try {
    const oc = new OfflineAudioContext(2, Math.ceil((L + 0.5) * 44100), 44100);
    buildGraph(oc, 0, 0).lim.connect(oc.destination);
    const ab = await oc.startRendering();
    btn.textContent = kind === 'mp3' ? 'Encoding…' : 'Saving…';
    const blob = kind === 'mp3' ? await mp3Blob(ab) : wavBlob(ab);
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = DAW.name + '.' + kind;
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 4000);
    toast('Exported ' + a.download);
  } catch (e) { toast(kind === 'mp3' ? 'MP3 export needs an internet connection the first time. WAV works offline.' : 'Export failed: ' + e.message) }
  btn.disabled = false; btn.textContent = label;
}

/* ---------------- wiring ---------------- */
document.addEventListener('click', async e => {
  const t = e.target; let b;
  if (t.closest('#lpPlay')) { LE.playing ? LE.stop() : LE.play(); return }
  if (t.closest('#recBtn')) { recToggle(); return }
  if (b = t.closest('[data-pad]')) {
    const id = b.dataset.pad;
    if (LE.mode === 'chain') LE.chain.push(id);
    else { if (LE.mode === 'random') LE.mode = 'manual'; if (LE.playing) LE.queue = id; else { LE.cur = id; await LE.play() } }
    announceMix(); return;
  }
  if (b = t.closest('[data-lmode]')) { LE.mode = b.dataset.lmode; if (LE.mode === 'chain') LE.chainAt = Math.max(0, LE.chain.indexOf(LE.cur)); announceMix(); return }
  if (t.closest('#chainClear')) { LE.chain = []; LE.chainAt = 0; announceMix(); return }
  if (b = t.closest('[data-tplay]')) { playTake(b.dataset.tplay); return }
  if (b = t.closest('[data-tdaw]')) { openTakeInDaw(b.dataset.tdaw); return }
  if (b = t.closest('[data-tdel]')) {
    const id = b.dataset.tdel;
    if (takeDelArm !== id) { takeDelArm = id; renderTakes(); setTimeout(() => { if (takeDelArm === id) { takeDelArm = null; renderTakes() } }, 4000); return }
    takeDelArm = null; await IDB.del(id); renderTakes(); toast('Take deleted'); return;
  }
  if (t.closest('#dawPlay')) { DAW.playing ? dawStop() : dawPlay(); return }
  if (t.closest('#dawRec')) { DAW.recording ? dawRecStop() : dawRecStart(); return }
  if (t.closest('#dawToStart')) { const was = DAW.playing; dawStop(); DAW.pos = 0; if (was) dawPlay(0); else dawUI(); return }
  if (t.closest('#dawSave')) { dawSave(); return }
  if (b = t.closest('.recpick button')) { b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true')); store.set('ggrap.recpick', { beat: recWant('Beat'), vocal: recWant('Vocal') }); return }
  if (b = t.closest('[data-hopen]')) { openProject(b.dataset.hopen); return }
  if (b = t.closest('[data-hdel]')) {
    const id = b.dataset.hdel;
    if (histDelArm !== id) { histDelArm = id; renderHistory(); setTimeout(() => { if (histDelArm === id) { histDelArm = null; renderHistory() } }, 4000); return }
    histDelArm = null; await IDB.del(id, 'projects'); if (DAW.projectId === id) DAW.projectId = null; renderHistory(); toast('Deleted from history'); return;
  }
  if (b = t.closest('[data-mute]')) { const tr = DAW.tr[b.dataset.mute]; tr.mute = !tr.mute; dawChanged(); return }
  if (b = t.closest('[data-fxon]')) { const [k, fx] = b.dataset.fxon.split('.'); DAW.tr[k].fx[fx].on = !DAW.tr[k].fx[fx].on; dawChanged(); return }
  if (b = t.closest('[data-export]')) { dawExport(b.dataset.export); return }
  if (b = t.closest('.wave')) { const r = b.getBoundingClientRect(), L = dawLen(); if (!L) return; const p = (e.clientX - r.left) / r.width * L; if (DAW.playing) dawPlay(p); else { DAW.pos = p; dawUI() } }
});
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'lpVol') { if (LE.out) LE.out.gain.setTargetAtTime(+t.value, ctx.currentTime, 0.02); store.set('ggrap.vol', +t.value) }
  if (t.id === 'beatVol' || t.id === 'vocalVol') { DAW.tr[t.id.replace('Vol', '')].vol = +t.value; dawChanged() }
  if (t.id === 'masterVol') { DAW.master.vol = +t.value; dawChanged() }
  if (t.id === 'dawOffset') { DAW.offset = +t.value / 1000; $('#dawOffsetOut').textContent = t.value + ' ms'; drawWave($('#vocalWave canvas'), DAW.vocal) }
  if (t.dataset && t.dataset.fx) { const [k, fx, p] = t.dataset.fx.split('.'); DAW.tr[k].fx[fx][p] = t.tagName === 'SELECT' ? t.value : +t.value; if (DAW.playing && !DAW.recording) dawPlay(DAW.from + ctx.currentTime - DAW.t0) }
});
document.addEventListener('change', async e => {
  const t = e.target;
  if (t.id === 'lpBpm') LE.setTempo(+t.value);
  if (t.id === 'dawOffset' && DAW.playing) dawChanged();
});
window.addEventListener('resize', () => { if (!$('#daw').hidden) dawUI() });
try { const v = store.get('ggrap.vol', 0.85); $('#lpVol').value = v } catch (e) { }
{ const rp = store.get('ggrap.recpick', { beat: true, vocal: true }); $('#recBeat').setAttribute('aria-pressed', String(!!rp.beat)); $('#recVocal').setAttribute('aria-pressed', String(!!rp.vocal)) }
requestAnimationFrame(drawLoopBars);
