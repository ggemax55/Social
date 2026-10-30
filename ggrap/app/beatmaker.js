/* ================= In-app beat maker =================
   Builds a new beat for every session from its style, key, emotion and tempo,
   using the real instrument samples packed into the page (window.GGRAP_SAMPLES).
   Each beat has 4 versions (A-D): 4 bars each, same key and tempo, different
   instrument, chords and melody, ending in a 2-beat transition. Rendered with
   an OfflineAudioContext, so it sounds the same every time you open it. */
const BM = { ready: null, drums: {}, inst: {} };
function bmLoad() {
  if (BM.ready) return BM.ready;
  ensureCtx();
  BM.ready = (async () => {
    const S = window.GGRAP_SAMPLES;
    await Promise.all(Object.entries(S.drums).map(async ([k, b]) => { BM.drums[k] = await decode(b64ToBuf(b)) }));
    await Promise.all(Object.entries(S.inst).map(async ([name, zones]) => {
      const z = {};
      await Promise.all(Object.entries(zones).map(async ([m, b]) => { z[+m] = await decode(b64ToBuf(b)) }));
      BM.inst[name] = { zones: z, notes: Object.keys(z).map(Number).sort((a, b) => a - b) };
    }));
  })();
  return BM.ready;
}
function mulberry(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296 } }
function hashStr(s) { let h = 2166136261; for (const c of String(s)) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0 }
const bmShuffle = (a, r) => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1));[a[i], a[j]] = [a[j], a[i]] } return a };

const KITS = {
  rap: { kick: 'kick', snare: 'snare', clap: 'clap', hat: 'hat', ohat: 'ohat', rim: 'rim', toms: ['tomH', 'tomM', 'tomL'] },
  808: { kick: 'kick', snare: 'snare808', clap: 'clap', hat: 'hat808', ohat: 'ohat808', rim: 'rim', toms: ['tom808H', 'tom808M', 'tom808L'] },
  live: { kick: 'kick2', snare: 'snare2', clap: 'clap', hat: 'hat', ohat: 'ohat', rim: 'rim', toms: ['tomH', 'tomM', 'tomL'] },
};
const STYLE_CFG = { // per drum pattern (the app's beat presets)
  boombap: { kit: 'rap', bass: 'upright', swing: 0.28, dusty: true }, lofi: { kit: 'rap', bass: 'upright', swing: 0.22, dusty: true },
  oldschool: { kit: 'live', bass: 'upright', swing: 0.12, dusty: true }, gfunk: { kit: 'live', bass: 'upright', swing: 0.12 },
  fast: { kit: 'rap', bass: 'upright', swing: 0.1 }, trap: { kit: '808', bass: '808', rolls: true }, drill: { kit: '808', bass: '808', slide: true, rolls: true },
  phonk: { kit: '808', bass: '808', bell: true }, grime: { kit: '808', bass: '808' }, oriental: { kit: '808', bass: '808', rolls: true },
  house: { kit: '808', bass: '808short' }, jersey: { kit: '808', bass: '808short' }, dembow: { kit: '808', bass: '808short' },
  afro: { kit: 'live', bass: 'upright', swing: 0.1 }, amapiano: { kit: 'live', bass: '808short', swing: 0.08 },
  kochari: { kit: 'live', bass: 'upright' }, tamzara: { kit: 'live', bass: 'upright' }, shalakho: { kit: 'live', bass: 'upright' },
};
const SCALES = { minor: [0, 2, 3, 5, 7, 8, 10], 'harmonic minor': [0, 2, 3, 5, 7, 8, 11], major: [0, 2, 4, 5, 7, 9, 11] };
const PROG_BANK = {
  minor: [[[0, 'm'], [8, 'M'], [3, 'M'], [10, 'M']], [[0, 'm'], [5, 'm'], [8, 'M'], [7, 'M']], [[0, 'm'], [10, 'M'], [8, 'M'], [10, 'M']],
  [[0, 'm'], [8, 'M'], [5, 'm'], [7, 'M']], [[0, 'm'], [3, 'M'], [10, 'M'], [5, 'm']], [[0, 'm7'], [5, 'm7'], [10, '7'], [3, 'maj7']]],
  major: [[[0, 'M'], [7, 'M'], [9, 'm'], [5, 'M']], [[9, 'm'], [5, 'M'], [0, 'M'], [7, 'M']], [[0, 'M'], [5, 'M'], [7, 'M'], [5, 'M']],
  [[0, 'maj7'], [9, 'm7'], [2, 'm7'], [7, '7']], [[5, 'M'], [7, 'M'], [4, 'm'], [9, 'm']], [[0, 'M'], [4, 'm'], [5, 'M'], [7, 'M']]],
};
const FEAT_NAME = { keys: 'Piano', pizz: 'Pizzicato', pad: 'Strings', lead: 'Flute' };
const chordName = (key, [s, t]) => NOTES[(key + s) % 12] + ({ m: 'm', M: '', m7: 'm7', '7': '7', maj7: 'maj7' }[t] || '');

function bmManifest(spec) {
  const st = STYLES[spec.preset] || STYLES.boombap, barBeats = st.steps / st.spb, base = Math.round(spec.bpm);
  const tempos = [-10, -5, 0, 5, 10].map(d => base + d).filter(t => t >= 60 && t <= 180);
  const r = mulberry(spec.seed), feats = bmShuffle(['keys', 'pizz', 'pad', 'lead'], r);
  const trans = bmShuffle(['snare roll', 'tom fill', 'stop + riser', 'hat roll'], r);
  const fam = spec.mode === 'major' ? 'major' : 'minor', bank = bmShuffle(PROG_BANK[fam], r);
  const versions = ['A', 'B', 'C', 'D'].map((id, i) => {
    const prog = i === 0 ? spec.prog : bank[i - 1];
    return { id, idx: i, feature: feats[i], transition: trans[i], prog, name: FEAT_NAME[feats[i]] + ' · ' + prog.map(c => chordName(spec.key, c)).join(' ') };
  });
  return { style: spec.styleName, key: NOTES[spec.key] + ' ' + spec.mode, tempos, default_bpm: base, versions, barBeats, generated: true };
}

function bmRhythm(r, barBeats, dense) {
  const T = dense ? [[[0, .75], [.75, .75], [1.5, .5], [2, 1]], [[0, .5], [.5, .5], [1, 1], [3, .75]], [[0, .5], [1, .5], [1.5, .5], [2.5, 1]]]
    : [[[0, 1], [1.5, .5], [2, 1.5]], [[.5, .5], [1, 1], [2.5, 1]], [[0, 1.5], [2, 1.5]], [[0, 1], [2, .5], [2.5, 1]]];
  return T[Math.floor(r() * T.length)].filter(([b]) => b < barBeats).map(([b, l]) => [b, Math.min(l, barBeats - b)]);
}
function bmMelody(r, key, scaleIv, prog, barBeats, lo, hi, dense) {
  const scale = []; for (let m = lo; m <= hi; m++) if (scaleIv.includes(((m - key) % 12 + 12) % 12)) scale.push(m);
  let cur = scale[Math.floor(scale.length / 2)]; const out = [];
  prog.forEach(([semi, type], bar) => {
    const pcs = INTV[type].slice(0, 3).map(i => (key + semi + i) % 12), tones = scale.filter(n => pcs.includes(n % 12));
    for (const [b, ln] of bmRhythm(r, barBeats, dense)) {
      if ((b % 1 === 0 || r() < 0.35) && tones.length) { const c = cur; cur = tones.reduce((a, n) => Math.abs(n - c) + r() * 3 < Math.abs(a - c) + r() * 3 ? n : a) }
      else { const i = scale.indexOf(cur) + [-2, -1, 1, 2][Math.floor(r() * 4)]; cur = scale[Math.max(0, Math.min(scale.length - 1, i))] }
      out.push([bar * barBeats + b, cur, ln]);
    }
  });
  return out;
}
const voiceChord = (key, [semi, type], center) => INTV[type].map(i => { const pc = (key + semi + i) % 12; let n = pc + 12 * Math.round((center - pc) / 12); return n }).sort((a, b) => a - b);
const lowNote = (pc, lo) => lo + ((pc - lo) % 12 + 12) % 12;

async function bmRender(spec, ver, tempo) {
  await bmLoad();
  const st = STYLES[spec.preset] || STYLES.boombap, cfg = STYLE_CFG[spec.preset] || STYLE_CFG.boombap, kit = KITS[cfg.kit];
  const spb = st.spb, barBeats = st.steps / spb, beat = 60 / tempo, stepSec = beat / spb, loopBeats = 4 * barBeats;
  const sr = 44100, oc = new OfflineAudioContext(2, Math.ceil((loopBeats * beat + 2.5) * sr), sr);
  const r = mulberry(spec.seed * 7 + ver.idx * 1013 + 1), key = spec.key, prog = ver.prog, fill = loopBeats - 2;
  const D = n => BM.drums[n], swing = cfg.swing || 0, dusty = cfg.dusty || spec.sample > 0;
  const T = (b, j = 0.004) => { const s16 = Math.round(b * spb * 1e4) / 1e4, late = spb === 4 && Math.abs(s16 - Math.round(s16)) < 1e-6 && Math.round(s16) % 2 === 1 ? swing * stepSec : 0; return Math.max(0, b * beat + late + (j ? (r() - 0.5) * 2 * j : 0)) };

  // mix buses
  const master = oc.createGain(), glue = oc.createDynamicsCompressor(), lim = oc.createDynamicsCompressor();
  glue.threshold.value = -16; glue.ratio.value = 2.5; glue.attack.value = 0.012; glue.release.value = 0.15;
  lim.threshold.value = -2; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.002; lim.release.value = 0.08;
  master.connect(glue); glue.connect(lim); lim.connect(oc.destination);
  const verb = oc.createConvolver(); verb.buffer = irBuffer(oc); const vret = oc.createGain(); vret.gain.value = 0.3; verb.connect(vret); vret.connect(master);
  const bus = (gain, send = 0, lp = 0, hp = 0) => {
    const g = oc.createGain(); g.gain.value = gain; let out = g;
    if (hp) { const f = oc.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = hp; out.connect(f); out = f }
    if (lp) { const f = oc.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = lp; out.connect(f); out = f }
    out.connect(master); if (send) { const s = oc.createGain(); s.gain.value = send; out.connect(s); s.connect(verb) } return g;
  };
  const drums = (() => { const g = oc.createGain(), c = oc.createDynamicsCompressor(), mk = oc.createGain(); c.threshold.value = -18; c.ratio.value = 4; c.attack.value = 0.006; c.release.value = 0.08; mk.gain.value = 1.6; g.connect(c); c.connect(mk); mk.connect(master); return g })();
  const keysB = bus(0.32, 0.15, dusty ? 6500 : 0, 120), padB = bus(0.26, 0.45, 0, 180), leadB = bus(0.4, 0.28, dusty ? 7000 : 0, 250),
    pizzB = bus(0.36, 0.25, 0, 150), bassB = bus(0.95, 0, 3500, 30), b808 = bus(0.8, 0, 0, 28);

  const play = (buf, t, rate, gain, dest, dur, rel = 0.25, pan = 0) => {
    if (!buf) return; const s = oc.createBufferSource(), g = oc.createGain(); s.buffer = buf; s.playbackRate.value = rate;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + 0.004);
    if (dur) { g.gain.setValueAtTime(gain, t + dur); g.gain.linearRampToValueAtTime(0, t + dur + rel) }
    let n = g; if (pan) { const p = oc.createStereoPanner(); p.pan.value = pan; g.connect(p); n = p }
    s.connect(g); n.connect(dest); s.start(t); if (dur) s.stop(t + dur + rel + 0.05);
  };
  const hit = (name, b, gain, pan = 0, j = 0.004) => play(D(name), T(b, j), 1, gain, drums, 0, 0, pan);
  const note = (inst, midi, t, dur, vel, dest, pan = 0, rel = 0.3) => { const I = BM.inst[inst], src = I.notes.reduce((a, n) => Math.abs(n - midi) < Math.abs(a - midi) ? n : a); play(I.zones[src], t, Math.pow(2, (midi - src) / 12), 0.25 + 0.6 * vel, dest, dur, rel, pan) };
  const curve = new Float32Array(1024); for (let i = 0; i < 1024; i++) { const x = i / 511.5 - 1; curve[i] = Math.tanh(2.5 * x) / Math.tanh(2.5) }
  const e808 = (midi, t, dur, from) => {
    const o = oc.createOscillator(), ws = oc.createWaveShaper(), g = oc.createGain(), f = 440 * Math.pow(2, (midi - 69) / 12);
    if (from != null) { o.frequency.setValueAtTime(440 * Math.pow(2, (from - 69) / 12), t); o.frequency.exponentialRampToValueAtTime(f, t + 0.09) }
    else { o.frequency.setValueAtTime(f * 1.6, t); o.frequency.exponentialRampToValueAtTime(f, t + 0.05) }
    ws.curve = curve; g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.9, t + 0.005); g.gain.setTargetAtTime(0.0001, t + dur * 0.7, dur * 0.25 + 0.05);
    o.connect(ws); ws.connect(g); g.connect(b808); o.start(t); o.stop(t + dur + 0.5);
  };
  const bell = (midi, t) => { [1, 1.48].forEach(m => { const o = oc.createOscillator(), f = oc.createBiquadFilter(), g = oc.createGain(); o.type = 'square'; o.frequency.value = 440 * Math.pow(2, (midi - 69) / 12) * m; f.type = 'bandpass'; f.frequency.value = o.frequency.value * 1.2; f.Q.value = 3; g.gain.setValueAtTime(0.09, t); g.gain.exponentialRampToValueAtTime(0.0005, t + 0.16); o.connect(f); f.connect(g); g.connect(leadB); o.start(t); o.stop(t + 0.2) }) };

  const at = s => s / spb, inFill = b => b >= fill - 1e-6;
  let prevRoot = null;
  for (let bar = 0; bar < 4; bar++) {
    const x = bar * barBeats, ch = prog[bar % prog.length], keep = b => !inFill(x + b) || ver.transition === 'hat roll';
    // drums
    (st.kick || []).forEach(s => { if (!inFill(x + at(s))) hit(kit.kick, x + at(s), 1, 0, 0) });
    (st.snare || []).forEach(s => { if (keep(at(s))) hit(kit.snare, x + at(s), 0.8) });
    (st.clap || []).forEach(s => { if (keep(at(s))) hit(kit.clap, x + at(s), 0.5) });
    (st.hat || []).forEach(s => { if (!inFill(x + at(s))) hit(kit.hat, x + at(s), s % spb === 0 ? 0.45 : 0.28, 0.2, 0.002) });
    (st.ohat || []).forEach(s => { if (!inFill(x + at(s))) hit(kit.ohat, x + at(s), 0.3, 0.2) });
    (st.dum || []).forEach(s => { if (!inFill(x + at(s))) { hit(kit.toms[2], x + at(s), 0.9); hit(kit.kick, x + at(s), 0.6, 0, 0) } });
    (st.tak || []).forEach(s => { if (!inFill(x + at(s))) hit(kit.rim, x + at(s), 0.5, -0.1) });
    if (cfg.rolls && bar % 2 === 1 && !inFill(x + barBeats - 1)) for (let k = 0; k < 6; k++) hit(kit.hat, x + barBeats - 1 + k / 6, 0.22 + k * 0.03, 0.2, 0);
    if (cfg.dusty && bar % 2 === 1 && !inFill(x + 3.75)) hit(kit.snare, x + 3.75, 0.18);
    // bass: root of the chord on the pattern's bass hits
    const pc = (key + ch[0]) % 12, root = cfg.bass === 'upright' ? lowNote(pc, 33) : lowNote(pc, 28);
    const bsteps = st.bass ? Object.keys(st.bass).map(Number).sort((a, b) => a - b) : [0, st.steps / 2];
    bsteps.forEach((s, i) => {
      const b = at(s); if (inFill(x + b) && ver.transition === 'stop + riser') return;
      const len = ((i + 1 < bsteps.length ? at(bsteps[i + 1]) : barBeats) - b) * beat * 0.95;
      if (cfg.bass === 'upright') note('bass', root, T(x + b), Math.min(len, 1.2), 0.85, bassB, 0, 0.1);
      else e808(root, T(x + b, 0), cfg.bass === '808short' ? Math.min(len, 0.4) : len, cfg.slide && i === 0 && prevRoot !== null && prevRoot !== root ? prevRoot : null);
    });
    prevRoot = root;
    // harmony: each version has its own lead instrument
    const chord = voiceChord(key, ch, 64), fast = tempo >= 110 || cfg.kit === '808', t0 = T(x, 0.002);
    if (ver.feature === 'keys') {
      const hits = fast ? [[0, barBeats / 2 - 0.1], [barBeats / 2, barBeats / 2 - 0.1]] : [[0, 1.4], [1.5, 0.9], [3.5, 0.3]].filter(([b]) => b < barBeats);
      for (const [b, l] of hits) if (!inFill(x + b)) chord.forEach(n => note('piano', fast ? n + 12 : n, T(x + b), l * beat, fast ? 0.45 : 0.6, keysB, -0.15));
    } else if (ver.feature === 'pizz') {
      const arp = [0, 2, 1, 3, 2, 1, 2, 0].map((k, i) => chord[k % chord.length] + 12 * (i >= 4 && i < 6 ? 1 : 0));
      for (let i = 0; i < barBeats * 2; i++) if (!inFill(x + i / 2)) note('pizz', arp[i % arp.length], T(x + i / 2), 0.4 * beat, 0.6, pizzB, i % 2 ? 0.25 : -0.25);
    } else if (ver.feature === 'pad') {
      chord.slice(-3).forEach(n => note('violins', n < 62 ? n + 12 : n, t0, barBeats * beat * 0.98, 0.5, padB, 0, 0.6));
      note('cellos', lowNote(pc, 45), t0, barBeats * beat * 0.98, 0.55, padB, 0, 0.6);
    } else {
      chord.forEach(n => note('piano', n, t0, Math.min(1.8, barBeats * 0.45) * beat, 0.4, keysB));
    }
    if (cfg.bell) for (let i = 0; i < barBeats * 2; i += 1) if ([0, 3, 6].includes(i % 8) && !inFill(x + i / 2)) bell(chord[i % chord.length] + 12, T(x + i / 2, 0));
  }
  // melody line, different seed per version
  const leadInst = { keys: 'piano', pizz: 'pizz', pad: 'piano', lead: 'flute' }[ver.feature];
  const [lo, hi] = { piano: [69, 86], pizz: [67, 84], flute: [72, 88] }[leadInst];
  for (const [b, n, l] of bmMelody(r, key, SCALES[spec.mode] || SCALES.minor, prog, barBeats, lo, hi, cfg.kit === '808'))
    if (!inFill(b) || ver.transition === 'hat roll') note(leadInst, n, T(b), l * beat, 0.65, leadB, 0.1);
  // the 2-beat transition into the next version
  if (ver.transition === 'snare roll') for (let i = 0; i < 8; i++) hit(kit.snare, fill + i / 4, 0.3 + 0.08 * i, 0, 0);
  else if (ver.transition === 'tom fill') { for (let i = 0; i < 8; i++) hit(kit.toms[Math.min(2, Math.floor(i / 3))], fill + i / 4, 0.45, (i % 3 - 1) * 0.3, 0); hit(kit.kick, fill + 1.75, 0.8, 0, 0) }
  else if (ver.transition === 'stop + riser') {
    const src = D(kit.ohat), n = Math.floor(2 * beat * sr), rev = oc.createBuffer(2, n, sr);
    for (let c = 0; c < 2; c++) { const o = rev.getChannelData(c), d = src.getChannelData(Math.min(c, src.numberOfChannels - 1)); for (let i = 0; i < n; i++) o[i] = d[(d.length - 1 - (i % d.length))] * Math.pow(i / n, 2) * 0.9 }
    play(rev, fill * beat, 1, 0.7, leadB, 0, 0);
  } else { let t = 0; while (t < 2) { hit(kit.hat, fill + t, 0.25 + 0.2 * t, 0.2, 0); t += t < 1 ? 1 / 6 : 1 / 8 } hit(kit.ohat, fill + 1.5, 0.45, 0.2, 0) }
  // record texture: hiss and crackle
  if (dusty) {
    const n = oc.length, nb = oc.createBuffer(2, n, sr), amt = 0.4 + 0.6 * (spec.sample || 0) + (cfg.dusty ? 0.3 : 0);
    for (let c = 0; c < 2; c++) { const d = nb.getChannelData(c); for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * 0.002 * amt + (Math.random() < 0.0004 ? (Math.random() - 0.5) * 0.12 * amt : 0) }
    play(nb, 0, 1, 1, master, 0, 0);
  }
  const out = await oc.startRendering();
  let pk = 0; for (let c = 0; c < out.numberOfChannels; c++) for (const v of out.getChannelData(c)) pk = Math.max(pk, Math.abs(v));
  if (pk > 0) for (let c = 0; c < out.numberOfChannels; c++) { const d = out.getChannelData(c); for (let i = 0; i < d.length; i++) d[i] *= 0.95 / pk }
  return out;
}

/* session -> beat spec. The seed changes when you press New beat. */
function specFromVibe(v, seed, bpm) {
  const keep = vibe; vibe = v; const R = recipe(); vibe = keep;
  return { seed, preset: R.S.preset, styleName: R.S.name, key: v.key, prog: R.E.prog, mode: R.E.mode, bpm: bpm || R.bpm, sample: v.sample || 0 };
}
function sessGen(s) {
  if (s.beatSrc === 'boombap' || s.beatSrc === 'trap') return s.beatSrc; // a ready-made set
  if (!s.beat) { s.beat = { seed: hashStr(s.id) }; saveSessions() }
  const k = 'g:' + s.id + ':' + s.beat.seed; if (!LE.specs[k]) LE.specs[k] = specFromVibe(s.vibe, s.beat.seed, s.bpm); return k;
}
function previewGen() { const k = 'p:' + hashStr(JSON.stringify(vibe)); if (!LE.specs[k]) LE.specs[k] = specFromVibe(vibe, hashStr(JSON.stringify(vibe))); return k }
