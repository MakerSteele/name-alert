import { registerPlugin } from '@capacitor/core';

const NameAlert = registerPlugin('NameAlert');
const $ = (id) => document.getElementById(id);
const FIELDS = ['wakeWords', 'decoyWords', 'minConf', 'gain', 'cooldownSec', 'chime', 'vibrate', 'flash', 'flashSeconds'];
let lastStatus = null;
let dirty = false;

function parseWords(text) {
  const out = [];
  for (const w of (text || '').toLowerCase().split(/[,\s]+/)) {
    if (/^[a-z']+$/.test(w) && !out.includes(w)) out.push(w);
  }
  return out;
}

function fill(s) {
  for (const k of FIELDS) {
    const el = $(k);
    if (el.type === 'checkbox') el.checked = !!s[k];
    else el.value = s[k];
  }
  showSliderValues();
}

function collect() {
  const o = {};
  for (const k of FIELDS) {
    const el = $(k);
    o[k] = el.type === 'checkbox' ? el.checked
      : (el.tagName === 'TEXTAREA' ? el.value : Number(el.value));
  }
  return o;
}

function showSliderValues() {
  $('minConfVal').textContent = Number($('minConf').value).toFixed(2);
  $('gainVal').textContent = Number($('gain').value).toFixed(1) + 'x';
}

// ---------------------------------------------------------------- vocabulary chips
let vocabTimer = null;
async function checkVocab() {
  const wake = parseWords($('wakeWords').value);
  const decoy = parseWords($('decoyWords').value);
  $('vocabNote').textContent = 'Checking words against the speech model...';
  try {
    const r = await NameAlert.checkWords({ words: [...wake, ...decoy] });
    const bad = new Set(r.unknown || []);
    const chips = (list) => list.map((w) =>
      `<span class="chip ${bad.has(w) ? 'bad' : 'ok'}">${bad.has(w) ? '&#x2717; ' : '&#x2713; '}${w}</span>`).join('');
    $('wakeChips').innerHTML = chips(wake);
    $('decoyChips').innerHTML = chips(decoy);
    if (!r.available) $('vocabNote').textContent = 'Vocabulary check not available on this phone.';
    else if (bad.size) $('vocabNote').innerHTML = `<span style="color:#ff8a8a">Red words aren't in the speech model and will be ignored.</span> Try a different spelling or a nickname.`;
    else $('vocabNote').textContent = 'All words recognized.';
  } catch (e) {
    $('vocabNote').textContent = 'Vocabulary check failed: ' + (e.message || e);
  }
}
function scheduleVocab() {
  clearTimeout(vocabTimer);
  vocabTimer = setTimeout(checkVocab, 500);
}

// ---------------------------------------------------------------- status polling
function renderStatus(st) {
  lastStatus = st;
  const btn = $('toggle');
  if (st.listening) { btn.textContent = 'LISTENING - tap to pause'; btn.className = 'big on'; }
  else if (st.running) { btn.textContent = 'PAUSED - tap to listen'; btn.className = 'big off'; }
  else { btn.textContent = 'Start listening'; btn.className = 'big off'; }
  $('level').style.width = (st.level || 0) + '%';
  $('status').textContent = st.status || '';

  const w = [];
  if (!st.micPermission) w.push(`Microphone permission is off. <br><button data-act="perms">Allow microphone</button>`);
  if (!st.notifications) w.push(`Notifications are off, so the flash and the pause button can't show. <br><button data-act="perms">Allow notifications</button>`);
  if (!st.fullScreen) w.push(`To flash the screen when it's locked, turn on <b>full-screen notifications</b> for Name Alert. <br><button data-act="fullscreen">Open setting</button>`);
  const html = w.map((x) => `<div class="warn">${x}</div>`).join('');
  if ($('warnings').dataset.html !== html) { $('warnings').innerHTML = html; $('warnings').dataset.html = html; }

  const logText = (st.log || []).slice().reverse().join('\n');
  if ($('log').textContent !== logText) $('log').textContent = logText;
}

async function poll() {
  try { renderStatus(await NameAlert.getStatus()); } catch (e) { $('status').textContent = 'Error: ' + (e.message || e); }
  setTimeout(poll, document.hidden ? 1500 : 250);
}

// ---------------------------------------------------------------- actions
async function save() {
  const s = await NameAlert.saveSettings(collect());
  fill(s);
  dirty = false;
  $('save').textContent = 'Saved';
  setTimeout(() => { $('save').textContent = 'Save'; }, 1200);
  checkVocab();
}

$('toggle').addEventListener('click', async () => {
  try {
    if (dirty) await save();
    if (lastStatus && lastStatus.listening) await NameAlert.pause();
    else {
      if (!parseWords($('wakeWords').value).length) { alert('Add your name first.'); $('wakeWords').focus(); return; }
      await NameAlert.start();
    }
  } catch (e) { alert(e.message || e); }
});
$('test').addEventListener('click', async () => { if (dirty) await save(); NameAlert.testAlert(); });
$('save').addEventListener('click', () => save().catch((e) => alert(e.message || e)));
$('warnings').addEventListener('click', (ev) => {
  const act = ev.target.dataset && ev.target.dataset.act;
  if (act === 'perms') NameAlert.requestPerms().then(renderStatus).catch(() => {});
  if (act === 'fullscreen') NameAlert.openFullScreenSettings();
});
for (const k of FIELDS) $(k).addEventListener('input', () => { dirty = true; showSliderValues(); $('save').textContent = 'Save changes'; });
$('wakeWords').addEventListener('input', scheduleVocab);
$('decoyWords').addEventListener('input', scheduleVocab);

(async () => {
  fill(await NameAlert.getSettings());
  poll();
  checkVocab();
})();
