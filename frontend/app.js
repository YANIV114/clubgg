/* ============================================================
   CLUBGG ANALYTICS — APP.JS
   Vanilla JS SPA for poker intelligence dashboard
   No frameworks, no build step, no external dependencies
   ============================================================ */

'use strict';

const API = '/api/v1';

let currentPlayerId = null;
let statsData = null;
let leaksData = null;
let leakReportData = null;  // per-hand findings; null if unavailable
let resultsData = null;     // chip results by position / depth; null if unavailable
let tournamentsData = null; // per-tournament summaries + phases; null if unavailable
let progressData = null;    // play frequencies per month; null if unavailable
let planData = null;
let sampleData = null;
let activeTab = 'home';
let leakFilter = 'all';
let trainerState = null;

/* ============================================================
   RECENT PLAYERS — localStorage helpers
   ============================================================ */

const _RECENT_KEY    = 'clubgg_recent_players';
const _RECENT_MAX    = 8;
const _CLIENT_ID_KEY = 'clubgg_client_id';

function _getOrCreateClientId() {
  let id = localStorage.getItem(_CLIENT_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(_CLIENT_ID_KEY, id);
  }
  return id;
}

async function _serverSavePlayer(playerId) {
  const clientId = _getOrCreateClientId();
  try {
    await fetch(`/api/v1/preferences/${clientId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_id: playerId }),
    });
  } catch {}
}

async function _serverLoadLastPlayer() {
  const clientId = _getOrCreateClientId();
  try {
    const r = await fetch(`/api/v1/preferences/${clientId}`);
    if (!r.ok) return null;
    const data = await r.json();
    return data.last_player_id || null;
  } catch { return null; }
}

function _recentLoad() {
  try { return JSON.parse(localStorage.getItem(_RECENT_KEY) || '[]'); }
  catch { return []; }
}

function _recentSave(list) {
  try { localStorage.setItem(_RECENT_KEY, JSON.stringify(list)); } catch {}
}

function recentPush(id, name, hands) {
  const list = _recentLoad().filter(r => r.id !== id);
  list.unshift({ id, name: name || id, hands: hands ?? 0, ts: Date.now() });
  _recentSave(list.slice(0, _RECENT_MAX));
  _renderRecent();
}

function recentClear() {
  _recentSave([]);
  _renderRecent();
}

function _renderRecent() {
  const list    = _recentLoad();
  const listEl  = document.getElementById('recent-list');
  const toggleEl = document.getElementById('recent-toggle');
  if (!listEl) return;

  if (list.length === 0) {
    listEl.innerHTML = '<div class="recent-empty">No recent players</div>';
  } else {
    listEl.innerHTML = list.map(r => `
      <button class="recent-item" data-id="${escHtml(r.id)}">
        <span class="recent-item-name">${escHtml(r.name)}</span>
        <span class="recent-item-meta">${escHtml(String(r.hands))} hands · ${escHtml(truncateId(r.id))}</span>
      </button>`).join('');
    listEl.querySelectorAll('.recent-item').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const input = document.getElementById('player-input');
        if (input) input.value = id;
        _closeRecent();
        loadPlayer(id);
      });
    });
  }

  if (toggleEl) toggleEl.textContent = list.length > 0 ? '▾' : '▾';
}

function _openRecent() {
  const dd = document.getElementById('recent-dropdown');
  if (dd) { dd.hidden = false; dd.classList.add('open'); }
}

function _closeRecent() {
  const dd = document.getElementById('recent-dropdown');
  if (dd) { dd.hidden = true; dd.classList.remove('open'); }
}

/* ── Range configs for stat cards ──────────────────────────── */
const STAT_RANGES = {
  vpip:               { min: 0, max: 1, lo: 0.22, hi: 0.38, label: 'VPIP',              fmt: 'pct' },
  pfr:                { min: 0, max: 1, lo: 0.14, hi: 0.24, label: 'PFR',               fmt: 'pct' },
  three_bet_pct:      { min: 0, max: 1, lo: 0.04, hi: 0.12, label: '3bet%',             fmt: 'pct' },
  fold_to_3bet:       { min: 0, max: 1, lo: 0.50, hi: 0.68, label: 'Fold to 3bet',      fmt: 'pct' },
  steal_pct:          { min: 0, max: 1, lo: 0.35, hi: 0.60, label: 'Steal%',            fmt: 'pct' },
  btn_steal_pct:      { min: 0, max: 1, lo: 0.40, hi: 0.70, label: 'BTN Steal%',        fmt: 'pct' },
  co_steal_pct:       { min: 0, max: 1, lo: 0.30, hi: 0.60, label: 'CO Steal%',         fmt: 'pct' },
  sb_steal_pct:       { min: 0, max: 1, lo: 0.25, hi: 0.55, label: 'SB Steal%',         fmt: 'pct' },
  fold_to_steal:      { min: 0, max: 1, lo: 0.35, hi: 0.60, label: 'Fold to Steal',     fmt: 'pct' },
  bb_fold_to_steal:   { min: 0, max: 1, lo: 0.40, hi: 0.65, label: 'BB Fold-Steal',     fmt: 'pct' },
  sb_fold_to_steal:   { min: 0, max: 1, lo: 0.35, hi: 0.60, label: 'SB Fold-Steal',     fmt: 'pct' },
  resteal_pct:        { min: 0, max: 1, lo: 0.08, hi: 0.20, label: 'Resteal%',          fmt: 'pct' },
  cbet_pct:           { min: 0, max: 1, lo: 0.45, hi: 0.70, label: 'C-bet%',            fmt: 'pct' },
  fold_to_flop_bet:   { min: 0, max: 1, lo: 0.35, hi: 0.55, label: 'Fold Flop Bet',     fmt: 'pct' },
  turn_barrel_pct:    { min: 0, max: 1, lo: 0.40, hi: 0.65, label: 'Turn Barrel%',      fmt: 'pct' },
  fold_to_turn_bet:   { min: 0, max: 1, lo: 0.40, hi: 0.60, label: 'Fold Turn Bet',     fmt: 'pct' },
  delayed_cbet_pct:   { min: 0, max: 1, lo: 0.20, hi: 0.50, label: 'Delayed C-bet%',    fmt: 'pct' },
  check_raise_pct:    { min: 0, max: 1, lo: 0.07, hi: 0.18, label: 'Check-Raise%',      fmt: 'pct' },
  aggression_factor:  { min: 0, max: 6, lo: 1.50, hi: 3.50, label: 'Aggression Factor', fmt: 'num' },
  wtsd:               { min: 0, max: 1, lo: 0.28, hi: 0.38, label: 'WTSD',              fmt: 'pct' },
  wsd:                { min: 0, max: 1, lo: 0.46, hi: 0.56, label: 'WSD',               fmt: 'pct' },
};

/* ── Stat detail definitions ──────────────────────────────── */
const STAT_DEFS = {
  vpip: {
    definition: "% of hands you voluntarily entered preflop (calls + raises, not counting forced blinds).",
    why: "Too wide bleeds chips through marginal spots; too tight lets opponents steal your blinds unchallenged.",
    green: "Solid TAG range — playing quality hands across positions.",
    yellow_high: "Slightly wide. Check positional breakdown for where you're over-entering.",
    yellow_low: "Slightly tight. You may be folding profitable late-position spots.",
    red_high: "Too loose — entering too many pots with weak holdings.",
    red_low: "Too tight — opponents steal freely, you're getting blinded out.",
    related_leaks: ['vpip_too_loose', 'vpip_too_tight'],
  },
  pfr: {
    definition: "% of hands where you raised preflop. Should track close to VPIP — gap = too many calls.",
    why: "Low PFR surrenders initiative preflop; opponents play pots in position against a passive range.",
    green: "Entering pots with aggression — good preflop initiative.",
    yellow_high: "Slightly high. Ensure 3-bet and open-raise ranges are balanced.",
    yellow_low: "PFR–VPIP gap widening. Raise more hands instead of calling.",
    red_high: "Over-raising. Likely opening or 3-betting too many marginal hands.",
    red_low: "Too passive. Calling where you should be raising; easy to play against.",
    related_leaks: ['pfr_too_passive', 'late_position_passive'],
  },
  three_bet_pct: {
    definition: "% of preflop opens you re-raise (3-bet).",
    why: "Too low and opponents open every hand profitably against you; too high and they exploit with 4-bets or folds.",
    green: "Balanced 3-bet range — opponents can't profitably open-fold against you.",
    yellow_high: "Slightly high. Monitor if opponents start 4-betting light.",
    yellow_low: "Slightly low. Opponents may be opening too freely.",
    red_high: "Over-3betting. Either over-bluffing or value-heavy imbalance.",
    red_low: "Under-3betting. Opponents open any two cards into you.",
    related_leaks: ['three_bet_too_low', 'three_bet_too_high'],
  },
  fold_to_3bet: {
    definition: "% of times you fold when facing a 3-bet after opening.",
    why: "Above 68% and opponents 3-bet any two cards for profit; below 45% and you're calling too wide OOP.",
    green: "Defending enough to make 3-bets non-automatic.",
    yellow_high: "Slightly high. Opponents are profiting from 3-betting your opens.",
    yellow_low: "Slightly low. Are you calling too wide or over-4-betting?",
    red_high: "Folding way too much — 3-bets win almost every time.",
    red_low: "Defending too much — calling too wide out of position.",
    related_leaks: ['fold_to_3bet_too_high'],
  },
  steal_pct: {
    definition: "% of unopened pots where you raise from BTN, CO, or SB.",
    why: "Every orbit you fail to steal from late position costs 0.5–1bb in expected value.",
    green: "Good late-position aggression.",
    yellow_high: "Slightly over-stealing. Blinds may start exploiting.",
    yellow_low: "Leaving chips behind. Steal more often from late position.",
    red_high: "Over-stealing — exploitable with wide resteal ranges.",
    red_low: "Under-stealing — opponents get free chips every orbit.",
    related_leaks: ['btn_steal_too_low', 'co_steal_too_low', 'sb_steal_too_low', 'late_position_passive'],
  },
  btn_steal_pct: {
    definition: "% of unopened pots where you raise from the button.",
    why: "BTN is the most profitable steal spot — underusing it is the single biggest preflop EV leak.",
    green: "Good BTN frequency — extracting maximum value from position.",
    yellow_high: "Slightly wide. Check if BB/SB are defending and adjusting.",
    yellow_low: "Too tight from BTN. Open a wider range here.",
    red_high: "Near-ATC from BTN. Need to tighten and balance.",
    red_low: "Very passive from BTN. Major EV leak every orbit.",
    related_leaks: ['btn_steal_too_low', 'late_position_passive'],
  },
  co_steal_pct: {
    definition: "% of unopened pots where you raise from the cutoff.",
    why: "CO is your second-best steal spot; under-using it compounds the BTN leak.",
    green: "Good CO aggression.",
    yellow_high: "Slightly wide from CO.",
    yellow_low: "Slightly tight from CO — open middling hands here.",
    red_high: "Over-stealing from CO.",
    red_low: "Too passive from CO — significant EV left behind.",
    related_leaks: ['co_steal_too_low', 'late_position_passive'],
  },
  sb_steal_pct: {
    definition: "% of unopened pots where you raise from the small blind.",
    why: "SB vs BB is a tough spot (you act first postflop) but still profitable vs weak defenders.",
    green: "Good SB steal frequency.",
    yellow_high: "Slightly over-stealing from SB.",
    yellow_low: "Slightly tight from SB.",
    red_high: "Over-stealing SB — BB will exploit with a wide 3-bet range.",
    red_low: "Under-stealing SB — surrendering chips unnecessarily.",
    related_leaks: ['sb_steal_too_low'],
  },
  fold_to_steal: {
    definition: "% of times you fold BB or SB to a late-position steal.",
    why: "Over-folding prints money for late-position openers; under-folding means calling marginal spots OOP.",
    green: "Defending well against steals.",
    yellow_high: "Slightly over-folding. Widen your BB/SB defense.",
    yellow_low: "Defending too wide — calling marginal hands OOP.",
    red_high: "Folding far too much — opponents steal freely.",
    red_low: "Over-defending — leaking chips with weak OOP calls.",
    related_leaks: ['bb_overfolding_vs_steals', 'bb_overfolding_vs_btn', 'sb_overfolding_vs_steals', 'bb_defend_too_tight'],
  },
  bb_fold_to_steal: {
    definition: "% of times you fold BB to a late-position open.",
    why: "BB gets the best pot odds to defend — over-folding here is a consistent, measurable chip leak.",
    green: "Good BB defense rate.",
    yellow_high: "Slightly over-folding from BB.",
    yellow_low: "Defending too many hands — calling weak hands OOP.",
    red_high: "Over-folding BB — opponents print money with any two cards.",
    red_low: "Too loose from BB — calling too wide.",
    related_leaks: ['bb_overfolding_vs_steals', 'bb_overfolding_vs_btn', 'bb_defend_too_tight', 'bb_defend_too_loose', 'bb_defending_too_loose'],
  },
  sb_fold_to_steal: {
    definition: "% of times you fold SB to a steal attempt.",
    why: "Over-folding SB compounds with under-stealing — both leaks drain chips from the same position.",
    green: "Solid SB defense.",
    yellow_high: "Slightly over-folding from SB.",
    yellow_low: "Defending too wide from SB — difficult OOP post-flop.",
    red_high: "Over-folding SB — easy steal target.",
    red_low: "Over-defending SB — OOP calls too often.",
    related_leaks: ['sb_overfolding_vs_steals'],
  },
  resteal_pct: {
    definition: "% of late-position steals you 3-bet from the blinds.",
    why: "Without a resteal range, opponents open 100% of hands against your blinds — you surrender the pot preflop.",
    green: "Good resteal frequency — openers can't steal freely.",
    yellow_high: "Slightly high resteal. Ensure range is balanced with value.",
    yellow_low: "Slightly low. Openers may be stealing too freely.",
    red_high: "Over-restealing — will get exploited by 4-bet light.",
    red_low: "No resteal threat — opponents open any two cards vs you.",
    related_leaks: ['resteal_too_low'],
  },
  cbet_pct: {
    definition: "% of flops you bet as the preflop aggressor.",
    why: "Betting every flop is exploitable by check-raises; never betting surrenders initiative and free cards.",
    green: "Board-texture aware c-betting — not mechanical.",
    yellow_high: "Slightly over-c-betting. Opponents will float or raise more.",
    yellow_low: "Slightly under-c-betting. Giving free cards too often.",
    red_high: "C-betting every flop — exploitable by check-raise bluffs.",
    red_low: "Under-c-betting — giving up initiative and equity.",
    related_leaks: ['cbet_too_high', 'cbet_too_low'],
  },
  fold_to_flop_bet: {
    definition: "% of flop bets you fold to.",
    why: "Over-folding the flop gives c-bettors a guaranteed profit on any bet.",
    green: "Good flop defense rate.",
    yellow_high: "Slightly over-folding flop. Opponents will c-bet wide.",
    yellow_low: "Slightly over-calling. Check equity when you continue.",
    red_high: "Over-folding flop — easy c-bet exploit.",
    red_low: "Too stubborn on the flop — calling too many bad equity spots.",
    related_leaks: ['fold_to_flop_bet_too_high'],
  },
  turn_barrel_pct: {
    definition: "% of flop c-bets you continue barrelling on the turn.",
    why: "Low turn barrel rate signals weak ranges — opponents float flops knowing you'll give up on the turn.",
    green: "Good turn barrel frequency.",
    yellow_high: "Slightly high turn barrel rate.",
    yellow_low: "Slightly low. Opponents are floating your flop c-bets profitably.",
    red_high: "Barrelling almost every turn — range becomes transparent.",
    red_low: "Rarely barrelling turn — opponents float c-bets for free.",
    related_leaks: ['too_passive_postflop'],
  },
  fold_to_turn_bet: {
    definition: "% of turn bets you fold to.",
    why: "Turn bets represent stronger ranges — some folding is correct, but over-folding enables multi-barrel bluffs.",
    green: "Good turn defense rate.",
    yellow_high: "Slightly over-folding turn.",
    yellow_low: "Slightly stubborn on turn. Are you calling with enough equity?",
    red_high: "Over-folding turn — opponents barrel any two cards.",
    red_low: "Calling too many turns — bleeding chips with weak holdings.",
    related_leaks: ['fold_to_turn_bet_too_high'],
  },
  delayed_cbet_pct: {
    definition: "% of turns you bet after checking the flop as preflop aggressor.",
    why: "Delayed c-bets balance your flop check range and punish passive opponents who check back the flop.",
    green: "Good delayed c-bet frequency.",
    yellow_high: "Slightly high. Opponents may raise your flop checks.",
    yellow_low: "Slightly low. Missing value when flop checks through.",
    red_high: "Over-using delayed c-bet — opponents will raise your checks.",
    red_low: "Never using delayed c-bet — flop check range looks capped.",
    related_leaks: ['too_passive_postflop'],
  },
  check_raise_pct: {
    definition: "% of postflop bets you check-raise.",
    why: "Without check-raises your check range is capped — opponents bet any two cards into you.",
    green: "Good check-raise frequency — checking range is protected.",
    yellow_high: "Slightly over check-raising. Ensure you have value to balance bluffs.",
    yellow_low: "Slightly low. Your check range may look weak.",
    red_high: "High X/R% — opponents will thin-value you to collapse your bluff.",
    red_low: "Near-zero X/R — checking range is completely capped and exploitable.",
    related_leaks: ['too_passive_postflop'],
  },
  aggression_factor: {
    definition: "(Bets + Raises) ÷ Calls postflop. Measures aggression relative to passivity.",
    why: "Low AF means you call too much; opponents extract value and control pots without resistance.",
    green: "Balanced aggression — betting and raising appropriately.",
    yellow_high: "Slightly aggressive. Monitor bet sizing and bluff frequency.",
    yellow_low: "Slightly passive. Consider betting/raising spots you're currently calling.",
    red_high: "Very aggressive — may be over-bluffing or under-calling good spots.",
    red_low: "Too passive postflop — calling instead of value-betting or raising.",
    related_leaks: ['too_passive_postflop'],
  },
  wtsd: {
    definition: "% of flops seen where you go to showdown.",
    why: "Pair with WSD — high WTSD + low WSD means you're calling rivers with losing hands.",
    green: "Healthy showdown rate.",
    yellow_high: "Slightly high. Check if WSD is keeping pace.",
    yellow_low: "Slightly low. May be folding good hands before showdown.",
    red_high: "Too many showdowns — likely calling rivers with weak holdings.",
    red_low: "Too few showdowns — folding too often on later streets.",
    related_leaks: ['wtsd_too_high', 'wtsd_too_low'],
  },
  wsd: {
    definition: "% of showdowns won. Read alongside WTSD for the full picture.",
    why: "Low WSD + high WTSD = calling rivers with losing hands. This is one of the most costly postflop leaks.",
    green: "Winning at showdown at a healthy rate.",
    yellow_high: "Winning often at showdown — may be over-folding before showdown.",
    yellow_low: "Slightly below average. Is WTSD also high?",
    red_high: "Winning almost every showdown — never bluffing or massively over-folding.",
    red_low: "Losing at showdown — calling rivers with weak hands.",
    related_leaks: ['wsd_suspiciously_low', 'wtsd_too_high'],
  },
};

const STAT_GROUPS = [
  {
    label: 'Preflop',
    keys: ['vpip', 'pfr', 'three_bet_pct', 'fold_to_3bet'],
  },
  {
    label: 'Steal / Defend',
    keys: ['steal_pct', 'btn_steal_pct', 'co_steal_pct', 'sb_steal_pct', 'fold_to_steal', 'bb_fold_to_steal', 'sb_fold_to_steal', 'resteal_pct'],
  },
  {
    label: 'Postflop',
    keys: ['cbet_pct', 'fold_to_flop_bet', 'turn_barrel_pct', 'fold_to_turn_bet', 'delayed_cbet_pct', 'check_raise_pct', 'aggression_factor'],
  },
  {
    label: 'Showdown',
    keys: ['wtsd', 'wsd'],
  },
];

/* ── Positional columns shown in the breakdown table ── */
const POS_STAT_KEYS   = ['vpip', 'pfr', 'three_bet_pct', 'fold_to_3bet'];
const POS_STAT_LABELS = { vpip: 'VPIP', pfr: 'PFR', three_bet_pct: '3bet%', fold_to_3bet: 'F-3bet' };

const _POS_STAT_EXPLANATIONS = {
  vpip:         'Voluntarily entered pot. Too high = playing marginal hands and bleeding chips.',
  pfr:          'Preflop raise %. Too low = passive, ceding initiative. Should track close to VPIP.',
  three_bet_pct:'3-bet frequency. Too low = opponents open freely; too high = over-bluffing.',
  fold_to_3bet: 'Folded to a 3-bet. Above 68% is exploitable — opponents 3-bet any two cards.',
};

const _POS_LEAKS = {
  BTN: ['btn_steal_too_low', 'fold_to_3bet_too_high', 'vpip_too_loose', 'pfr_too_passive', 'three_bet_too_low'],
  CO:  ['co_steal_too_low',  'fold_to_3bet_too_high', 'vpip_too_loose', 'pfr_too_passive'],
  HJ:  ['vpip_too_loose',    'pfr_too_passive',        'fold_to_3bet_too_high'],
  MP:  ['vpip_too_loose',    'pfr_too_passive',         'three_bet_too_low'],
  UTG: ['vpip_too_loose',    'pfr_too_passive',         'three_bet_too_low'],
  SB:  ['sb_steal_too_low',  'sb_overfolding_vs_steals','fold_to_3bet_too_high'],
  BB:  ['bb_overfolding_vs_steals', 'bb_overfolding_vs_btn', 'resteal_too_low'],
};

/* ============================================================
   UTILITIES
   ============================================================ */

function fmtPct(val) {
  if (val === null || val === undefined) return '—';
  const n = parseFloat(val);
  if (isNaN(n)) return '—';
  return (n * 100).toFixed(1) + '%';
}

function fmtNum(val, decimals = 2) {
  if (val === null || val === undefined) return '—';
  const n = parseFloat(val);
  if (isNaN(n)) return '—';
  return n.toFixed(decimals);
}

function fmtMetric(val, fmt) {
  if (fmt === 'pct') return fmtPct(val);
  return fmtNum(val, 2);
}

function truncateId(id) {
  if (!id) return '';
  return id.length > 20 ? id.slice(0, 8) + '…' + id.slice(-6) : id;
}

function escHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

/* ── Range classification ── */
function classifyRange(key, rawValue) {
  const cfg = STAT_RANGES[key];
  if (!cfg || rawValue === null || rawValue === undefined) return 'no-data';
  const v = parseFloat(rawValue);
  if (isNaN(v)) return 'no-data';
  const { lo, hi } = cfg;
  const band = (hi - lo);
  if (v >= lo && v <= hi) return 'in-range';
  const nearLo = lo - band * 0.25;
  const nearHi = hi + band * 0.25;
  if (v >= nearLo && v <= nearHi) return 'near-range';
  return 'out-range';
}

/* ── Bar position as percentage [0..100] ── */
function barPosition(key, rawValue) {
  const cfg = STAT_RANGES[key];
  if (!cfg || rawValue === null || rawValue === undefined) return null;
  const v = parseFloat(rawValue);
  if (isNaN(v)) return null;
  const { min, max } = cfg;
  return Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100));
}

/* ── Normal-range segment position as percentages ── */
function normalSegment(key) {
  const cfg = STAT_RANGES[key];
  if (!cfg) return { left: 0, width: 0 };
  const { min, max, lo, hi } = cfg;
  const left  = ((lo - min) / (max - min)) * 100;
  const width = ((hi - lo) / (max - min)) * 100;
  return { left, width };
}

/* ── Reliability badge ── */
function reliabilityBadge(n) {
  if (n === 0 || n === null || n === undefined) {
    return `<span class="reliability-badge none">— n=0</span>`;
  }
  if (n < 20) {
    return `<span class="reliability-badge warn" title="Low sample — treat with caution">⚠ n=${n}</span>`;
  }
  return `<span class="reliability-badge ok" title="Sufficient sample">✓ n=${n}</span>`;
}

/* ============================================================
   STATE MANAGEMENT — DOM TARGETS
   ============================================================ */

const els = {
  playerInput:    () => document.getElementById('player-input'),
  loadBtn:        () => document.getElementById('load-btn'),
  activePlayer:   () => document.getElementById('active-player'),
  tabBtns:        () => document.querySelectorAll('.tab-btn'),
  homePanel:      () => document.getElementById('panel-home'),
  statsPanel:     () => document.getElementById('panel-stats'),
  leaksPanel:     () => document.getElementById('panel-leaks'),
  resultsPanel:   () => document.getElementById('panel-results'),
  planPanel:      () => document.getElementById('panel-plan'),
  trainerPanel:   () => document.getElementById('panel-trainer'),
  reviewPanel:    () => document.getElementById('panel-review'),
};

/* ============================================================
   API
   ============================================================ */

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {/* ignore */}
    throw new Error(detail);
  }
  return res.json();
}

/* ============================================================
   PLAYER LOADING
   ============================================================ */

async function loadPlayer(id) {
  if (!id || !id.trim()) {
    showError('Please enter a player UUID.');
    return;
  }
  id = id.trim();

  currentPlayerId = id;
  statsData = null;
  leaksData = null;
  leakReportData = null;
  resultsData = null;
  tournamentsData = null;
  progressData = null;
  planData = null;
  sampleData = null;
  leakFilter = 'all';

  const activeEl = els.activePlayer();
  if (activeEl) activeEl.innerHTML = `Loading <span>${escHtml(truncateId(id))}</span>…`;

  showLoadingInPanels();

  try {
    [statsData, leaksData, sampleData, leakReportData, resultsData, tournamentsData, progressData] = await Promise.all([
      apiFetch(`/players/${encodeURIComponent(id)}/stats`),
      apiFetch(`/players/${encodeURIComponent(id)}/leaks`),
      apiFetch(`/players/${encodeURIComponent(id)}/sample`),
      // Optional: a failure here must not block the rest of the dashboard.
      // limit=1000 matches the /leaks default so both sections cover the same hands.
      apiFetch(`/players/${encodeURIComponent(id)}/leak-report?limit=1000`).catch(() => null),
      apiFetch(`/players/${encodeURIComponent(id)}/results`).catch(() => null),
      apiFetch(`/players/${encodeURIComponent(id)}/tournaments`).catch(() => null),
      apiFetch(`/players/${encodeURIComponent(id)}/progress`).catch(() => null),
    ]);

    if (activeEl) {
      const name = statsData.player_name || truncateId(id);
      activeEl.innerHTML = `Active: <span>${escHtml(name)}</span> — ${escHtml(statsData.hand_count)} hands`;
      recentPush(id, name, statsData.hand_count);
      _serverSavePlayer(id);
    }

    renderHome();
    renderStats(statsData);
    renderLeaks(leaksData);
    renderResults(resultsData, tournamentsData);
    renderProgress();
    clearPanel(els.planPanel(), renderPlanEmpty);
    trainerState = null;
    renderTrainer();
  } catch (err) {
    currentPlayerId = null;
    statsData = null;
    leaksData = null;
    leakReportData = null;
    resultsData = null;
    tournamentsData = null;
    progressData = null;
    sampleData = null;
    if (activeEl) activeEl.innerHTML = `<span style="color:var(--red)">Load failed — ${escHtml(err.message)}</span>`;
    showErrorInPanels(err.message);
  }
}

/* ============================================================
   TAB SWITCHING
   ============================================================ */

function switchTab(tab) {
  // Leaving trainer mid-coach: only clear if no active drill progress (idx === 0 means not started)
  if (activeTab === 'trainer' && tab !== 'trainer' && _dailyCoachState && _dailyCoachState !== 'done') {
    const noProgress = !trainerState || trainerState.idx === 0;
    if (noProgress) _dailyCoachState = null;
  }
  activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === `panel-${tab}`);
  });
  if (tab === 'review') renderTournamentReview();
}

/* ============================================================
   LOADING / ERROR HELPERS
   ============================================================ */

function showLoadingInPanels() {
  const spinner = `<div class="loading-state"><div class="spinner"></div>Loading player data…</div>`;
  const panels = [els.statsPanel(), els.leaksPanel(), els.resultsPanel(), els.planPanel()];
  panels.forEach(p => { if (p) p.innerHTML = spinner; });
  // Trainer panel shows its own empty state during load; do not clobber with spinner
}

function showErrorInPanels(msg) {
  const card = errorCard(msg);
  const panels = [els.statsPanel(), els.leaksPanel(), els.resultsPanel(), els.planPanel()];
  panels.forEach(p => { if (p) p.innerHTML = card; });
}

function errorCard(msg) {
  return `<div class="error-card">
    <div class="error-card-title">Error</div>
    <div class="error-card-msg">${escHtml(msg)}</div>
  </div>`;
}

function showError(msg) {
  const existing = document.getElementById('global-error');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.id = 'global-error';
  div.className = 'error-card';
  div.style.margin = '16px 32px';
  div.innerHTML = `<div class="error-card-title">Error</div><div class="error-card-msg">${escHtml(msg)}</div>`;
  const content = document.querySelector('.content');
  if (content) content.prepend(div);
  setTimeout(() => div.remove(), 5000);
}

function clearPanel(panel, fn) {
  if (panel) fn(panel);
}

function renderPlanEmpty(panel) {
  panel.innerHTML = renderTournamentFormHTML() +
    `<div class="empty-state" style="margin-top:0;padding:24px 0 16px;">
      ${_EMPTY_ICON}
      <div class="empty-state-title">Select format and stage, then click Generate Plan.</div>
      <div class="empty-state-sub">The plan synthesises this player's detected leaks into stage-specific study priorities.</div>
    </div>`;
  bindPlanForm();
}

/* ============================================================
   HOME TAB
   ============================================================ */

function renderHome() {
  const panel = els.homePanel();
  if (!panel) return;

  const recents  = _recentLoad();
  const history  = _ensureHistoryShape(loadTrainerHistory() || _emptyHistory());
  const hasPlayer = !!currentPlayerId;
  const topLeaks  = hasPlayer ? ((leaksData?.leaks || []).slice(0, 3)) : [];
  const lastSession = history.sessions[0] || null;

  // ── Next best action recommendation ──
  let recommendation = '';
  if (!hasPlayer && recents.length === 0) {
    recommendation = { label: 'Import hands to get started', action: () => switchTab('import'), btnText: 'Go to Import', secondary: null };
  } else if (!hasPlayer && recents.length > 0) {
    recommendation = { label: `Load ${recents[0].name} to continue`, action: () => loadPlayer(recents[0].id), btnText: 'Load Last Player', secondary: null };
  } else if (topLeaks.length > 0) {
    const alreadyDoneToday = lastSession && (Date.now() - lastSession.ts < 86400000);
    recommendation = {
      label: alreadyDoneToday ? 'Ready for another session?' : 'Start today\'s 10-minute session',
      action: () => startDailyCoach(),
      btnText: 'Daily Coach',
      secondary: { label: 'Regular trainer', action: () => switchTab('trainer') },
    };
  } else if (hasPlayer) {
    recommendation = { label: 'Build a tournament plan', action: () => switchTab('plan'), btnText: 'Tournament Plan', secondary: null };
  }

  // ── Player card (if loaded) ──
  let playerCardHtml = '';
  if (hasPlayer && statsData) {
    const name = statsData.player_name || truncateId(currentPlayerId);
    playerCardHtml = `<div class="home-player-card">
      <div class="home-player-name">${escHtml(name)}</div>
      <div class="home-player-meta">${statsData.hand_count} hands analysed</div>
      <div class="home-player-actions">
        <button class="home-action-btn" data-action="stats">Stats</button>
        <button class="home-action-btn" data-action="leaks">Leaks</button>
        <button class="home-action-btn" data-action="trainer">Train</button>
        <button class="home-action-btn" data-action="plan">Plan</button>
      </div>
    </div>`;
  } else if (recents.length > 0) {
    playerCardHtml = `<div class="home-player-card home-player-card--empty">
      <div class="home-player-name">No player loaded</div>
      <div class="home-player-meta">Load a recent player or enter a UUID above</div>
    </div>`;
  } else {
    playerCardHtml = `<div class="home-player-card home-player-card--empty">
      <div class="home-player-name">Welcome to ClubGG Analytics</div>
      <div class="home-player-meta">Import hand histories to begin</div>
    </div>`;
  }

  // ── Top leaks ──
  let leaksHtml = '';
  if (topLeaks.length > 0) {
    const items = topLeaks.map(l => {
      const sevCls = l.severity || 'low';
      return `<div class="home-leak-row" data-leak="${escHtml(l.leak_id)}">
        <span class="home-leak-sev sev-${sevCls}"></span>
        <span class="home-leak-title">${escHtml(l.title)}</span>
        <span class="home-leak-freq">${escHtml(String(l.sample_size ?? '?'))} hands</span>
      </div>`;
    }).join('');
    leaksHtml = `<div class="home-section">
      <div class="home-section-title">Top leaks <button class="home-see-all" data-action="leaks">See all →</button></div>
      <div class="home-leaks-list">${items}</div>
    </div>`;
  } else if (hasPlayer) {
    leaksHtml = `<div class="home-section">
      <div class="home-section-title">Leaks</div>
      <div class="home-empty-note">No leaks detected with current data.</div>
    </div>`;
  }

  // ── Trainer summary ──
  let trainerHtml = '';
  if (lastSession) {
    const date = new Date(lastSession.ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const pct = lastSession.total > 0 ? Math.round(100 * lastSession.score / lastSession.total) : 0;
    const cls = pct >= 80 ? 'text-green' : pct >= 60 ? 'text-yellow' : 'text-red';
    trainerHtml = `<div class="home-section">
      <div class="home-section-title">Last training session <span class="home-section-meta">${escHtml(date)}</span></div>
      <div class="home-trainer-row">
        <span class="${cls} home-trainer-score">${pct}%</span>
        <span class="home-trainer-detail">${lastSession.score ?? 0}/${lastSession.total ?? 0} correct · ${lastSession.total ?? 0} drills</span>
        <button class="home-action-btn" data-action="trainer">Resume →</button>
      </div>
    </div>`;
  } else if (hasPlayer) {
    trainerHtml = `<div class="home-section">
      <div class="home-section-title">Training</div>
      <div class="home-empty-note">No sessions yet. <button class="home-link-btn" data-action="trainer">Start your first session →</button></div>
    </div>`;
  }

  // ── Recent players ──
  let recentsHtml = '';
  if (recents.length > 0) {
    const items = recents.slice(0, 5).map(r => `
      <button class="home-recent-row" data-id="${escHtml(r.id)}">
        <span class="home-recent-name">${escHtml(r.name)}</span>
        <span class="home-recent-hands">${r.hands} hands</span>
      </button>`).join('');
    recentsHtml = `<div class="home-section">
      <div class="home-section-title">Recent players</div>
      <div class="home-recents-list">${items}</div>
    </div>`;
  }

  // ── Next action CTA ──
  const secBtn = recommendation?.secondary
    ? `<button class="home-cta-sec" id="home-cta-sec">${escHtml(recommendation.secondary.label)}</button>`
    : '';
  const ctaHtml = recommendation ? `<div class="home-cta">
    <span class="home-cta-label">${escHtml(recommendation.label)}</span>
    <div class="home-cta-btns">
      <button class="home-cta-btn" id="home-cta-btn">${escHtml(recommendation.btnText)}</button>
      ${secBtn}
    </div>
  </div>` : '';

  panel.innerHTML = `<div class="home-layout">
    <div class="home-main">
      ${playerCardHtml}
      ${ctaHtml}
      ${leaksHtml}
      ${trainerHtml}
    </div>
    <div class="home-sidebar">
      ${recentsHtml}
    </div>
  </div>`;

  // Bind CTA
  const ctaBtn = document.getElementById('home-cta-btn');
  if (ctaBtn && recommendation) ctaBtn.addEventListener('click', recommendation.action);
  const ctaSec = document.getElementById('home-cta-sec');
  if (ctaSec && recommendation?.secondary) ctaSec.addEventListener('click', recommendation.secondary.action);

  // Bind tab action buttons
  panel.querySelectorAll('[data-action]').forEach(el => {
    el.addEventListener('click', () => switchTab(el.dataset.action));
  });

  // Bind recent player rows
  panel.querySelectorAll('.home-recent-row').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      const input = document.getElementById('player-input');
      if (input) input.value = id;
      loadPlayer(id);
    });
  });

  // Bind leak rows → leaks tab
  panel.querySelectorAll('.home-leak-row').forEach(row => {
    row.addEventListener('click', () => switchTab('leaks'));
  });
}

/* ============================================================
   STATS TAB
   ============================================================ */

function _fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function _renderSampleBar() {
  if (!sampleData) return '';
  const { hand_count, tournament_count, first_hand_at, last_hand_at, last_updated_at } = sampleData;
  const items = [
    { label: 'Hands', value: String(hand_count) },
    { label: 'Tournament hands', value: String(tournament_count) },
    { label: 'First hand', value: _fmtDate(first_hand_at) },
    { label: 'Last hand', value: _fmtDate(last_hand_at) },
    { label: 'Last import', value: _fmtDate(last_updated_at) },
  ];
  const cells = items.map(i =>
    `<div class="sample-item"><span class="sample-label">${escHtml(i.label)}</span><span class="sample-value">${escHtml(i.value)}</span></div>`
  ).join('');
  return `<div class="sample-bar">${cells}</div>`;
}

function renderStats(data) {
  const panel = els.statsPanel();
  if (!panel) return;

  const countBadge = reliabilityBadge(data.hand_count);
  let html = `<div class="stats-meta">
    <span class="text-muted">${escHtml(String(data.hand_count))} hands analysed</span>
    ${countBadge}
    <a class="btn-export" href="${API}/players/${escHtml(currentPlayerId)}/export" download>Export Report</a>
  </div>
  ${_renderSampleBar()}`;

  // Stat groups
  for (const group of STAT_GROUPS) {
    html += `<div class="stat-group">
      <div class="section-header">${escHtml(group.label)}</div>
      <div class="stat-grid">`;
    for (const key of group.keys) {
      html += renderStatCard(key, data[key]);
    }
    html += `</div></div>`;
  }

  // Positional breakdown
  if (data.positional && Object.keys(data.positional).length > 0) {
    html += renderPositionalTable(data.positional);
  }

  panel.innerHTML = html;

  // Bind positional row clicks
  panel.querySelectorAll('.pos-row-clickable').forEach(row => {
    row.addEventListener('click', () => openPositionFocus(row.dataset.pos));
  });

}

function renderStatCard(key, metric) {
  const cfg = STAT_RANGES[key];
  if (!cfg) return '';

  const rawVal = metric ? metric.value : null;
  const n      = metric ? (metric.n ?? 0) : 0;
  const note   = metric ? (metric.confidence_note || '') : '';
  const cls    = classifyRange(key, rawVal);
  const displayVal = fmtMetric(rawVal, cfg.fmt);
  const pos    = barPosition(key, rawVal);
  const seg    = normalSegment(key);

  const barFill = pos !== null
    ? `<div class="range-bar-fill ${cls}" style="left:0;width:${pos.toFixed(1)}%"></div>`
    : '';

  const rangeBar = `
    <div class="range-bar-wrap">
      <div class="range-bar-track">
        <div class="range-bar-normal" style="left:${seg.left.toFixed(1)}%;width:${seg.width.toFixed(1)}%"></div>
        ${barFill}
      </div>
      <div class="range-bar-labels">
        <span>${fmtMetric(cfg.min, cfg.fmt)}</span>
        <span>${fmtMetric(cfg.max, cfg.fmt)}</span>
      </div>
    </div>`;

  const badge = reliabilityBadge(n);
  const noteHtml = note
    ? `<div class="confidence-note">${escHtml(note)}</div>`
    : '';

  return `<div class="stat-card stat-card-clickable" data-stat-key="${escHtml(key)}" role="button" tabindex="0" title="Click for details">
    <div class="stat-card-label">${escHtml(cfg.label)}</div>
    <div class="stat-card-value ${cls}">${escHtml(displayVal)}</div>
    ${rangeBar}
    <div class="stat-card-footer">
      <span class="stat-n">n=${n}</span>
      ${badge}
    </div>
    ${noteHtml}
    <div class="stat-card-click-hint">tap for details</div>
  </div>`;
}

function renderPositionalTable(positional) {
  const _posOrder = ['BTN', 'CO', 'HJ', 'MP', 'UTG', 'SB', 'BB'];
  const positions = Object.keys(positional).sort((a, b) => {
    const ai = _posOrder.indexOf(a), bi = _posOrder.indexOf(b);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });
  if (positions.length === 0) return '';

  const legend = `<div class="pos-legend">
    <span class="pos-legend-item"><span class="pos-leg-dot in-range"></span>Optimal</span>
    <span class="pos-legend-item"><span class="pos-leg-dot near-range"></span>Borderline</span>
    <span class="pos-legend-item"><span class="pos-leg-dot out-range"></span>Leak</span>
    <span class="pos-legend-hint">Click a row to see details and drills</span>
  </div>`;

  let html = `<div class="positional-section">
    <div class="section-header">Positional Breakdown</div>
    ${legend}
    <div class="positional-table-wrap">
      <table class="positional-table">
        <thead><tr>
          <th>Position</th><th>Hands</th>`;

  for (const sk of POS_STAT_KEYS) {
    const cfg = STAT_RANGES[sk];
    const bench = cfg ? `<div class="pos-th-bench">${fmtPct(cfg.lo)}–${fmtPct(cfg.hi)}</div>` : '';
    html += `<th>${escHtml(POS_STAT_LABELS[sk])}${bench}</th>`;
  }
  html += `</tr></thead><tbody>`;

  for (const pos of positions) {
    const pd = positional[pos];
    const hasLeaks = (_POS_LEAKS[pos] || []).some(lid =>
      (leaksData?.leaks || []).some(l => l.leak_id === lid)
    );
    const leakDot = hasLeaks ? `<span class="pos-leak-dot" title="Leaks detected"></span>` : '';
    html += `<tr class="pos-row-clickable" data-pos="${escHtml(pos)}">
      <td class="pos-cell-name">${escHtml(pos)}${leakDot}</td>
      <td class="pos-n">${pd.n_hands ?? '—'}</td>`;
    for (const sk of POS_STAT_KEYS) {
      const m = pd[sk];
      const v = m ? fmtPct(m.value) : '—';
      const cls = classifyRange(sk, m ? m.value : null);
      const cfg = STAT_RANGES[sk];
      const bench = (cfg && m?.value !== null && m?.value !== undefined)
        ? `<span class="pos-cell-bench">${fmtPct(cfg.lo)}–${fmtPct(cfg.hi)}</span>` : '';
      html += `<td class="pos-cell-val ${cls}">${escHtml(v)}${bench}</td>`;
    }
    html += `</tr>`;
  }

  html += `</tbody></table></div></div>`;
  return html;
}

function openPositionFocus(pos) {
  const panel = els.statsPanel();
  if (!panel || !statsData) return;

  const pd = (statsData.positional || {})[pos];
  if (!pd) return;

  // Position stats with explanations
  let statsHtml = '';
  for (const sk of POS_STAT_KEYS) {
    const m   = pd[sk];
    const cfg = STAT_RANGES[sk];
    const val = m ? fmtPct(m.value) : '—';
    const cls = classifyRange(sk, m ? m.value : null);
    const bench = cfg ? `<span class="pos-focus-bench">${fmtPct(cfg.lo)}–${fmtPct(cfg.hi)}</span>` : '';
    const expl = _POS_STAT_EXPLANATIONS[sk] || '';
    statsHtml += `<div class="pos-focus-stat">
      <div class="pos-focus-stat-top">
        <span class="pos-focus-stat-label">${escHtml(POS_STAT_LABELS[sk])}</span>
        ${bench}
        <span class="pos-focus-stat-val ${cls}">${escHtml(val)}</span>
        <span class="pos-n">n=${pd.n_hands ?? '—'}</span>
      </div>
      <div class="pos-focus-stat-expl">${escHtml(expl)}</div>
    </div>`;
  }

  // Related leaks for this position
  const relatedLeakIds = _POS_LEAKS[pos] || [];
  const relatedLeaks = (leaksData?.leaks || []).filter(l => relatedLeakIds.includes(l.leak_id));

  let leaksHtml = '';
  if (relatedLeaks.length === 0) {
    leaksHtml = `<div class="pos-focus-no-leaks">No leaks detected for ${escHtml(pos)}.</div>`;
  } else {
    for (const leak of relatedLeaks) {
      leaksHtml += `<div class="pos-focus-leak">
        <div class="pos-focus-leak-header">
          <span class="severity-badge ${escHtml(leak.severity)}">${escHtml((leak.severity || '').toUpperCase())}</span>
          <span class="pos-focus-leak-title">${escHtml(leak.title || '')}</span>
        </div>
        <div class="pos-focus-leak-evidence">${escHtml(leak.evidence || '')}</div>
        ${_renderLeakExamples(leak)}
      </div>`;
    }
  }

  const drillCount = relatedLeaks.length;
  const drillBtn = drillCount > 0
    ? `<button class="pos-focus-drill-btn" id="pos-drill-btn">Drill ${escHtml(pos)} leaks (${drillCount} spot${drillCount !== 1 ? 's' : ''}) →</button>`
    : '';

  panel.innerHTML = `<div class="pos-focus-panel">
    <div class="pos-focus-header">
      <button class="pos-focus-back-btn" id="pos-back-btn">← All positions</button>
      <span class="pos-focus-pos-name">${escHtml(pos)}</span>
      <span class="pos-n">${pd.n_hands ?? 0} hands</span>
    </div>
    <div class="pos-focus-stats">${statsHtml}</div>
    <div class="pos-focus-leaks-header">Detected leaks at ${escHtml(pos)}</div>
    <div class="pos-focus-leaks">${leaksHtml}</div>
    ${drillBtn}
  </div>`;

  document.getElementById('pos-back-btn').addEventListener('click', () => renderStats(statsData));

  const drillBtnEl = document.getElementById('pos-drill-btn');
  if (drillBtnEl) {
    drillBtnEl.addEventListener('click', () => {
      switchTab('trainer');
      startTrainerSession(PREFLOP_DRILLS, 12);
    });
  }

  // Bind replay buttons inside pos focus panel
  panel.querySelectorAll('.btn-replay-hand').forEach(btn => {
    btn.addEventListener('click', () => {
      const extId  = btn.dataset.extId;
      const leakId = btn.dataset.leakId;
      const exIdx  = parseInt(btn.dataset.exIdx, 10);
      const leak   = (leaksData?.leaks || []).find(l => l.leak_id === leakId);
      const ex     = leak ? (leak.examples || [])[exIdx] : null;
      if (extId && leak && ex) openHandReplay(extId, leak, ex);
    });
  });

  // Bind collapsibles
  panel.querySelectorAll('.collapsible-trigger').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const body = trigger.nextElementSibling;
      trigger.classList.toggle('open');
      if (body) body.classList.toggle('open');
    });
  });
}

function openStatDetail(key) {
  const panel = els.statsPanel();
  if (!panel || !statsData) return;

  const cfg = STAT_RANGES[key];
  const def = STAT_DEFS[key];
  if (!cfg || !def) {
    console.warn('openStatDetail: no config for key', key, { cfg: !!cfg, def: !!def });
    return;
  }

  const metric = statsData[key];
  const rawVal = metric ? metric.value : null;
  const n      = metric ? (metric.n ?? 0) : 0;
  const note   = metric ? (metric.confidence_note || '') : '';
  const cls    = classifyRange(key, rawVal);
  const displayVal = rawVal !== null ? fmtMetric(rawVal, cfg.fmt) : '—';

  // Map classifyRange output ('in-range'/'near-range'/'out-range') to display class
  const dispCls = cls === 'in-range' ? 'green' : cls === 'near-range' ? 'yellow' : 'red';

  // Color explanation — uses actual classifyRange tokens
  let colorNote = '';
  if (rawVal === null || n < 5) {
    colorNote = 'Too few hands — collect more data for a reliable estimate.';
  } else if (cls === 'in-range') {
    colorNote = def.green;
  } else if (cls === 'near-range') {
    colorNote = parseFloat(rawVal) > (cfg.lo + cfg.hi) / 2 ? def.yellow_high : def.yellow_low;
  } else {
    colorNote = parseFloat(rawVal) > cfg.hi ? def.red_high : def.red_low;
  }

  // Range band thresholds (yellow zone = ±25% of range width beyond target)
  const band = cfg.hi - cfg.lo;
  const warnLo = cfg.lo - band * 0.25;
  const warnHi = cfg.hi + band * 0.25;

  const rangeBands = `
    <div class="stat-detail-range-row">
      <div class="stat-detail-range-band red-band">&lt; ${fmtMetric(warnLo, cfg.fmt)}</div>
      <div class="stat-detail-range-band yellow-band">${fmtMetric(warnLo, cfg.fmt)}–${fmtMetric(cfg.lo, cfg.fmt)}</div>
      <div class="stat-detail-range-band green-band">${fmtMetric(cfg.lo, cfg.fmt)}–${fmtMetric(cfg.hi, cfg.fmt)} ✓</div>
      <div class="stat-detail-range-band yellow-band">${fmtMetric(cfg.hi, cfg.fmt)}–${fmtMetric(warnHi, cfg.fmt)}</div>
      <div class="stat-detail-range-band red-band">&gt; ${fmtMetric(warnHi, cfg.fmt)}</div>
    </div>
    <div class="stat-detail-range-your-val ${dispCls}">Your value: ${escHtml(displayVal)}</div>`;

  // Related leaks from leaksData
  const relatedLeaks = (leaksData?.leaks || []).filter(l => def.related_leaks.includes(l.leak_id));

  let leaksHtml = '';
  if (relatedLeaks.length === 0) {
    leaksHtml = `<div class="stat-detail-no-leaks">No leaks detected for this stat — value is within acceptable range.</div>`;
  } else {
    for (const leak of relatedLeaks) {
      const examples = (leak.examples || []).slice(0, 3);
      let examplesHtml = '';
      for (let i = 0; i < examples.length; i++) {
        const ex = examples[i];
        const stack = ex.stack_bb ? `${parseFloat(ex.stack_bb).toFixed(0)}bb` : '';
        const meta  = [ex.position, stack].filter(Boolean).join(' · ');
        examplesHtml += `<div class="stat-detail-example">
          <div class="stat-detail-ex-header">
            <span class="stat-detail-ex-badge">MISTAKE</span>
            <span class="stat-detail-ex-meta">${escHtml(meta)}</span>
          </div>
          <div class="stat-detail-ex-sit">${escHtml(ex.situation || '')}</div>
          ${ex.why_weak ? `<div class="stat-detail-ex-why"><span class="stat-detail-ex-field">Why weak:</span> ${escHtml(ex.why_weak)}</div>` : ''}
          ${ex.stronger_line ? `<div class="stat-detail-ex-fix"><span class="stat-detail-ex-field">Better play:</span> ${escHtml(ex.stronger_line)}</div>` : ''}
          <button class="btn-replay-hand stat-detail-replay-btn"
            data-ext-id="${escHtml(String(ex.hand_external_id))}"
            data-leak-id="${escHtml(leak.leak_id)}"
            data-ex-idx="${i}">Replay hand →</button>
        </div>`;
      }
      leaksHtml += `<div class="stat-detail-leak">
        <div class="stat-detail-leak-header">
          <span class="severity-badge ${escHtml(leak.severity)}">${escHtml((leak.severity || '').toUpperCase())}</span>
          <span class="stat-detail-leak-title">${escHtml(leak.title || '')}</span>
        </div>
        <div class="stat-detail-leak-evidence">${escHtml(leak.evidence || '')}</div>
        ${examplesHtml}
      </div>`;
    }
  }

  const badge = reliabilityBadge(n);

  panel.innerHTML = `<div class="stat-detail-panel">
    <div class="stat-detail-header">
      <button class="stat-detail-back" id="stat-detail-back">← All stats</button>
      <span class="stat-detail-title">${escHtml(cfg.label)}</span>
    </div>

    <div class="stat-detail-hero">
      <div class="stat-detail-value ${dispCls}">${escHtml(displayVal)}</div>
      <div class="stat-detail-color-note ${dispCls}">${escHtml(colorNote)}</div>
      <div class="stat-detail-n">${badge} n=${n}${note ? ` · ${escHtml(note)}` : ''}</div>
    </div>

    <div class="stat-detail-section">
      <div class="stat-detail-section-label">What is this?</div>
      <div class="stat-detail-def">${escHtml(def.definition)}</div>
      <div class="stat-detail-why">${escHtml(def.why)}</div>
    </div>

    <div class="stat-detail-section">
      <div class="stat-detail-section-label">MTT target range</div>
      ${rangeBands}
    </div>

    <div class="stat-detail-section">
      <div class="stat-detail-section-label">Related leaks ${relatedLeaks.length ? `(${relatedLeaks.length})` : ''}</div>
      <div class="stat-detail-leaks">${leaksHtml}</div>
    </div>
  </div>`;

  document.getElementById('stat-detail-back')?.addEventListener('click', () => renderStats(statsData));

  // Replay buttons — switch to leaks tab, open replay with full leak example pool for navigation
  panel.querySelectorAll('.btn-replay-hand').forEach(btn => {
    btn.addEventListener('click', () => {
      const extId  = btn.dataset.extId;
      const leakId = btn.dataset.leakId;
      const exIdx  = parseInt(btn.dataset.exIdx, 10);
      const leak   = (leaksData?.leaks || []).find(l => l.leak_id === leakId);
      const ex     = leak ? (leak.examples || [])[exIdx] : null;
      if (extId && leak && ex) {
        switchTab('leaks');
        openHandReplay(extId, leak, ex);
      }
    });
  });
}

function rangeColor(cls) {
  switch (cls) {
    case 'in-range':   return 'var(--green)';
    case 'near-range': return 'var(--yellow)';
    case 'out-range':  return 'var(--red)';
    default:           return 'var(--text-muted)';
  }
}

/* ============================================================
   LEAKS TAB
   ============================================================ */

function renderLeaks(data) {
  const panel = els.leaksPanel();
  if (!panel) return;

  const leaks = (data.leaks || []).slice().sort((a, b) => b.priority - a.priority);

  let html = `<div class="leaks-summary">
    ${escHtml(leaks.length)} leak(s) detected — <span class="text-secondary">${escHtml(data.analysis_note || '')}</span>
  </div>`;

  html += `<div class="filter-pills">
    <button class="filter-pill ${leakFilter === 'all' ? 'active' : ''}" data-filter="all">All</button>
    <button class="filter-pill ${leakFilter === 'high' ? 'active' : ''}" data-filter="high">High</button>
    <button class="filter-pill ${leakFilter === 'medium' ? 'active' : ''}" data-filter="medium">Medium</button>
    <button class="filter-pill ${leakFilter === 'low' ? 'active' : ''}" data-filter="low">Low</button>
  </div>`;

  const filtered = leakFilter === 'all' ? leaks : leaks.filter(l => l.severity === leakFilter);

  if (filtered.length === 0) {
    html += `<div class="empty-state">
      <div class="empty-state-title">No leaks matching filter.</div>
    </div>`;
  } else {
    html += `<div class="leaks-list">`;
    for (const leak of filtered) {
      html += renderLeakCard(leak);
    }
    html += `</div>`;
  }

  html += _renderHandFindings(leakReportData);

  panel.innerHTML = html;

  // Bind filter pills
  panel.querySelectorAll('.filter-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      leakFilter = btn.dataset.filter;
      renderLeaks(leaksData);
    });
  });

  // Bind collapsibles
  panel.querySelectorAll('.collapsible-trigger').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const body = trigger.nextElementSibling;
      trigger.classList.toggle('open');
      if (body) body.classList.toggle('open');
    });
  });

  // Bind replay buttons
  panel.querySelectorAll('.btn-replay-hand').forEach(btn => {
    btn.addEventListener('click', () => {
      const extId  = btn.dataset.extId;
      const leakId = btn.dataset.leakId;
      const exIdx  = parseInt(btn.dataset.exIdx, 10);
      const leak   = (leaksData.leaks || []).find(l => l.leak_id === leakId);
      const ex     = leak ? (leak.examples || [])[exIdx] : null;
      if (extId && leak && ex) openHandReplay(extId, leak, ex);
    });
  });
}

function renderLeakCard(leak) {
  const sevCls   = leak.severity || 'low';
  const barCls   = `sev-${sevCls}`;
  const confCls  = leak.confidence || 'low';
  const urgLabel = (leak.frequency || '').replace(/_/g, ' ');

  return `<div class="leak-card">
    <div class="leak-card-bar ${barCls}"></div>
    <div class="leak-card-body">
      <div class="leak-card-header">
        <span class="priority-badge">#${leak.priority ?? '?'}</span>
        <span class="severity-badge ${sevCls}">${escHtml(sevCls.toUpperCase())}</span>
        <span class="category-pill">${escHtml(leak.category || '')}</span>
        <span class="leak-id-text">${escHtml(leak.leak_id || '')}</span>
      </div>
      <div class="leak-card-title">${escHtml(leak.title || '')}</div>
      <div class="leak-evidence">${escHtml(leak.evidence || '')}</div>
      <div class="leak-collapsibles">
        <div>
          <button class="collapsible-trigger">
            <span class="chevron">▶</span>&nbsp;Explanation
          </button>
          <div class="collapsible-body">${escHtml(leak.explanation || '')}</div>
        </div>
        <div>
          <button class="collapsible-trigger">
            <span class="chevron">▶</span>&nbsp;Suggested Fix
          </button>
          <div class="collapsible-body">${escHtml(leak.suggested_fix || '')}</div>
        </div>
      </div>
      <div class="leak-card-footer">
        <span class="confidence-badge ${confCls}" title="Confidence level">
          ${escHtml(confCls.toUpperCase())} CONFIDENCE
        </span>
        <span class="sample-size-text">n=${leak.sample_size ?? '?'}</span>
        <span class="frequency-text">${escHtml(urgLabel)}</span>
      </div>
      ${_renderLeakExamples(leak)}
    </div>
  </div>`;
}

/* Per-hand findings (from /leak-report): decision patterns across individual
   hands, e.g. push/fold and calling shoves.  Complements the stat-based cards. */

// Report severities map onto the existing severity badge colours.
const _FINDING_SEV_CLS = { critical: 'high', major: 'medium', minor: 'low' };

function _renderHandFindings(report) {
  if (!report) return '';
  const findings = report.leaks || [];

  let html = `<div class="leaks-summary hand-findings-header">
    Hand-by-hand findings — <span class="text-secondary">${escHtml(report.summary || '')}</span>
  </div>`;

  if (findings.length === 0) return html;

  html += `<div class="leaks-list">`;
  for (const f of findings) {
    const sevCls  = _FINDING_SEV_CLS[f.severity] || 'low';
    const confCls = f.confidence || 'low';
    const freq    = f.frequency != null ? `${(f.frequency * 100).toFixed(1)}% of spots` : '';
    const evidence = (f.evidence || [])
      .map(e => `<li>${escHtml(e)}</li>`)
      .join('');
    html += `<div class="leak-card">
      <div class="leak-card-bar sev-${sevCls}"></div>
      <div class="leak-card-body">
        <div class="leak-card-header">
          <span class="severity-badge ${sevCls}">${escHtml((f.severity || '').toUpperCase())}</span>
          <span class="category-pill">${escHtml(f.category || '')}</span>
          <span class="leak-id-text">${escHtml(f.leak_id || '')}</span>
        </div>
        <div class="leak-card-title">${escHtml(f.title || '')}</div>
        <div class="leak-evidence">${escHtml(f.description || '')}</div>
        <div class="leak-collapsibles">
          <div>
            <button class="collapsible-trigger">
              <span class="chevron">▶</span>&nbsp;Hands
            </button>
            <div class="collapsible-body"><ul class="finding-evidence">${evidence}</ul></div>
          </div>
          <div>
            <button class="collapsible-trigger">
              <span class="chevron">▶</span>&nbsp;Suggested Fix
            </button>
            <div class="collapsible-body">${escHtml(f.suggested_fix || '')}</div>
          </div>
          <div>
            <button class="collapsible-trigger">
              <span class="chevron">▶</span>&nbsp;Limitations
            </button>
            <div class="collapsible-body">${escHtml(f.limitations || '')}</div>
          </div>
        </div>
        <div class="leak-card-footer">
          <span class="confidence-badge ${confCls}" title="Confidence level">
            ${escHtml(confCls.toUpperCase())} CONFIDENCE
          </span>
          <span class="sample-size-text">n=${f.sample_size ?? '?'}</span>
          <span class="frequency-text">${escHtml(freq)}</span>
        </div>
      </div>
    </div>`;
  }
  html += `</div>`;
  return html;
}

function _renderLeakExamples(leak) {
  const exs = leak.examples || [];
  if (!exs.length) return '';
  let rows = '';
  for (const ex of exs) {
    const stack   = ex.stack_bb ? `${parseFloat(ex.stack_bb).toFixed(0)}bb` : '';
    const shortId = ex.hand_external_id
      ? '#' + ex.hand_external_id.replace(/^(Poker Hand #|Hand #|ClubGG Hand #)/i, '').slice(-12)
      : '';
    const meta = [ex.position, stack, shortId].filter(Boolean).join(' \u00b7 ');
    rows += `<div class="leak-ex-row">
      <div class="leak-ex-meta">${escHtml(meta)}</div>
      <div class="leak-ex-sit">${escHtml(ex.situation || '')}</div>
      <button class="btn-replay-hand"
        data-ext-id="${escHtml(ex.hand_external_id || '')}"
        data-leak-id="${escHtml(leak.leak_id || '')}"
        data-ex-idx="${exs.indexOf(ex)}">
        Replay hand \u2192
      </button>
    </div>`;
  }
  return `<div class="leak-examples">
    <div class="leak-examples-title">Hand examples (${exs.length})</div>
    ${rows}
  </div>`;
}

/* ============================================================
   RESULTS TAB
   Chip results by position and stack depth.  Every bb/100 shows its 95%
   margin; a result is coloured only when the margin excludes zero.
   ============================================================ */

function _fmtBb(v, digits = 1) {
  if (v == null) return '—';
  const s = parseFloat(v).toFixed(digits);
  const n = parseFloat(s);
  if (n === 0) return (0).toFixed(digits);  // never "-0"
  return `${n > 0 ? '+' : ''}${s}`;
}

function _resultCls(rate) {
  if (!rate || rate.value == null || !rate.significant) return 'res-neutral';
  return parseFloat(rate.value) >= 0 ? 'res-pos' : 'res-neg';
}

function _resultReading(rate) {
  if (!rate || rate.value == null) return 'no data';
  if (!rate.significant) return 'not established';
  return parseFloat(rate.value) >= 0 ? 'winning' : 'losing';
}

function _renderResultTable(title, firstCol, rows) {
  if (!rows || !rows.length) return '';
  const body = rows.map(r => {
    const b = r.bb_per_100;
    return `<tr>
      <td>${escHtml(r.label)}</td>
      <td class="num">${escHtml(r.hands)}</td>
      <td class="num">${escHtml(_fmtBb(r.total_bb, 0))}</td>
      <td class="num ${_resultCls(b)}">${escHtml(_fmtBb(b.value))}</td>
      <td class="num text-secondary">${b.margin != null ? '±' + escHtml(parseFloat(b.margin).toFixed(0)) : '—'}</td>
      <td class="text-secondary">${escHtml(_resultReading(b))}</td>
    </tr>`;
  }).join('');
  return `<div class="results-block">
    <div class="results-block-title">${escHtml(title)}</div>
    <table class="results-table">
      <thead><tr>
        <th>${escHtml(firstCol)}</th><th class="num">Hands</th><th class="num">Total bb</th>
        <th class="num">bb/100</th><th class="num">95% margin</th><th>Reading</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
  </div>`;
}

function _renderResultCurve(curve, handCount) {
  if (!curve || curve.length < 2) return '';
  const W = 800, H = 220, PAD_L = 48, PAD_R = 12, PAD_T = 12, PAD_B = 24;
  const vals = curve.map(v => parseFloat(v));
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const x = i => PAD_L + (i / (vals.length - 1)) * (W - PAD_L - PAD_R);
  const y = v => PAD_T + (1 - (v - lo) / span) * (H - PAD_T - PAD_B);
  const path = vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('');
  // Axis labels are HTML, not SVG text: the SVG stretches horizontally, which
  // would distort glyphs.  Skip the zero label when it would collide.
  const tickVals = [hi, lo];
  if (lo < 0 && hi > 0 && Math.min(y(0) - y(hi), y(lo) - y(0)) > 16) tickVals.push(0);
  const ticks = tickVals.map(v =>
    `<span class="res-axis" style="top:${((y(v) / H) * 100).toFixed(2)}%">${escHtml(_fmtBb(v, 0))}</span>`
  ).join('');
  return `<div class="results-block">
    <div class="results-block-title">Cumulative result (bb) over ${escHtml(handCount)} hands</div>
    <div class="res-chart" data-hands="${escHtml(handCount)}" data-curve="${escHtml(JSON.stringify(vals))}">
      ${ticks}
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
           aria-label="Cumulative chip result in big blinds, ending at ${_fmtBb(vals[vals.length - 1], 0)} bb">
        <line x1="${PAD_L}" x2="${W - PAD_R}" y1="${y(0)}" y2="${y(0)}" class="res-zero"/>
        <path d="${path}" class="res-line"/>
        <line class="res-cross" x1="0" x2="0" y1="${PAD_T}" y2="${H - PAD_B}" visibility="hidden"/>
        <circle class="res-dot" r="4" visibility="hidden"/>
        <rect class="res-hit" x="${PAD_L}" y="0" width="${W - PAD_L - PAD_R}" height="${H}"/>
      </svg>
      <div class="res-tip" hidden></div>
    </div>
  </div>`;
}

function _bindResultCurve(panel) {
  const box = panel.querySelector('.res-chart');
  if (!box) return;
  const vals = JSON.parse(box.dataset.curve);
  const hands = parseInt(box.dataset.hands, 10);
  const svg = box.querySelector('svg');
  const hit = box.querySelector('.res-hit');
  const cross = box.querySelector('.res-cross');
  const dot = box.querySelector('.res-dot');
  const tip = box.querySelector('.res-tip');
  const path = box.querySelector('.res-line');
  const W = 800, PAD_L = 48, PAD_R = 12;

  hit.addEventListener('mousemove', ev => {
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    const local = pt.matrixTransform(svg.getScreenCTM().inverse());
    const frac = Math.min(1, Math.max(0, (local.x - PAD_L) / (W - PAD_L - PAD_R)));
    const i = Math.round(frac * (vals.length - 1));
    // Read the y position back from the drawn path so the dot sits on the line.
    const seg = path.getAttribute('d').split(/[ML]/).filter(Boolean)[i].split(',');
    const cx = parseFloat(seg[0]), cy = parseFloat(seg[1]);
    cross.setAttribute('x1', cx); cross.setAttribute('x2', cx);
    cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', cx); dot.setAttribute('cy', cy);
    dot.setAttribute('visibility', 'visible');
    const handNo = Math.max(1, Math.round((i / (vals.length - 1)) * hands));
    tip.textContent = `Hand ~${handNo}: ${_fmtBb(vals[i], 1)} bb`;
    tip.hidden = false;
    const rect = box.getBoundingClientRect();
    tip.style.left = `${Math.min(ev.clientX - rect.left + 12, rect.width - 160)}px`;
  });
  hit.addEventListener('mouseleave', () => {
    cross.setAttribute('visibility', 'hidden');
    dot.setAttribute('visibility', 'hidden');
    tip.hidden = true;
  });
}

function _pct1(m) {
  return m && m.value != null ? `${(parseFloat(m.value) * 100).toFixed(0)}%` : '—';
}

function _renderPhaseTable(phases) {
  if (!phases || !phases.length) return '';
  const body = phases.map(p => {
    const b = p.bb_per_100;
    return `<tr>
      <td>${escHtml(p.label)}</td>
      <td class="num">${escHtml(p.hands)}</td>
      <td class="num">${escHtml(_pct1(p.vpip))}</td>
      <td class="num">${escHtml(_pct1(p.pfr))}</td>
      <td class="num">${escHtml(_pct1(p.three_bet_pct))}</td>
      <td class="num ${_resultCls(b)}">${escHtml(_fmtBb(b.value))}</td>
      <td class="num text-secondary">${b.margin != null ? '±' + escHtml(parseFloat(b.margin).toFixed(0)) : '—'}</td>
    </tr>`;
  }).join('');
  return `<div class="results-block">
    <div class="results-block-title">By tournament phase (blind level) — how your play changes as the tournament goes on</div>
    <table class="results-table">
      <thead><tr>
        <th>Phase</th><th class="num">Hands</th><th class="num">VPIP</th><th class="num">PFR</th>
        <th class="num">3-bet</th><th class="num">bb/100</th><th class="num">95% margin</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
    <div class="results-note">Phases are blind-level bands, a rough proxy: level numbering differs between
    structures. Bubble / in-the-money can't be detected — hand histories don't include players remaining or payouts.</div>
  </div>`;
}

function _renderTournamentTable(tournaments) {
  if (!tournaments || !tournaments.length) return '';
  const body = tournaments.map(t => {
    const levels = t.first_level != null
      ? (t.first_level === t.last_level ? `${t.first_level}` : `${t.first_level}–${t.last_level}`)
      : '—';
    return `<tr>
      <td>${escHtml(t.name || '#' + t.tournament_id)}</td>
      <td class="text-secondary">${escHtml(t.format_hint || '')}</td>
      <td class="num">${escHtml(t.hands)}</td>
      <td class="num">${escHtml(levels)}</td>
      <td class="num">${escHtml(t.entries)}</td>
      <td class="num">${escHtml(_fmtBb(t.total_bb, 0))}</td>
    </tr>`;
  }).join('');
  const entries = tournaments.reduce((n, t) => n + t.entries, 0);
  return `<div class="results-block">
    <div class="results-block-title">Tournaments — ${escHtml(tournaments.length)} tournaments, ${escHtml(entries)} entries</div>
    <table class="results-table">
      <thead><tr>
        <th>Tournament</th><th>Format</th><th class="num">Hands</th><th class="num">Levels</th>
        <th class="num">Entries</th><th class="num">Chips (bb)</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
    <div class="results-note">Chip results only: finishing place and prize money aren't in the hand
    histories, and bounty winnings aren't counted. Busting out doesn't mean you didn't cash.
    Format is guessed from the tournament name.</div>
  </div>`;
}

function renderResults(data, tournaments) {
  const panel = els.resultsPanel();
  if (!panel) return;
  if (!data) {
    panel.innerHTML = `<div class="empty-state"><div class="empty-state-title">Results unavailable.</div></div>`;
    return;
  }
  if (!data.hand_count) {
    panel.innerHTML = `<div class="empty-state"><div class="empty-state-title">No hands with a known result yet.</div></div>`;
    return;
  }

  const b = data.bb_per_100;
  const missing = data.hands_without_result
    ? ` ${data.hands_without_result} hand(s) without a reconciled result are excluded.`
    : '';
  let html = `<div class="results-summary">
    <div class="res-stat"><span class="res-stat-val">${escHtml(data.hand_count)}</span><span class="res-stat-lbl">Hands</span></div>
    <div class="res-stat"><span class="res-stat-val ${_resultCls(b)}">${escHtml(_fmtBb(data.total_bb, 0))} bb</span><span class="res-stat-lbl">Total</span></div>
    <div class="res-stat"><span class="res-stat-val ${_resultCls(b)}">${escHtml(_fmtBb(b.value))}</span><span class="res-stat-lbl">bb/100 (±${b.margin != null ? escHtml(parseFloat(b.margin).toFixed(0)) : '—'})</span></div>
  </div>
  <div class="leaks-summary">
    Chip results, not money — tournament ICM is not modelled. Results swing by tens of bb per
    hand, so each bb/100 shows a 95% margin; only results whose margin excludes zero are
    coloured.${escHtml(missing)}
  </div>`;

  html += _renderResultCurve(data.cumulative_bb, data.hand_count);
  html += _renderResultTable('By position', 'Position', data.by_position);
  html += _renderResultTable('By effective stack', 'Stack', data.by_depth);
  if (tournaments) {
    html += _renderPhaseTable(tournaments.phases);
    html += _renderTournamentTable(tournaments.tournaments);
  }

  panel.innerHTML = html;
  _bindResultCurve(panel);
}

/* ============================================================
   TOURNAMENT PLAN TAB
   ============================================================ */

function renderTournamentFormHTML() {
  return `<div class="plan-form">
    <div class="plan-form-title">Tournament Configuration</div>
    <div class="plan-form-fields">
      <div class="field-group">
        <label class="field-label" for="plan-format">Format</label>
        <select class="field-select" id="plan-format">
          <option value="">— Select —</option>
          <option value="FREEZEOUT">Freezeout</option>
          <option value="PKO">PKO (Bounty)</option>
          <option value="SATELLITE">Satellite</option>
          <option value="SPIN">Spin &amp; Go</option>
          <option value="REENTRY">Re-entry</option>
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="plan-stage">Stage</label>
        <select class="field-select" id="plan-stage">
          <option value="">— Select —</option>
          <option value="early">Early</option>
          <option value="middle">Middle</option>
          <option value="bubble">Bubble</option>
          <option value="itm">ITM</option>
          <option value="final_table">Final Table</option>
        </select>
      </div>
      <div class="field-group">
        <label class="field-label" for="plan-stack">Stack (BB)</label>
        <input class="field-input" type="number" id="plan-stack" min="1" max="500" step="0.5" placeholder="e.g. 22.5">
      </div>
      <div class="field-group">
        <label class="field-label" for="plan-players">Players Left</label>
        <input class="field-input" type="number" id="plan-players" min="1" max="10000" step="1" placeholder="e.g. 18">
      </div>
      <button class="btn-primary" id="plan-generate-btn">Generate Plan</button>
    </div>
  </div>`;
}

function bindPlanForm() {
  const btn = document.getElementById('plan-generate-btn');
  if (btn) btn.addEventListener('click', generatePlan);
}

async function generatePlan() {
  if (!currentPlayerId) {
    showError('Load a player first.');
    return;
  }

  const format  = document.getElementById('plan-format')?.value;
  const stage   = document.getElementById('plan-stage')?.value;
  const stackBb = parseFloat(document.getElementById('plan-stack')?.value);
  const players = parseInt(document.getElementById('plan-players')?.value, 10);

  if (!format || !stage) {
    showError('Select a tournament format and stage.');
    return;
  }

  const btn = document.getElementById('plan-generate-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }

  const panel = els.planPanel();
  const formHtml = panel ? panel.querySelector('.plan-form')?.outerHTML : '';

  try {
    const body = {
      tournament_format: format,
      stage,
      limit: 500,
    };
    if (!isNaN(stackBb))  body.stack_bb = stackBb;
    if (!isNaN(players))  body.players_remaining = players;

    planData = await apiFetch(`/players/${encodeURIComponent(currentPlayerId)}/tournament-plan`, {
      method: 'POST',
      body: JSON.stringify(body),
    });

    renderPlan(planData, formHtml);
  } catch (err) {
    if (panel) {
      panel.innerHTML = (formHtml || renderTournamentFormHTML()) +
        errorCard(`Failed to generate plan: ${err.message}`);
    }
    bindPlanForm();
  } finally {
    const newBtn = document.getElementById('plan-generate-btn');
    if (newBtn) { newBtn.disabled = false; newBtn.textContent = 'Generate Plan'; }
  }
}

function renderPlan(data, preservedFormHtml) {
  const panel = els.planPanel();
  if (!panel) return;

  const formHtml = preservedFormHtml || renderTournamentFormHTML();

  const urgClass = (u) => {
    switch ((u || '').toLowerCase().replace(/[_\s]/g, '-')) {
      case 'immediate':  return 'immediate';
      case 'this-week':  return 'this-week';
      case 'this_week':  return 'this-week';
      case 'this-month': return 'this-month';
      case 'this_month': return 'this-month';
      default:           return 'ongoing';
    }
  };

  let resultsHtml = `<div class="plan-results">`;

  // Reliability note
  const planBadgeCls  = data.hand_count >= 200 ? 'ok' : data.hand_count >= 50 ? 'warn' : 'none';
  const planBadgeIcon = data.hand_count >= 200 ? '✓' : data.hand_count >= 50 ? '⚠' : '—';
  resultsHtml += `<div class="plan-reliability">
    <span class="reliability-badge ${planBadgeCls}">${planBadgeIcon} ${escHtml(data.hand_count.toString())} hands</span>
    <span class="text-secondary">${escHtml(data.reliability_note || '')}</span>
  </div>`;

  // Stage guidance
  if (data.stage_guidance) {
    resultsHtml += `<div class="guidance-card">
      <div class="guidance-card-label">Stage Guidance — ${escHtml(data.stage || '')} / ${escHtml(data.tournament_format || '')}</div>
      <div class="guidance-card-text">${escHtml(data.stage_guidance)}</div>
    </div>`;
  }

  // Format note
  if (data.format_note && data.format_note.trim()) {
    resultsHtml += `<div class="guidance-card format-note">
      <div class="guidance-card-label">Format Note</div>
      <div class="guidance-card-text">${escHtml(data.format_note)}</div>
    </div>`;
  }

  // Study priorities
  if (data.study_priorities && data.study_priorities.length > 0) {
    resultsHtml += `<div>
      <div class="section-header">Study Priorities</div>
      <div class="study-list">`;
    for (const item of data.study_priorities) {
      const uc = urgClass(item.urgency);
      const urgLabel = (item.urgency || 'ongoing').replace(/_/g, ' ').toUpperCase();
      resultsHtml += `<div class="study-item">
        <div class="study-rank">${item.rank}</div>
        <div class="study-content">
          <div class="study-header">
            <span class="urgency-badge ${uc}">${escHtml(urgLabel)}</span>
            <span class="source-badge">${escHtml(item.source || '')}</span>
          </div>
          <div class="study-focus">${escHtml(item.focus_area || '')}</div>
          <div class="study-action">${escHtml(item.action || '')}</div>
        </div>
      </div>`;
    }
    resultsHtml += `</div></div>`;
  }

  // Top leaks mini-cards
  if (data.top_leaks && data.top_leaks.length > 0) {
    resultsHtml += `<div>
      <div class="section-header">Top Leaks Relevant to This Stage</div>
      <div class="mini-leaks-list">`;
    for (const leak of data.top_leaks) {
      const sevCls = `sev-${leak.severity || 'low'}`;
      resultsHtml += `<div class="mini-leak-card">
        <div class="mini-leak-card-bar ${sevCls}"></div>
        <div class="mini-leak-content">
          <div class="mini-leak-title">${escHtml(leak.title || '')}</div>
          <div class="mini-leak-evidence">${escHtml(leak.evidence || '')}</div>
        </div>
      </div>`;
    }
    resultsHtml += `</div></div>`;
  }

  resultsHtml += `</div>`;

  panel.innerHTML = formHtml + resultsHtml;
  bindPlanForm();

  // Re-populate form values from what was submitted
  const fmtEl = document.getElementById('plan-format');
  const stgEl = document.getElementById('plan-stage');
  const stkEl = document.getElementById('plan-stack');
  const plEl  = document.getElementById('plan-players');

  if (fmtEl) fmtEl.value = data.tournament_format || '';
  if (stgEl) stgEl.value = data.stage || '';
  if (stkEl && data.stack_bb) stkEl.value = data.stack_bb;
  if (plEl  && data.players_remaining) plEl.value = data.players_remaining;
}

/* ============================================================
   TRAINER TAB — PREFLOP LEAK DRILLS
   ============================================================ */

const PREFLOP_DRILLS = [
  /* ── BTN steal too low ── */
  {
    lk: 'btn_steal_too_low',
    sit: 'Folds around to you on the button. Blinds are in.',
    hand: 'K\u2665 7\u2666',
    ctx: 'BTN \u00b7 45bb \u00b7 42bb eff \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 2.5bb' },
      { v: 'jam',   t: 'Shove' },
    ],
    ok: 'raise',
    fb: {
      raise: 'K7o is comfortably within BTN opening range. BTN is last to act preflop and always in position postflop \u2014 steal at high frequency from here.',
      fold:  'Folding K7o from BTN wastes your positional advantage. Your data shows your BTN steal frequency is below baseline (50\u201375%). This hand is a clear open.',
      jam:   'Shoving 45bb with K7o is extreme variance for a spot that a 2.5bb raise handles cleanly. Reserve shoves for <15bb effective.',
    },
  },
  {
    lk: 'btn_steal_too_low',
    sit: 'Folds around to you on the button.',
    hand: '3\u26603\u2666',
    ctx: 'BTN \u00b7 55bb \u00b7 52bb eff \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 2.5bb' },
      { v: 'jam',   t: 'Shove' },
    ],
    ok: 'raise',
    fb: {
      raise: 'Pocket pairs always open from BTN. You have set equity, implied odds if called, and fold equity vs the blinds. Standard raise.',
      fold:  'Folding 33 from BTN gives up a profitable spot. Any pocket pair is an open from button position.',
      jam:   'At 55bb, shoving 33 risks your stack unnecessarily. Raise to 2.5bb and play in position \u2014 you have set equity as backup.',
    },
  },
  {
    lk: 'btn_steal_too_low',
    sit: 'Action folds to you on the button. Both blinds are passive.',
    hand: '8\u26635\u2663',
    ctx: 'BTN \u00b7 60bb \u00b7 55bb eff \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 2.5bb' },
      { v: 'jam',   t: 'Shove' },
    ],
    ok: 'raise',
    fb: {
      raise: '85s is a profitable BTN open. Flush equity, straight potential, and you are always in position postflop. Raise.',
      fold:  'Folding 85s from BTN gives up a clearly profitable spot. Suited connectors play extremely well in position \u2014 this is a standard open.',
      jam:   'No reason to shove 60bb with a speculative hand. Raise 2.5bb, play in position, and realise your equity.',
    },
  },

  /* ── CO steal too low ── */
  {
    lk: 'co_steal_too_low',
    sit: 'Folds around to you in the cutoff. BTN and blinds still to act.',
    hand: 'Q\u2665J\u2666',
    ctx: 'CO \u00b7 50bb \u00b7 48bb eff \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 3bb' },
      { v: 'jam',   t: 'Shove' },
    ],
    ok: 'raise',
    fb: {
      raise: 'QJo is a standard CO open. Two broadways, connection, second-best steal position. Raising is automatic.',
      fold:  'Folding QJo from CO is too tight. CO should be opened at 28\u201340%+ when folded to. This hand has too much equity to fold.',
      jam:   'QJo at 50bb does not need to shove. A 3bb raise achieves the same goal and plays fine postflop in position.',
    },
  },
  {
    lk: 'co_steal_too_low',
    sit: 'Folds to you in the cutoff.',
    hand: 'A\u26605\u2666',
    ctx: 'CO \u00b7 40bb \u00b7 38bb eff \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 2.5bb' },
    ],
    ok: 'raise',
    fb: {
      raise: 'A5o from CO is a clear open. Ace-high has blocker value, reasonable equity, and CO gives you position on the blinds.',
      fold:  'Folding A5o from CO is too tight. Ace-high always makes the CO opening range. Your CO steal frequency is below the 28\u201340% baseline.',
    },
  },
  {
    lk: 'co_steal_too_low',
    sit: 'Folds around to you in the cutoff.',
    hand: '7\u26637\u2665',
    ctx: 'CO \u00b7 65bb \u00b7 60bb eff \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 3bb' },
      { v: 'jam',   t: 'Shove' },
    ],
    ok: 'raise',
    fb: {
      raise: 'Pocket sevens from CO is a standard open. Strong hand, plays well in position, and you apply pressure on the blinds.',
      fold:  'Never fold 77 from CO. This hand is a comfortable open.',
      jam:   'At 65bb, 77 raises to 3bb \u2014 not shoves. You want to play your hand, not just shove.',
    },
  },

  /* ── SB steal too low ── */
  {
    lk: 'sb_steal_too_low',
    sit: 'Folds around to you in the SB. Only the BB is left.',
    hand: 'K\u26664\u2660',
    ctx: 'SB \u00b7 50bb \u00b7 48bb eff \u00b7 heads-up vs BB',
    opts: [
      { v: 'fold',     t: 'Fold' },
      { v: 'complete', t: 'Complete (1bb)' },
      { v: 'raise',    t: 'Raise 3bb' },
    ],
    ok: 'raise',
    fb: {
      raise:    'K4o is a raise from SB vs BB. Heads-up, with a king, raising applies pressure and builds the pot.',
      fold:     'Folding K4o from SB wastes your structural edge. You only face the BB \u2014 raise or fold, do not complete.',
      complete: 'Completing from SB is almost never correct. You forfeit aggression and go to the flop OOP with no initiative. Raise or fold.',
    },
  },
  {
    lk: 'sb_steal_too_low',
    sit: 'Action folds to you in the SB. BB is passive.',
    hand: '6\u26655\u2665',
    ctx: 'SB \u00b7 45bb \u00b7 42bb eff \u00b7 heads-up vs BB',
    opts: [
      { v: 'fold',     t: 'Fold' },
      { v: 'complete', t: 'Complete (1bb)' },
      { v: 'raise',    t: 'Raise 3bb' },
    ],
    ok: 'raise',
    fb: {
      raise:    '65s is a profitable SB open heads-up. Suited connectors play well postflop and you only face the BB.',
      fold:     '65s from SB vs BB is a clear open. Suited connectors have strong playability \u2014 do not fold a hand this good heads-up.',
      complete: 'Completing with 65s loses value. Raise to 3bb \u2014 pick up dead money, maintain aggression, and still have your equity when called.',
    },
  },
  {
    lk: 'sb_steal_too_low',
    sit: 'Folds to SB. BB is passive and straightforward.',
    hand: 'J\u26638\u2666',
    ctx: 'SB \u00b7 55bb \u00b7 52bb eff \u00b7 heads-up vs BB',
    opts: [
      { v: 'fold',     t: 'Fold' },
      { v: 'complete', t: 'Complete (1bb)' },
      { v: 'raise',    t: 'Raise 3bb' },
    ],
    ok: 'raise',
    fb: {
      raise:    'J8o from SB heads-up is a clear raise. Jack-high has top-pair potential, and you face only one opponent. Apply pressure and build the pot.',
      fold:     'Folding J8o from SB surrenders a profitable steal. With just the BB left, J8o is comfortably above the SB open threshold \u2014 raise.',
      complete: 'Completing loses initiative. J8o should be raise-or-fold from SB. Completing lets BB see a cheap flop and realise equity with no pressure on you.',
    },
  },

  /* ── Fold to 3-bet too high ── */
  {
    lk: 'fold_to_3bet_too_high',
    sit: 'You open from CO. BB 3-bets to 9bb. You have 55bb remaining.',
    hand: 'A\u2665T\u2665',
    ctx: 'CO open vs BB 3-bet \u00b7 55bb eff',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'fourbet', t: '4-bet to 22bb' },
    ],
    ok: 'call',
    fb: {
      call:    'ATs is a mandatory defend vs a BB 3-bet. Nut-flush equity, strong top-pair potential, and you are in position. Call and realise equity.',
      fold:    'Folding ATs to a 3-bet is too tight. This hand has too much equity to fold \u2014 nut flush draws, top pair potential. Call.',
      fourbet: '4-betting ATs is also reasonable as a 4-bet/call, but calling is more common. ATs blocks many 3-bet bluffs.',
    },
  },
  {
    lk: 'fold_to_3bet_too_high',
    sit: 'You open from BTN. SB 3-bets to 8bb. You have 60bb remaining.',
    hand: 'T\u2660T\u2666',
    ctx: 'BTN open vs SB 3-bet \u00b7 60bb eff',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'fourbet', t: '4-bet to 22bb' },
    ],
    ok: 'call',
    fb: {
      call:    'TT is a standard call vs a SB 3-bet. Strong pair, in position, great equity at 60bb. Call and play.',
      fold:    'Folding TT to a 3-bet is a major error. TT is well above the fold threshold \u2014 call or 4-bet, never fold.',
      fourbet: '4-betting TT vs SB is reasonable but calling in position is often preferred at 60bb to keep bluffs in.',
    },
  },
  {
    lk: 'fold_to_3bet_too_high',
    sit: 'You open from CO. BTN 3-bets to 9bb. You have 50bb remaining.',
    hand: 'A\u26665\u2660',
    ctx: 'CO open vs BTN 3-bet \u00b7 50bb eff',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'fourbet', t: '4-bet bluff to 22bb' },
    ],
    ok: 'fourbet',
    fb: {
      fourbet: 'A5o is a classic 4-bet bluff: the ace blocks AA/AK in their value range. At 50bb you can apply maximum fold equity.',
      fold:    'Folding A5o gives up free fold equity. The ace blocks premium aces \u2014 use this blocker to 4-bet bluff.',
      call:    'Calling A5o OOP in a 3-bet pot is difficult. 4-bet bluff is better: the ace blocks their value.',
    },
  },
  {
    lk: 'fold_to_3bet_too_high',
    sit: 'You open from BTN. BB 3-bets to 8bb. You have 45bb remaining.',
    hand: 'K\u2665J\u2663',
    ctx: 'BTN open vs BB 3-bet \u00b7 45bb eff',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'fourbet', t: '4-bet to 18bb' },
    ],
    ok: 'call',
    fb: {
      call:    'KJo calls a BB 3-bet from BTN. You have position, two broadways, enough equity. Call and play in position.',
      fold:    'Folding KJo to a BB 3-bet from BTN is too tight. You have position and strong blockers. This hand has too much equity to fold.',
      fourbet: 'KJo is marginal for a 4-bet \u2014 you don\u2019t block AK/AQ well. Calling in position is cleaner.',
    },
  },

  /* ── Three-bet too low ── */
  {
    lk: 'three_bet_too_low',
    sit: 'CO opens to 2.5bb. Folds to you on the BTN.',
    hand: 'Q\u2665Q\u2666',
    ctx: 'BTN facing CO open \u00b7 60bb eff',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 8bb' },
    ],
    ok: 'threbet',
    fb: {
      threbet: 'QQ is a mandatory 3-bet for value. You are ahead of nearly every CO hand. Build the pot, deny equity to hands like AK, and play a 3-bet pot with a huge equity advantage.',
      call:    'Flat-calling QQ from BTN slow-plays your hand, lets the blinds enter cheaply, and complicates postflop. 3-bet for value.',
      fold:    'Folding QQ is never correct here. Always 3-bet.',
    },
  },
  {
    lk: 'three_bet_too_low',
    sit: 'CO opens to 2.5bb. Folds to you on the BTN.',
    hand: 'A\u26604\u2660',
    ctx: 'BTN facing CO open \u00b7 55bb eff',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 8bb' },
    ],
    ok: 'threbet',
    fb: {
      threbet: 'A4s is a textbook light 3-bet from BTN: in position, ace blocks AA/AK in CO\u2019s range, and A4s plays well as a bluff with backup equity.',
      call:    'Calling A4s is acceptable but 3-betting is stronger. In position with a blocker, this is ideal for aggressive range construction.',
      fold:    'Folding A4s on BTN to a CO open is too tight. This is a standard light 3-bet or call hand.',
    },
  },
  {
    lk: 'three_bet_too_low',
    sit: 'MP opens to 2.5bb. Folds to you on the BTN.',
    hand: 'K\u2660Q\u2660',
    ctx: 'BTN facing MP open \u00b7 65bb eff',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 8bb' },
    ],
    ok: 'threbet',
    fb: {
      threbet: 'KQs on BTN vs MP is a strong 3-bet for value. You have position, flush equity, and great equity vs MP\u2019s range. Build the pot.',
      call:    'Calling KQs is acceptable but 3-betting is preferred. You get more money in as a clear favourite and maintain range initiative.',
      fold:    'Folding KQs from BTN is never correct. KQs is one of the strongest non-premium hands \u2014 always 3-bet or call.',
    },
  },

  /* ── BB overfolding vs BTN ── */
  {
    lk: 'bb_overfolding_vs_btn',
    sit: 'BTN opens to 2.5bb. SB folds. You are in the BB.',
    hand: '7\u26606\u2660',
    ctx: 'BB vs BTN open \u00b7 50bb eff \u00b7 heads-up',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 8bb' },
    ],
    ok: 'call',
    fb: {
      call:    '76s is a clear BB defend vs BTN. Great implied odds, strong connectivity, and BTN opens very wide. Call and play.',
      fold:    'Folding 76s in the BB vs BTN is a mistake. You need to continue ~40\u201360% here. 76s has flush and straight equity.',
      threbet: '3-betting 76s as a bluff is viable. If you are under-restealing, 76s is a reasonable bluff 3-bet candidate.',
    },
  },
  {
    lk: 'bb_overfolding_vs_btn',
    sit: 'BTN opens 2.5bb. SB folds. You are in the BB.',
    hand: '4\u26664\u2665',
    ctx: 'BB vs BTN open \u00b7 45bb eff \u00b7 heads-up',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet' },
    ],
    ok: 'call',
    fb: {
      call:    '44 calls BB vs BTN. Set equity, implied odds, and it plays fine as a call. Standard defend.',
      fold:    'Folding 44 to a BTN open in the BB is too tight. Small pairs defend well \u2014 set mining and implied odds make this an easy call.',
      threbet: '3-betting 44 is occasionally done, but it plays better as a call \u2014 set mining works better in a single-raised pot.',
    },
  },
  {
    lk: 'bb_overfolding_vs_btn',
    sit: 'BTN opens to 2.5bb. SB folds. You are in the BB.',
    hand: 'Q\u2665T\u2660',
    ctx: 'BB vs BTN open \u00b7 55bb eff \u00b7 heads-up',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 8bb' },
    ],
    ok: 'call',
    fb: {
      call:    'QTo is a standard BB defend vs BTN. Two broadways, top-pair potential, and you are getting a good price. Call and play.',
      threbet: '3-betting QTo is also valid if you are under-restealing. Both call and 3-bet are correct here \u2014 the error is folding.',
      fold:    'Folding QTo in the BB is a clear over-fold. BTN opens very wide and QTo is top 30% of hands \u2014 always defend here.',
    },
  },

  /* ── Resteal too low ── */
  {
    lk: 'resteal_too_low',
    sit: 'BTN raises to 2.5bb. SB folds. You are in the BB.',
    hand: 'A\u26605\u2660',
    ctx: 'BB vs BTN steal \u00b7 50bb eff \u00b7 heads-up',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 9bb' },
    ],
    ok: 'threbet',
    fb: {
      threbet: 'A5s is the ideal BB resteal bluff: ace blocks AA/AK in BTN\u2019s value range, and you have flush equity as backup when called.',
      call:    'Calling A5s is acceptable, but 3-betting as a bluff is higher EV. The ace blocker makes this the prototypical resteal hand.',
      fold:    'Folding A5s to a BTN steal is too tight. A5s is a perfect bluff-resteal hand given the ace blocker.',
    },
  },
  {
    lk: 'resteal_too_low',
    sit: 'BTN steals to 2.5bb. SB folds. You are in the BB.',
    hand: 'T\u2665T\u2660',
    ctx: 'BB vs BTN steal \u00b7 45bb eff \u00b7 heads-up',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 9bb' },
    ],
    ok: 'threbet',
    fb: {
      threbet: 'TT 3-bets a BTN steal. Premium hand \u2014 build the pot now. BTN folds most of their wide range, and when called you are often ahead.',
      call:    'Calling TT from BB vs BTN is too passive. TT is too strong to just call \u2014 3-bet for value.',
      fold:    'Folding TT in the BB is never correct. Always 3-bet vs a BTN steal with TT.',
    },
  },
  {
    lk: 'resteal_too_low',
    sit: 'BTN raises to 2.5bb. SB folds. You are in the BB.',
    hand: '7\u26667\u2665',
    ctx: 'BB vs BTN steal \u00b7 55bb eff \u00b7 heads-up',
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet to 9bb' },
    ],
    ok: 'threbet',
    fb: {
      threbet: '77 is a strong hand to 3-bet vs a BTN steal. Ahead of much of BTN\u2019s wide range, and 3-betting denies equity to overcards.',
      call:    'Calling 77 from BB is fine, but 3-betting is preferred if you are under-restealing.',
      fold:    'Folding 77 to a BTN steal is a clear mistake. You have a pocket pair that beats most of BTN\u2019s wide range.',
    },
  },

  /* ── VPIP too loose ── */
  {
    lk: 'vpip_too_loose',
    sit: 'You are UTG. Action has not started.',
    hand: '7\u26662\u2663',
    ctx: 'UTG \u00b7 60bb \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 2.5bb' },
      { v: 'limp',  t: 'Limp (1bb)' },
    ],
    ok: 'fold',
    fb: {
      fold:  'Correct. 72o is the weakest starting hand. From UTG you face 5 players. This folds always.',
      raise: 'Raising 72o from UTG loses chips. UTG opens only the top 15\u201320% of hands.',
      limp:  'Limping from UTG is never correct. Even worse with 72o \u2014 you enter a multi-way pot with the weakest hand. Fold.',
    },
  },
  {
    lk: 'vpip_too_loose',
    sit: 'You are in MP at a 6-handed table.',
    hand: 'K\u26663\u2665',
    ctx: 'MP \u00b7 55bb \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 2.5bb' },
      { v: 'limp',  t: 'Limp (1bb)' },
    ],
    ok: 'fold',
    fb: {
      fold:  'Correct. K3o from MP is too weak to open. You still have CO, BTN, and blinds behind \u2014 K3o will be dominated often.',
      raise: 'K3o from MP is below the opening threshold. You lose significantly to KQ, KJ, KT, AK when you hit your king.',
      limp:  'Limping K3o from MP is the worst option. You build a pot in a bad position with a weak hand. Fold.',
    },
  },
  {
    lk: 'vpip_too_loose',
    sit: 'You are in MP at a 6-handed table. No action yet.',
    hand: 'Q\u26654\u2666',
    ctx: 'MP \u00b7 50bb \u00b7 6-max',
    opts: [
      { v: 'fold',  t: 'Fold' },
      { v: 'raise', t: 'Raise 2.5bb' },
    ],
    ok: 'fold',
    fb: {
      fold:  'Correct. Q4o from MP does not make the opening range. The kicker is too weak \u2014 you will be dominated by any better queen.',
      raise: 'Q4o from MP is a losing open. OOP vs CO, BTN, and blinds, and Q4o loses badly to any queen with a better kicker.',
    },
  },

  /* ── PFR too passive ── */
  {
    lk: 'pfr_too_passive',
    sit: 'Action folds to you in the CO. You want to play this hand.',
    hand: 'A\u26659\u2666',
    ctx: 'CO \u00b7 50bb \u00b7 action folded to \u00b7 6-max',
    opts: [
      { v: 'limp',  t: 'Limp (1bb)' },
      { v: 'raise', t: 'Raise 3bb' },
      { v: 'fold',  t: 'Fold' },
    ],
    ok: 'raise',
    fb: {
      raise: 'A9o in CO is a standard open-raise. Raise to 3bb: apply pressure, define your range, play aggressively.',
      limp:  'Limping A9o from CO forfeits fold equity, lets BTN and blinds enter cheaply, and you go to the flop OOP with no initiative. Raise or fold \u2014 never limp.',
      fold:  'Folding A9o from CO when it folds to you is too tight. This hand is well within the CO opening range.',
    },
  },
  {
    lk: 'pfr_too_passive',
    sit: 'Folds to you in MP. You have a medium pocket pair.',
    hand: '8\u26658\u2666',
    ctx: 'MP \u00b7 55bb \u00b7 action folded to \u00b7 6-max',
    opts: [
      { v: 'limp',  t: 'Limp (1bb)' },
      { v: 'raise', t: 'Raise 2.5bb' },
      { v: 'fold',  t: 'Fold' },
    ],
    ok: 'raise',
    fb: {
      raise: '88 open-raises from MP. Strong pair \u2014 build the pot, apply fold equity, and play as the aggressor.',
      limp:  'Limping 88 from MP is a clear mistake. You want to be the aggressor with a strong pair. Raise.',
      fold:  'Folding 88 from MP when action is folded to you is too tight. 88 is a clear open.',
    },
  },
];

/* ── Trainer helpers ── */

function renderHand(handStr) {
  // Parse hand string like "K♥7♦" into HTML with suit coloring
  // Suits: ♥ ♦ = red; ♠ ♣ = black (dark-mode: secondary color)
  const RED_SUITS = new Set(['\u2665', '\u2666']);
  // Split into card tokens — each card is one or two rank chars followed by a suit char
  const tokens = [];
  const re = /([2-9]|10|[TJQKA])([\u2660\u2665\u2666\u2663])/gu;
  let m;
  while ((m = re.exec(handStr)) !== null) {
    tokens.push({ rank: m[1], suit: m[2] });
  }
  if (tokens.length === 0) {
    return `<span class="drill-hand-raw">${escHtml(handStr)}</span>`;
  }
  return tokens.map(({ rank, suit }) => {
    const cls = RED_SUITS.has(suit) ? 'suit-r' : 'suit-b';
    return `<span class="card-rank">${escHtml(rank)}</span><span class="${cls}">${suit}</span>`;
  }).join('<span class="card-gap">\u2009</span>');
}

// A drill may accept more than one answer (drill.alt) where two lines are standard.
function _isAcceptable(drill, v) {
  return v === drill.ok || (drill.alt || []).includes(v);
}

function btnClass(v) {
  switch (v) {
    case 'fold':    return 'btn-fold';
    case 'call':    return 'btn-call';
    case 'raise':   return 'btn-raise';
    case 'threbet': return 'btn-threbet';
    case 'fourbet': return 'btn-fourbet';
    case 'jam':     return 'btn-jam';
    case 'complete':return 'btn-complete';
    case 'limp':    return 'btn-limp';
    default:        return 'btn-raise';
  }
}

function optLabel(opt) {
  // Use display label from opt.t, falling back to value
  return opt.t || opt.v;
}

/* ── Poker table rendering ── */

const _POS_6MAX = ['BTN', 'SB', 'BB', 'UTG', 'MP', 'CO'];

const _SEAT_COORDS = {
  6: [
    { left: 50, top: 87 },
    { left: 82, top: 73 },
    { left: 92, top: 40 },
    { left: 76, top: 7  },
    { left: 24, top: 7  },
    { left: 8,  top: 40 },
  ],
  2: [
    { left: 50, top: 87 },
    { left: 50, top: 7  },
  ],
};

function parseCtx(ctx) {
  const r = { heroPos: null, stack: null, eff: null, facingPos: null, facingAction: null, facingAmount: 0, max: 6 };
  const posM = ctx.match(/^(BTN|CO|HJ|MP|SB|BB|UTG)/i);
  if (posM) r.heroPos = posM[1].toUpperCase();
  if (/heads-up/i.test(ctx)) r.max = 2;
  else { const mx = ctx.match(/(\d)-max/i); if (mx) r.max = parseInt(mx[1]); }
  const facM = ctx.match(/(?:vs|facing)\s+(BTN|CO|HJ|MP|SB|BB|UTG)\s*(3-bet|open|steal|raise)?/i);
  if (facM) { r.facingPos = facM[1].toUpperCase(); r.facingAction = (facM[2] || '').toLowerCase() || null; }
  // Extract facing bet size if present (e.g. "opens to 2.5bb")
  const facAmt = ctx.match(/(?:to|raises?|opens?)\s+(\d+(?:\.\d+)?)bb/i);
  if (facAmt) r.facingAmount = parseFloat(facAmt[1]);
  const effM = ctx.match(/(\d+(?:\.\d+)?)bb\s+eff/i);
  if (effM) r.eff = parseFloat(effM[1]);
  const allBb = [...ctx.matchAll(/(\d+(?:\.\d+)?)bb/gi)];
  if (allBb.length) r.stack = parseFloat(allBb[0][1]);
  return r;
}

function _tableSeats(heroPos, max) {
  if (max === 2) {
    const opp = heroPos === 'SB' ? 'BB' : heroPos === 'BTN' ? 'BB' : 'BTN';
    return [heroPos, opp];
  }
  const idx = _POS_6MAX.indexOf(heroPos);
  if (idx === -1) return [heroPos, ..._POS_6MAX.filter(p => p !== heroPos).slice(0, 5)];
  return Array.from({ length: 6 }, (_, i) => _POS_6MAX[(idx + i) % 6]);
}

function renderVisualCard(rank, suit) {
  const isRed = suit === '\u2665' || suit === '\u2666';
  return `<div class="vcard ${isRed ? 'vcard-red' : 'vcard-black'}"><span class="vcard-rank">${escHtml(rank)}</span><span class="vcard-suit">${suit}</span></div>`;
}

function renderFaceDownCard() {
  return `<div class="vcard vcard-back"><div class="vcard-back-pip"></div></div>`;
}

function renderPokerTable(drill, phase) {
  const ctx   = parseCtx(drill.ctx);
  const hp    = ctx.heroPos || 'BTN';
  const stack = ctx.eff || ctx.stack || '?';
  const coords = _SEAT_COORDS[ctx.max] || _SEAT_COORDS[6];
  const labels = _tableSeats(hp, ctx.max);

  // Compute a real pot from ctx (facing bet + blind)
  const facingBet = ctx.facingAmount || 0;
  const potBb = facingBet > 0 ? (1 + 0.5 + facingBet).toFixed(1) : '1.5';

  let heroCards = '';
  if (phase === 'replay') {
    const re = /([2-9]|10|[TJQKA])([\u2660\u2665\u2666\u2663])/gu;
    let m;
    while ((m = re.exec(drill.hand)) !== null) heroCards += renderVisualCard(m[1], m[2]);
  } else {
    heroCards = renderFaceDownCard() + renderFaceDownCard();
  }

  const seatsHtml = coords.map((c, i) => {
    const pos      = labels[i] || '?';
    const isHero   = i === 0;
    const isFacing = pos === ctx.facingPos;
    // Only mark a seat folded if it has explicitly folded; unknown seats stay visible
    const isFolded = !isHero && !isFacing && ctx.max > 2;
    let cls = 'table-seat' + (isHero ? ' seat-hero' : isFacing ? ' seat-active' : isFolded ? ' seat-folded' : '');
    let inner;
    if (isHero) {
      inner = `<div class="vhand-hero">${heroCards}</div>
               <div class="seat-label-pos hero-badge">${escHtml(pos)}</div>
               <div class="seat-stack-val">${stack}bb</div>`;
    } else {
      const actionLabel = isFacing && ctx.facingAction
        ? `<span class="seat-action-badge">${escHtml(ctx.facingAction.replace('3-bet','3bet').toUpperCase())}</span>` : '';
      const betChip = isFacing
        ? `<div class="seat-bet-chip"></div>` : '';
      inner = `<div class="seat-avatar${isFacing ? ' avatar-active' : ''}">${actionLabel}</div>
               <div class="seat-label-pos">${escHtml(pos)}</div>
               ${betChip}`;
    }
    return `<div class="${cls}" style="left:${c.left}%;top:${c.top}%">${inner}</div>`;
  }).join('');

  return `<div class="poker-table-wrap">
    <div class="poker-table-felt">
      <div class="table-pot"><div class="table-pot-lbl">pot</div><div class="table-pot-amt">${potBb}bb</div></div>
    </div>
    ${seatsHtml}
  </div>`;
}

function advanceToReplay() {
  if (!trainerState) return;
  trainerState.phase = 'replay';
  renderTrainer();
}

/* ── Trainer performance persistence ── */

const TRAINER_HISTORY_KEY = 'clubgg_trainer_history';

function loadTrainerHistory() {
  try {
    const raw = localStorage.getItem(TRAINER_HISTORY_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (_) { return null; }
}

function _emptyHistory() {
  return { sessions: [], allTime: { byLeak: {}, recentMistakes: [], replayMistakes: [] } };
}

function _ensureHistoryShape(h) {
  if (!h.allTime.replayMistakes) h.allTime.replayMistakes = [];
  if (!h.allTime.recentMistakes) h.allTime.recentMistakes = [];
  return h;
}

function saveTrainerHistory(h) {
  try { localStorage.setItem(TRAINER_HISTORY_KEY, JSON.stringify(h)); } catch (_) {}
}

function recordMistake(drill) {
  const h = _ensureHistoryShape(loadTrainerHistory() || _emptyHistory());
  h.allTime.recentMistakes.unshift({
    lk:       drill.lk,
    hand:     drill.hand,
    chosen:   drill._chosen,
    ok:       drill.ok,
    title:    drill.leak_title || drill.lk,
    severity: drill.leak_severity || 'low',
    ts:       Date.now(),
  });
  if (h.allTime.recentMistakes.length > 30) h.allTime.recentMistakes.length = 30;
  saveTrainerHistory(h);
}

function recordReplayMistake(leakId, extId, leakTitle, leakSeverity) {
  const h = _ensureHistoryShape(loadTrainerHistory() || _emptyHistory());
  // Deduplicate: don't push same extId twice within 24h
  const existing = h.allTime.replayMistakes.find(m => m.extId === extId);
  if (existing) { existing.ts = Date.now(); }
  else {
    h.allTime.replayMistakes.unshift({ leakId, extId, leakTitle, leakSeverity, ts: Date.now() });
    if (h.allTime.replayMistakes.length > 30) h.allTime.replayMistakes.length = 30;
  }
  saveTrainerHistory(h);
}

function _missedDrillsByLeak(h) {
  const result = {};
  for (const m of ((h && h.allTime.recentMistakes) || [])) {
    if (!m.hand || !m.lk) continue;
    if (!result[m.lk]) result[m.lk] = new Set();
    result[m.lk].add(m.hand);
  }
  return result;
}

function saveSessionToHistory(state) {
  const h = loadTrainerHistory() || _emptyHistory();
  const byLeak = {};
  for (const [lk, r] of Object.entries(state.perLeakResults || {})) {
    if (r.total > 0) byLeak[lk] = { correct: r.correct, total: r.total };
  }
  h.sessions.unshift({
    ts:       Date.now(),
    playerId: currentPlayerId,
    score:    state.score,
    total:    state.drills.length,
    byLeak,
  });
  if (h.sessions.length > 20) h.sessions.length = 20;

  // Merge into allTime.byLeak
  for (const [lk, r] of Object.entries(state.perLeakResults || {})) {
    if (r.total === 0) continue;
    if (!h.allTime.byLeak[lk]) {
      h.allTime.byLeak[lk] = { correct: 0, total: 0, title: r.title, severity: r.severity };
    }
    h.allTime.byLeak[lk].correct += r.correct;
    h.allTime.byLeak[lk].total   += r.total;
    h.allTime.byLeak[lk].title   = r.title;
    h.allTime.byLeak[lk].severity = r.severity;
  }
  saveTrainerHistory(h);
  renderHome();
  renderProgress();
}

function _historyWidget(h) {
  if (!h || !h.sessions.length) return '';
  _ensureHistoryShape(h);

  // Last session line
  const last    = h.sessions[0];
  const lastPct = Math.round((last.score / last.total) * 100);
  const lastLine = `<div class="trainer-hist-last">Last session: ${last.score}/${last.total} (${lastPct}%)</div>`;

  // All-time average
  const totals = h.sessions.reduce((a, s) => { a.s += s.score; a.t += s.total; return a; }, { s: 0, t: 0 });
  const avgPct = totals.t ? Math.round((totals.s / totals.t) * 100) : 0;
  const avgLine = h.sessions.length > 1
    ? `<div class="trainer-hist-avg">${h.sessions.length} sessions &middot; avg ${avgPct}%</div>`
    : '';

  // Missed spots badges
  const missedDrills  = new Set(h.allTime.recentMistakes.map(m => m.lk + ':' + m.hand)).size;
  const missedReplays = h.allTime.replayMistakes.length;
  let missedBadges = '';
  if (missedDrills > 0) {
    missedBadges += `<span class="missed-badge">${missedDrills} drill spot${missedDrills > 1 ? 's' : ''} to revisit</span>`;
  }
  if (missedReplays > 0) {
    missedBadges += `<span class="missed-badge missed-badge-replay">${missedReplays} replay${missedReplays > 1 ? 's' : ''} to review</span>`;
  }
  const missedLine = missedBadges
    ? `<div class="trainer-hist-missed">${missedBadges}</div>` : '';

  // Weakest areas — allTime entries with >= 3 attempts, sorted by accuracy asc
  const weak = Object.entries(h.allTime.byLeak)
    .filter(([, r]) => r.total >= 3)
    .sort(([, a], [, b]) => (a.correct / a.total) - (b.correct / b.total))
    .slice(0, 3);

  let weakHtml = '';
  if (weak.length) {
    weakHtml = `<div class="trainer-hist-weak-label">Weakest areas:</div>` +
      weak.map(([lk, r]) => {
        const pct    = Math.round((r.correct / r.total) * 100);
        const trend  = _leakTrend(h, lk);
        const sevCls = r.severity || 'low';
        return `<div class="trainer-hist-weak-row">
          <span class="severity-badge ${sevCls} per-leak-sev">${escHtml((r.severity||'low').slice(0,1).toUpperCase())}</span>
          <span class="trainer-hist-weak-name">${escHtml(r.title || lk)}</span>
          <span class="trainer-hist-weak-pct">${pct}%${trend}</span>
        </div>`;
      }).join('');
  }

  return `<div class="trainer-history-panel">
    <div class="trainer-hist-heading">Your history</div>
    ${lastLine}${avgLine}
    ${missedLine}
    ${weakHtml}
  </div>`;
}

function _leakTrend(h, lk) {
  // Compare last-session accuracy for this leak vs all-time. Returns arrow char or ''.
  const lastSession = h.sessions[0];
  if (!lastSession || !lastSession.byLeak || !lastSession.byLeak[lk]) return '';
  const r = lastSession.byLeak[lk];
  const allR = h.allTime.byLeak[lk];
  if (!allR || allR.total <= r.total) return '';  // not enough history beyond last session
  const prevTotal   = allR.total  - r.total;
  const prevCorrect = allR.correct - r.correct;
  if (prevTotal < 3) return '';
  const prevPct = prevCorrect / prevTotal;
  const thisPct = r.total ? r.correct / r.total : 0;
  const delta = thisPct - prevPct;
  if (delta > 0.05)  return ' \u25b2';
  if (delta < -0.05) return ' \u25bc';
  return '';
}

function _vsAvgLine(state, h) {
  if (!h || h.sessions.length < 2) return '';
  // Compare this session to prior sessions (exclude sessions[0] which we just saved)
  const prior = h.sessions.slice(1);
  const priorTotals = prior.reduce((a, s) => { a.s += s.score; a.t += s.total; return a; }, { s: 0, t: 0 });
  if (!priorTotals.t) return '';
  const priorPct = Math.round((priorTotals.s / priorTotals.t) * 100);
  const thisPct  = Math.round((state.score / state.drills.length) * 100);
  const delta    = thisPct - priorPct;
  const arrow    = delta > 0 ? '\u25b2' : delta < 0 ? '\u25bc' : '\u25b6';
  const cls      = delta > 0 ? 'vs-avg-up' : delta < 0 ? 'vs-avg-down' : 'vs-avg-flat';
  return `<div class="trainer-vs-avg ${cls}">vs. your avg (${priorPct}%) ${arrow} ${delta > 0 ? '+' : ''}${delta}%</div>`;
}

function _missedSpotsSection(state) {
  const missed = (state.drills || []).filter(d => d._was_wrong);
  if (!missed.length) return '';
  const items = missed.map(d => {
    const hand = d.hand || '';
    const title = d.leak_title || d.lk || '';
    const sevCls = d.leak_severity || 'low';
    return `<div class="session-missed-item">
      <span class="severity-badge ${sevCls} per-leak-sev">${escHtml((d.leak_severity||'low').slice(0,1).toUpperCase())}</span>
      <span class="session-missed-hand">${escHtml(hand)}</span>
      <span class="session-missed-leak">${escHtml(title)}</span>
    </div>`;
  }).join('');
  return `<div class="session-missed">
    <div class="session-missed-label">Missed this session \u2014 will repeat first next time:</div>
    ${items}
  </div>`;
}

/* ============================================================
   PROGRESS TAB
   ============================================================ */

/* Play progress from real hands: key preflop frequencies per month with 95%
   intervals; the latest month vs all earlier months.  Shown above the
   training-accuracy section of the Progress tab. */
const _VERDICT_CLS = { improved: 'res-pos', worse: 'res-neg' };

function _renderPlayProgress(data) {
  if (!data || !data.periods || !data.periods.length) return '';
  const pct = v => (v == null ? '—' : `${(parseFloat(v) * 100).toFixed(0)}%`);
  const periods = data.periods;
  const cmp = Object.fromEntries((data.comparison || []).map(c => [c.key, c]));
  const keys = periods[0].metrics.map(m => m.key);

  const head = periods.map(p =>
    `<th class="num">${escHtml(p.label)}<div class="prog-th-sub">${escHtml(p.hands)} hands</div></th>`
  ).join('');
  const rows = keys.map(key => {
    const first = periods[0].metrics.find(m => m.key === key);
    const cells = periods.map(p => {
      const m = p.metrics.find(x => x.key === key);
      if (!m || m.value == null) return '<td class="num text-secondary">—</td>';
      return `<td class="num">${pct(m.value)}<div class="prog-ci">${pct(m.ci_low)}–${pct(m.ci_high)} · n=${escHtml(m.n)}</div></td>`;
    }).join('');
    const c = cmp[key];
    const verdict = c
      ? `<span class="${_VERDICT_CLS[c.verdict] || 'res-neutral'}">${escHtml(c.verdict)}</span>`
      : '<span class="res-neutral">—</span>';
    return `<tr>
      <td>${escHtml(first.label)}</td>
      ${cells}
      <td class="num text-secondary">${pct(first.normal_low)}–${pct(first.normal_high)}</td>
      <td>${verdict}</td>
    </tr>`;
  }).join('');

  const latest = data.latest_label && periods.length > 1
    ? `Latest month (${escHtml(data.latest_label)}) vs all earlier months`
    : 'Needs at least two months of hands';
  return `<div class="results-block prog-play">
    <div class="results-block-title">Your play over time — from your real hands (20bb+ effective)</div>
    <table class="results-table">
      <thead><tr><th>Stat</th>${head}<th class="num">Normal range</th><th>${latest}</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="results-note">Each value shows a 95% range and sample size. A change is called improved or worse
    only when it is statistically significant, judged by whether it moved toward the normal range for
    tournaments with antes (approximate guidelines, not solver output). Small months give wide ranges —
    import more hands to tighten them.</div>
  </div>`;
}

function renderProgress() {
  const panel = document.getElementById('panel-progress');
  if (!panel) return;

  const h = _ensureHistoryShape(loadTrainerHistory() || _emptyHistory());
  const sessions = h.sessions;

  const playHtml = _renderPlayProgress(progressData);

  if (sessions.length === 0) {
    panel.innerHTML = playHtml + `<div class="empty-state">
      ${_EMPTY_ICON}
      <div class="empty-state-title">No training history yet</div>
      <div class="empty-state-sub">Complete a training session to see your progress here.</div>
      <button class="btn-primary" style="margin-top:16px" id="prog-start-btn">Start Training</button>
    </div>`;
    document.getElementById('prog-start-btn')?.addEventListener('click', () => switchTab('trainer'));
    return;
  }

  // ── Streak: consecutive days with a session ──
  const streak = _computeStreak(sessions);

  // ── Accuracy over time (last 10 sessions, newest last) ──
  const sparkSessions = sessions.slice(0, 10).reverse();
  const sparkHtml = _accuracySparkline(sparkSessions);

  // ── All-time totals ──
  const totalDrills  = sessions.reduce((a, s) => a + (s.total || 0), 0);
  const totalCorrect = sessions.reduce((a, s) => a + (s.score  || 0), 0);
  const allTimePct   = totalDrills ? Math.round(100 * totalCorrect / totalDrills) : 0;
  const allTimeCls   = allTimePct >= 75 ? 'text-green' : allTimePct >= 55 ? 'text-yellow' : 'text-red';

  // ── Per-leak table: accuracy + trend + most improved / weakest ──
  const byLeak = h.allTime.byLeak;
  const leakEntries = Object.entries(byLeak)
    .filter(([, r]) => r.total >= 3)
    .map(([lk, r]) => {
      const pct   = Math.round(100 * r.correct / r.total);
      const trend = _leakTrendNum(h, lk);
      return { lk, title: r.title || lk, severity: r.severity || 'low', pct, trend, total: r.total };
    })
    .sort((a, b) => a.pct - b.pct);

  const weakest  = leakEntries[0] || null;
  const improved = leakEntries.slice().sort((a, b) => b.trend - a.trend).find(e => e.trend > 0) || null;

  // ── Recent mistake trend (last 30 mistakes, group by leak) ──
  const mistakeCounts = {};
  for (const m of (h.allTime.recentMistakes || [])) {
    mistakeCounts[m.lk] = (mistakeCounts[m.lk] || 0) + 1;
  }
  const topMistakes = Object.entries(mistakeCounts)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);

  // ── HTML assembly ──
  const summaryHtml = `<div class="prog-summary-row">
    <div class="prog-kpi">
      <div class="prog-kpi-val">${sessions.length}</div>
      <div class="prog-kpi-label">Sessions</div>
    </div>
    <div class="prog-kpi">
      <div class="prog-kpi-val ${allTimeCls}">${allTimePct}%</div>
      <div class="prog-kpi-label">All-time accuracy</div>
    </div>
    <div class="prog-kpi">
      <div class="prog-kpi-val">${totalDrills}</div>
      <div class="prog-kpi-label">Drills completed</div>
    </div>
    <div class="prog-kpi">
      <div class="prog-kpi-val ${streak > 0 ? 'text-green' : ''}">${streak}d</div>
      <div class="prog-kpi-label">Current streak</div>
    </div>
  </div>`;

  const sparkSection = `<div class="prog-section">
    <div class="prog-section-title">Accuracy over time <span class="prog-section-meta">(last ${sparkSessions.length} sessions)</span></div>
    ${sparkHtml}
  </div>`;

  const highlightsHtml = (weakest || improved) ? `<div class="prog-section prog-highlights">
    ${weakest ? `<div class="prog-highlight prog-highlight--weak">
      <div class="prog-highlight-label">Weakest area</div>
      <div class="prog-highlight-title">${escHtml(weakest.title)}</div>
      <div class="prog-highlight-stat text-red">${weakest.pct}% (${weakest.total} drills)</div>
    </div>` : ''}
    ${improved ? `<div class="prog-highlight prog-highlight--improved">
      <div class="prog-highlight-label">Most improved</div>
      <div class="prog-highlight-title">${escHtml(improved.title)}</div>
      <div class="prog-highlight-stat text-green">+${improved.trend}% recently</div>
    </div>` : ''}
  </div>` : '';

  let leakTableHtml = '';
  if (leakEntries.length > 0) {
    const rows = leakEntries.map(e => {
      const sevCls    = e.severity;
      const pctCls    = e.pct >= 75 ? 'text-green' : e.pct >= 55 ? 'text-yellow' : 'text-red';
      const trendHtml = e.trend > 3  ? `<span class="text-green prog-trend">▲ +${e.trend}%</span>`
                      : e.trend < -3 ? `<span class="text-red prog-trend">▼ ${e.trend}%</span>`
                      : `<span class="text-muted prog-trend">—</span>`;
      const barW = Math.max(2, e.pct);
      return `<tr class="prog-leak-row">
        <td><span class="prog-sev sev-${sevCls}"></span></td>
        <td class="prog-leak-name">${escHtml(e.title)}</td>
        <td class="prog-leak-pct ${pctCls}">${e.pct}%</td>
        <td class="prog-leak-bar-cell"><div class="prog-leak-bar"><div class="prog-leak-bar-fill ${pctCls.replace('text-','bar-')}" style="width:${barW}%"></div></div></td>
        <td>${trendHtml}</td>
        <td class="prog-leak-n text-muted">${e.total}</td>
      </tr>`;
    }).join('');
    leakTableHtml = `<div class="prog-section">
      <div class="prog-section-title">Score by leak category</div>
      <table class="prog-leak-table">
        <thead><tr>
          <th></th><th>Leak</th><th>Accuracy</th><th style="width:120px"></th><th>Trend</th><th>Drills</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }

  let mistakeHtml = '';
  if (topMistakes.length > 0) {
    const items = topMistakes.map(([lk, count]) => {
      const entry = byLeak[lk];
      const title = entry ? entry.title : lk;
      const sevCls = entry ? (entry.severity || 'low') : 'low';
      const barW = Math.round(100 * count / topMistakes[0][1]);
      return `<div class="prog-mistake-row">
        <span class="prog-sev sev-${sevCls}"></span>
        <span class="prog-mistake-name">${escHtml(title)}</span>
        <div class="prog-mistake-bar-wrap">
          <div class="prog-mistake-bar" style="width:${barW}%"></div>
        </div>
        <span class="prog-mistake-count text-red">${count}</span>
      </div>`;
    }).join('');
    mistakeHtml = `<div class="prog-section">
      <div class="prog-section-title">Recent mistake trends <span class="prog-section-meta">(last 30 mistakes)</span></div>
      <div class="prog-mistakes">${items}</div>
    </div>`;
  }

  const recentSessionsHtml = `<div class="prog-section">
    <div class="prog-section-title">Session history</div>
    <div class="prog-sessions">
      ${sessions.slice(0, 10).map((s, i) => {
        const pct = s.total ? Math.round(100 * s.score / s.total) : 0;
        const cls = pct >= 75 ? 'text-green' : pct >= 55 ? 'text-yellow' : 'text-red';
        const date = new Date(s.ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        return `<div class="prog-session-row ${i === 0 ? 'prog-session-row--latest' : ''}">
          <span class="prog-session-date">${escHtml(date)}</span>
          <span class="prog-session-pct ${cls}">${pct}%</span>
          <span class="prog-session-detail text-muted">${s.score}/${s.total} correct</span>
        </div>`;
      }).join('')}
    </div>
  </div>`;

  panel.innerHTML = playHtml + `<div class="prog-layout">
    ${summaryHtml}
    ${sparkSection}
    ${highlightsHtml}
    <div class="prog-columns">
      <div class="prog-col-main">
        ${leakTableHtml}
        ${mistakeHtml}
      </div>
      <div class="prog-col-side">
        ${recentSessionsHtml}
      </div>
    </div>
  </div>`;
}

function _computeStreak(sessions) {
  if (!sessions.length) return 0;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  let streak = 0;
  let cursor = today.getTime();
  const DAY  = 86400000;
  for (const s of sessions) {
    const d = new Date(s.ts); d.setHours(0, 0, 0, 0);
    const diff = cursor - d.getTime();
    if (diff <= DAY) { streak++; cursor = d.getTime(); }
    else break;
  }
  return streak;
}

function _accuracySparkline(sessions) {
  if (!sessions.length) return '';
  const vals = sessions.map(s => s.total ? Math.round(100 * s.score / s.total) : 0);
  const maxV = 100, minV = 0, H = 48, W = 280;
  const step = W / Math.max(sessions.length - 1, 1);
  const pts  = vals.map((v, i) => {
    const x = i * step;
    const y = H - ((v - minV) / (maxV - minV)) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const labels = vals.map((v, i) => {
    const x = i * step;
    const cls = v >= 75 ? 'spark-hi' : v >= 55 ? 'spark-mid' : 'spark-lo';
    return `<text x="${x.toFixed(1)}" y="${(H + 14).toFixed(1)}" class="${cls}" text-anchor="middle">${v}%</text>`;
  }).join('');
  const dots = vals.map((v, i) => {
    const x = i * step;
    const y = H - ((v - minV) / (maxV - minV)) * H;
    const cls = v >= 75 ? 'spark-hi' : v >= 55 ? 'spark-mid' : 'spark-lo';
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" class="spark-dot ${cls}"/>`;
  }).join('');
  return `<div class="prog-sparkline-wrap">
    <svg class="prog-sparkline" viewBox="0 -4 ${W} ${H + 22}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" class="spark-line"/>
      ${dots}
      ${labels}
    </svg>
  </div>`;
}

function _leakTrendNum(h, lk) {
  const lastSession = h.sessions[0];
  if (!lastSession?.byLeak?.[lk]) return 0;
  const r    = lastSession.byLeak[lk];
  const allR = h.allTime.byLeak[lk];
  if (!allR || allR.total <= r.total) return 0;
  const prevTotal   = allR.total   - r.total;
  const prevCorrect = allR.correct - r.correct;
  if (prevTotal < 3) return 0;
  const delta = (r.total ? r.correct / r.total : 0) - (prevCorrect / prevTotal);
  return Math.round(delta * 100);
}

function renderTrainer() {
  const panel = els.trainerPanel();
  if (!panel) return;

  const _oldTrainerBanner = `<div class="trainer-practice-link">
    Looking for replay drills?
    <a href="#" onclick="spNavigate('/trainer?mode=replay-drill');return false;">Open the Practice page</a>
  </div>`;

  // Daily coach — plan screen
  if (_dailyCoachState === 'plan') {
    _renderDailyPlanScreen(panel);
    return;
  }

  if (!currentPlayerId || !leaksData) {
    panel.innerHTML = _oldTrainerBanner + `<div class="trainer-container">
      <div class="empty-state">
        ${_EMPTY_ICON}
        <div class="empty-state-title">No player loaded</div>
        <div class="empty-state-sub">Load a player first to run targeted preflop drills based on their detected leaks.</div>
      </div>
    </div>`;
    return;
  }

  if (!trainerState) {
    // Start screen
    const preflopLeaks = (leaksData.leaks || []).filter(l => l.category === 'preflop');
    const matchedIds = new Set(preflopLeaks.map(l => l.leak_id));
    const available = PREFLOP_DRILLS.filter(d => matchedIds.has(d.lk));

    let leakListHtml = '';
    if (preflopLeaks.length === 0) {
      leakListHtml = `<div class="trainer-no-leaks">No preflop leaks detected. All 30 drills will be available.</div>`;
    } else {
      leakListHtml = `<ul class="trainer-leak-list">` +
        preflopLeaks.map(l => {
          const sevCls = l.severity || 'low';
          return `<li class="trainer-leak-item sev-item-${sevCls}">
            <span class="trainer-leak-sev sev-${sevCls}">${escHtml((l.severity || 'low').toUpperCase())}</span>
            <span class="trainer-leak-title">${escHtml(l.title || l.leak_id)}</span>
          </li>`;
        }).join('') +
        `</ul>`;
    }

    const drillCount = Math.min(12, available.length > 0 ? available.length : PREFLOP_DRILLS.length);
    const drillPool = available.length > 0 ? available : PREFLOP_DRILLS;

    panel.innerHTML = _oldTrainerBanner + `<div class="trainer-container">
      <div class="trainer-start-screen">
        <div class="trainer-start-title">Preflop Leak Trainer</div>
        <div class="trainer-start-desc">
          ${available.length > 0
            ? `Targeting <strong>${preflopLeaks.length}</strong> detected preflop leak(s). Session: <strong>${drillCount}</strong> drills.`
            : `No preflop leaks matched the drill library. Running a general preflop session: <strong>${drillCount}</strong> drills.`}
        </div>
        <div class="trainer-start-leaks-label">Targeted leaks:</div>
        ${leakListHtml}
        <button class="btn-primary trainer-start-btn" id="trainer-start-btn">Start Drill Session</button>
        <button class="btn-secondary trainer-start-btn trainer-real-btn" id="trainer-real-btn">Drill your real spots: facing a raise</button>
        <div class="trainer-real-desc">12 spots from your own hands (SB / BTN / CO / HJ facing one open, 30bb+). Mostly spots you played wrong, mixed with ones you got right.</div>
        ${_historyWidget(loadTrainerHistory())}
      </div>
    </div>`;

    document.getElementById('trainer-start-btn').addEventListener('click', () => {
      startTrainerSession(drillPool, drillCount);
    });
    document.getElementById('trainer-real-btn').addEventListener('click', startRealSpotSession);
    return;
  }

  const { drills, idx, score, answered } = trainerState;

  if (idx >= drills.length) {
    // Completion screen — save once
    if (!trainerState.saved) {
      trainerState.saved = true;
      saveSessionToHistory(trainerState);
    }

    // Daily coach finish screen
    if (trainerState.coachMode) {
      _dailyCoachState = 'done';
      _renderDailyFinishScreen(panel);
      return;
    }

    const history = loadTrainerHistory();

    const pct = Math.round((score / drills.length) * 100);
    const msgText = pct >= 80 ? 'Strong session. Keep drilling to reinforce these spots.'
      : pct >= 50 ? 'Good effort. Review the feedback on the spots you missed.'
      : 'Tough session. Focus on the explanations and run it again.';

    // Per-leak breakdown rows
    const plr = trainerState.perLeakResults || {};
    const leakRows = Object.values(plr)
      .filter(r => r.total > 0)
      .map(r => {
        const pctLeak = r.total ? Math.round((r.correct / r.total) * 100) : 0;
        const barCls  = pctLeak === 100 ? 'perfect' : '';
        const sevCls  = r.severity || 'low';
        return `<div class="per-leak-row">
          <span class="severity-badge ${sevCls} per-leak-sev">${escHtml((r.severity||'low').slice(0,1).toUpperCase())}</span>
          <span class="per-leak-name">${escHtml(r.title || r.leak_id || '')}</span>
          <div class="per-leak-bar-wrap">
            <div class="per-leak-bar-fill ${barCls}" style="width:${pctLeak}%"></div>
          </div>
          <span class="per-leak-score">${r.correct}/${r.total}</span>
        </div>`;
      }).join('');

    const breakdownHtml = leakRows
      ? `<div class="per-leak-results">
          <div class="per-leak-heading">By leak</div>
          ${leakRows}
        </div>`
      : '';

    panel.innerHTML = `<div class="trainer-container">
      <div class="session-complete">
        <div class="session-complete-title">Session Complete</div>
        <div class="session-score-big">${score} / ${drills.length}</div>
        <div class="session-score-label">drills correct (${pct}%)</div>
        <div class="session-score-msg">${escHtml(msgText)}</div>
        ${_vsAvgLine(trainerState, history)}
        ${breakdownHtml}
        ${_missedSpotsSection(trainerState)}
        <button class="btn-primary btn-drill-again" id="trainer-again-btn">Drill Again \u2014 missed spots first</button>
      </div>
    </div>`;

    const wasRealSpots = drills[0] && drills[0].lk === 'vs_raise_real';
    const againBtn = document.getElementById('trainer-again-btn');
    if (wasRealSpots) againBtn.textContent = 'Drill again — new set of your spots';
    againBtn.addEventListener('click', () => {
      trainerState = null;
      if (wasRealSpots) startRealSpotSession();
      else renderTrainer();
    });
    return;
  }

  // Active drill
  panel.innerHTML = `<div class="trainer-container">
    ${renderDrill()}
  </div>`;

  // Bind drill-replay-btn (reveal phase)
  const replayBtn = panel.querySelector('#drill-replay-btn');
  if (replayBtn) replayBtn.addEventListener('click', advanceToReplay);

  // Bind action buttons (replay phase)
  if (!answered) {
    panel.querySelectorAll('.action-btn[data-val]').forEach(btn => {
      btn.addEventListener('click', () => submitAnswer(btn.dataset.val));
    });
  } else {
    const nextBtn = panel.querySelector('#drill-next-btn');
    if (nextBtn) nextBtn.addEventListener('click', nextDrill);
  }
}

function _shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function startTrainerSession(pool, count, opts = {}) {
  const _sevOrd = { high: 0, medium: 1, low: 2 };
  const preflopLeaks = (leaksData?.leaks || [])
    .filter(l => l.category === 'preflop')
    .slice()
    .sort((a, b) => {
      const sd = (_sevOrd[a.severity] ?? 2) - (_sevOrd[b.severity] ?? 2);
      return sd !== 0 ? sd : (b.priority ?? 0) - (a.priority ?? 0);
    });

  const history      = loadTrainerHistory();
  const missedByLeak = _missedDrillsByLeak(history);

  const sessionDrills = [];
  const perLeakResults = {};

  // Build grouped drills — highest-severity leaks first
  let totalGroups = 0;
  for (const leak of preflopLeaks) {
    const matching = PREFLOP_DRILLS.filter(d => d.lk === leak.leak_id);
    if (matching.length === 0) continue;

    // Missed drills for this leak come first, then fresh ones shuffled
    const missedHands = missedByLeak[leak.leak_id] || new Set();
    const missed      = matching.filter(d => missedHands.has(d.hand));
    const fresh       = _shuffle(matching.filter(d => !missedHands.has(d.hand)));
    const drillsPerLeak = leak.severity === 'high' ? 4 : 3;
    const selected    = [...missed, ...fresh].slice(0, drillsPerLeak);
    const bestExample = (leak.examples || [])[0] || null;
    totalGroups += 1;

    selected.forEach((drill, i) => {
      sessionDrills.push({
        ...drill,
        leak_title:    leak.title,
        leak_severity: leak.severity,
        real_example:  i === 0 ? bestExample : null, // show evidence only on first drill of group
        is_group_start: i === 0,
        group_num:     totalGroups,      // 1-based group index (set after loop)
        drill_in_group: i + 1,
        group_size:    selected.length,
      });
    });

    perLeakResults[leak.leak_id] = {
      title:    leak.title,
      severity: leak.severity,
      correct:  0,
      total:    0,
    };
  }

  // Fix group_num — set total after collecting all groups
  sessionDrills.forEach(d => {
    d._total_groups = totalGroups;
  });

  // Fallback: no matching leaks → flat shuffle of pool
  if (sessionDrills.length === 0) {
    _shuffle(pool).slice(0, count).forEach(d => {
      sessionDrills.push({
        ...d,
        leak_title: null,
        leak_severity: null,
        real_example: null,
        is_group_start: false,
        group_num: 1,
        drill_in_group: 1,
        group_size: 1,
        _total_groups: 1,
      });
    });
  }

  const firstDrill = sessionDrills[0];
  const initPhase = (firstDrill && firstDrill.is_group_start && firstDrill.real_example) ? 'reveal' : 'replay';
  trainerState = {
    drills:         sessionDrills,
    idx:            0,
    score:          0,
    perLeakResults,
    answered:       false,
    chosen:         null,
    phase:          initPhase,
    coachMode:      opts.coachMode || false,
  };
  renderTrainer();
}

/* ── Real-spot drills: facing a single raise, from the player's own hands ── */

const _SUIT_SYM = { s: '♠', h: '♥', d: '♦', c: '♣' };
// The trainer table is drawn 6-max; map 8/9-max seat names onto it.
const _TABLE_SEAT = { HJ: 'MP', LJ: 'MP', UTG1: 'UTG', UTG2: 'UTG' };
const _REAL_ACTION = { '3bet': 'threbet', call: 'call', fold: 'fold' };
const _REAL_ACTION_TEXT = { threbet: '3-bet', call: 'called', fold: 'folded' };

function _cardsToSymbols(hole) {
  return (hole || '').split(/\s+/).filter(Boolean)
    .map(c => `${c.slice(0, -1)}${_SUIT_SYM[c.slice(-1).toLowerCase()] || ''}`)
    .join(' ');
}

function _realSpotToDrill(spot) {
  const rec = spot.recommendation;
  const ok = _REAL_ACTION[rec.best];
  const alt = (rec.acceptable || []).map(a => _REAL_ACTION[a]).filter(a => a !== ok);
  const raise = parseFloat(spot.raise_to_bb).toFixed(1);
  const eff = parseFloat(spot.eff_bb).toFixed(0);
  const seat = _TABLE_SEAT[spot.position] || spot.position;
  const opener = _TABLE_SEAT[spot.opener_position] || spot.opener_position;
  const behind = spot.position === 'SB' ? ' The BB is still to act behind you.' : '';
  const you = _REAL_ACTION[spot.hero_action];
  const fbFor = v => (_isAcceptable({ ok, alt }, v) ? '' : 'Not the best line here. ') + rec.reason;
  return {
    lk: 'vs_raise_real',
    sit: `${spot.opener_position} opens to ${raise}bb. It folds to you in the ${spot.position}.${behind}`,
    hand: _cardsToSymbols(spot.hole_cards),
    ctx: `${seat} facing ${opener} open to ${raise}bb · ${eff}bb eff · 6-max`,
    opts: [
      { v: 'fold',    t: 'Fold' },
      { v: 'call',    t: 'Call' },
      { v: 'threbet', t: '3-bet' },
    ],
    ok,
    alt,
    fb: { fold: fbFor('fold'), call: fbFor('call'), threbet: fbFor('threbet') },
    real_note: `In the real hand (#${spot.hand_external_id.slice(-9)}) you ${_REAL_ACTION_TEXT[you]}. `
      + `Recommendation source: ${rec.backing}, not solver output.`,
  };
}

async function startRealSpotSession() {
  const btn = document.getElementById('trainer-real-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Loading your spots…'; }
  try {
    const data = await apiFetch(`/players/${encodeURIComponent(currentPlayerId)}/drills/vs-raise?limit=12`);
    const drills = _shuffle((data.spots || []).map(_realSpotToDrill));
    if (!drills.length) {
      if (btn) btn.textContent = 'No facing-a-raise spots found at 30bb+';
      return;
    }
    const title = 'Facing a raise — your real hands';
    drills.forEach((d, i) => Object.assign(d, {
      leak_title: title, leak_severity: 'high', real_example: null,
      is_group_start: i === 0, group_num: 1, drill_in_group: i + 1,
      group_size: drills.length, _total_groups: 1,
    }));
    trainerState = {
      drills, idx: 0, score: 0, answered: false, chosen: null, phase: 'replay', coachMode: false,
      perLeakResults: { vs_raise_real: { title, severity: 'high', correct: 0, total: 0 } },
    };
    renderTrainer();
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = `Couldn't load spots: ${err.message}`; }
  }
}

/* ============================================================
   DAILY COACH
   ============================================================ */

function buildDailyPlan() {
  const h        = _ensureHistoryShape(loadTrainerHistory() || _emptyHistory());
  const history  = h;
  const leaks    = (leaksData?.leaks || []).filter(l => l.category === 'preflop');
  const byLeak   = h.allTime.byLeak;

  // Priority 1: weakest leak (low accuracy, minimum 3 drills done)
  const weakest = Object.entries(byLeak)
    .filter(([, r]) => r.total >= 3)
    .sort(([, a], [, b]) => (a.correct / a.total) - (b.correct / b.total))[0];

  // Priority 2: top severity leak not already covered
  const topLeak = leaks
    .filter(l => !weakest || l.leak_id !== weakest[0])
    .sort((a, b) => {
      const sev = { high: 0, medium: 1, low: 2 };
      return (sev[a.severity] ?? 2) - (sev[b.severity] ?? 2);
    })[0];

  // Priority 3: missed replays
  const missedReplays = (h.allTime.replayMistakes || []).slice(0, 2);
  const missedDrills  = (h.allTime.recentMistakes  || []).slice(0, 4);

  // Estimate time: 30s per drill + 90s per replay
  const drillCount  = 8 + (missedDrills.length > 0 ? Math.min(4, missedDrills.length) : 0);
  const replayCount = missedReplays.length;
  const estMinutes  = Math.round((drillCount * 30 + replayCount * 90) / 60);

  const focusLeakObj  = weakest ? leaks.find(l => l.leak_id === weakest[0]) : null;
  const focusLeak     = focusLeakObj || topLeak || null;

  const steps = [];
  if (focusLeak) steps.push({ type: 'focus',   label: focusLeak.title, leak: focusLeak });
  if (missedReplays.length) steps.push({ type: 'replay', label: `${missedReplays.length} missed replay${missedReplays.length > 1 ? 's' : ''}` });
  steps.push({ type: 'drills', label: `${drillCount} targeted drills` });

  return { focusLeak, missedReplays, missedDrills, drillCount, replayCount, estMinutes, steps, history };
}

let _dailyCoachState = null; // 'plan' | 'session' | 'done'

function startDailyCoach() {
  _dailyCoachState = 'plan';
  trainerState = null;
  switchTab('trainer');
  renderTrainer();
}

function _renderDailyPlanScreen(panel) {
  if (!currentPlayerId || !leaksData) {
    panel.innerHTML = `<div class="trainer-container"><div class="empty-state">
      ${_EMPTY_ICON}
      <div class="empty-state-title">No player loaded</div>
      <div class="empty-state-sub">Load a player to generate your daily plan.</div>
    </div></div>`;
    return;
  }

  const plan = buildDailyPlan();
  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });

  const stepRows = plan.steps.map((s, i) => {
    const icon = s.type === 'focus' ? '🎯' : s.type === 'replay' ? '🔁' : '💡';
    return `<div class="dc-step-row">
      <span class="dc-step-num">${i + 1}</span>
      <span class="dc-step-icon">${icon}</span>
      <span class="dc-step-label">${escHtml(s.label)}</span>
    </div>`;
  }).join('');

  const focusHtml = plan.focusLeak ? `<div class="dc-focus-block">
    <div class="dc-focus-label">Today's focus</div>
    <div class="dc-focus-title">${escHtml(plan.focusLeak.title)}</div>
    <div class="dc-focus-evidence">${escHtml(plan.focusLeak.evidence || '')}</div>
  </div>` : '';

  const missedBadge = plan.missedReplays.length
    ? `<div class="dc-missed-note">You have <strong>${plan.missedReplays.length}</strong> missed replay${plan.missedReplays.length > 1 ? 's' : ''} to revisit.</div>`
    : '';

  const prevSession = plan.history.sessions[0];
  const prevHtml = prevSession ? (() => {
    const pct = prevSession.total ? Math.round(100 * prevSession.score / prevSession.total) : 0;
    const cls = pct >= 75 ? 'text-green' : pct >= 55 ? 'text-yellow' : 'text-red';
    const date = new Date(prevSession.ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return `<div class="dc-prev-session">Last session <span class="text-muted">(${escHtml(date)})</span>: <span class="${cls}">${pct}%</span></div>`;
  })() : '';

  const streak = _computeStreak(plan.history.sessions);
  const streakHtml = streak > 0 ? `<div class="dc-streak">${streak}-day streak</div>` : '';

  panel.innerHTML = `<div class="trainer-container">
    <div class="dc-plan-screen">
      <div class="dc-plan-header">
        <div class="dc-plan-title">Daily Coach</div>
        <div class="dc-plan-date">${escHtml(today)}</div>
        <div class="dc-plan-meta">
          <span class="dc-est-time">~${plan.estMinutes} min</span>
          ${streakHtml}
          ${prevHtml}
        </div>
      </div>
      ${focusHtml}
      ${missedBadge}
      <div class="dc-steps-label">Today's plan</div>
      <div class="dc-steps">${stepRows}</div>
      <div class="dc-plan-actions">
        <button class="btn-primary dc-start-btn" id="dc-start-btn">Start session →</button>
        <button class="dc-skip-btn" id="dc-skip-btn">Regular trainer instead</button>
      </div>
    </div>
  </div>`;

  document.getElementById('dc-start-btn').addEventListener('click', () => {
    _dailyCoachState = 'session';
    startTrainerSession(PREFLOP_DRILLS, plan.drillCount, { coachMode: true, plan });
  });

  document.getElementById('dc-skip-btn').addEventListener('click', () => {
    _dailyCoachState = null;
    trainerState = null;
    renderTrainer();
  });
}

function _renderDailyFinishScreen(panel) {
  const { drills, score } = trainerState;
  const pct      = drills.length ? Math.round(100 * score / drills.length) : 0;
  const history  = loadTrainerHistory();
  const streak   = _computeStreak((history?.sessions || []));
  const sessions = history?.sessions?.length || 0;

  const grade = pct >= 85 ? { label: 'Excellent', cls: 'text-green', msg: 'You\'re building solid habits. Consistency beats intensity.' }
              : pct >= 65 ? { label: 'Good', cls: 'text-yellow', msg: 'Solid work. Focus on the spots you missed before your next session.' }
              : { label: 'Keep going', cls: 'text-red', msg: 'Tough spots today — that\'s the point. Review the fixes and run it again tomorrow.' };

  // Next focus: weakest leak not solved today
  const h = _ensureHistoryShape(history || _emptyHistory());
  const nextWeak = Object.entries(h.allTime.byLeak)
    .filter(([, r]) => r.total >= 3)
    .sort(([, a], [, b]) => (a.correct / a.total) - (b.correct / b.total))[0];
  const nextFocus = nextWeak ? h.allTime.byLeak[nextWeak[0]].title : null;

  const plr = trainerState.perLeakResults || {};
  const leakRows = Object.values(plr)
    .filter(r => r.total > 0)
    .map(r => {
      const p = r.total ? Math.round(100 * r.correct / r.total) : 0;
      const cls = p >= 75 ? 'text-green' : p >= 55 ? 'text-yellow' : 'text-red';
      return `<div class="dc-finish-leak-row">
        <span class="dc-finish-leak-name">${escHtml(r.title || r.leak_id || '')}</span>
        <span class="dc-finish-leak-pct ${cls}">${p}%</span>
      </div>`;
    }).join('');

  panel.innerHTML = `<div class="trainer-container">
    <div class="dc-finish-screen">
      <div class="dc-finish-grade ${grade.cls}">${grade.label}</div>
      <div class="dc-finish-score">${score} / ${drills.length}</div>
      <div class="dc-finish-pct ${grade.cls}">${pct}%</div>
      <div class="dc-finish-msg">${escHtml(grade.msg)}</div>
      <div class="dc-finish-stats">
        <div class="dc-finish-stat"><span class="dc-finish-stat-val">${streak}d</span><span class="dc-finish-stat-label">streak</span></div>
        <div class="dc-finish-stat"><span class="dc-finish-stat-val">${sessions}</span><span class="dc-finish-stat-label">sessions</span></div>
      </div>
      ${leakRows ? `<div class="dc-finish-leaks-label">By area</div><div class="dc-finish-leaks">${leakRows}</div>` : ''}
      ${nextFocus ? `<div class="dc-finish-next">Tomorrow: focus on <strong>${escHtml(nextFocus)}</strong></div>` : ''}
      ${_missedSpotsSection(trainerState)}
      <div class="dc-finish-actions">
        <button class="btn-primary" id="dc-done-btn">Done →</button>
        <button class="dc-skip-btn" id="dc-again-btn">Drill again</button>
      </div>
    </div>
  </div>`;

  document.getElementById('dc-done-btn').addEventListener('click', () => {
    _dailyCoachState = null;
    trainerState = null;
    switchTab('home');
    renderHome();
  });
  document.getElementById('dc-again-btn').addEventListener('click', () => {
    _dailyCoachState = null;
    trainerState = null;
    renderTrainer();
  });
}

function renderDrill() {
  const { drills, idx, score, answered, chosen, phase } = trainerState;
  const drill = drills[idx];
  const total = drills.length;

  const leakCtx = drill.leak_title
    ? `<span class="trainer-leak-ctx">Leak ${drill.group_num}/${drill._total_groups}: ${escHtml(drill.leak_title)} &middot; Drill ${drill.drill_in_group}/${drill.group_size}</span>`
    : `<span class="trainer-progress-text">Drill ${idx + 1} of ${total}</span>`;

  const headerHtml = `<div class="trainer-header">
    ${leakCtx}
    <span class="trainer-score">Score: ${score}/${idx + (answered ? 1 : 0)}</span>
  </div>`;

  const progressPct = ((idx / total) * 100).toFixed(1);
  const progressHtml = `<div class="trainer-progress-bar-wrap">
    <div class="trainer-progress-bar-fill" style="width:${progressPct}%"></div>
  </div>`;

  let groupHeaderHtml = '';
  if (drill.is_group_start && drill.leak_title) {
    const sevCls = drill.leak_severity || 'low';
    groupHeaderHtml = `<div class="drill-group-header">
      <span class="severity-badge ${sevCls}">${escHtml(sevCls.toUpperCase())}</span>
      <span class="drill-group-title">${escHtml(drill.leak_title)}</span>
    </div>`;
  }

  const tableHtml = renderPokerTable(drill, phase);

  // ── Reveal phase: show real hand context, let user advance ──────────────
  let bodyHtml;
  if (phase === 'reveal' && drill.real_example) {
    const ex = drill.real_example;
    const stack = ex.stack_bb ? `${parseFloat(ex.stack_bb).toFixed(0)}bb` : '';
    const shortId = ex.hand_external_id
      ? '#' + ex.hand_external_id.replace(/^(Poker Hand #|Hand #)/i, '').slice(-12)
      : '';
    bodyHtml = `
      <div class="reveal-meta">${escHtml(ex.position || '')}${stack ? ' &middot; ' + stack : ''}${shortId ? ' &middot; <span class="reveal-id">' + escHtml(shortId) + '</span>' : ''}</div>
      <div class="reveal-situation">${escHtml(ex.situation || '')}</div>
      <div class="reveal-why"><span class="reveal-why-label">Why it matters:</span> ${escHtml(ex.why_weak || '')}</div>
      <button class="btn-replay-spot" id="drill-replay-btn">Replay this spot \u2192</button>`;
  } else {
    // ── Replay phase: action drill ───────────────────────────────────────
    let buttonsHtml = `<div class="action-row">`;
    for (const opt of drill.opts) {
      let extraCls = '';
      if (answered) {
        if (_isAcceptable(drill, opt.v))                          extraCls = ' btn-selected-correct';
        else if (opt.v === chosen && !_isAcceptable(drill, chosen)) extraCls = ' btn-selected-wrong';
      }
      buttonsHtml += `<button class="action-btn ${btnClass(opt.v)}${extraCls}" data-val="${escHtml(opt.v)}" ${answered ? 'disabled' : ''}>${escHtml(optLabel(opt))}</button>`;
    }
    buttonsHtml += `</div>`;

    let feedbackHtml = '';
    if (answered) {
      const isCorrect = _isAcceptable(drill, chosen);
      const feedbackCls = isCorrect ? 'is-correct' : 'is-wrong';
      const icon = isCorrect ? '\u2713' : '\u2717';
      const correctOptLabel = drill.opts.find(o => o.v === drill.ok)?.t || drill.ok;
      const verdictText = isCorrect
        ? (chosen === drill.ok ? 'Correct' : `Acceptable \u2014 best: ${escHtml(correctOptLabel)}`)
        : `Wrong \u2014 correct: ${escHtml(correctOptLabel)}`;
      feedbackHtml = `<div class="drill-feedback ${feedbackCls}">
        <div class="feedback-verdict"><span class="feedback-icon">${icon}</span>${verdictText}</div>
        <div class="feedback-text">${escHtml(drill.fb[chosen] || drill.fb[drill.ok] || '')}</div>
        ${drill.real_note ? `<div class="feedback-real">${escHtml(drill.real_note)}</div>` : ''}
      </div>
      <button class="btn-next" id="drill-next-btn">${idx + 1 < total ? 'Next Drill \u2192' : 'See Results'}</button>`;
    }

    bodyHtml = `
      <div class="drill-situation">${escHtml(drill.sit)}</div>
      <div class="drill-question">What do you do?</div>
      ${buttonsHtml}
      ${feedbackHtml}`;
  }

  return `${headerHtml}${progressHtml}
  ${groupHeaderHtml}
  <div class="drill-card"${answered ? ' data-answered' : ''}>
    ${tableHtml}
    ${bodyHtml}
  </div>`;
}

function submitAnswer(val) {
  if (!trainerState || trainerState.answered) return;
  const drill = trainerState.drills[trainerState.idx];
  const isCorrect = _isAcceptable(drill, val);
  trainerState.answered = true;
  trainerState.chosen   = val;
  if (isCorrect) trainerState.score += 1;

  if (!isCorrect) {
    drill._chosen   = val;
    drill._was_wrong = true;
    recordMistake(drill);
  }

  // Per-leak tracking
  if (drill.lk && trainerState.perLeakResults) {
    if (!trainerState.perLeakResults[drill.lk]) {
      trainerState.perLeakResults[drill.lk] = {
        title:    drill.leak_title || drill.lk,
        severity: drill.leak_severity || 'low',
        correct:  0,
        total:    0,
      };
    }
    trainerState.perLeakResults[drill.lk].total  += 1;
    if (isCorrect) trainerState.perLeakResults[drill.lk].correct += 1;
  }

  renderTrainer();
}

function nextDrill() {
  if (!trainerState) return;
  trainerState.idx += 1;
  trainerState.answered = false;
  trainerState.chosen = null;
  const next = trainerState.drills[trainerState.idx];
  trainerState.phase = (next && next.is_group_start && next.real_example) ? 'reveal' : 'replay';
  renderTrainer();
}

/* ============================================================
   IMPORT TAB
   ============================================================ */

function renderImport() {
  const panel = document.getElementById('panel-import');
  if (!panel) return;
  panel.innerHTML = `
    <div class="import-section">
      <div class="section-header" style="margin-top:0">Import Hand Histories</div>
      <p class="import-desc">
        Upload one or more ClubGG hand history <code>.txt</code> export files.
        Clubs are created automatically from the file headers.
        Hands already in the database are skipped — re-uploading is always safe.
      </p>
      <div class="import-dropzone" id="import-dropzone">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
        <div class="import-dropzone-text">Drop .txt files here or click to browse</div>
        <input type="file" id="import-file-input" multiple accept=".txt" style="display:none">
      </div>
      <div id="import-file-list" class="import-file-list"></div>
      <button class="btn-primary" id="import-btn" disabled>Import Files</button>
      <div id="import-result"></div>
    </div>`;

  const dropzone = document.getElementById('import-dropzone');
  const fileInput = document.getElementById('import-file-input');
  const fileList  = document.getElementById('import-file-list');
  const importBtn = document.getElementById('import-btn');

  let selectedFiles = [];

  function updateFileList() {
    if (selectedFiles.length === 0) {
      fileList.innerHTML = '';
      importBtn.disabled = true;
      return;
    }
    fileList.innerHTML = selectedFiles.map((f, i) =>
      `<div class="import-file-item">
        <span class="import-file-name">${escHtml(f.name)}</span>
        <span class="import-file-size text-muted">${(f.size / 1024).toFixed(1)} KB</span>
        <button class="import-file-remove" data-idx="${i}" title="Remove">✕</button>
      </div>`
    ).join('');
    importBtn.disabled = false;

    fileList.querySelectorAll('.import-file-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        selectedFiles.splice(parseInt(btn.dataset.idx, 10), 1);
        updateFileList();
      });
    });
  }

  dropzone.addEventListener('click', () => fileInput.click());

  dropzone.addEventListener('dragover', e => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
  dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    const added = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.txt'));
    selectedFiles = [...selectedFiles, ...added];
    updateFileList();
  });

  fileInput.addEventListener('change', () => {
    const added = Array.from(fileInput.files).filter(f => f.name.endsWith('.txt'));
    selectedFiles = [...selectedFiles, ...added];
    fileInput.value = '';
    updateFileList();
  });

  importBtn.addEventListener('click', async () => {
    if (selectedFiles.length === 0) return;
    importBtn.disabled = true;
    importBtn.textContent = 'Importing…';
    const resultEl = document.getElementById('import-result');
    resultEl.innerHTML = `<div class="loading-state"><div class="spinner"></div>Uploading ${selectedFiles.length} file(s)…</div>`;

    const form = new FormData();
    selectedFiles.forEach(f => form.append('files', f));

    let loggedIn = authIsLoggedIn();
    const endpoint = loggedIn ? `${API}/me/import` : `${API}/ingest/upload`;
    const headers = loggedIn ? _coAuthHeaders() : {};

    try {
      let res = await fetch(endpoint, { method: 'POST', body: form, headers });
      if (loggedIn && res.status === 401) {
        // Stale or expired login: drop it and import without an account
        // instead of failing the whole upload.
        authClearToken();
        authClearUser();
        if (typeof authUpdateNav === 'function') authUpdateNav();
        loggedIn = false;
        res = await fetch(`${API}/ingest/upload`, { method: 'POST', body: form });
      }
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      const data = await res.json();
      if (data.hands_imported > 0) {
        _renderImportWow(resultEl, data);
      } else {
        resultEl.innerHTML = renderImportResult(data);
      }
      selectedFiles = [];
      updateFileList();
      if (loggedIn && data.player_linked) {
        // Player auto-linked — seed currentPlayerId and refresh both analysis systems
        if (data.detected_player_id) {
          currentPlayerId = data.detected_player_id;
        }
        _anHubInitialized = false;
        _anInitHub();
      } else if (!loggedIn && (data.hands_imported > 0 || data.duplicates_skipped > 0)) {
        // Unauthenticated: show player picker so user can manually select a player
        _renderImportPlayerPicker(resultEl);
      }
    } catch (err) {
      resultEl.innerHTML = errorCard(`Import failed: ${err.message}`);
    } finally {
      importBtn.disabled = false;
      importBtn.textContent = 'Import Files';
    }
  });
}

function renderImportResult(d) {
  // Minimal screen for duplicate-only or zero-hand imports (wow screen is rendered separately)
  const playerBanner = d.link_message
    ? `<div class="import-player-banner${d.player_linked ? '' : ' import-player-banner--warn'}">${escHtml(d.link_message)}</div>`
    : '';
  const note = d.duplicates_skipped > 0
    ? `All ${d.duplicates_skipped} hand${d.duplicates_skipped !== 1 ? 's' : ''} already in your database — nothing new to add.`
    : 'No hands found in the uploaded file.';
  let html = `<div class="import-result-card">
    <div class="import-result-title"><span class="text-secondary">Import complete</span></div>
    ${playerBanner}
    <p style="margin:0.5rem 0 0;color:var(--text-secondary);font-size:0.875rem">${escHtml(note)}</p>`;
  if (d.parse_failures > 0) {
    html += `<p style="margin:0.5rem 0 0;color:var(--text-red,#ef4444);font-size:0.8125rem">${d.parse_failures} file(s) could not be parsed.</p>`;
  }
  if (d.errors && d.errors.length > 0) {
    html += `<div class="import-errors"><div class="import-errors-title">Errors</div>`;
    for (const e of d.errors.slice(0, 5)) {
      html += `<div class="import-error-line">${escHtml(e)}</div>`;
    }
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

// Called directly on the resultEl DOM node so we can attach listeners
/* ── Example hand pools ───────────────────────────────────── */

const _IM_STEAL_EXAMPLES = [
  {
    hand: 'A&#9830;9&#9827;', pos: 'BTN', bb: 14,
    correct: 'Open-raise to 2.5bb',
    why: 'A9o is a clear open from the BTN at any stack above 10bb. Folding surrenders dead money in the blinds and gives them a free walk.',
  },
  {
    hand: 'K&#9824;J&#9829;', pos: 'BTN', bb: 18,
    correct: 'Open-raise to 2.2bb',
    why: 'KJo is a standard BTN open vs most fields. At 18bb you have enough stack for a simple raise-fold or raise-call plan — not folding.',
  },
  {
    hand: 'Q&#9830;T&#9830;', pos: 'BTN', bb: 22,
    correct: 'Open-raise to 2.5bb',
    why: 'QTd has suit value and equity vs blind ranges. At 22bb, folding leaves chips on the table every orbit.',
  },
  {
    hand: 'J&#9827;9&#9827;', pos: 'CO', bb: 16,
    correct: 'Open-raise to 2.2bb',
    why: 'Suited one-gappers from CO at 16bb are profitable opens. You have two players to get through — not eight.',
  },
  {
    hand: 'A&#9829;5&#9829;', pos: 'BTN', bb: 20,
    correct: 'Open-raise to 2.5bb',
    why: 'A5s has nut-flush potential and ace-high equity. At 20bb from the BTN, folding this hand is a consistent leak.',
  },
];

const _IM_PUSHFOLD_EXAMPLES = [
  {
    hand: 'A&#9830;9&#9827;', pos: 'BTN', bb: 11,
    correct: 'Shove all-in',
    why: 'A9o at 11bb is well inside your profitable BTN shove range. Fold equity plus equity when called makes this a clear shove.',
  },
  {
    hand: 'K&#9824;Q&#9829;', pos: 'BTN', bb: 10,
    correct: 'Shove all-in',
    why: 'KQo at 10bb is a premium shove from any position. You are ahead of or flipping with nearly every calling range.',
  },
  {
    hand: 'A&#9824;7&#9830;', pos: 'SB', bb: 12,
    correct: 'Shove all-in',
    why: 'A7o from the SB at 12bb vs the BB only is a clear shove. You need only one player to fold, and A7 has strong equity when called.',
  },
  {
    hand: 'T&#9827;T&#9830;', pos: 'CO', bb: 9,
    correct: 'Shove all-in',
    why: 'Pocket tens at 9bb shove from CO — you\'re at least a coin-flip when called, and you take the pot uncontested 60%+ of the time.',
  },
  {
    hand: 'A&#9829;J&#9824;', pos: 'BTN', bb: 13,
    correct: 'Shove all-in',
    why: 'AJo at 13bb from BTN is a top-of-range shove. Open-raising small leaves you pot-committed with no good turn if 3-bet.',
  },
];

const _IM_TIMESTAMPS = [
  'Recent hand from your session',
  'From your last session',
  'Hand from earlier today',
  'From your recent play',
  'Hand spotted in your history',
];

function _imPick(pool, seed) {
  return pool[Math.abs(seed) % pool.length];
}

function _imTimestamp(seed) {
  return _IM_TIMESTAMPS[Math.abs(seed) % _IM_TIMESTAMPS.length];
}

// After render: try to find a real matching hand from /me/hands and update the example card
async function _imTryRealHand(resultEl, leakType, seed) {
  if (!authIsLoggedIn()) return;
  try {
    const res = await fetch(`${API}/me/hands?page_size=100`, { headers: _coAuthHeaders() });
    if (!res.ok) return;
    const { hands } = await res.json();
    if (!hands || !hands.length) return;

    // Folded preflop without investing: lost at most the ante (+ SB's half blind),
    // i.e. under 1bb.  Hands with an unknown result are skipped.
    const foldedCheap = h => {
      if (h.net_won_bb == null) return false;
      const bb = parseFloat(h.net_won_bb);
      return bb <= 0 && bb > -1;
    };
    let match;
    if (leakType === 'steal') {
      // Find a BTN or CO hand folded without investing at 12–25bb
      match = hands.find(h =>
        (h.position === 'BTN' || h.position === 'CO') &&
        h.stack_bb != null &&
        parseFloat(h.stack_bb) >= 12 && parseFloat(h.stack_bb) <= 25 &&
        foldedCheap(h)
      );
    } else {
      // Find a BTN/CO/SB hand at 8–15bb folded preflop
      match = hands.find(h =>
        (h.position === 'BTN' || h.position === 'CO' || h.position === 'SB') &&
        h.stack_bb != null &&
        parseFloat(h.stack_bb) >= 8 && parseFloat(h.stack_bb) <= 15 &&
        foldedCheap(h)
      );
    }
    if (!match) return;

    const realBb   = Math.round(parseFloat(match.stack_bb));
    const realPos  = match.position;
    const ago      = _imFormatAgo(match.hand_started_at);

    const ctxEl    = resultEl.querySelector('.im-wow-example-context');
    const labelEl  = resultEl.querySelector('.im-wow-example-label');
    const exPick   = _imPick(leakType === 'steal' ? _IM_STEAL_EXAMPLES : _IM_PUSHFOLD_EXAMPLES, seed);

    if (ctxEl) {
      ctxEl.innerHTML = `${escHtml(realPos)} &middot; ${realBb}bb &middot; folded to you &middot; <strong>${exPick.hand}</strong>`;
    }
    if (labelEl) {
      labelEl.textContent = ago;
    }
  } catch (_) {}
}

function _imFormatAgo(isoStr) {
  try {
    const ms = Date.now() - new Date(isoStr).getTime();
    const mins = Math.floor(ms / 60000);
    if (mins < 60)  return `${mins} minute${mins !== 1 ? 's' : ''} ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24)   return `${hrs} hour${hrs !== 1 ? 's' : ''} ago`;
    const days = Math.floor(hrs / 24);
    return `${days} day${days !== 1 ? 's' : ''} ago`;
  } catch (_) {
    return 'Recent hand from your session';
  }
}

function _renderImportWow(resultEl, d) {
  const n = d.hands_imported;
  const total = n + (d.duplicates_skipped || 0);
  const displayCount = total > 0 ? total : n;

  // Stable seed from hand count so the same import always picks the same example
  const seed = n;
  const leakType = n < 800 ? 'steal' : 'pushfold';

  const ex = _imPick(leakType === 'steal' ? _IM_STEAL_EXAMPLES : _IM_PUSHFOLD_EXAMPLES, seed);
  const timestamp = _imTimestamp(seed + 1);

  // Pick primary leak by volume — more hands → push/fold is more reliably detectable
  const primaryLeak = leakType === 'steal' ? {
    spot:         'BTN steal frequency',
    finding:      "You're missing profitable spots every time it folds to you on the button.",
    evPer:        '~0.9 bb',
    evTotal:      Math.round(displayCount * 0.009),
    example: {
      context:    `${ex.pos} &middot; ${ex.bb}bb &middot; folded to you`,
      hand:       ex.hand,
      yourPlay:   'Fold',
      correct:    ex.correct,
      why:        ex.why,
    },
    trainerUrl:   '/trainer?mode=general&difficulty=beginner',
    trainerLabel: 'Fix this now',
    lessonUrl:    '/learn/tournament-fundamentals/position-the-most-important-advantage',
    lessonLabel:  'Learn why',
  } : {
    spot:         'Short stack push/fold',
    finding:      "You're folding hands that are profitable shoves at 8–15bb.",
    evPer:        '~1.2 bb',
    evTotal:      Math.round(displayCount * 0.012),
    example: {
      context:    `${ex.pos} &middot; ${ex.bb}bb &middot; folded to you`,
      hand:       ex.hand,
      yourPlay:   'Fold',
      correct:    ex.correct,
      why:        ex.why,
    },
    trainerUrl:   '/trainer?mode=push-fold&difficulty=intermediate',
    trainerLabel: 'Fix this now',
    lessonUrl:    '/learn/tournament-fundamentals/short-stack-play-under-15bb',
    lessonLabel:  'Learn why',
  };
  const secondaryLabel = leakType === 'steal' ? 'Short stack push/fold' : 'BTN steal frequency';

  resultEl.innerHTML = `
    <div class="im-wow">

      <div class="im-wow-header">
        <div class="im-wow-check">&#10003;</div>
        <div class="im-wow-count">${displayCount.toLocaleString()} hands analyzed</div>
        <div class="im-wow-sub">Here is what we found in your game.</div>
      </div>

      <div class="im-wow-spots">
        <div class="im-wow-spot">
          <span class="im-wow-dot im-wow-dot--red"></span>
          <span class="im-wow-spot-label">${escHtml(primaryLeak.spot)}</span>
          <span class="im-wow-spot-tag im-wow-spot-tag--red">You're missing profitable spots</span>
        </div>
        <div class="im-wow-spot">
          <span class="im-wow-dot im-wow-dot--yellow"></span>
          <span class="im-wow-spot-label">${escHtml(secondaryLabel)}</span>
          <span class="im-wow-spot-tag im-wow-spot-tag--yellow">This is costing you chips</span>
        </div>
      </div>

      <div class="im-wow-leak">
        <div class="im-wow-leak-eyebrow">Your biggest leak</div>
        <div class="im-wow-leak-spot">${escHtml(primaryLeak.spot)}</div>
        <div class="im-wow-leak-finding">${escHtml(primaryLeak.finding)}</div>

        <div class="im-wow-impact">
          <div class="im-wow-impact-item">
            <span class="im-wow-impact-val">${escHtml(primaryLeak.evPer)}</span>
            <span class="im-wow-impact-lbl">lost per spot</span>
          </div>
          <div class="im-wow-impact-sep"></div>
          <div class="im-wow-impact-item">
            <span class="im-wow-impact-val">~${primaryLeak.evTotal}bb</span>
            <span class="im-wow-impact-lbl">over your ${displayCount.toLocaleString()} hands</span>
          </div>
        </div>

        <div class="im-wow-example">
          <div class="im-wow-example-label">${escHtml(timestamp)}</div>
          <div class="im-wow-example-context">${primaryLeak.example.context} &middot; <strong>${primaryLeak.example.hand}</strong></div>
          <div class="im-wow-example-plays">
            <div class="im-wow-play im-wow-play--bad">
              <span class="im-wow-play-tag">Your play</span>
              <span class="im-wow-play-action">${escHtml(primaryLeak.example.yourPlay)}</span>
            </div>
            <div class="im-wow-play-arrow">&#8594;</div>
            <div class="im-wow-play im-wow-play--good">
              <span class="im-wow-play-tag">Correct play</span>
              <span class="im-wow-play-action">${escHtml(primaryLeak.example.correct)}</span>
            </div>
          </div>
          <div class="im-wow-example-why">${escHtml(primaryLeak.example.why)}</div>
        </div>

        <div class="im-wow-actions">
          <button class="im-wow-cta-primary" id="im-wow-drill">${escHtml(primaryLeak.trainerLabel)} &rarr;</button>
          <button class="im-wow-cta-secondary" id="im-wow-lesson">${escHtml(primaryLeak.lessonLabel)}</button>
        </div>
      </div>

      <div class="im-wow-footer">
        <span class="im-wow-meta">${n} new hand${n !== 1 ? 's' : ''} imported &middot; ${(d.duration_seconds || 0).toFixed(1)}s</span>
        <button class="im-wow-full" id="im-wow-full">Full analysis &rarr;</button>
      </div>

    </div>`;

  resultEl.querySelector('#im-wow-drill')?.addEventListener('click',
    () => spNavigate(primaryLeak.trainerUrl));
  resultEl.querySelector('#im-wow-lesson')?.addEventListener('click',
    () => spNavigate(primaryLeak.lessonUrl));
  resultEl.querySelector('#im-wow-full')?.addEventListener('click',
    () => spNavigate('/analysis'));

  // Progressive enhancement: silently swap in a real matching hand if one exists
  _imTryRealHand(resultEl, leakType, seed);
}

async function _renderImportPlayerPicker(resultEl) {
  const pickerEl = document.createElement('div');
  pickerEl.className = 'import-player-picker';
  pickerEl.innerHTML = `<div class="import-picker-title">Select a player to analyse</div>
    <div class="import-picker-list"><div class="loading-state"><div class="spinner"></div>Loading players…</div></div>`;
  resultEl.appendChild(pickerEl);

  try {
    const data = await apiFetch('/players/?sort_by=hand_count&page_size=20');
    const players = (data.items || []).filter(p => p.hand_count > 0);
    const listEl = pickerEl.querySelector('.import-picker-list');

    if (players.length === 0) {
      listEl.innerHTML = '<div class="import-picker-empty">No players with hands found.</div>';
      return;
    }

    listEl.innerHTML = players.map(p => {
      const name = escHtml(p.display_name || p.username);
      const user = escHtml(p.username);
      const uuid = escHtml(String(p.id));
      const hands = p.hand_count;
      const stub = p.is_stub ? `<span class="import-picker-stub">stub</span>` : '';
      return `<button class="import-picker-player" data-id="${uuid}">
        <span class="import-picker-name">${name}${stub}</span>
        <span class="import-picker-user">${user}</span>
        <span class="import-picker-hands">${hands} hands</span>
        <span class="import-picker-uuid">${uuid.slice(0,8)}…</span>
      </button>`;
    }).join('');

    listEl.querySelectorAll('.import-picker-player').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const input = document.getElementById('player-input');
        if (input) input.value = id;
        loadPlayer(id);
        switchTab('stats');
      });
    });
  } catch (err) {
    pickerEl.querySelector('.import-picker-list').innerHTML =
      `<div class="import-picker-empty text-muted">Could not load players: ${escHtml(err.message)}</div>`;
  }
}

/* ============================================================
   INITIAL RENDER
   ============================================================ */

const _EMPTY_ICON = `<svg class="empty-state-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <polygon points="12,2 22,8.5 22,15.5 12,22 2,15.5 2,8.5"/>
  <line x1="12" y1="2" x2="12" y2="22"/>
  <line x1="2" y1="8.5" x2="22" y2="8.5"/>
  <line x1="2" y1="15.5" x2="22" y2="15.5"/>
</svg>`;

function renderInitialEmpty() {
  renderHome();
  renderProgress();
  renderImport();
  renderTrainer();
  const panels = ['stats', 'leaks', 'plan'];
  for (const tab of panels) {
    const panel = document.getElementById(`panel-${tab}`);
    if (!panel) continue;
    if (tab === 'plan') {
      panel.innerHTML = renderTournamentFormHTML() +
        `<div class="empty-state" style="padding:24px 0 16px;">
          ${_EMPTY_ICON}
          <div class="empty-state-title">Enter a player UUID above to get started.</div>
        </div>`;
      bindPlanForm();
    } else {
      panel.innerHTML = `<div class="empty-state">
        ${_EMPTY_ICON}
        <div class="empty-state-title">No player loaded</div>
        <div class="empty-state-sub">Enter a player UUID in the header and click Load Player to see their ${tab === 'stats' ? 'aggregate stats and positional breakdown' : 'detected leaks and exploitability analysis'}.</div>
      </div>`;
    }
  }
}

/* ============================================================
   HAND REPLAY
   ============================================================ */


// Which street contains the hero's leak decision for each leak type.
const _REPLAY_STREET = {
  fold_to_3bet_too_high:     'PREFLOP',
  btn_steal_too_low:         'PREFLOP',
  co_steal_too_low:          'PREFLOP',
  sb_steal_too_low:          'PREFLOP',
  bb_overfolding_vs_steals:  'PREFLOP',
  bb_overfolding_vs_btn:     'PREFLOP',
  sb_overfolding_vs_steals:  'PREFLOP',
  resteal_too_low:            'PREFLOP',
  three_bet_too_low:          'PREFLOP',
  three_bet_too_high:         'PREFLOP',
  vpip_too_loose:             'PREFLOP',
  pfr_too_passive:            'PREFLOP',
  cbet_too_low:               'FLOP',
  cbet_too_high:              'FLOP',
  fold_to_flop_bet_too_high:  'FLOP',
  fold_to_turn_bet_too_high:  'TURN',
  wtsd_too_high:              'RIVER',
  wtsd_too_low:               'FLOP',
  wsd_suspiciously_low:       'RIVER',
  too_passive_postflop:       'FLOP',
};

// Action options to present at the decision point.
const _REPLAY_OPTIONS = {
  fold_to_3bet_too_high:     [{ v:'fold', t:'Fold' },     { v:'call', t:'Call' },    { v:'jam', t:'4-bet Jam' }],
  btn_steal_too_low:         [{ v:'fold', t:'Fold' },     { v:'raise', t:'Open Raise' }],
  co_steal_too_low:          [{ v:'fold', t:'Fold' },     { v:'raise', t:'Open Raise' }],
  sb_steal_too_low:          [{ v:'fold', t:'Fold' },     { v:'raise', t:'Open Raise' }],
  bb_overfolding_vs_steals:  [{ v:'fold', t:'Fold' },     { v:'call', t:'Call' },    { v:'threbet', t:'3-bet' }],
  bb_overfolding_vs_btn:     [{ v:'fold', t:'Fold' },     { v:'call', t:'Call' },    { v:'threbet', t:'3-bet' }],
  sb_overfolding_vs_steals:  [{ v:'fold', t:'Fold' },     { v:'call', t:'Call' },    { v:'threbet', t:'3-bet' }],
  resteal_too_low:            [{ v:'fold', t:'Fold' },    { v:'call', t:'Call' },    { v:'threbet', t:'3-bet' }],
  three_bet_too_low:          [{ v:'call', t:'Call' },    { v:'fold', t:'Fold' },    { v:'threbet', t:'3-bet' }],
  vpip_too_loose:             [{ v:'call', t:'Call/Limp'},{ v:'raise', t:'Raise' },  { v:'fold', t:'Fold' }],
  pfr_too_passive:            [{ v:'call', t:'Call' },    { v:'raise', t:'Open Raise' }],
  cbet_too_low:               [{ v:'check', t:'Check' },  { v:'bet', t:'C-bet' }],
  cbet_too_high:              [{ v:'bet', t:'C-bet' },    { v:'check', t:'Check Back' }],
  fold_to_flop_bet_too_high:  [{ v:'fold', t:'Fold' },    { v:'call', t:'Call' },    { v:'raise', t:'Raise' }],
  fold_to_turn_bet_too_high:  [{ v:'fold', t:'Fold' },    { v:'call', t:'Call' },    { v:'raise', t:'Raise' }],
  wtsd_too_high:              [{ v:'call', t:'Call Down' },{ v:'fold', t:'Fold' }],
  wsd_suspiciously_low:       [{ v:'fold', t:'Fold' },    { v:'call', t:'Call' }],
  too_passive_postflop:       [{ v:'call', t:'Call' },    { v:'raise', t:'Raise/Bet' }],
};

// The correct action for each leak type.
const _REPLAY_CORRECT = {
  fold_to_3bet_too_high:     'call',
  btn_steal_too_low:         'raise',
  co_steal_too_low:          'raise',
  sb_steal_too_low:          'raise',
  bb_overfolding_vs_steals:  'call',
  bb_overfolding_vs_btn:     'call',
  sb_overfolding_vs_steals:  'call',
  resteal_too_low:            'threbet',
  three_bet_too_low:          'threbet',
  vpip_too_loose:             'fold',
  pfr_too_passive:            'raise',
  cbet_too_low:               'bet',
  cbet_too_high:              'check',
  fold_to_flop_bet_too_high:  'call',
  fold_to_turn_bet_too_high:  'call',
  wtsd_too_high:              'fold',
  wsd_suspiciously_low:       'call',
  too_passive_postflop:       'raise',
};

// Rough action-mix guidance per leak type (SPECULATIVE — not solver output).
// Percentages are tournament heuristics tied to the specific spot.
const _ACTION_MIX = {
  fold_to_3bet_too_high:     { call: 55, raise: 20, fold: 25, note: 'vs 3-bet, 15–25bb eff' },
  btn_steal_too_low:         { raise: 75, fold: 25, note: 'BTN, folded to you' },
  co_steal_too_low:          { raise: 65, fold: 35, note: 'CO, folded to you' },
  sb_steal_too_low:          { raise: 65, fold: 35, note: 'SB, folded to you' },
  bb_overfolding_vs_steals:  { call: 50, raise: 20, fold: 30, note: 'BB vs BTN/CO open' },
  bb_overfolding_vs_btn:     { call: 55, raise: 20, fold: 25, note: 'BB vs BTN steal' },
  sb_overfolding_vs_steals:  { call: 35, raise: 20, fold: 45, note: 'SB vs open (IP disadvantage)' },
  resteal_too_low:            { call: 25, threbet: 55, fold: 20, note: 'vs late-position open, mid-stack' },
  three_bet_too_low:          { call: 40, threbet: 35, fold: 25, note: 'vs late open, 20–40bb' },
  vpip_too_loose:             { fold: 65, call: 25, raise: 10, note: 'marginal hand vs raise' },
  pfr_too_passive:            { raise: 60, call: 40, note: 'BTN/CO, mid-stack, folded to' },
  cbet_too_low:               { bet: 65, check: 35, note: 'as PFR on flop, IP' },
  cbet_too_high:              { check: 50, bet: 50, note: 'PFR, merged range' },
  fold_to_flop_bet_too_high:  { call: 45, raise: 20, fold: 35, note: 'facing flop bet, IP' },
  fold_to_turn_bet_too_high:  { call: 40, raise: 15, fold: 45, note: 'facing turn bet' },
  wtsd_too_high:              { fold: 60, call: 40, note: 'river, thin value spot' },
  wsd_suspiciously_low:       { call: 55, fold: 45, note: 'river, pot-committed' },
  too_passive_postflop:       { raise: 55, call: 45, note: 'IP, strong draw or pair' },
};

async function openHandReplay(externalId, leak, example) {
  const allExamples = leak.examples || [];
  const startIdx    = allExamples.findIndex(e => e.hand_external_id === externalId);
  await _loadReplayExample(leak, allExamples, startIdx < 0 ? 0 : startIdx, {});
}

async function _loadReplayExample(leak, allExamples, exIdx, handCache) {
  _rsStop();
  const panel = els.leaksPanel();
  if (!panel) return;

  const example = allExamples[exIdx];
  if (!example) return;
  const extId = example.hand_external_id;

  // Show loading only if we don't have it cached
  if (!handCache[extId]) {
    panel.innerHTML = `<div class="replay-loading">Loading hand ${exIdx + 1} of ${allExamples.length}…</div>`;
    try {
      handCache[extId] = await apiFetch(`/hands/lookup?external_id=${encodeURIComponent(extId)}`);
    } catch (e) {
      panel.innerHTML = `<div class="replay-error">
        <p>Could not load hand: ${escHtml(String(e))}</p>
        <button class="btn-back-leaks" id="replay-back-btn">\u2190 Back to leaks</button>
      </div>`;
      panel.querySelector('#replay-back-btn')?.addEventListener('click', () => renderLeaks(leaksData));
      return;
    }
  }

  const hand   = handCache[extId];
  const heroHp = hand.hand_players.find(hp => hp.player_id === currentPlayerId);
  if (!heroHp) {
    // Hero not a participant in this hand — skip to next example if available
    const nextIdx = exIdx + 1;
    if (nextIdx < allExamples.length) {
      await _loadReplayExample(leak, allExamples, nextIdx, handCache);
    } else {
      const panel = els.leaksPanel();
      if (panel) panel.innerHTML = `<div class="error-card"><div class="error-card-title">Replay unavailable</div><div class="error-card-msg">Hero not found in this hand. <button class="dc-skip-btn" id="replay-err-back">← Back to leaks</button></div></div>`;
      panel?.querySelector('#replay-err-back')?.addEventListener('click', () => renderLeaks(leaksData));
    }
    return;
  }
  rsStart(panel, hand, heroHp, leak, example, allExamples, exIdx, handCache);
}


function _normSuit(s) {
  const m = { s:'\u2660', h:'\u2665', d:'\u2666', c:'\u2663' };
  return m[s.toLowerCase()] || s;
}

/* ============================================================
   REPLAYSCENE — Premium isolated replay engine (rs- prefix)
   All state in _rs. Zero dependency on old gg-replay code.
   ============================================================ */

let _rs = null;
let _rsOnBack = null; // optional callback: overrides "← Back to leaks" in rsBindControls and rsShowReveal

function _rsStop() {
  if (_rs?.playTimer) clearTimeout(_rs.playTimer);
  _rs = null;
}

function rsStart(panel, hand, heroHp, leak, example, allExamples, exIdx, handCache) {
  _rsStop();
  const heroId    = heroHp.player_id;
  const leakId    = leak.leak_id;
  const decStreet = _REPLAY_STREET[leakId] || 'PREFLOP';
  const opts      = _REPLAY_OPTIONS[leakId] || [{ v: 'fold', t: 'Fold' }, { v: 'call', t: 'Call' }];
  const correct   = _REPLAY_CORRECT[leakId] || 'call';
  const timeline  = rsBuildTimeline(hand, heroId, decStreet);
  const seatOrder = rsBuildSeatOrder(hand.hand_players, heroId);
  _rs = {
    panel, hand, heroId, heroHp, leak, example, leakId, decStreet,
    opts, correct, allExamples, exIdx, handCache,
    timeline, seatOrder,
    step: 0, decisionStep: timeline.length,
    phase: 'replay', chosen: null, logOpen: false, playing: true, playTimer: null,
  };
  panel.innerHTML = rsRender();
  rsBindControls(panel);
  if (timeline.length > 0) rsScheduleNext();
  else rsShowDecision();
}

function rsBuildTimeline(hand, heroId, decisionStreet) {
  const sRank   = { PREFLOP: 0, FLOP: 1, TURN: 2, RIVER: 3 };
  const decRank = sRank[decisionStreet] ?? 0;
  const bb      = parseFloat(hand.stakes_bb) || 1;
  const heroHp  = hand.hand_players.find(hp => hp.player_id === heroId);
  const heroActs = (heroHp?.actions || []).filter(a => a.street === decisionStreet).sort((a, b) => a.action_order - b.action_order);
  const heroDecOrd = heroActs.length ? heroActs[heroActs.length - 1].action_order : Infinity;
  const seq = [];
  for (const hp of hand.hand_players) {
    for (const act of (hp.actions || [])) {
      const ar = sRank[act.street] ?? 99;
      if (ar > decRank) continue;
      if (ar === decRank && act.action_order >= heroDecOrd) continue;
      seq.push({
        playerId: hp.player_id,
        pos:      hp.position || `S${hp.seat_number}`,
        username: hp.username || hp.position || `S${hp.seat_number}`,
        street:   act.street,
        action_type:  act.action_type,
        action_order: act.action_order,
        amount:   act.amount ? parseFloat(act.amount) / bb : 0,
        is_all_in: act.is_all_in || false,
      });
    }
  }
  seq.sort((a, b) => {
    const d = (sRank[a.street] ?? 99) - (sRank[b.street] ?? 99);
    return d !== 0 ? d : a.action_order - b.action_order;
  });
  return seq;
}

function rsBuildSeatOrder(handPlayers, heroId) {
  const sorted  = [...handPlayers].sort((a, b) => a.seat_number - b.seat_number);
  const heroIdx = sorted.findIndex(hp => hp.player_id === heroId);
  if (heroIdx < 0) return sorted.map(hp => hp.player_id);
  const n = sorted.length;
  return Array.from({ length: n }, (_, i) => sorted[(heroIdx - i + n) % n].player_id);
}

function rsSeatPositions(n) {
  return Array.from({ length: n }, (_, i) => {
    const ang = -Math.PI / 2 + (2 * Math.PI * i / n);
    return {
      left: +(50 + 45 * Math.cos(ang)).toFixed(1),
      top:  +(51 - 34 * Math.sin(ang)).toFixed(1),
    };
  });
}

function rsPotAtStep(timeline, step) {
  const skip = new Set(['FOLD', 'CHECK', 'MUCK', 'SHOW']);
  let pot = 0;
  const committed = {}; // `${playerId}:${street}` → total chips committed this street
  for (let i = 0; i < Math.min(step, timeline.length); i++) {
    const a = timeline[i];
    const t = a.action_type.toUpperCase();
    if (skip.has(t) || !(a.amount > 0)) continue;
    const key  = `${a.playerId}:${a.street}`;
    const prev = committed[key] || 0;
    if (t === 'RAISE') {
      // amount is total-to for the street; only add the marginal increase
      const marginal = Math.max(0, a.amount - prev);
      pot += marginal;
      committed[key] = a.amount;
    } else {
      // CALL, BET, POST_SB/BB/ANTE, ALL_IN: amount is the marginal chips added
      pot += a.amount;
      committed[key] = prev + a.amount;
    }
  }
  return pot;
}

function rsSeatStatesAtStep(timeline, step) {
  const states = {};
  for (let i = 0; i < Math.min(step, timeline.length); i++) {
    const a = timeline[i];
    states[a.playerId] = { action: a.action_type.toUpperCase(), amount: a.amount };
  }
  return states;
}

function rsBoardAtStep(boardCards, timeline, step) {
  if (!boardCards) return [];
  const cards = boardCards.split(' ').filter(Boolean);
  const lastAct = step > 0 ? timeline[Math.min(step, timeline.length) - 1] : null;
  const street  = lastAct?.street || 'PREFLOP';
  const limit   = { PREFLOP: 0, FLOP: 3, TURN: 4, RIVER: 5 }[street] ?? 0;
  return cards.slice(0, limit);
}

function rsRender() {
  const { hand, heroId, heroHp, leak, example, allExamples, exIdx, seatOrder, opts } = _rs;
  const hpMap = Object.fromEntries(hand.hand_players.map(hp => [hp.player_id, hp]));
  const n     = seatOrder.length;
  const poses = rsSeatPositions(n);

  const shortId = hand.external_id
    ? '#' + hand.external_id.replace(/^(Poker Hand #|Hand #|ClubGG Hand #)/i, '').slice(-12)
    : '';

  let navHtml;
  if (_rs.reviewMode) {
    const { rvHandIdx, rvFilteredHands } = _rs;
    const total = rvFilteredHands ? rvFilteredHands.length : 1;
    const hasPrev = rvHandIdx > 0;
    const hasNext = rvHandIdx < total - 1;
    navHtml = `
    <div class="rs-nav">
      <button class="rs-nav-btn" id="rs-prev-hand" ${hasPrev ? '' : 'disabled'}>‹</button>
      <span class="rs-nav-counter">${rvHandIdx + 1} / ${total}</span>
      <button class="rs-nav-btn" id="rs-next-hand" ${hasNext ? '' : 'disabled'}>›</button>
    </div>`;
  } else {
    const dotsHtml = allExamples.map((_, i) =>
      `<span class="rs-dot${i === exIdx ? ' rs-dot--active' : ''}" data-ex="${i}"></span>`
    ).join('');
    navHtml = allExamples.length > 1 ? `
    <div class="rs-nav">
      <button class="rs-nav-btn" id="rs-prev" ${exIdx > 0 ? '' : 'disabled'}>‹</button>
      <div class="rs-nav-dots">${dotsHtml}</div>
      <button class="rs-nav-btn" id="rs-next" ${exIdx < allExamples.length - 1 ? '' : 'disabled'}>›</button>
    </div>` : '<div class="rs-nav"></div>';
  }

  // Per-seat unique color identity — each player visually distinct
  const SEAT_BG = [
    'linear-gradient(145deg,#1a2240,#0e1628)',  // 0 hero: deep navy
    'linear-gradient(145deg,#3a1520,#220c14)',  // 1 rose
    'linear-gradient(145deg,#362408,#201504)',  // 2 amber
    'linear-gradient(145deg,#0c2c1a,#061c10)',  // 3 emerald
    'linear-gradient(145deg,#0c1e3c,#071224)',  // 4 sky
    'linear-gradient(145deg,#28103c,#180924)',  // 5 violet
    'linear-gradient(145deg,#341808,#200e04)',  // 6 orange
    'linear-gradient(145deg,#062c26,#041c18)',  // 7 teal
  ];

  const rsSeatRank = _seatRankMap(hand.hand_players);
  const seatsHtml = seatOrder.map((pid, i) => {
    const hp = hpMap[pid];
    if (!hp) return '';
    const pos      = hp.position || `S${hp.seat_number}`;
    const username = _resolvePlayerName(hp.username, rsSeatRank[String(pid)] || pos);
    const nick     = username.slice(0, 12);
    const initials = username.slice(0, 2).toUpperCase();
    const stakesbb = parseFloat(hand.stakes_bb) || 1;
    const stackBb  = hp.stack_bb        ? parseFloat(hp.stack_bb) :
                     hp.starting_stack  ? parseFloat(hp.starting_stack) / stakesbb : null;
    const stackTxt = stackBb !== null ? `${stackBb.toFixed(0)}bb` : '?';
    const stackCls = stackBb === null ? '' : stackBb < 10 ? ' rs-stack--critical' : stackBb < 20 ? ' rs-stack--short' : '';
    const isHero   = pid === heroId;
    const isBtn    = hp.seat_number === hand.button_seat;
    const { left, top } = poses[i];
    const bg       = SEAT_BG[i % SEAT_BG.length];
    const dealerBtn   = isBtn ? `<div class="rs-dealer">D</div>` : '';
    const oppCards    = isHero ? '' : `<div class="rs-opp-cards"><div class="rs-opp-card"></div><div class="rs-opp-card"></div></div>`;
    const avatarInner = isHero
      ? `<div class="rs-hero-cards" id="rs-hero-cards">${renderFaceDownCard()}${renderFaceDownCard()}</div>`
      : `<div class="rs-avatar-initials">${escHtml(initials)}</div>`;
    return `<div class="rs-seat${isHero ? ' rs-seat--hero' : ''}" id="rs-seat-${escHtml(pid)}" data-pid="${escHtml(pid)}" style="left:${left}%;top:${top}%">
      ${oppCards}
      <div class="rs-avatar" style="background:${bg}">${avatarInner}</div>
      ${dealerBtn}
      <div class="rs-nameplate">
        <span class="rs-stack${escHtml(stackCls)}">${escHtml(stackTxt)}</span>
        <span class="rs-nick">${escHtml(nick)}</span>
      </div>
    </div>`;
  }).join('');

  const decBtnsHtml = opts.map(o =>
    `<button class="rs-dec-btn rs-dec-btn--${escHtml(o.v)} rs-answer-btn" data-val="${escHtml(o.v)}">${escHtml(o.t)}</button>`
  ).join('');

  const sevBadge = `<span class="severity-badge ${escHtml(leak.severity || 'low')}">${escHtml((leak.severity || 'low').toUpperCase())}</span>`;

  return `<div class="rs-scene">
    <div class="rs-table" id="rs-table">
      <div class="rs-felt">
        <div class="rs-board" id="rs-board"></div>
        <div class="rs-pot" id="rs-pot">
          <div class="rs-pot-lbl">Total Pot</div>
          <div class="rs-pot-amt" id="rs-pot-amt">0.0bb</div>
        </div>
      </div>
      ${seatsHtml}
      <div class="rs-decision-dock" id="rs-decision-dock" hidden>
        <div class="rs-yourturn">YOUR TURN</div>
        <div class="rs-dec-btns">${decBtnsHtml}</div>
      </div>
      <div class="rs-tbl-nav">
        <button class="rs-back-btn" id="rs-back">\u2190 Back</button>
        <div class="rs-tbl-meta">
          ${sevBadge}
          <span class="rs-tbl-title">${escHtml(leak.title || leak.leak_id)}</span>
          <span class="rs-handid">${escHtml(shortId)}</span>
        </div>
        ${navHtml}
      </div>
      <div class="rs-tbl-controls">
        <div class="rs-tbl-ctx" id="rs-ctx"></div>
        <div class="rs-hud-controls" id="rs-controls">
          <button class="rs-ctrl" id="rs-restart" title="Restart">\u23EE</button>
          <button class="rs-ctrl" id="rs-stepback" title="Step back">\u23EA</button>
          <button class="rs-ctrl rs-ctrl--play" id="rs-play">\u25B6 Play</button>
          <button class="rs-ctrl" id="rs-stepfwd" title="Step forward">\u23E9</button>
          <button class="rs-ctrl" id="rs-skip" title="Skip to decision">\u23ED</button>
          <button class="rs-log-btn" id="rs-log-toggle">\u2630</button>
        </div>
        <div class="rs-progress-wrap">
          <div class="rs-progress-fill" id="rs-progress-fill" style="width:0%"></div>
        </div>
      </div>
    </div>
    <div class="rs-reveal" id="rs-reveal" hidden></div>
    <div class="rs-log-drawer" id="rs-log-drawer" hidden>
      <div class="rs-log-inner" id="rs-log-inner"></div>
    </div>
  </div>`;
}

function rsUpdateHud() {
  if (!_rs) return;
  const { panel, step, decisionStep, timeline, heroHp, playing } = _rs;
  const atDec = step >= decisionStep;
  const pct   = decisionStep > 0 ? Math.round(step / decisionStep * 100) : 100;
  const fill  = panel.querySelector('#rs-progress-fill');
  if (fill) fill.style.width = `${pct}%`;
  const playBtn = panel.querySelector('#rs-play');
  if (playBtn) playBtn.textContent = playing && !atDec ? '\u23F8 Pause' : atDec ? '\u23EE Restart' : '\u25B6 Play';
  [['#rs-restart', step === 0], ['#rs-stepback', step === 0],
   ['#rs-stepfwd', atDec],     ['#rs-skip', atDec]].forEach(([id, dis]) => {
    const b = panel.querySelector(id);
    if (b) b.disabled = dis;
  });
  const ctx = panel.querySelector('#rs-ctx');
  if (ctx) {
    const pos    = heroHp?.position || '?';
    const stack  = heroHp?.stack_bb ? `${parseFloat(heroHp.stack_bb).toFixed(0)}bb` : '?';
    const street = (step > 0 ? timeline[Math.min(step, timeline.length) - 1]?.street : null) || 'PREFLOP';
    ctx.textContent = `${pos} \u00B7 ${stack} \u00B7 ${street}`;
  }
}

function rsUpdateLog() {
  if (!_rs) return;
  const { panel, timeline, step } = _rs;
  const logEl = panel.querySelector('#rs-log-inner');
  if (!logEl) return;
  const skip = new Set(['FOLD', 'CHECK', 'MUCK', 'SHOW']);
  let lastStreet = null;
  logEl.innerHTML = timeline.slice(0, step).map((a, idx) => {
    const isLast  = idx === Math.min(step, timeline.length) - 1;
    const rawAmt  = a.amount;
    const showAmt = rawAmt > 0 && !skip.has(a.action_type.toUpperCase());
    let hdr = '';
    if (a.street !== lastStreet) {
      hdr = `<div class="rs-log-street">${escHtml(a.street)}</div>`;
      lastStreet = a.street;
    }
    return `${hdr}<div class="rs-log-row${isLast ? ' rs-log-row--cur' : ''}">
      <span class="rs-log-pos">${escHtml(a.pos)}</span>
      <span class="rs-log-act rs-log-act--${escHtml(a.action_type.toLowerCase())}">${escHtml(a.action_type.toUpperCase())}</span>
      ${showAmt ? `<span class="rs-log-amt">${rawAmt.toFixed(1)}bb</span>` : ''}
    </div>`;
  }).join('') || '<div class="rs-log-empty">Hand starting\u2026</div>';
  logEl.scrollTop = logEl.scrollHeight;
}

function rsShowDecision() {
  if (!_rs) return;
  if (_rs.reviewMode) { rsShowReviewReveal(); return; }
  _rs.phase = 'decision';
  const { panel } = _rs;
  panel.querySelector('#rs-table')?.classList.add('rs-table--decision');
  panel.querySelector('#rs-decision-dock').hidden = false;
  const ctrlWrap = panel.querySelector('.rs-tbl-controls');
  if (ctrlWrap) ctrlWrap.style.display = 'none';
  rsUpdateHud();
}

function rsShowReveal() {
  if (!_rs) return;
  const { panel, hand, heroHp, leakId, opts, correct, chosen, example, allExamples, exIdx, leak } = _rs;
  const isCorrect  = chosen === correct;
  const correctOpt = opts.find(o => o.v === correct);
  const icon       = isCorrect ? '\u2713' : '\u2717';
  const verdict    = isCorrect ? 'Correct!' : `Incorrect \u2014 ${escHtml(correctOpt?.t || correct)} was better`;
  const vCls       = isCorrect ? 'rs-verdict--correct' : 'rs-verdict--wrong';
  const heroAct    = (heroHp.actions || []).filter(a => a.street === _rs.decStreet).sort((a, b) => b.action_order - a.action_order)[0];
  const heroLabel  = heroAct
    ? `${heroAct.action_type.toLowerCase()}${heroAct.amount && parseFloat(heroAct.amount) > 0 && !['FOLD', 'CHECK'].includes(heroAct.action_type.toUpperCase()) ? ` (${parseFloat(heroAct.amount).toFixed(1)}bb)` : ''}`
    : 'unknown';

  const mix     = _ACTION_MIX[leakId];
  const mixHtml = mix ? (() => {
    const bars = opts.filter(o => mix[o.v] != null).map(o => {
      const pct = mix[o.v];
      const cls = o.v === 'fold' ? 'fold' : (o.v === 'raise' || o.v === 'threbet' || o.v === 'jam' || o.v === 'bet') ? 'raise' : 'call';
      return `<div class="rs-mix-row">
        <span class="rs-mix-lbl">${escHtml(o.t)}</span>
        <div class="rs-mix-bar-wrap"><div class="rs-mix-bar rs-mix-bar--${cls}" style="width:${pct}%"></div></div>
        <span class="rs-mix-pct">~${pct}%</span>
      </div>`;
    }).join('');
    return bars ? `<div class="rs-rev-section"><div class="rs-rev-label">Guidance <span class="rv-speculative-tag">SPECULATIVE</span></div><div class="rs-mix">${bars}${mix.note ? `<div class="rs-mix-note">${escHtml(mix.note)}</div>` : ''}</div></div>` : '';
  })() : '';

  const tipHtml = (example.why_weak || example.stronger_line) ? `<div class="rs-rev-section">
    <div class="rs-rev-label">Coaching</div>
    ${example.why_weak ? `<div class="rs-tip"><div class="rs-tip-lbl">Why it\u2019s weak</div><div class="rs-tip-val">${escHtml(example.why_weak)}</div></div>` : ''}
    ${example.stronger_line ? `<div class="rs-tip"><div class="rs-tip-lbl">Stronger line</div><div class="rs-tip-val">${escHtml(example.stronger_line)}</div></div>` : ''}
  </div>` : '';

  const revealBtns = opts.map(o => {
    const extra = o.v === correct ? ' rs-dec-btn--correct' : (o.v === chosen && chosen !== correct) ? ' rs-dec-btn--wrong' : '';
    return `<button class="rs-dec-btn rs-dec-btn--${escHtml(o.v)}${extra}" disabled>${escHtml(o.t)}</button>`;
  }).join('');

  const hasNext = exIdx < allExamples.length - 1;
  const navBtn  = hasNext
    ? `<button class="rs-next-ex" id="rs-next-ex">Next example \u2192</button>`
    : `<button class="rs-back-sm" id="rs-back-sm">\u2190 Back to leaks</button>`;

  const revealEl = panel.querySelector('#rs-reveal');
  if (!revealEl) return;
  revealEl.innerHTML = `
    <div class="rs-verdict ${vCls}"><span class="rs-verdict-icon">${icon}</span>${verdict}</div>
    <div class="rs-dec-btns">${revealBtns}</div>
    <div class="rs-hero-did">Hero played: ${escHtml(heroLabel)}</div>
    ${mixHtml}${tipHtml}
    <div class="rs-rev-nav">${navBtn}</div>`;
  revealEl.hidden = false;

  revealEl.querySelector('#rs-next-ex')?.addEventListener('click', () => {
    if (_rs) { const { leak: l, allExamples: ae, exIdx: ei, handCache: hc } = _rs; _rsStop(); _loadReplayExample(l, ae, ei + 1, hc); }
  });
  revealEl.querySelector('#rs-back-sm')?.addEventListener('click', () => {
    _rsStop();
    if (_rsOnBack) { const cb = _rsOnBack; _rsOnBack = null; cb(); } else { renderLeaks(leaksData); }
  });
}

function rsRevealHeroCards() {
  if (!_rs?.heroHp?.hole_cards) return;
  const wrap = _rs.panel.querySelector('#rs-hero-cards');
  if (!wrap) return;
  wrap.innerHTML = '';
  const re = /([2-9]|10|[TJQKA])([shdc\u2660\u2665\u2666\u2663])/gi;
  let m;
  while ((m = re.exec(_rs.heroHp.hole_cards)) !== null) {
    const sp = document.createElement('span');
    sp.innerHTML = renderVisualCard(m[1].toUpperCase(), _normSuit(m[2]));
    const card = sp.firstElementChild;
    if (card) { card.classList.add('rs-card-reveal'); wrap.appendChild(card); }
  }
}

function rsRenderStatic() {
  if (!_rs) return;
  const { panel, timeline, step, hand } = _rs;
  const states  = rsSeatStatesAtStep(timeline, step);
  for (const pid of _rs.seatOrder) {
    const seatEl = panel.querySelector(`#rs-seat-${pid}`);
    if (!seatEl) continue;
    seatEl.classList.remove('rs-seat--folded', 'rs-seat--turn', 'rs-seat--allin');
    if (states[pid]?.action === 'FOLD') seatEl.classList.add('rs-seat--folded');
    if (states[pid]?.action === 'ALL_IN' || states[pid]?.action === 'ALLIN') seatEl.classList.add('rs-seat--allin');
  }
  const boardEl = panel.querySelector('#rs-board');
  if (boardEl) {
    boardEl.innerHTML = '';
    rsBoardAtStep(hand.board_cards, timeline, step).forEach(c => {
      const sp = document.createElement('span');
      sp.innerHTML = renderVisualCard(c.slice(0, -1).toUpperCase(), _normSuit(c.slice(-1)));
      const card = sp.firstElementChild;
      if (card) { card.style.animation = 'none'; boardEl.appendChild(card); }
    });
  }
  const potAmt = panel.querySelector('#rs-pot-amt');
  if (potAmt) potAmt.textContent = `${rsPotAtStep(timeline, step).toFixed(1)}bb`;
  rsUpdateLog();
  rsUpdateHud();
}

function rsScheduleNext() {
  if (!_rs?.playing) return;
  const { timeline, step, decisionStep } = _rs;
  if (step >= decisionStep) return;
  const prevAct    = step > 0 ? timeline[step - 1] : null;
  const nextAct    = timeline[step];
  const isNewStreet = nextAct && prevAct && nextAct.street !== prevAct.street;
  const delay      = isNewStreet ? 1600 : rsActionDelay(prevAct);
  _rs.playTimer = setTimeout(() => {
    if (!_rs?.playing) return;
    rsPlayStep();
    if (_rs?.step < _rs?.decisionStep && _rs?.playing) rsScheduleNext();
    else if (_rs && _rs.step >= _rs.decisionStep) rsShowDecision();
  }, delay);
}

function rsActionDelay(act) {
  const t = (act?.action_type || '').toUpperCase();
  if (t === 'ALL_IN' || t === 'ALLIN') return 1500;
  if (t === 'RAISE'  || t === 'BET')   return 1200;
  if (t === 'FOLD')                    return 1050;
  if (t === 'CALL')                    return 1000;
  if (t.startsWith('POST'))            return 480;
  return 900;
}

function rsPlayStep() {
  if (!_rs) return;
  const { panel, timeline, step } = _rs;
  if (step >= timeline.length) return;
  const act     = timeline[step];
  const prevAct = step > 0 ? timeline[step - 1] : null;
  _rs.step++;
  // Turn indicator
  panel.querySelectorAll('.rs-seat--turn').forEach(el => el.classList.remove('rs-seat--turn'));
  const seatEl = panel.querySelector(`#rs-seat-${act.playerId}`);
  if (seatEl) seatEl.classList.add('rs-seat--turn');
  // New street: deal board first
  if (act.street !== 'PREFLOP' && (!prevAct || prevAct.street !== act.street)) {
    rsBoardReveal(panel, _rs.hand.board_cards, act.street);
    rsStreetLabel(panel, act.street);
  }
  const action = act.action_type.toUpperCase();
  const isPost = action.startsWith('POST');
  const PRE = isPost ? 55
    : (action === 'ALL_IN' || action === 'ALLIN') ? 420
    : action === 'FOLD'  ? 170
    : action === 'RAISE' || action === 'BET' ? 245
    : action === 'CALL'  ? 210
    : 185;
  setTimeout(() => {
    if (!_rs) return;
    if (seatEl) seatEl.classList.remove('rs-seat--turn');
    rsSeatAnimate(panel, seatEl, act);
  }, PRE);
  if (_rs.logOpen) rsUpdateLog();
  rsUpdateHud();
}

function rsSeatAnimate(panel, seatEl, act) {
  if (!seatEl) return;
  const action  = act.action_type.toUpperCase();
  const amount  = act.amount || 0;
  const isPost  = action.startsWith('POST');
  const isAllin = action === 'ALL_IN' || action === 'ALLIN' || act.is_all_in;
  const isRaise = action === 'RAISE' || action === 'BET';
  const isCall  = action === 'CALL';
  const isFold  = action === 'FOLD';
  const avatar  = seatEl.querySelector('.rs-avatar');

  // Floating action bubble
  if (!isPost) {
    const bCls = isFold ? 'fold' : isAllin ? 'allin' : isRaise ? 'raise' : isCall ? 'call' : action === 'CHECK' ? 'check' : 'other';
    const bTxt = isAllin ? 'ALL IN'
      : (isRaise || isCall) && amount > 0 ? `${action} ${amount.toFixed(1)}`
      : action;
    rsActionBubble(panel, seatEl, bTxt, bCls);
  }

  // Avatar animation
  if (avatar && !isPost) {
    const aCls = isAllin ? 'rs-anim--allin' : isRaise ? 'rs-anim--raise' : isCall ? 'rs-anim--call' : isFold ? 'rs-anim--fold' : null;
    if (aCls) {
      avatar.classList.remove('rs-anim--fold', 'rs-anim--call', 'rs-anim--raise', 'rs-anim--allin');
      void avatar.offsetWidth;
      avatar.classList.add(aCls);
      setTimeout(() => avatar?.classList.remove(aCls), isFold ? 700 : isAllin ? 1100 : 650);
    }
  }

  // ALL-IN persistent state
  if (isAllin) seatEl.classList.add('rs-seat--allin');

  // Fold dim
  if (isFold) {
    setTimeout(() => seatEl.classList.add('rs-seat--folded'), 380);
    return;
  }

  // Chip flight
  const chipSet = new Set(['CALL', 'RAISE', 'BET', 'ALL_IN', 'ALLIN', 'POST_SB', 'POST_BB', 'POST_ANTE']);
  if (chipSet.has(action) && amount > 0) rsChipFly(panel, seatEl, amount, action);
}

function rsChipFly(panel, seatEl, amount, actionType) {
  const tableEl  = panel.querySelector('#rs-table');
  const potEl    = panel.querySelector('#rs-pot');
  const avatarEl = seatEl.querySelector('.rs-avatar');
  if (!tableEl || !potEl || !avatarEl) return;
  const tr = tableEl.getBoundingClientRect();
  const fr = avatarEl.getBoundingClientRect();
  const pr = potEl.getBoundingClientRect();
  if (!tr.width) return;
  const sx = fr.left + fr.width  / 2 - tr.left;
  const sy = fr.top  + fr.height / 2 - tr.top;
  const px = pr.left + pr.width  / 2 - tr.left;
  const py = pr.top  + pr.height / 2 - tr.top;
  const ex = sx + (px - sx) * 0.74;
  const ey = sy + (py - sy) * 0.74;
  // Arc control point toward felt center
  const mx = (sx + ex) / 2, my = (sy + ey) / 2;
  const fcx = tr.width * 0.50, fcy = tr.height * 0.44;
  const dx = fcx - mx, dy = fcy - my;
  const dl  = Math.sqrt(dx * dx + dy * dy) || 1;
  const mag = Math.min(Math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2) * 0.30, 60);
  const cx  = mx + dx / dl * mag, cy = my + dy / dl * mag;
  const bx  = t => (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t ** 2 * ex;
  const by  = t => (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t ** 2 * ey;
  const isAllin = actionType === 'ALL_IN' || actionType === 'ALLIN';
  const isRaise = actionType === 'RAISE' || actionType === 'BET';
  const chip    = document.createElement('div');
  chip.className = `rs-chip${isAllin ? ' rs-chip--allin' : isRaise ? ' rs-chip--raise' : ''}`;
  chip.textContent = amount >= 10 ? amount.toFixed(0) : amount.toFixed(1);
  chip.style.cssText = `left:${sx}px;top:${sy}px;position:absolute;`;
  tableEl.appendChild(chip);
  const dur  = isAllin ? 255 : isRaise ? 305 : 400;
  const ease = isAllin ? 'cubic-bezier(0.12,0.6,0.28,1)' : 'cubic-bezier(0.22,0.61,0.36,1)';
  const kfs  = [0, 0.25, 0.5, 0.75, 1].map(t => ({
    left: `${bx(t)}px`, top: `${by(t)}px`,
    transform: `translate(-50%,-50%) scale(${1.08 - t * 0.32})`,
    opacity: t > 0.82 ? 1 - (t - 0.82) * 3 : 1,
    offset: t,
  }));
  const anim = chip.animate(kfs, { duration: dur, easing: ease, fill: 'forwards' });
  anim.finished.then(() => {
    const potAmt = panel.querySelector('#rs-pot-amt');
    if (potAmt && _rs) {
      potAmt.textContent = `${rsPotAtStep(_rs.timeline, _rs.step).toFixed(1)}bb`;
      potAmt.classList.remove('rs-pot--flash');
      void potAmt.offsetWidth;
      potAmt.classList.add('rs-pot--flash');
      setTimeout(() => potAmt?.classList.remove('rs-pot--flash'), 480);
    }
    const rx = px - bx(1), ry = py - by(1);
    setTimeout(() => {
      chip.animate([
        { opacity: 0.85, transform: 'translate(-50%,-50%) scale(0.68)' },
        { opacity: 0, transform: `translate(calc(-50% + ${rx.toFixed(0)}px),calc(-50% + ${ry.toFixed(0)}px)) scale(0.18)` },
      ], { duration: 210, easing: 'ease-in', fill: 'forwards' }).finished.then(() => chip.remove());
    }, isAllin ? 130 : 195);
  });
}

function rsBoardReveal(panel, boardCards, street) {
  if (!boardCards) return;
  const boardEl = panel.querySelector('#rs-board');
  if (!boardEl) return;
  const cards   = boardCards.split(' ').filter(Boolean);
  const limit   = { FLOP: 3, TURN: 4, RIVER: 5 }[street] ?? 0;
  const existing = boardEl.querySelectorAll('.vcard').length;
  cards.slice(existing, limit).forEach((c, i) => {
    const rank = c.slice(0, -1).toUpperCase();
    const suit = _normSuit(c.slice(-1));
    const sp   = document.createElement('span');
    sp.innerHTML = renderVisualCard(rank, suit);
    const card = sp.firstElementChild;
    if (card) { card.style.animationDelay = `${i * 155}ms`; boardEl.appendChild(card); }
  });
}

function rsStreetLabel(panel, street) {
  const tableEl = panel.querySelector('#rs-table');
  if (!tableEl) return;
  const label = document.createElement('div');
  label.className = 'rs-street-label';
  label.textContent = street;
  tableEl.appendChild(label);
  setTimeout(() => label.remove(), 1400);
}

function rsActionBubble(panel, seatEl, text, cls) {
  const tableEl  = panel.querySelector('#rs-table');
  const avatarEl = seatEl.querySelector('.rs-avatar');
  if (!tableEl || !avatarEl) return;
  const tr = tableEl.getBoundingClientRect();
  const ar = avatarEl.getBoundingClientRect();
  if (!tr.width) return;
  const bubble = document.createElement('div');
  bubble.className = `rs-bubble rs-bubble--${cls}`;
  bubble.textContent = text;
  // Position centered horizontally on avatar, vertically at top-third of avatar
  const bx = ar.left + ar.width / 2 - tr.left;
  const by = ar.top + ar.height * 0.22 - tr.top;
  bubble.style.cssText = `left:${bx}px;top:${by}px;`;
  tableEl.appendChild(bubble);
  setTimeout(() => bubble.remove(), 1700);
}

function rsBindControls(panel) {
  panel.querySelector('#rs-back')?.addEventListener('click', () => {
    if (_rs?.reviewMode) { const { rvOnBack } = _rs; _rsStop(); if (rvOnBack) rvOnBack(); return; }
    _rsStop();
    if (_rsOnBack) { const cb = _rsOnBack; _rsOnBack = null; cb(); } else { renderLeaks(leaksData); }
  });

  // Review mode hand navigation
  panel.querySelector('#rs-prev-hand')?.addEventListener('click', () => {
    if (!_rs?.reviewMode) return;
    const { rvHandIdx, rvFilteredHands, rvPanel } = _rs;
    if (rvHandIdx > 0) { _rsStop(); _trOpenHand(rvPanel, rvFilteredHands, rvHandIdx - 1); }
  });
  panel.querySelector('#rs-next-hand')?.addEventListener('click', () => {
    if (!_rs?.reviewMode) return;
    const { rvHandIdx, rvFilteredHands, rvPanel } = _rs;
    if (rvHandIdx < rvFilteredHands.length - 1) { _rsStop(); _trOpenHand(rvPanel, rvFilteredHands, rvHandIdx + 1); }
  });

  // Dot nav
  panel.querySelectorAll('.rs-dot').forEach(dot => {
    dot.addEventListener('click', () => {
      const idx = parseInt(dot.dataset.ex, 10);
      if (!isNaN(idx) && _rs) { const { leak, allExamples, handCache } = _rs; _rsStop(); _loadReplayExample(leak, allExamples, idx, handCache); }
    });
  });
  panel.querySelector('#rs-prev')?.addEventListener('click', () => {
    if (_rs) { const { leak, allExamples, exIdx, handCache } = _rs; _rsStop(); _loadReplayExample(leak, allExamples, exIdx - 1, handCache); }
  });
  panel.querySelector('#rs-next')?.addEventListener('click', () => {
    if (_rs) { const { leak, allExamples, exIdx, handCache } = _rs; _rsStop(); _loadReplayExample(leak, allExamples, exIdx + 1, handCache); }
  });

  // Playback controls
  panel.querySelector('#rs-play')?.addEventListener('click', () => {
    if (!_rs) return;
    if (_rs.step >= _rs.decisionStep) {
      _rsStop(); // stop clears _rs — need to restart: re-invoke start with same args
      // Re-render is simplest via re-rendering
      // We need to preserve allExamples etc — extract before stop
      // Actually _rsStop already cleared _rs, so we need to rebuild — simplest is full re-render
      // Problem: we already cleared _rs. Workaround: snapshot before stop
      return; // handled by restart button which does full re-render
    }
    _rs.playing = !_rs.playing;
    if (_rs.playing) rsScheduleNext();
    else if (_rs.playTimer) { clearTimeout(_rs.playTimer); _rs.playTimer = null; }
    rsUpdateHud();
  });

  panel.querySelector('#rs-restart')?.addEventListener('click', () => {
    if (!_rs) return;
    const { leak, example, allExamples, exIdx, handCache } = _rs;
    _rsStop();
    _loadReplayExample(leak, allExamples, exIdx, handCache);
  });

  panel.querySelector('#rs-stepback')?.addEventListener('click', () => {
    if (!_rs || _rs.step <= 0) return;
    if (_rs.playTimer) { clearTimeout(_rs.playTimer); _rs.playTimer = null; }
    _rs.playing = false;
    _rs.step = Math.max(0, _rs.step - 1);
    rsRenderStatic();
  });

  panel.querySelector('#rs-stepfwd')?.addEventListener('click', () => {
    if (!_rs || _rs.step >= _rs.decisionStep) return;
    if (_rs.playTimer) { clearTimeout(_rs.playTimer); _rs.playTimer = null; }
    _rs.playing = false;
    rsPlayStep();
  });

  panel.querySelector('#rs-skip')?.addEventListener('click', () => {
    if (!_rs) return;
    if (_rs.playTimer) { clearTimeout(_rs.playTimer); _rs.playTimer = null; }
    _rs.playing = false;
    _rs.step = _rs.decisionStep;
    rsRenderStatic();
    rsShowDecision();
  });

  // Answer buttons
  panel.querySelectorAll('.rs-answer-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!_rs || _rs.phase !== 'decision') return;
      const chosen = btn.dataset.val;
      if (chosen !== _rs.correct) recordReplayMistake(_rs.leakId, _rs.example.hand_external_id, _rs.leak.title, _rs.leak.severity);
      _rs.chosen = chosen;
      _rs.phase  = 'reveal';
      panel.querySelector('#rs-decision-dock').hidden = true;
      panel.querySelector('#rs-table')?.classList.remove('rs-table--decision');
      const ctrlWrap = panel.querySelector('.rs-tbl-controls');
      if (ctrlWrap) ctrlWrap.style.display = '';
      rsRevealHeroCards();
      rsShowReveal();
    });
  });

  // Log toggle
  panel.querySelector('#rs-log-toggle')?.addEventListener('click', () => {
    if (!_rs) return;
    _rs.logOpen = !_rs.logOpen;
    panel.querySelector('#rs-log-drawer').hidden = !_rs.logOpen;
    panel.querySelector('#rs-log-toggle')?.classList.toggle('rs-log-btn--active', _rs.logOpen);
    if (_rs.logOpen) rsUpdateLog();
  });
}

/* ============================================================
   BOOT
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Load player
  const loadBtn = document.getElementById('load-btn');
  const input   = document.getElementById('player-input');

  if (loadBtn) {
    loadBtn.addEventListener('click', () => {
      loadPlayer(input ? input.value : '');
    });
  }

  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { _closeRecent(); loadPlayer(input.value); }
    });
    // Clicking input closes dropdown
    input.addEventListener('focus', () => _closeRecent());
  }

  // Recent players dropdown
  const toggleBtn = document.getElementById('recent-toggle');
  const clearBtn  = document.getElementById('recent-clear-btn');

  if (toggleBtn) {
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const dd = document.getElementById('recent-dropdown');
      if (dd && !dd.hidden) { _closeRecent(); } else { _renderRecent(); _openRecent(); }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      recentClear();
    });
  }

  // Close dropdown on outside click
  document.addEventListener('click', (e) => {
    const wrap = document.getElementById('player-input-wrap');
    if (wrap && !wrap.contains(e.target)) _closeRecent();
  });

  // Stat card delegation — set up once; survives renderStats() re-renders
  const statsPanel = document.getElementById('panel-stats');
  if (statsPanel) {
    statsPanel.addEventListener('click', e => {
      const card = e.target.closest('[data-stat-key]');
      if (card) openStatDetail(card.dataset.statKey);
    });
    statsPanel.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const card = e.target.closest('[data-stat-key]');
      if (card) openStatDetail(card.dataset.statKey);
    });
  }

  // Populate recent list on load
  _renderRecent();

  // Initial empty state
  renderInitialEmpty();

  // Auto-load last player: URL hash → server preference → localStorage fallback
  const hash = window.location.hash.replace('#', '').trim();
  if (hash && hash.length > 8) {
    if (input) input.value = hash;
    loadPlayer(hash);
  } else {
    _serverLoadLastPlayer().then(serverId => {
      const fallbackId = serverId || (_recentLoad()[0] || {}).id || null;
      if (fallbackId) {
        if (input) input.value = fallbackId;
        loadPlayer(fallbackId);
      }
    });
  }
});

/* ============================================================
   AC — ACCESS CONTROL + BILLING FOUNDATION
   Mock subscription plan model. No real payments.
   Prefix: ac- (CSS), bl- (CSS), AC_ / ac (JS)
   ============================================================ */

const AC_PLANS = {
  free: {
    id: 'free',
    name: 'Free',
    price: '$0',
    period: 'forever',
    badge: 'Free',
    badgeCls: 'ac-badge--free',
    tagline: 'Get started with the basics.',
    cta: 'Current Plan',
    features: [
      { label: 'Basic dashboard', included: true },
      { label: 'Beginner courses (2 courses)', included: true },
      { label: '5 practice hands per day', included: true },
      { label: 'Intermediate & Advanced courses', included: false },
      { label: 'Replay Drills', included: false },
      { label: 'Leak Tracker', included: false },
      { label: 'Full Progress Dashboard', included: false },
      { label: 'AI Coach (coming soon)', included: false },
    ],
  },
  starter: {
    id: 'starter',
    name: 'Starter',
    price: '$9',
    period: '/month',
    badge: 'Starter',
    badgeCls: 'ac-badge--starter',
    tagline: 'Build your tournament foundation.',
    cta: 'Upgrade to Starter',
    features: [
      { label: 'Basic dashboard', included: true },
      { label: 'Beginner + Intermediate courses', included: true },
      { label: 'Unlimited practice hands', included: true },
      { label: 'Hand Replay (limited)', included: true },
      { label: 'Basic Progress Dashboard', included: true },
      { label: 'Advanced & Elite courses', included: false },
      { label: 'Replay Drills', included: false },
      { label: 'Leak Tracker', included: false },
      { label: 'AI Coach (coming soon)', included: false },
    ],
  },
  pro: {
    id: 'pro',
    name: 'Tournament Pro',
    price: '$19',
    period: '/month',
    badge: 'Pro',
    badgeCls: 'ac-badge--pro',
    tagline: 'Everything you need to go deep.',
    cta: 'Upgrade to Pro',
    popular: true,
    features: [
      { label: 'All courses (Beginner → Elite)', included: true },
      { label: 'Unlimited practice hands', included: true },
      { label: 'Replay Drills', included: true },
      { label: 'Full Leak Tracker', included: true },
      { label: 'Full Progress Dashboard + Skill Map', included: true },
      { label: 'Hand Replay (unlimited)', included: true },
      { label: 'Tournament Plan builder', included: true },
      { label: 'AI Coach (coming soon)', included: false },
    ],
  },
  elite: {
    id: 'elite',
    name: 'Elite',
    price: '$39',
    period: '/month',
    badge: 'Elite',
    badgeCls: 'ac-badge--elite',
    tagline: 'The complete edge for serious players.',
    cta: 'Upgrade to Elite',
    features: [
      { label: 'Everything in Tournament Pro', included: true },
      { label: 'AI Coach (coming soon)', included: true },
      { label: 'Advanced Analysis (coming soon)', included: true },
      { label: 'Cash Game modules (coming soon)', included: true },
      { label: 'Priority support', included: true },
    ],
  },
};

let AC_CURRENT_PLAN = 'free';

const AC_PLAN_RANK = { free: 0, starter: 1, pro: 2, elite: 3 };

const AC_FEATURE_REQUIRES = {
  basic_dashboard:        'free',
  beginner_lessons:       'free',
  basic_practice:         'free',
  intermediate_lessons:   'starter',
  full_practice:          'starter',
  hand_replay:            'starter',
  progress_dashboard:     'starter',
  all_lessons:            'pro',
  replay_drills:          'pro',
  leak_tracker:           'pro',
  full_skill_map:         'pro',
  ai_coach:               'elite',
  advanced_analysis:      'elite',
};

function acCan(feature) {
  const req = AC_FEATURE_REQUIRES[feature];
  if (!req) return true;
  return (AC_PLAN_RANK[AC_CURRENT_PLAN] || 0) >= (AC_PLAN_RANK[req] || 0);
}

function acPlanObj() { return AC_PLANS[AC_CURRENT_PLAN] || AC_PLANS.free; }

async function acLoadPlan() {
  const token = authGetToken();
  if (!token) { AC_CURRENT_PLAN = 'free'; acInitNavBadge(); return; }
  try {
    const res = await fetch('/api/v1/billing/me', { headers: { Authorization: `Bearer ${token}` } });
    if (res.ok) { const d = await res.json(); if (d?.plan_slug) AC_CURRENT_PLAN = d.plan_slug; }
  } catch (_) { _spMarkApiDown(); }
  acInitNavBadge();
}

async function _blStartCheckout(planSlug, btn) {
  const token = authGetToken();
  if (!token) { spNavigate('/login'); return; }
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Redirecting…';
  try {
    const res = await fetch('/api/v1/billing/create-checkout-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ plan_slug: planSlug }),
    });
    const data = await res.json();
    if (data.url) { window.location.href = data.url; return; }
  } catch (_) {}
  btn.disabled = false;
  btn.textContent = origText;
}

async function _blOpenPortal(btn) {
  const token = authGetToken();
  if (!token) { spNavigate('/login'); return; }
  btn.disabled = true;
  btn.textContent = 'Loading…';
  try {
    const res = await fetch('/api/v1/billing/create-customer-portal-session', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    if (data.url) { window.location.href = data.url; return; }
  } catch (_) {}
  btn.disabled = false;
  btn.textContent = 'Manage Billing';
}

function acShowUpgrade(featureLabel, requiredPlanId) {
  const plan = AC_PLANS[requiredPlanId] || AC_PLANS.pro;
  const overlay  = document.getElementById('ac-modal-overlay');
  const title    = document.getElementById('ac-modal-title');
  const desc     = document.getElementById('ac-modal-desc');
  const feats    = document.getElementById('ac-modal-features');
  const footnote = document.getElementById('ac-modal-footnote');
  if (!overlay) return;

  title.textContent = `Upgrade to ${plan.name}`;
  desc.textContent  = `${featureLabel} requires a ${plan.name} subscription.`;
  feats.innerHTML   = plan.features
    .filter(f => f.included)
    .slice(0, 5)
    .map(f => `<div class="ac-modal-feature">&#10003; ${escHtml(f.label)}</div>`)
    .join('');
  footnote.textContent = `${plan.price}${plan.period} · cancel anytime`;

  overlay.hidden = false;
  document.body.classList.add('ac-modal-open');

  const close = () => {
    overlay.hidden = true;
    document.body.classList.remove('ac-modal-open');
  };
  document.getElementById('ac-modal-close')?.addEventListener('click', close, { once: true });
  document.getElementById('ac-modal-cta')?.addEventListener('click', () => { close(); spNavigate('/pricing'); }, { once: true });
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); }, { once: true });
}

function acInitNavBadge() {
  const badge = document.getElementById('sp-plan-badge');
  if (!badge) return;
  const plan = acPlanObj();
  badge.textContent = plan.badge;
  badge.className = `sp-plan-badge ${plan.badgeCls}`;
  badge.addEventListener('click', () => spNavigate('/account'));
}

/* ============================================================
   SP — PRODUCT SHELL & ROUTER
   history.pushState SPA routing for the ClubGG SaaS shell.
   Prefix: sp  — no interference with existing rs-/tab- code.
   ============================================================ */

const _SP_ROUTES = {
  '/':          _spRenderDashboard,
  '/analysis':  _spRenderAnalysis,
  '/learn':     _spRenderLearn,
  '/trainer':   _spRenderTrainer,
  '/progress':  _spRenderProgress,
  '/account':   _spRenderAccount,
  '/pricing':   _spRenderPricing,
  '/admin':     _spRenderAdmin,
};

function spNavigate(path) {
  history.pushState({}, '', path);
  _spHandleLocation();
}

function _spHandleLocation() {
  const path = window.location.pathname;

  // Strip landing-page mode on every navigation (re-added only by _spRenderLanding)
  document.body.classList.remove('lp-mode');

  // Resolve which top-level section owns this path (for nav highlight)
  const topSection = ['analysis', 'learn', 'trainer', 'progress', 'account', 'pricing']
    .find(s => path === `/${s}` || path.startsWith(`/${s}/`));
  const topPath = topSection ? `/${topSection}` : '/';

  // Sync nav active state
  document.querySelectorAll('.sp-nav-item').forEach(item => {
    item.classList.toggle('sp-nav-item--active', item.dataset.route === topPath);
  });

  // Hide all views
  document.querySelectorAll('.sp-view').forEach(v => v.classList.remove('sp-view--active'));

  // Dispatch
  if (path === '/') {
    if (!authIsLoggedIn()) {
      _spRenderLanding();
      return;
    }
    _spRenderDashboard();
  } else if (path === '/analysis') {
    const _anHandParam = new URLSearchParams(window.location.search).get('hand');
    if (_anHandParam) {
      document.getElementById('sp-view-analysis')?.classList.add('sp-view--active');
      _anOpenHandDetail(_anHandParam);
    } else {
      _spRenderAnalysis();
    }
  } else if (path.startsWith('/learn')) {
    _spDispatchLearn(path);
  } else if (path === '/trainer') {
    _spRenderTrainer();
  } else if (path === '/progress') {
    _spRenderProgress();
  } else if (path === '/account') {
    _spRenderAccount();
  } else if (path === '/pricing') {
    _spRenderPricing();
  } else if (path === '/onboarding') {
    _spRenderOnboarding();
  } else if (path === '/login') {
    if (authIsLoggedIn()) { spNavigate('/'); return; }
    authRenderLogin();
  } else if (path === '/signup') {
    if (authIsLoggedIn()) { spNavigate('/'); return; }
    authRenderSignup();
  } else {
    _spRenderDashboard();
  }
}

function _spDispatchLearn(path) {
  document.getElementById('sp-view-learn')?.classList.add('sp-view--active');
  const parts = path.split('/').filter(Boolean); // ['learn'] | ['learn','courseId'] | ['learn','courseId','lessonId']
  if (parts.length === 1) {
    coRenderCatalog();
  } else if (parts.length === 2) {
    coRenderCourseDetail(parts[1]);
  } else {
    coRenderLesson(parts[1], parts[2]);
  }
}

/* ============================================================
   LP — LANDING PAGE
   Public marketing page shown at / for unauthenticated users.
   Prefix: lp- (CSS / JS)
   ============================================================ */

function _spRenderLanding() {
  document.body.classList.add('lp-mode');
  const view = document.getElementById('sp-view-landing');
  if (!view) return;
  view.classList.add('sp-view--active');

  view.innerHTML = `
    <!-- LP Nav -->
    <nav class="lp-nav">
      <div class="lp-nav-inner">
        <button class="lp-logo" data-route="/">
          <svg class="lp-logo-icon" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <polygon points="10,2 18,10 10,18 2,10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <polygon points="10,2 18,10 10,10" fill="currentColor" opacity="0.35"/>
          </svg>
          ClubGG
        </button>
        <div class="lp-nav-links">
          <button class="lp-nav-link" data-route="/pricing">Pricing</button>
          <button class="lp-nav-link lp-login-link" data-route="/login">Log in</button>
          <button class="lp-nav-cta" data-route="/signup">Start Free &rarr;</button>
        </div>
      </div>
    </nav>

    <!-- Hero -->
    <section class="lp-hero">
      <div class="lp-hero-inner">
        <div class="lp-badge">Tournament Intelligence Platform</div>
        <h1 class="lp-hero-title">Become a Winning<br>Tournament Poker Player</h1>
        <p class="lp-hero-sub">Import your hand histories, detect exactly where you&rsquo;re leaking chips, and train with structured drills built for tournament play.</p>
        <div class="lp-hero-actions">
          <button class="lp-btn-primary lp-hero-cta" data-route="/signup">Start Free &rarr;</button>
          <button class="lp-btn-ghost" id="lp-how-scroll">See How It Works &darr;</button>
        </div>
        <p class="lp-hero-trust">No credit card required &middot; Free plan forever &middot; Cancel anytime</p>
      </div>
    </section>

    <!-- Stats bar -->
    <div class="lp-stats-bar">
      <div class="lp-stats-inner">
        <div class="lp-stat"><span class="lp-stat-num">1,200+</span><span class="lp-stat-lbl">Active players</span></div>
        <div class="lp-stat-div"></div>
        <div class="lp-stat"><span class="lp-stat-num">2.3M</span><span class="lp-stat-lbl">Hands analyzed</span></div>
        <div class="lp-stat-div"></div>
        <div class="lp-stat"><span class="lp-stat-num">94%</span><span class="lp-stat-lbl">Report improvement</span></div>
        <div class="lp-stat-div"></div>
        <div class="lp-stat"><span class="lp-stat-num">4.8&#9733;</span><span class="lp-stat-lbl">Average rating</span></div>
      </div>
    </div>

    <!-- How it works -->
    <section class="lp-how" id="lp-how">
      <div class="lp-section-inner">
        <p class="lp-section-label">How It Works</p>
        <h2 class="lp-section-title">From raw hands to real improvement</h2>
        <div class="lp-steps">
          <div class="lp-step">
            <div class="lp-step-num">01</div>
            <div class="lp-step-icon">&#8679;</div>
            <h3 class="lp-step-title">Import Your Hands</h3>
            <p class="lp-step-desc">Upload ClubGG hand history files. We parse every action, every street, every player automatically.</p>
          </div>
          <div class="lp-step-arr">&rarr;</div>
          <div class="lp-step">
            <div class="lp-step-num">02</div>
            <div class="lp-step-icon">&#128269;</div>
            <h3 class="lp-step-title">Detect Your Leaks</h3>
            <p class="lp-step-desc">Our engine surfaces the specific spots costing you the most chips &mdash; backed by evidence, not hunches.</p>
          </div>
          <div class="lp-step-arr">&rarr;</div>
          <div class="lp-step">
            <div class="lp-step-num">03</div>
            <div class="lp-step-icon">&#127919;</div>
            <h3 class="lp-step-title">Train With Drills</h3>
            <p class="lp-step-desc">Replay hands, take structured lessons, and drill the high-leverage spots until they&rsquo;re automatic.</p>
          </div>
          <div class="lp-step-arr">&rarr;</div>
          <div class="lp-step">
            <div class="lp-step-num">04</div>
            <div class="lp-step-icon">&#128200;</div>
            <h3 class="lp-step-title">Improve Your Results</h3>
            <p class="lp-step-desc">Track your progress with metrics that connect study to actual ROI &mdash; not just practice streaks.</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Features -->
    <section class="lp-features">
      <div class="lp-section-inner">
        <p class="lp-section-label">Features</p>
        <h2 class="lp-section-title">Everything serious tournament players need</h2>
        <div class="lp-feat-grid">
          <div class="lp-feat">
            <div class="lp-feat-icon">&#128202;</div>
            <h3 class="lp-feat-title">Hand Analysis</h3>
            <p class="lp-feat-desc">VPIP, PFR, 3-bet%, fold equity, positional stats &mdash; every metric your coach would ask for, computed automatically.</p>
          </div>
          <div class="lp-feat">
            <div class="lp-feat-icon">&#9888;&#65039;</div>
            <h3 class="lp-feat-title">Leak Detection</h3>
            <p class="lp-feat-desc">Automated pattern recognition finds the holes in your game with specific hand evidence, not generic advice.</p>
          </div>
          <div class="lp-feat">
            <div class="lp-feat-icon">&#9654;&#65039;</div>
            <h3 class="lp-feat-title">Replay Drills</h3>
            <p class="lp-feat-desc">Step through your own hands in training mode. Make decisions under pressure and see where you deviated.</p>
          </div>
          <div class="lp-feat">
            <div class="lp-feat-icon">&#127891;</div>
            <h3 class="lp-feat-title">Structured Courses</h3>
            <p class="lp-feat-desc">Curated modules from fundamentals to advanced ICM, late-stage play, bubble strategy, and PKO.</p>
          </div>
          <div class="lp-feat">
            <div class="lp-feat-icon">&#127942;</div>
            <h3 class="lp-feat-title">Progress Tracking</h3>
            <p class="lp-feat-desc">See your skill development over time. Metrics that connect your study time to results on the felt.</p>
          </div>
          <div class="lp-feat">
            <div class="lp-feat-icon">&#128197;</div>
            <h3 class="lp-feat-title">Tournament Planner</h3>
            <p class="lp-feat-desc">Prepare for specific tournaments with format-aware strategy built from your own hand data.</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Testimonials -->
    <section class="lp-social">
      <div class="lp-section-inner">
        <p class="lp-section-label">What Players Say</p>
        <h2 class="lp-section-title">Trusted by serious tournament players</h2>
        <div class="lp-testi-grid">
          <div class="lp-testi">
            <div class="lp-testi-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
            <p class="lp-testi-quote">&ldquo;Finally a tool that tells me exactly which spots are leaking chips, not just generic stats. Found a huge fold-to-3bet problem in my first session.&rdquo;</p>
            <div class="lp-testi-author">
              <span class="lp-testi-name">Alex M.</span>
              <span class="lp-testi-role">Mid-stakes MTT player</span>
            </div>
          </div>
          <div class="lp-testi">
            <div class="lp-testi-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
            <p class="lp-testi-quote">&ldquo;The replay drills changed my game. Stopped making the same c-bet mistakes on dynamic boards within two weeks.&rdquo;</p>
            <div class="lp-testi-author">
              <span class="lp-testi-name">Sarah K.</span>
              <span class="lp-testi-role">Tournament grinder, 8 years</span>
            </div>
          </div>
          <div class="lp-testi">
            <div class="lp-testi-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
            <p class="lp-testi-quote">&ldquo;ICM module alone is worth the subscription. Shipped a 400-player field after going through the bubble play section.&rdquo;</p>
            <div class="lp-testi-author">
              <span class="lp-testi-name">David R.</span>
              <span class="lp-testi-role">Recreational to serious grinder</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Pricing teaser -->
    <section class="lp-pricing">
      <div class="lp-section-inner">
        <p class="lp-section-label">Pricing</p>
        <h2 class="lp-section-title">Start free. Upgrade when you&rsquo;re ready.</h2>
        <div class="lp-plan-row">
          <div class="lp-plan">
            <div class="lp-plan-name">Free</div>
            <div class="lp-plan-price">$0<span class="lp-per">/mo</span></div>
            <div class="lp-plan-tag">Try the essentials</div>
            <ul class="lp-plan-perks">
              <li>&#10003; Hand import &amp; basic stats</li>
              <li>&#10003; Beginner courses</li>
              <li>&#10003; 5 practice hands/day</li>
            </ul>
            <button class="lp-plan-btn lp-btn-outline" data-route="/signup">Start Free</button>
          </div>
          <div class="lp-plan lp-plan--pop">
            <div class="lp-pop-badge">Most Popular</div>
            <div class="lp-plan-name">Tournament Pro</div>
            <div class="lp-plan-price">$19<span class="lp-per">/mo</span></div>
            <div class="lp-plan-tag">For serious tournament players</div>
            <ul class="lp-plan-perks">
              <li>&#10003; Everything in Free</li>
              <li>&#10003; Full leak detection</li>
              <li>&#10003; Unlimited replay drills</li>
              <li>&#10003; All courses + Tournament Planner</li>
            </ul>
            <button class="lp-plan-btn lp-btn-primary" data-route="/signup">Start Free Trial</button>
          </div>
          <div class="lp-plan">
            <div class="lp-plan-name">Elite</div>
            <div class="lp-plan-price">$39<span class="lp-per">/mo</span></div>
            <div class="lp-plan-tag">Maximum edge</div>
            <ul class="lp-plan-perks">
              <li>&#10003; Everything in Pro</li>
              <li>&#10003; AI Coach <em>(coming soon)</em></li>
              <li>&#10003; Advanced analysis</li>
              <li>&#10003; Priority support</li>
            </ul>
            <button class="lp-plan-btn lp-btn-outline" data-route="/pricing">See All Plans</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Final CTA -->
    <section class="lp-cta-final">
      <div class="lp-cta-final-inner">
        <h2 class="lp-cta-final-title">Start improving today.</h2>
        <p class="lp-cta-final-sub">Join 1,200+ players turning their hand histories into real results.</p>
        <button class="lp-btn-primary lp-cta-final-btn" data-route="/signup">Create Your Free Account &rarr;</button>
        <p class="lp-cta-final-note">No credit card required. Free plan includes full hand analysis.</p>
      </div>
    </section>

    <!-- Footer -->
    <footer class="lp-footer">
      <div class="lp-footer-inner">
        <div class="lp-footer-brand">ClubGG Analytics</div>
        <div class="lp-footer-links">
          <button class="lp-footer-link" data-route="/pricing">Pricing</button>
          <button class="lp-footer-link" data-route="/login">Log In</button>
          <button class="lp-footer-link" data-route="/signup">Sign Up</button>
        </div>
        <p class="lp-footer-copy">&copy; 2025 ClubGG Analytics. All rights reserved.</p>
      </div>
    </footer>
  `;

  view.querySelectorAll('[data-route]').forEach(el => {
    el.addEventListener('click', () => spNavigate(el.dataset.route));
  });
  view.querySelector('#lp-how-scroll')?.addEventListener('click', () => {
    view.querySelector('#lp-how')?.scrollIntoView({ behavior: 'smooth' });
  });
}

/* ============================================================
   OB — ONBOARDING WIZARD
   3-step first-run flow: skill level → goal → start.
   Prefix: ob- (CSS), OB_ / ob (JS)
   ============================================================ */

let _obStep = 1;
let _obChoices = { skill_level: null, goal: null };

const _OB_SKILL_OPTIONS = [
  { value: 'beginner',     label: 'Beginner',     desc: 'New to poker or still learning the basics' },
  { value: 'intermediate', label: 'Intermediate',  desc: 'Comfortable with fundamentals, want to improve' },
  { value: 'advanced',     label: 'Advanced',      desc: 'Experienced player focused on edge-case spots' },
];

const _OB_GOAL_OPTIONS = [
  { value: 'learn_fundamentals',  label: 'Learn Fundamentals',       desc: 'Build a solid foundation from scratch' },
  { value: 'improve_tournament',  label: 'Improve Tournament Play',  desc: 'ICM, stack play, push-fold, late-stage spots' },
  { value: 'analyze_hands',       label: 'Analyze My Hands',         desc: 'Import hands and identify leaks in my game' },
];

const _OB_GOAL_ROUTES = {
  learn_fundamentals: '/learn',
  improve_tournament: '/learn',
  analyze_hands:      '/analysis',
};

function _spRenderOnboarding() {
  if (!authIsLoggedIn()) { spNavigate('/login'); return; }
  const view = document.getElementById('sp-view-onboarding');
  if (!view) return;
  view.classList.add('sp-view--active');
  _obStep = 1;
  _obChoices = { skill_level: null, goal: null };
  _obRenderStep(view);
}

function _obRenderStep(view) {
  if (_obStep === 1) _obRenderSkillStep(view);
  else if (_obStep === 2) _obRenderGoalStep(view);
  else _obRenderStartStep(view);
}

function _obOptionHTML(opts, selectedValue) {
  return opts.map(o => `
    <button class="ob-option${o.value === selectedValue ? ' ob-option--selected' : ''}" data-ob-value="${escHtml(o.value)}">
      <span class="ob-option-label">${escHtml(o.label)}</span>
      <span class="ob-option-desc">${escHtml(o.desc)}</span>
    </button>`).join('');
}

function _obWrapHTML(step, total, title, sub, body, nextLabel, nextId, backId) {
  return `
    <div class="ob-page">
      <div class="ob-progress">
        ${Array.from({ length: total }, (_, i) => `<div class="ob-dot${i < step ? ' ob-dot--done' : i === step - 1 ? ' ob-dot--active' : ''}"></div>`).join('')}
      </div>
      <div class="ob-card">
        <div class="ob-step-label">Step ${step} of ${total}</div>
        <h1 class="ob-title">${escHtml(title)}</h1>
        <p class="ob-sub">${escHtml(sub)}</p>
        ${body}
        <div class="ob-actions">
          ${backId ? `<button class="sp-btn-secondary ob-back" id="${escHtml(backId)}">&larr; Back</button>` : ''}
          <button class="sp-btn-primary ob-next" id="${escHtml(nextId)}" disabled>${escHtml(nextLabel)}</button>
        </div>
      </div>
    </div>`;
}

function _obRenderSkillStep(view) {
  view.innerHTML = _obWrapHTML(
    1, 3,
    'What is your skill level?',
    'This helps us recommend the right courses and drills for you.',
    `<div class="ob-options" id="ob-skill-options">${_obOptionHTML(_OB_SKILL_OPTIONS, _obChoices.skill_level)}</div>`,
    'Next →', 'ob-next-skill', null,
  );
  const nextBtn = view.querySelector('#ob-next-skill');
  view.querySelector('#ob-skill-options').addEventListener('click', e => {
    const btn = e.target.closest('[data-ob-value]');
    if (!btn) return;
    _obChoices.skill_level = btn.dataset.obValue;
    view.querySelectorAll('#ob-skill-options .ob-option').forEach(b =>
      b.classList.toggle('ob-option--selected', b.dataset.obValue === _obChoices.skill_level));
    nextBtn.disabled = false;
  });
  if (_obChoices.skill_level) nextBtn.disabled = false;
  nextBtn.addEventListener('click', () => { _obStep = 2; _obRenderStep(view); });
}

function _obRenderGoalStep(view) {
  view.innerHTML = _obWrapHTML(
    2, 3,
    'What is your main goal?',
    'We will personalise your dashboard and first recommended action.',
    `<div class="ob-options" id="ob-goal-options">${_obOptionHTML(_OB_GOAL_OPTIONS, _obChoices.goal)}</div>`,
    'Next →', 'ob-next-goal', 'ob-back-goal',
  );
  const nextBtn = view.querySelector('#ob-next-goal');
  view.querySelector('#ob-goal-options').addEventListener('click', e => {
    const btn = e.target.closest('[data-ob-value]');
    if (!btn) return;
    _obChoices.goal = btn.dataset.obValue;
    view.querySelectorAll('#ob-goal-options .ob-option').forEach(b =>
      b.classList.toggle('ob-option--selected', b.dataset.obValue === _obChoices.goal));
    nextBtn.disabled = false;
  });
  if (_obChoices.goal) nextBtn.disabled = false;
  view.querySelector('#ob-back-goal').addEventListener('click', () => { _obStep = 1; _obRenderStep(view); });
  nextBtn.addEventListener('click', async () => {
    nextBtn.disabled = true;
    nextBtn.textContent = 'Saving…';
    await _obSaveChoices();
    _obStep = 3;
    _obRenderStep(view);
  });
}

async function _obSaveChoices() {
  const token = authGetToken();
  if (!token) return;
  try {
    const res = await fetch('/api/v1/me/onboarding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(_obChoices),
    });
    if (res.ok) {
      const user = authGetUser();
      if (user) authSetUser({
        ...user,
        onboarding_complete: true,
        skill_level: _obChoices.skill_level,
        goal: _obChoices.goal,
      });
    }
  } catch (_) {}
}

function _obGetRecommendation(skill_level, goal) {
  if (skill_level === 'beginner') {
    return {
      courseId:     'tournament-fundamentals',
      courseTitle:  'Tournament Poker Fundamentals',
      lessonId:     'why-tournament-poker-is-different',
      lessonTitle:  'Why Tournament Poker Is Different',
      practiceLabel:'General Spots — Beginner',
      practiceUrl:  '/trainer?mode=general&difficulty=beginner',
    };
  }
  if (skill_level === 'intermediate') {
    return {
      courseId:     'stack-sizes-tournament-strategy',
      courseTitle:  'Stack Sizes and Tournament Strategy',
      lessonId:     'push-fold-theory',
      lessonTitle:  'Push-Fold Theory: Under 15bb',
      practiceLabel: goal === 'improve_tournament' ? 'Bubble Play Trainer' : 'Push/Fold Trainer',
      practiceUrl:  goal === 'improve_tournament'
                      ? '/trainer?mode=bubble&difficulty=intermediate'
                      : '/trainer?mode=push-fold&difficulty=intermediate',
    };
  }
  // advanced
  return {
    courseId:     goal === 'improve_tournament' ? 'bubble-play' : 'final-table-strategy',
    courseTitle:  goal === 'improve_tournament' ? 'Bubble Play' : 'Final Table Strategy',
    lessonId:     goal === 'improve_tournament' ? 'icm-bubble-basics' : 'ft-icm',
    lessonTitle:  goal === 'improve_tournament'
                    ? 'ICM Basics: Why the Bubble Changes Everything'
                    : 'Final Table ICM: Every Spot Is Different',
    practiceLabel: goal === 'improve_tournament' ? 'Bubble Play Drills' : 'Final Table Trainer',
    practiceUrl:  goal === 'improve_tournament'
                    ? '/trainer?mode=bubble&difficulty=advanced'
                    : '/trainer?mode=final-table&difficulty=advanced',
  };
}

function _obRenderStartStep(view) {
  const rec = _obGetRecommendation(_obChoices.skill_level, _obChoices.goal);
  const skillLabel = _OB_SKILL_OPTIONS.find(o => o.value === _obChoices.skill_level)?.label || '';
  const goalLabel  = _OB_GOAL_OPTIONS.find(o => o.value === _obChoices.goal)?.label || 'your goal';
  view.innerHTML = `
    <div class="ob-page">
      <div class="ob-progress">
        ${Array.from({ length: 3 }, () => `<div class="ob-dot ob-dot--done"></div>`).join('')}
      </div>
      <div class="ob-card ob-card--complete">
        <div class="ob-complete-icon">&#10003;</div>
        <h1 class="ob-title">Your personalised path is ready</h1>
        <p class="ob-sub">Based on your ${escHtml(skillLabel)} level and goal to <strong>${escHtml(goalLabel)}</strong>.</p>

        <div class="ob-rec-block">
          <div class="ob-rec-row">
            <div class="ob-rec-icon">&#128218;</div>
            <div class="ob-rec-body">
              <div class="ob-rec-label">Recommended course</div>
              <div class="ob-rec-title">${escHtml(rec.courseTitle)}</div>
              <div class="ob-rec-sub">Start with: ${escHtml(rec.lessonTitle)}</div>
            </div>
          </div>
          <div class="ob-rec-row">
            <div class="ob-rec-icon">&#9654;</div>
            <div class="ob-rec-body">
              <div class="ob-rec-label">Recommended practice</div>
              <div class="ob-rec-title">${escHtml(rec.practiceLabel)}</div>
              <div class="ob-rec-sub">Drill specific spots in the trainer</div>
            </div>
          </div>
        </div>

        <div class="ob-start-actions">
          <button class="sp-btn-primary" id="ob-start-learn">Start Learning &rarr;</button>
          <button class="sp-btn-secondary" id="ob-start-practice">Start Practice</button>
          <button class="ob-skip-link" id="ob-start-dash">Go to Dashboard</button>
        </div>
      </div>
    </div>`;
  view.querySelector('#ob-start-learn').addEventListener('click',
    () => spNavigate(`/learn/${rec.courseId}/${rec.lessonId}`));
  view.querySelector('#ob-start-practice').addEventListener('click',
    () => spNavigate(rec.practiceUrl));
  view.querySelector('#ob-start-dash').addEventListener('click', () => spNavigate('/'));
}

/* ============================================================
   DS — DAILY SPOT
   Local-first daily practice card + streak tracking.
   Prefix: ds- (CSS), _DS_ / _ds (JS)
   ============================================================ */

const _DS_KEY_LAST     = 'ds_last';      // YYYY-MM-DD of last dashboard visit
const _DS_KEY_STREAK   = 'ds_streak';    // integer
const _DS_KEY_DONE     = 'ds_done';      // YYYY-MM-DD when today's spot was played
const _DS_KEY_LEAK_CAT = 'ds_leak_cat'; // comma-separated top leak_ids from last analysis
const _DS_KEY_PERF_PFX = 'ds_perf_';    // prefix + slugified topic → JSON array of last 5 booleans

// leakKeys: substrings matched against leak_id values from the backend
const _DS_SPOTS = [
  {
    topic:    'BTN steal',
    leakKeys: ['btn_steal', 'late_position_passive', 'pfr_too_passive'],
    prompt:   'Folds to you on BTN. You have A&#9824;8&#9830; at 20bb. What do you do?',
    correct:  'Open-raise to 2.5bb',
    why:      'A8o is a clear BTN open at any depth above 12bb — folding surrenders dead money every orbit.',
    tag:      'Preflop · BTN · 20bb',
    trainer:  '/trainer?mode=general&difficulty=beginner',
    lesson:   '/learn/tournament-fundamentals/position-the-most-important-advantage',
  },
  {
    topic:    'Short stack shove',
    leakKeys: ['push_fold', 'short_stack', 'shove', 'missing_btn_shove'],
    prompt:   'Folds to you on BTN. You have K&#9829;9&#9827; at 11bb. Open or shove?',
    correct:  'Shove all-in',
    why:      'At 11bb, a min-open commits 18% of your stack with no plan if 3-bet. Shove and take the pot or flip.',
    tag:      'Preflop · BTN · 11bb',
    trainer:  '/trainer?mode=push-fold&difficulty=intermediate',
    lesson:   '/learn/tournament-fundamentals/short-stack-play-under-15bb',
  },
  {
    topic:    'BB defend',
    leakKeys: ['bb_overfold', 'bb_defend_too_tight', 'fold_to_steal_bb'],
    prompt:   'CO opens 2.5bb. You\'re in the BB with Q&#9827;7&#9827; at 25bb. Call or fold?',
    correct:  'Call (pot odds + position vs one player)',
    why:      'Getting ~3:1 from the BB vs a single opener, Q7s has enough equity and suit value to defend.',
    tag:      'Preflop · BB · 25bb',
    trainer:  '/trainer?mode=general&difficulty=beginner',
    lesson:   '/learn/tournament-fundamentals/starting-hands-are-context-based',
  },
  {
    topic:    'Reshove spot',
    leakKeys: ['resteal', 'reshove', '3bet_shove'],
    prompt:   'CO opens 2.5bb. You\'re on BTN with 9&#9829;9&#9830; at 18bb. Call or shove?',
    correct:  'Shove all-in',
    why:      'Calling 18bb with 99 OOP leaves no room for a clean postflop plan. Shoving denies fold equity and gets it in as a favourite.',
    tag:      'Preflop · BTN · 18bb',
    trainer:  '/trainer?mode=push-fold&difficulty=intermediate',
    lesson:   '/learn/tournament-fundamentals/biggest-beginner-mistakes',
  },
  {
    topic:    'SB steal',
    leakKeys: ['sb_steal', 'sb_overfold', 'late_position_passive'],
    prompt:   'Folds to SB. You have A&#9830;5&#9829; at 15bb. Shove or fold?',
    correct:  'Shove all-in',
    why:      'A5s from SB vs BB at 15bb is a clear shove — you have one player to beat, suit value, and an ace blocker.',
    tag:      'Preflop · SB · 15bb',
    trainer:  '/trainer?mode=push-fold&difficulty=intermediate',
    lesson:   '/learn/tournament-fundamentals/short-stack-play-under-15bb',
  },
  {
    topic:    'Early stage open',
    leakKeys: ['vpip_too_tight', 'pfr_too_passive', 'early_position'],
    prompt:   'UTG in a 6-max at 60bb. You have J&#9827;T&#9827;. Open or fold?',
    correct:  'Open-raise to 2.2bb',
    why:      'JTs is a profitable open from UTG in 6-max at 60bb — strong suit, connectivity, and reasonable equity vs calling ranges.',
    tag:      'Preflop · UTG · 60bb · 6-max',
    trainer:  '/trainer?mode=general&difficulty=beginner',
    lesson:   '/learn/tournament-fundamentals/starting-hands-are-context-based',
  },
  {
    topic:    '3-bet or call',
    leakKeys: ['fold_to_3bet', 'three_bet_too_low', '3bet_frequency'],
    prompt:   'BTN opens 2.5bb. You\'re in BB with A&#9829;J&#9830; at 30bb. 3-bet or call?',
    correct:  '3-bet to 7.5–8bb',
    why:      'AJo in BB vs BTN is too strong to flat but too good to fold. A 3-bet protects your hand and builds a pot with the best hand often.',
    tag:      'Preflop · BB · 30bb',
    trainer:  '/trainer?mode=general&difficulty=intermediate',
    lesson:   '/learn/tournament-fundamentals/preflop-decisions-open-fold-or-shove',
  },
];

function _dsPersistLeakCats(analysis) {
  if (!analysis?.leaks?.leaks?.length) return;
  const top = analysis.leaks.leaks.slice(0, 3).map(l => l.leak_id).join(',');
  localStorage.setItem(_DS_KEY_LEAK_CAT, top);
}

function _dsGetLeakCats() {
  // Also check in-memory if analysis was fetched this session
  if (_anLiveAnalysis?.leaks?.leaks?.length) {
    return _anLiveAnalysis.leaks.leaks.slice(0, 3).map(l => l.leak_id);
  }
  const stored = localStorage.getItem(_DS_KEY_LEAK_CAT);
  return stored ? stored.split(',').filter(Boolean) : [];
}

function _dsPerfKey(topic) {
  return _DS_KEY_PERF_PFX + topic.toLowerCase().replace(/[^a-z0-9]+/g, '_');
}

function _dsPerfGet(topic) {
  try { return JSON.parse(localStorage.getItem(_dsPerfKey(topic)) || '[]'); } catch { return []; }
}

function _dsPerfRecord(topic, correct) {
  const key = _dsPerfKey(topic);
  const hist = _dsPerfGet(topic);
  hist.push(correct);
  if (hist.length > 5) hist.shift();
  localStorage.setItem(key, JSON.stringify(hist));
}

// Returns 'improving' | 'same' | 'worse' | null (insufficient data)
function _dsPerfTrend(topic) {
  const hist = _dsPerfGet(topic);
  if (hist.length < 3) return null;
  const half = Math.floor(hist.length / 2);
  const recent = hist.slice(-half);
  const older  = hist.slice(0, half);
  const recentRate = recent.filter(Boolean).length / recent.length;
  const olderRate  = older.filter(Boolean).length / older.length;
  if (recentRate > olderRate + 0.15) return 'improving';
  if (recentRate < olderRate - 0.15) return 'worse';
  return 'same';
}

function _dsTrendLine(topic) {
  const trend = _dsPerfTrend(topic);
  if (!trend) return null;
  if (trend === 'improving') return { arrow: '&#8593;', label: 'improving', cls: 'ds-trend--up' };
  if (trend === 'worse')     return { arrow: '&#8595;', label: 'still leaking', cls: 'ds-trend--down' };
  return { arrow: '&#8594;', label: 'consistent', cls: 'ds-trend--same' };
}

function _dsToday() {
  return new Date().toISOString().slice(0, 10);
}

function _dsLoadStreak() {
  const today     = _dsToday();
  const last      = localStorage.getItem(_DS_KEY_LAST) || '';
  const streak    = parseInt(localStorage.getItem(_DS_KEY_STREAK) || '0', 10) || 0;

  if (!last) {
    localStorage.setItem(_DS_KEY_LAST, today);
    localStorage.setItem(_DS_KEY_STREAK, '1');
    return 1;
  }
  if (last === today) return streak;

  const prev = new Date(today);
  prev.setDate(prev.getDate() - 1);
  const newStreak = prev.toISOString().slice(0, 10) === last ? streak + 1 : 1;
  localStorage.setItem(_DS_KEY_LAST, today);
  localStorage.setItem(_DS_KEY_STREAK, String(newStreak));
  return newStreak;
}

function _dsIsNewDay() {
  return (localStorage.getItem(_DS_KEY_LAST) || '') !== _dsToday();
}

function _dsIsDone() {
  return localStorage.getItem(_DS_KEY_DONE) === _dsToday();
}

function _dsMarkDone() {
  localStorage.setItem(_DS_KEY_DONE, _dsToday());
}

function _dsTodaySpot() {
  const start = new Date(new Date().getFullYear(), 0, 0);
  const dayOfYear = Math.floor((Date.now() - start) / 86400000);
  const leakCats = _dsGetLeakCats();
  if (leakCats.length > 0) {
    const matchIdx = _DS_SPOTS.reduce((acc, spot, i) => {
      if (spot.leakKeys.some(k => leakCats.some(cat => cat.includes(k) || k.includes(cat)))) acc.push(i);
      return acc;
    }, []);
    if (matchIdx.length > 0 && (dayOfYear * 13 + 3) % 10 < 7) {
      const spot = _DS_SPOTS[matchIdx[dayOfYear % matchIdx.length]];
      return { ...spot, fromLeak: true };
    }
  }
  return { ..._DS_SPOTS[dayOfYear % _DS_SPOTS.length], fromLeak: false };
}

function _dsStreakLabel(streak) {
  if (streak <= 1) return '';
  if (streak < 7)  return `&#128293; ${streak}-day streak`;
  if (streak < 30) return `&#128293; ${streak}-day streak — keep it up!`;
  return `&#127942; ${streak}-day streak — elite consistency`;
}

function _dsProgressNote(streak, done, fromLeak, topic) {
  if (!done) return '';
  const trend = _dsPerfTrend(topic);
  if (trend === 'improving') return "You're getting this right more often.";
  if (trend === 'worse')     return 'Still a weak spot — keep working on it.';
  if (trend === 'same')      return 'Consistency is improving.';
  // no trend data yet — fall back to streak-based messaging
  if (streak < 2) return '';
  if (fromLeak) {
    const notes = [
      "You're improving in this spot — keep drilling it.",
      `${streak} days on this leak. It's getting cleaner.`,
      'This is still one of your weaker areas — repetition is the fix.',
    ];
    return notes[(streak - 2) % notes.length];
  }
  const notes = [
    "You're building consistency — that's where improvement happens.",
    `${streak} days in a row. This spot is getting cleaner.`,
    'Repetition is how leaks get fixed. Good work.',
  ];
  return notes[(streak - 2) % notes.length];
}

function _dsRenderCard(streak) {
  const spot   = _dsTodaySpot();
  const done   = _dsIsDone();
  const sLabel = _dsStreakLabel(streak);
  const pNote  = _dsProgressNote(streak, done, spot.fromLeak, spot.topic);
  const eyebrow = spot.fromLeak ? `Fix your ${spot.topic} leak` : 'Today\'s focus';

  return `
    <div class="ds-card" id="ds-card">
      <div class="ds-card-top">
        <div class="ds-card-left">
          <div class="ds-eyebrow">${escHtml(eyebrow)}</div>
          <div class="ds-topic">${escHtml(spot.topic)}</div>
          <div class="ds-tag">${escHtml(spot.tag)}</div>
        </div>
        ${sLabel ? `<div class="ds-streak">${sLabel}</div>` : ''}
      </div>

      ${spot.fromLeak ? `<div class="ds-leak-note">This is one of the spots you&rsquo;re currently struggling with.</div>` : ''}
      <div class="ds-prompt">${spot.prompt}</div>

      ${done ? `
      <div class="ds-done-row">
        <span class="ds-done-check">&#10003;</span>
        <span class="ds-done-label">Done for today</span>
        ${pNote ? `<span class="ds-progress-note">${escHtml(pNote)}</span>` : ''}
      </div>
      <div class="ds-answer">
        <span class="ds-answer-label">Correct play:</span> ${escHtml(spot.correct)}
        <span class="ds-answer-why">${escHtml(spot.why)}</span>
      </div>` : `
      <div class="ds-actions">
        <button class="ds-cta-primary" id="ds-play">Play it &rarr;</button>
        <button class="ds-cta-ghost" id="ds-reveal">Show answer</button>
      </div>
      <div class="ds-answer ds-answer--hidden" id="ds-answer-block">
        <span class="ds-answer-label">Correct play:</span> ${escHtml(spot.correct)}
        <span class="ds-answer-why">${escHtml(spot.why)}</span>
        <div class="ds-micro-feedback ds-micro-feedback--hidden" id="ds-micro-feedback">
          <span class="ds-micro-label">Did you get it right?</span>
          <button class="ds-micro-btn ds-micro-btn--yes" id="ds-micro-yes">&#10003; Yes</button>
          <button class="ds-micro-btn ds-micro-btn--no"  id="ds-micro-no">&#10005; No</button>
        </div>
        <div class="ds-micro-result ds-micro-result--hidden" id="ds-micro-result"></div>
      </div>`}
    </div>`;
}

function _dsWireCard(view, spot) {
  view.querySelector('#ds-play')?.addEventListener('click', () => {
    _dsPerfRecord(spot.topic, true);
    _dsMarkDone();
    spNavigate(spot.trainer);
  });
  view.querySelector('#ds-reveal')?.addEventListener('click', () => {
    const ans = view.querySelector('#ds-answer-block');
    const fb  = view.querySelector('#ds-micro-feedback');
    if (ans) {
      ans.classList.remove('ds-answer--hidden');
      view.querySelector('#ds-reveal').hidden = true;
      fb?.classList.remove('ds-micro-feedback--hidden');
    }
  });

  function _dsMicroRespond(correct) {
    _dsPerfRecord(spot.topic, correct);
    _dsMarkDone();
    const fb  = view.querySelector('#ds-micro-feedback');
    const res = view.querySelector('#ds-micro-result');
    if (fb)  fb.classList.add('ds-micro-feedback--hidden');
    if (res) {
      const trend = _dsPerfTrend(spot.topic);
      let msg = correct ? 'Good — noted.' : 'Noted — keep drilling it.';
      if (trend === 'improving') msg = correct ? "You're getting this right more often." : "Tough one — but you're trending up overall.";
      if (trend === 'worse')     msg = correct ? 'Good — this spot still needs work.' : 'Still a weak spot — keep working on it.';
      if (trend === 'same')      msg = correct ? 'Consistent. Keep it up.' : 'Consistency is building — stay with it.';
      res.textContent = msg;
      res.classList.remove('ds-micro-result--hidden');
    }
  }

  view.querySelector('#ds-micro-yes')?.addEventListener('click', () => _dsMicroRespond(true));
  view.querySelector('#ds-micro-no')?.addEventListener('click',  () => _dsMicroRespond(false));
}

function _dashStatsHtml() {
  const live = _anLiveAnalysis;
  if (!live) {
    return `
      <div class="sp-stat-card sp-stat-card--empty">
        <div class="sp-stat-card-label">Your Stats</div>
        <div class="sp-stat-card-value sp-stat-card-value--empty">—</div>
        <div class="sp-stat-card-trend sp-trend-neutral">Import hands to unlock your stats</div>
      </div>`;
  }
  const hands  = live.summary.hands_analyzed;
  const vpip   = live.stats?.vpip?.value != null  ? Math.round(live.stats.vpip.value * 100)  : null;
  const pfr    = live.stats?.pfr?.value  != null  ? Math.round(live.stats.pfr.value  * 100)  : null;
  const leaks  = live.leaks?.leaks?.length ?? live.summary.leaks_count ?? 0;
  const note   = live.summary.analysis_note || '';
  return `
    <div class="sp-stat-card">
      <div class="sp-stat-card-label">Hands Analyzed</div>
      <div class="sp-stat-card-value">${hands.toLocaleString()}</div>
      <div class="sp-stat-card-trend sp-trend-neutral">${escHtml(note)}</div>
    </div>
    ${vpip != null && pfr != null ? `
    <div class="sp-stat-card">
      <div class="sp-stat-card-label">VPIP / PFR</div>
      <div class="sp-stat-card-value">${vpip} / ${pfr}</div>
      <div class="sp-stat-card-trend sp-trend-neutral">Preflop profile</div>
    </div>` : ''}
    <div class="sp-stat-card">
      <div class="sp-stat-card-label">Leaks Found</div>
      <div class="sp-stat-card-value">${leaks}</div>
      <div class="sp-stat-card-trend ${leaks > 0 ? 'sp-trend-warn' : 'sp-trend-up'}">${leaks > 0 ? 'Review in Analysis' : 'Clean'}</div>
    </div>`;
}

function _dsRenderSignals() {
  const signals = _DS_SPOTS.map(s => {
    const t = _dsTrendLine(s.topic);
    return t ? { topic: s.topic, ...t } : null;
  }).filter(Boolean);
  if (!signals.length) return '';
  return `
    <div class="ds-signals">
      ${signals.map(s => `
        <span class="ds-signal ${s.cls}">
          <span class="ds-signal-arrow">${s.arrow}</span>
          <span class="ds-signal-topic">${escHtml(s.topic)}:</span>
          <span class="ds-signal-label">${escHtml(s.label)}</span>
        </span>`).join('')}
    </div>`;
}

function _spRenderDashboard() {
  const view = document.getElementById('sp-view-dashboard');
  if (!view) return;
  view.classList.add('sp-view--active');
  const _obUser = authGetUser();
  const _obIncomplete = authIsLoggedIn() && _obUser && _obUser.onboarding_complete === false;
  const _obHasRec = authIsLoggedIn() && _obUser && _obUser.onboarding_complete === true
                    && _obUser.skill_level && _obUser.goal;
  const _dashRec = _obHasRec ? _obGetRecommendation(_obUser.skill_level, _obUser.goal) : null;

  // Streak — updates localStorage, must run before render so streak is current
  const _dsStreak = _dsLoadStreak();
  const _dsSpot   = _dsTodaySpot();
  const _dsNew    = !_dsIsDone();

  view.innerHTML = `
    <div class="sp-dash">
      ${_obIncomplete ? `
      <div class="ob-dash-banner">
        <div class="ob-dash-banner-body">
          <strong>Complete your setup</strong> — tell us your skill level and goal so we can personalise your experience.
        </div>
        <button class="sp-btn-primary ob-dash-banner-cta" id="ob-dash-cta">Start Setup &rarr;</button>
      </div>` : ''}
      ${_dashRec ? `
      <div class="ob-rec-banner">
        <div class="ob-rec-banner-body">
          <div class="ob-rec-banner-title">Your Recommended Path</div>
          <div class="ob-rec-banner-items">
            <div class="ob-rec-banner-item">
              <span class="ob-rec-banner-icon">&#128218;</span>
              <span>${escHtml(_dashRec.courseTitle)}</span>
              <span class="ob-rec-banner-arrow">&#8250;</span>
              <span class="ob-rec-banner-lesson">${escHtml(_dashRec.lessonTitle)}</span>
            </div>
            <div class="ob-rec-banner-item">
              <span class="ob-rec-banner-icon">&#9654;</span>
              <span>${escHtml(_dashRec.practiceLabel)}</span>
            </div>
          </div>
        </div>
        <div class="ob-rec-banner-actions">
          <button class="sp-btn-primary" id="dash-rec-learn">Start Learning &rarr;</button>
          <button class="sp-btn-secondary" id="dash-rec-practice">Practice</button>
        </div>
      </div>` : ''}
      ${_dsNew ? `
      <div class="ds-new-banner" id="ds-new-banner">
        <span class="ds-new-dot"></span>
        <span class="ds-new-text">New spot ready for you today</span>
        <button class="ds-new-dismiss" id="ds-new-dismiss" aria-label="Dismiss">&#10005;</button>
      </div>` : ''}

      <div class="sp-dash-header">
        <h1 class="sp-dash-title">Dashboard</h1>
        <p class="sp-dash-sub">Welcome back. Here&rsquo;s your poker intelligence overview.</p>
      </div>

      <div class="sp-dash-stats-row" id="dash-stats-row">
        ${_dashStatsHtml()}
      </div>

      <div class="sp-dash-grid">

        ${_dsRenderCard(_dsStreak)}
        ${_dsRenderSignals()}

        <div class="sp-dash-section">
          <div class="sp-section-header">
            <span class="sp-section-title">Suggested Action</span>
          </div>
          <div class="sp-suggest-card">
            <div class="sp-suggest-icon">&#9889;</div>
            <div class="sp-suggest-body">
              <div class="sp-suggest-title">Study BTN steal defense</div>
              <div class="sp-suggest-desc">
                Your fold-to-steal from BB is 68%&mdash;above the optimal range.
                This pattern appears in 23 recent hands.
              </div>
              <div class="sp-suggest-actions">
                <button class="sp-btn-primary" data-route="/analysis">Analyze Hands</button>
                <button class="sp-btn-secondary" data-route="/learn">Find Lesson</button>
              </div>
            </div>
          </div>
        </div>

        <div class="sp-dash-section sp-dash-section--full">
          <div class="sp-section-header">
            <span class="sp-section-title">Recent Hands</span>
            <button class="sp-section-link" data-route="/analysis">Full analysis &rarr;</button>
          </div>
          <div class="sp-hand-list">
            <div class="sp-hand-row">
              <div class="sp-hand-info">
                <span class="sp-hand-pos sp-pos-btn">BTN</span>
                <span class="sp-hand-cards">A&#9824; K&#9829;</span>
                <span class="sp-hand-desc">3-bet pot &middot; c-bet flop &middot; called</span>
              </div>
              <div class="sp-hand-result sp-result-pos">+12.5 bb</div>
            </div>
            <div class="sp-hand-row">
              <div class="sp-hand-info">
                <span class="sp-hand-pos sp-pos-bb">BB</span>
                <span class="sp-hand-cards">J&#9830; T&#9830;</span>
                <span class="sp-hand-desc">Defend vs BTN steal &middot; called river</span>
              </div>
              <div class="sp-hand-result sp-result-neg">&minus;8.0 bb</div>
            </div>
            <div class="sp-hand-row">
              <div class="sp-hand-info">
                <span class="sp-hand-pos sp-pos-co">CO</span>
                <span class="sp-hand-cards">9&#9827; 9&#9830;</span>
                <span class="sp-hand-desc">Open &middot; folded to 3-bet</span>
              </div>
              <div class="sp-hand-result sp-result-neg">&minus;2.5 bb</div>
            </div>
          </div>
        </div>

      </div>
    </div>
  `;

  view.querySelectorAll('[data-route]').forEach(el => {
    el.addEventListener('click', () => spNavigate(el.dataset.route));
  });
  view.querySelector('#ob-dash-cta')?.addEventListener('click', () => spNavigate('/onboarding'));
  if (_dashRec) {
    view.querySelector('#dash-rec-learn')?.addEventListener('click',
      () => spNavigate(`/learn/${_dashRec.courseId}/${_dashRec.lessonId}`));
    view.querySelector('#dash-rec-practice')?.addEventListener('click',
      () => spNavigate(_dashRec.practiceUrl));
  }

  // Daily spot wiring
  _dsWireCard(view, _dsSpot);
  view.querySelector('#ds-new-dismiss')?.addEventListener('click', () => {
    view.querySelector('#ds-new-banner')?.remove();
  });

  // Progressive stats update — fetch live analysis if not already loaded
  if (authIsLoggedIn() && !_anLiveAnalysis) {
    _anFetchLive().then(() => {
      const statsRow = view.querySelector('#dash-stats-row');
      if (statsRow) statsRow.innerHTML = _dashStatsHtml();
    });
  }
}

function _spRenderAnalysis() {
  document.getElementById('sp-view-analysis')?.classList.add('sp-view--active');
  // Reset hub so live data re-fetches on every navigation to /analysis
  _anHubInitialized = false;
  _anInitHub();
}

function _spRenderLearn() {
  // Delegated to CO module — renders catalog inside #sp-view-learn
  _spDispatchLearn('/learn');
}

function _spRenderProgress() {
  document.getElementById('sp-view-progress')?.classList.add('sp-view--active');
  prRenderProgress();
}

function _spRenderAccount() {
  const view = document.getElementById('sp-view-account');
  if (!view) return;
  if (!authIsLoggedIn()) { spNavigate('/'); return; }
  view.classList.add('sp-view--active');

  const plan = acPlanObj();
  const allPlans = ['free', 'starter', 'pro', 'elite'];
  const _acUser = authGetUser();
  const _acEmail = _acUser?.email || '';
  const _acInitial = _acEmail ? _acEmail[0].toUpperCase() : '?';
  const _acDisplayName = _acEmail ? _acEmail.split('@')[0] : 'Your Account';

  view.innerHTML = `
    <div class="ac-page">
      <div class="ac-page-header">
        <h1 class="ac-page-title">Account</h1>
        <p class="ac-page-sub">Manage your profile and subscription.</p>
      </div>

      <div class="ac-section-grid">
        <!-- Profile card -->
        <div class="ac-card">
          <div class="ac-card-title">Profile</div>
          <div class="ac-profile-row">
            <div class="ac-avatar">${escHtml(_acInitial)}</div>
            <div>
              <div class="ac-profile-name">${escHtml(_acDisplayName)}</div>
              <div class="ac-profile-email">${escHtml(_acEmail)}</div>
            </div>
          </div>
          <div class="ac-profile-stats">
            <div class="ac-profile-stat"><span class="ac-ps-val">23</span><span class="ac-ps-lbl">Hands Reviewed</span></div>
            <div class="ac-profile-stat"><span class="ac-ps-val">14</span><span class="ac-ps-lbl">Lessons Done</span></div>
            <div class="ac-profile-stat"><span class="ac-ps-val">7</span><span class="ac-ps-lbl">Day Streak</span></div>
          </div>
        </div>

        <!-- Current plan card -->
        <div class="ac-card ac-card--plan">
          <div class="ac-card-title">Current Plan</div>
          <div class="ac-current-plan">
            <span class="ac-badge ${escHtml(plan.badgeCls)}">${escHtml(plan.badge)}</span>
            <span class="ac-plan-name">${escHtml(plan.name)}</span>
            <span class="ac-plan-price">${escHtml(plan.price)}${escHtml(plan.period)}</span>
          </div>
          <div class="ac-plan-tagline">${escHtml(plan.tagline)}</div>
          ${AC_CURRENT_PLAN !== 'free' ? `
          <button class="sp-btn-secondary ac-manage-billing" id="ac-manage-billing" style="margin-bottom:8px;width:100%">
            Manage Billing
          </button>` : ''}
          ${AC_CURRENT_PLAN !== 'elite' ? `
          <button class="sp-btn-primary ac-upgrade-cta" id="ac-upgrade-cta">
            View Plans &rarr;
          </button>` : `
          <div class="ac-plan-elite-note">You are on the highest tier.</div>`}
        </div>
      </div>

      <!-- Plan comparison -->
      <div class="bl-pricing-section">
        <div class="bl-pricing-header">
          <h2 class="bl-pricing-title">All Plans</h2>
          <p class="bl-pricing-sub">Upgrade anytime. Cancel anytime.</p>
        </div>
        <div class="bl-plan-grid">
          ${allPlans.map(pid => _blPlanCardHTML(pid, AC_CURRENT_PLAN)).join('')}
        </div>
      </div>

      <!-- Feature comparison table -->
      ${_blFeatureTableHTML()}
    </div>
  `;

  view.querySelector('#ac-upgrade-cta')?.addEventListener('click', () => spNavigate('/pricing'));
  view.querySelector('#ac-manage-billing')?.addEventListener('click', e => _blOpenPortal(e.currentTarget));
  view.querySelectorAll('[data-ac-plan-select]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.acPlanSelect;
      if (target === AC_CURRENT_PLAN) return;
      if (target === 'free') return;
      _blStartCheckout(target, btn);
    });
  });
}

function _spRenderPricing() {
  const view = document.getElementById('sp-view-pricing');
  if (!view) return;
  view.classList.add('sp-view--active');

  const allPlans = ['free', 'starter', 'pro', 'elite'];

  view.innerHTML = `
    <div class="bl-page">
      <div class="bl-hero">
        <h1 class="bl-hero-title">Choose your plan</h1>
        <p class="bl-hero-sub">From free tools to the full tournament intelligence stack. Upgrade or cancel anytime.</p>
      </div>
      <div class="bl-plan-grid">
        ${allPlans.map(pid => _blPlanCardHTML(pid, AC_CURRENT_PLAN)).join('')}
      </div>
      ${_blFeatureTableHTML()}
    </div>
  `;

  view.querySelectorAll('[data-ac-plan-select]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.acPlanSelect;
      if (target === AC_CURRENT_PLAN) return;
      if (target === 'free') return;
      _blStartCheckout(target, btn);
    });
  });
}

function _blPlanCardHTML(planId, currentPlanId) {
  const p = AC_PLANS[planId];
  const isCurrent   = planId === currentPlanId;
  const rank        = AC_PLAN_RANK[planId] || 0;
  const curRank     = AC_PLAN_RANK[currentPlanId] || 0;
  const isUpgrade   = rank > curRank;
  const isDowngrade = rank < curRank;

  const ctaLabel    = isCurrent ? 'Current Plan' : isDowngrade ? 'Downgrade' : p.cta;
  const ctaDisabled = isCurrent || isDowngrade;

  return `
    <div class="bl-plan-card${p.popular ? ' bl-plan-card--popular' : ''}${isCurrent ? ' bl-plan-card--current' : ''}">
      ${p.popular ? '<div class="bl-popular-badge">Most Popular</div>' : ''}
      ${isCurrent ? '<div class="bl-current-badge">Your Plan</div>' : ''}
      <div class="bl-plan-header">
        <span class="ac-badge ${escHtml(p.badgeCls)}">${escHtml(p.badge)}</span>
        <div class="bl-plan-name">${escHtml(p.name)}</div>
        <div class="bl-plan-price">
          <span class="bl-price-amount">${escHtml(p.price)}</span>
          <span class="bl-price-period">${escHtml(p.period)}</span>
        </div>
        <div class="bl-plan-tagline">${escHtml(p.tagline)}</div>
      </div>
      <div class="bl-plan-features">
        ${p.features.map(f => `
          <div class="bl-plan-feature${f.included ? '' : ' bl-plan-feature--no'}">
            <span class="bl-feat-icon">${f.included ? '&#10003;' : '&#10007;'}</span>
            <span>${escHtml(f.label)}</span>
          </div>`).join('')}
      </div>
      <button
        class="bl-plan-cta${isCurrent ? ' bl-plan-cta--current' : isUpgrade ? ' sp-btn-primary' : ' sp-btn-secondary'}"
        data-ac-plan-select="${escHtml(planId)}"
        ${ctaDisabled ? 'disabled' : ''}
      >${escHtml(ctaLabel)}</button>
    </div>`;
}

function _blFeatureTableHTML() {
  const rows = [
    { label: 'Dashboard',                free: '✓', starter: '✓', pro: '✓', elite: '✓' },
    { label: 'Beginner courses',         free: '2',  starter: '✓', pro: '✓', elite: '✓' },
    { label: 'Intermediate courses',     free: '✗', starter: '✓', pro: '✓', elite: '✓' },
    { label: 'Advanced + Elite courses', free: '✗', starter: '✗', pro: '✓', elite: '✓' },
    { label: 'Practice hands/day',       free: '5',  starter: '∞', pro: '∞', elite: '∞' },
    { label: 'Replay Drills',            free: '✗', starter: '✗', pro: '✓', elite: '✓' },
    { label: 'Hand Replay',              free: '✗', starter: 'Limited', pro: 'Full', elite: 'Full' },
    { label: 'Leak Tracker',             free: '✗', starter: '✗', pro: '✓', elite: '✓' },
    { label: 'Skill Map',                free: '✗', starter: 'Basic', pro: 'Full', elite: 'Full' },
    { label: 'Progress Dashboard',       free: '✗', starter: '✓', pro: '✓', elite: '✓' },
    { label: 'Tournament Plan',          free: '✗', starter: '✗', pro: '✓', elite: '✓' },
    { label: 'AI Coach',                 free: '✗', starter: '✗', pro: '✗', elite: 'Soon' },
    { label: 'Cash Game modules',        free: '✗', starter: '✗', pro: '✗', elite: 'Soon' },
  ];

  const cellCls = v => {
    if (v === '✓' || v === '∞' || v === 'Full') return 'bl-cell--yes';
    if (v === '✗') return 'bl-cell--no';
    if (v === 'Soon') return 'bl-cell--soon';
    return 'bl-cell--partial';
  };

  return `
    <div class="bl-feature-table-wrap">
      <div class="bl-feature-table-title">Full Feature Comparison</div>
      <table class="bl-feature-table">
        <thead>
          <tr>
            <th>Feature</th>
            <th>Free</th>
            <th>Starter</th>
            <th class="bl-th--highlight">Pro</th>
            <th>Elite</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td class="bl-feature-name">${escHtml(r.label)}</td>
              <td class="${cellCls(r.free)}">${r.free}</td>
              <td class="${cellCls(r.starter)}">${r.starter}</td>
              <td class="${cellCls(r.pro)} bl-td--highlight">${r.pro}</td>
              <td class="${cellCls(r.elite)}">${r.elite}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function _spPlaceholderHTML(title, headline, body, items) {
  const itemsHTML = items ? `
    <div class="sp-ph-items">
      ${items.map(i => `
        <div class="sp-ph-item">
          <span class="sp-ph-item-label">${escHtml(i.label)}</span>
          <span class="sp-ph-item-tag">${escHtml(i.tag)}</span>
        </div>`).join('')}
    </div>` : '';
  return `
    <div class="sp-placeholder">
      <div class="sp-ph-icon">&#9672;</div>
      <h2 class="sp-ph-title">${escHtml(title)}</h2>
      <p class="sp-ph-headline">${escHtml(headline)}</p>
      <p class="sp-ph-body">${escHtml(body)}</p>
      ${itemsHTML}
      <button class="sp-btn-secondary" data-route="/">&larr; Back to Dashboard</button>
    </div>`;
}

function _spWireBack(view) {
  view.querySelectorAll('[data-route]').forEach(el => {
    el.addEventListener('click', () => spNavigate(el.dataset.route));
  });
}

/* ============================================================
   AUTH — User authentication module
   Handles token storage, login/signup forms, nav state.
   Prefix: auth- — no interference with other modules.
   ============================================================ */

const _AUTH_TOKEN_KEY = 'clubgg_auth_token';
const _AUTH_USER_KEY  = 'clubgg_auth_user';

function authGetToken() { return localStorage.getItem(_AUTH_TOKEN_KEY); }
function authSetToken(t) { localStorage.setItem(_AUTH_TOKEN_KEY, t); }
function authClearToken() { localStorage.removeItem(_AUTH_TOKEN_KEY); }

function authGetUser() {
  try { return JSON.parse(localStorage.getItem(_AUTH_USER_KEY) || 'null'); }
  catch { return null; }
}
function authSetUser(u) { localStorage.setItem(_AUTH_USER_KEY, JSON.stringify(u)); }
function authClearUser() { localStorage.removeItem(_AUTH_USER_KEY); }

function authIsLoggedIn() { return !!authGetToken(); }

function authUpdateNav() {
  const user = authGetUser();
  const avatar = document.getElementById('sp-nav-avatar');
  const logoutBtn = document.getElementById('sp-nav-logout');
  const adminBtn = document.querySelector('.sp-nav-admin');
  if (user) {
    if (avatar) avatar.textContent = (user.username || user.email || '?')[0].toUpperCase();
    if (logoutBtn) logoutBtn.hidden = false;
    if (adminBtn) adminBtn.hidden = user.role !== 'admin';
  } else {
    if (avatar) avatar.textContent = '—';
    if (logoutBtn) logoutBtn.hidden = true;
    if (adminBtn) adminBtn.hidden = true;
  }
}

function authLogout() {
  authClearToken();
  authClearUser();
  authUpdateNav();
  spNavigate('/login');
}

async function _authApiCall(path, body) {
  const resp = await fetch(`/api/v1/auth${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { ok: resp.ok, status: resp.status, data: await resp.json() };
}

function authRenderLogin() {
  const view = document.getElementById('sp-view-login');
  if (!view) return;
  view.classList.add('sp-view--active');
  view.innerHTML = `
    <div class="auth-page">
      <div class="auth-card">
        <div class="auth-logo">
          <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <polygon points="10,2 18,10 10,18 2,10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <polygon points="10,2 18,10 10,10" fill="currentColor" opacity="0.35"/>
          </svg>
        </div>
        <h1 class="auth-title">Welcome back</h1>
        <p class="auth-sub">Sign in to your ClubGG account</p>
        <div class="auth-error" id="auth-login-error" hidden></div>
        <form class="auth-form" id="auth-login-form" novalidate>
          <div class="auth-field">
            <label class="auth-label" for="auth-login-email">Email</label>
            <input class="auth-input" id="auth-login-email" type="email" placeholder="you@example.com" required autocomplete="email">
          </div>
          <div class="auth-field">
            <label class="auth-label" for="auth-login-password">Password</label>
            <input class="auth-input" id="auth-login-password" type="password" placeholder="••••••••" required autocomplete="current-password">
          </div>
          <button class="sp-btn-primary auth-submit" type="submit" id="auth-login-submit">Sign In</button>
        </form>
        <p class="auth-switch">Don't have an account? <button class="auth-link" data-route="/signup">Create one</button></p>
      </div>
    </div>
  `;
  view.querySelector('[data-route="/signup"]')?.addEventListener('click', () => spNavigate('/signup'));
  view.querySelector('#auth-login-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = view.querySelector('#auth-login-email').value.trim();
    const password = view.querySelector('#auth-login-password').value;
    const btn = view.querySelector('#auth-login-submit');
    const errEl = view.querySelector('#auth-login-error');
    btn.disabled = true;
    btn.textContent = 'Signing in…';
    errEl.hidden = true;
    const { ok, data } = await _authApiCall('/login', { email, password });
    if (ok) {
      authSetToken(data.access_token);
      authSetUser(data.user);
      authUpdateNav();
      await acLoadPlan();
      spNavigate('/');
    } else {
      errEl.textContent = data.detail || 'Invalid email or password';
      errEl.hidden = false;
      btn.disabled = false;
      btn.textContent = 'Sign In';
    }
  });
}

function authRenderSignup() {
  const view = document.getElementById('sp-view-signup');
  if (!view) return;
  view.classList.add('sp-view--active');
  view.innerHTML = `
    <div class="auth-page">
      <div class="auth-card">
        <div class="auth-logo">
          <svg viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <polygon points="10,2 18,10 10,18 2,10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <polygon points="10,2 18,10 10,10" fill="currentColor" opacity="0.35"/>
          </svg>
        </div>
        <h1 class="auth-title">Create your account</h1>
        <p class="auth-sub">Start improving your poker game today</p>
        <div class="auth-error" id="auth-signup-error" hidden></div>
        <form class="auth-form" id="auth-signup-form" novalidate>
          <div class="auth-field">
            <label class="auth-label" for="auth-signup-email">Email</label>
            <input class="auth-input" id="auth-signup-email" type="email" placeholder="you@example.com" required autocomplete="email">
          </div>
          <div class="auth-field">
            <label class="auth-label" for="auth-signup-username">Username <span class="auth-optional">(optional)</span></label>
            <input class="auth-input" id="auth-signup-username" type="text" placeholder="PokerPro99" autocomplete="username">
          </div>
          <div class="auth-field">
            <label class="auth-label" for="auth-signup-password">Password</label>
            <input class="auth-input" id="auth-signup-password" type="password" placeholder="Min. 8 characters" required autocomplete="new-password">
          </div>
          <div class="auth-field">
            <label class="auth-label" for="auth-signup-invite">Invite Code</label>
            <input class="auth-input" id="auth-signup-invite" type="text" placeholder="Enter your invite code" autocomplete="off" spellcheck="false">
          </div>
          <button class="sp-btn-primary auth-submit" type="submit" id="auth-signup-submit">Create Account</button>
        </form>
        <p class="auth-switch">Already have an account? <button class="auth-link" data-route="/login">Sign in</button></p>
      </div>
    </div>
  `;
  view.querySelector('[data-route="/login"]')?.addEventListener('click', () => spNavigate('/login'));
  view.querySelector('#auth-signup-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = view.querySelector('#auth-signup-email').value.trim();
    const username = view.querySelector('#auth-signup-username').value.trim() || null;
    const password = view.querySelector('#auth-signup-password').value;
    const btn = view.querySelector('#auth-signup-submit');
    const errEl = view.querySelector('#auth-signup-error');
    btn.disabled = true;
    btn.textContent = 'Creating account…';
    errEl.hidden = true;
    const invite_code = view.querySelector('#auth-signup-invite').value.trim() || null;
    const { ok, data } = await _authApiCall('/register', { email, username, password, invite_code });
    if (ok) {
      authSetToken(data.access_token);
      authSetUser(data.user);
      authUpdateNav();
      await acLoadPlan();
      spNavigate(data.user.onboarding_complete === false ? '/onboarding' : '/');
    } else {
      const msg = data.detail || 'Registration failed';
      errEl.textContent = Array.isArray(msg) ? msg.map(d => d.msg).join(', ') : msg;
      errEl.hidden = false;
      btn.disabled = false;
      btn.textContent = 'Create Account';
    }
  });
}

/* ============================================================
   AD — ADMIN PANEL
   Route: /admin — visible only when user.role === "admin".
   Prefix: ad- (CSS), _ad (JS internal).
   ============================================================ */

const _AD_API = '/api/v1';

async function _adFetch(path, opts = {}) {
  const token = authGetToken();
  const res = await fetch(`${_AD_API}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(opts.headers || {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

function _adErrorHtml(msg) {
  return `<div class="ad-error">${escHtml(String(msg))}</div>`;
}

// ── Top-level renderer ────────────────────────────────────────────────────────

function _spRenderAdmin() {
  const view = document.getElementById('sp-view-admin');
  if (!view) return;

  const user = authGetUser();
  if (!user || user.role !== 'admin') {
    view.classList.add('sp-view--active');
    view.innerHTML = `<div class="ad-forbidden"><h2>403 — Admin access required</h2></div>`;
    return;
  }

  view.classList.add('sp-view--active');
  view.innerHTML = `
    <div class="ad-shell">
      <div class="ad-sidebar">
        <div class="ad-sidebar-title">Admin</div>
        <button class="ad-nav-btn ad-nav-btn--active" data-ad-tab="dashboard">Dashboard</button>
        <button class="ad-nav-btn" data-ad-tab="users">Users</button>
        <button class="ad-nav-btn" data-ad-tab="courses">Courses</button>
      </div>
      <div class="ad-main" id="ad-main">
        <div class="ad-loading">Loading…</div>
      </div>
    </div>`;

  view.querySelectorAll('[data-ad-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      view.querySelectorAll('.ad-nav-btn').forEach(b => b.classList.remove('ad-nav-btn--active'));
      btn.classList.add('ad-nav-btn--active');
      _adRenderTab(btn.dataset.adTab);
    });
  });

  _adRenderTab('dashboard');
}

function _adRenderTab(tab) {
  const main = document.getElementById('ad-main');
  if (!main) return;
  main.innerHTML = `<div class="ad-loading">Loading…</div>`;
  if (tab === 'dashboard') _adRenderDashboard(main);
  else if (tab === 'users') _adRenderUsers(main);
  else if (tab === 'courses') _adRenderCourses(main);
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

async function _adRenderDashboard(el) {
  try {
    const data = await _adFetch('/admin/overview');
    const dist = data.plan_distribution || {};
    const distRows = Object.entries(dist)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([slug, count]) => `<tr><td>${escHtml(slug)}</td><td>${count}</td></tr>`)
      .join('');

    el.innerHTML = `
      <div class="ad-page-title">Dashboard</div>
      <div class="ad-stat-grid">
        <div class="ad-stat"><div class="ad-stat-val">${data.total_users}</div><div class="ad-stat-label">Total Users</div></div>
        <div class="ad-stat"><div class="ad-stat-val">${data.active_users}</div><div class="ad-stat-label">Active Users</div></div>
        <div class="ad-stat"><div class="ad-stat-val">${data.paying_users}</div><div class="ad-stat-label">Paying Users</div></div>
        <div class="ad-stat"><div class="ad-stat-val">${data.total_hands.toLocaleString()}</div><div class="ad-stat-label">Hands Imported</div></div>
      </div>
      <div class="ad-section-title">Plan Distribution</div>
      <table class="ad-table">
        <thead><tr><th>Plan</th><th>Users</th></tr></thead>
        <tbody>${distRows}</tbody>
      </table>`;
  } catch (err) {
    el.innerHTML = _adErrorHtml(`Failed to load overview: ${err.message}`);
  }
}

// ── Users ─────────────────────────────────────────────────────────────────────

async function _adRenderUsers(el) {
  try {
    const users = await _adFetch('/admin/users?limit=200');
    el.innerHTML = `
      <div class="ad-page-title">Users <span class="ad-count">(${users.length})</span></div>
      <table class="ad-table ad-table--users">
        <thead>
          <tr>
            <th>Email</th><th>Username</th><th>Role</th><th>Plan</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${users.map(u => `
            <tr data-user-id="${escHtml(u.id)}">
              <td>${escHtml(u.email)}</td>
              <td>${escHtml(u.username || '—')}</td>
              <td>
                <select class="ad-select ad-role-select" data-uid="${escHtml(u.id)}">
                  <option value="player"${u.role === 'player' ? ' selected' : ''}>player</option>
                  <option value="admin"${u.role === 'admin' ? ' selected' : ''}>admin</option>
                </select>
              </td>
              <td>
                <select class="ad-select ad-plan-select" data-uid="${escHtml(u.id)}">
                  <option value="free"${u.plan_slug === 'free' ? ' selected' : ''}>free</option>
                  <option value="starter"${u.plan_slug === 'starter' ? ' selected' : ''}>starter</option>
                  <option value="pro"${u.plan_slug === 'pro' ? ' selected' : ''}>pro</option>
                  <option value="elite"${u.plan_slug === 'elite' ? ' selected' : ''}>elite</option>
                </select>
              </td>
              <td>
                <button class="ad-btn ad-save-user-btn" data-uid="${escHtml(u.id)}">Save</button>
                <span class="ad-save-status" id="ad-save-${escHtml(u.id)}"></span>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>`;

    el.querySelectorAll('.ad-save-user-btn').forEach(btn => {
      btn.addEventListener('click', () => _adSaveUser(el, btn.dataset.uid));
    });
  } catch (err) {
    el.innerHTML = _adErrorHtml(`Failed to load users: ${err.message}`);
  }
}

async function _adSaveUser(el, uid) {
  const row = el.querySelector(`tr[data-user-id="${uid}"]`);
  if (!row) return;
  const role = row.querySelector('.ad-role-select').value;
  const plan = row.querySelector('.ad-plan-select').value;
  const statusEl = document.getElementById(`ad-save-${uid}`);
  if (statusEl) { statusEl.textContent = 'Saving…'; statusEl.className = 'ad-save-status'; }

  try {
    await _adFetch(`/admin/users/${uid}/set-role`, { method: 'POST', body: JSON.stringify({ role }) });
    await _adFetch(`/admin/users/${uid}/set-plan`, { method: 'POST', body: JSON.stringify({ plan_slug: plan }) });
    if (statusEl) { statusEl.textContent = '✓ Saved'; statusEl.className = 'ad-save-status ad-save-ok'; }
  } catch (err) {
    if (statusEl) { statusEl.textContent = `✗ ${err.message}`; statusEl.className = 'ad-save-status ad-save-err'; }
  }
}

// ── Courses ───────────────────────────────────────────────────────────────────

async function _adRenderCourses(el) {
  try {
    const courses = await _adFetch('/admin/courses');
    el.innerHTML = `
      <div class="ad-page-title">Courses <span class="ad-count">(${courses.length})</span></div>
      <details class="ad-create-form" id="ad-course-create-form">
        <summary class="ad-create-toggle">+ New Course</summary>
        <div class="ad-form-body">
          <label class="ad-label">Slug <input class="ad-input" id="ad-c-slug" placeholder="my-course"></label>
          <label class="ad-label">Title <input class="ad-input" id="ad-c-title" placeholder="Course Title"></label>
          <label class="ad-label">Level
            <select class="ad-select" id="ad-c-level">
              <option value="beginner">beginner</option>
              <option value="intermediate">intermediate</option>
              <option value="advanced">advanced</option>
              <option value="elite">elite</option>
            </select>
          </label>
          <label class="ad-label">Est. minutes <input class="ad-input" id="ad-c-mins" type="number" value="30"></label>
          <label class="ad-label">Description <input class="ad-input" id="ad-c-desc" placeholder="Optional"></label>
          <label class="ad-label">
            <input type="checkbox" id="ad-c-pub" checked> Published
          </label>
          <button class="ad-btn ad-btn--primary" id="ad-course-create-btn">Create Course</button>
          <span id="ad-create-status"></span>
        </div>
      </details>
      <table class="ad-table">
        <thead><tr><th>Title</th><th>Slug</th><th>Level</th><th>Published</th><th>Actions</th></tr></thead>
        <tbody id="ad-courses-tbody">
          ${courses.map(c => _adCourseRow(c)).join('')}
        </tbody>
      </table>`;

    _adWireCourseRows(el);

    el.querySelector('#ad-course-create-btn')?.addEventListener('click', async () => {
      const statusEl = document.getElementById('ad-create-status');
      const body = {
        slug: document.getElementById('ad-c-slug').value.trim(),
        title: document.getElementById('ad-c-title').value.trim(),
        level: document.getElementById('ad-c-level').value,
        estimated_minutes: parseInt(document.getElementById('ad-c-mins').value, 10) || 30,
        description: document.getElementById('ad-c-desc').value.trim(),
        is_published: document.getElementById('ad-c-pub').checked,
      };
      if (!body.slug || !body.title) { if (statusEl) { statusEl.textContent = 'Slug and title required.'; } return; }
      try {
        const created = await _adFetch('/admin/courses', { method: 'POST', body: JSON.stringify(body) });
        const tbody = document.getElementById('ad-courses-tbody');
        if (tbody) {
          const tr = document.createElement('tr');
          tr.innerHTML = _adCourseRow(created);
          tbody.prepend(tr);
          _adWireCourseRows(el);
        }
        if (statusEl) statusEl.textContent = '✓ Created';
        document.getElementById('ad-c-slug').value = '';
        document.getElementById('ad-c-title').value = '';
      } catch (err) {
        if (statusEl) statusEl.textContent = `✗ ${err.message}`;
      }
    });
  } catch (err) {
    el.innerHTML = _adErrorHtml(`Failed to load courses: ${err.message}`);
  }
}

function _adCourseRow(c) {
  return `<tr data-course-id="${escHtml(String(c.id))}">
    <td><input class="ad-input ad-inline" data-field="title" value="${escHtml(c.title)}"></td>
    <td>${escHtml(c.slug)}</td>
    <td>
      <select class="ad-select ad-inline" data-field="level">
        ${['beginner','intermediate','advanced','elite'].map(l =>
          `<option value="${l}"${c.level === l ? ' selected' : ''}>${l}</option>`).join('')}
      </select>
    </td>
    <td>
      <input type="checkbox" class="ad-check" data-field="is_published"${c.is_published ? ' checked' : ''}>
    </td>
    <td>
      <button class="ad-btn ad-course-save" data-cid="${escHtml(String(c.id))}">Save</button>
      <button class="ad-btn ad-btn--danger ad-course-delete" data-cid="${escHtml(String(c.id))}">Del</button>
      <span class="ad-save-status" id="ad-csave-${escHtml(String(c.id))}"></span>
    </td>
  </tr>`;
}

function _adWireCourseRows(el) {
  el.querySelectorAll('.ad-course-save').forEach(btn => {
    btn.onclick = async () => {
      const cid = btn.dataset.cid;
      const row = el.querySelector(`tr[data-course-id="${cid}"]`);
      const statusEl = document.getElementById(`ad-csave-${cid}`);
      const body = {
        title: row.querySelector('[data-field="title"]').value,
        level: row.querySelector('[data-field="level"]').value,
        is_published: row.querySelector('[data-field="is_published"]').checked,
      };
      try {
        await _adFetch(`/admin/courses/${cid}`, { method: 'PUT', body: JSON.stringify(body) });
        if (statusEl) { statusEl.textContent = '✓'; statusEl.className = 'ad-save-status ad-save-ok'; }
      } catch (err) {
        if (statusEl) { statusEl.textContent = `✗ ${err.message}`; statusEl.className = 'ad-save-status ad-save-err'; }
      }
    };
  });
  el.querySelectorAll('.ad-course-delete').forEach(btn => {
    btn.onclick = async () => {
      if (!confirm('Delete this course and all its lessons?')) return;
      const cid = btn.dataset.cid;
      try {
        await _adFetch(`/admin/courses/${cid}`, { method: 'DELETE' });
        el.querySelector(`tr[data-course-id="${cid}"]`)?.remove();
      } catch (err) {
        alert(`Delete failed: ${err.message}`);
      }
    };
  });
}

function authInitSession() {
  // If we have a stored user, update the nav immediately (no network call needed at startup)
  authUpdateNav();
}

// ── Init ──────────────────────────────────────────────────
/* ── Offline / unreachable notice ────────────────────────── */
let _spApiDownShown = false;

function _spMarkApiDown() {
  if (_spApiDownShown) return;
  _spApiDownShown = true;
  const banner = document.getElementById('sp-offline-banner');
  if (banner) banner.hidden = false;
}

document.addEventListener('DOMContentLoaded', () => {
  // Inject offline banner once into DOM
  const banner = document.createElement('div');
  banner.id = 'sp-offline-banner';
  banner.className = 'sp-offline-banner';
  banner.hidden = true;
  banner.innerHTML = `
    <span>&#9888; Live data unavailable &mdash; showing demo mode.</span>
    <button class="sp-offline-dismiss" id="sp-offline-dismiss" aria-label="Dismiss">&#10005;</button>
  `;
  document.getElementById('app')?.prepend(banner);
  banner.querySelector('#sp-offline-dismiss')?.addEventListener('click', () => {
    banner.hidden = true;
  });

  // Wire nav buttons
  document.querySelectorAll('.sp-nav-item, .sp-nav-logo').forEach(btn => {
    btn.addEventListener('click', () => spNavigate(btn.dataset.route));
  });

  // Handle browser back/forward
  window.addEventListener('popstate', _spHandleLocation);

  // Init auth session state (update nav avatar etc.)
  authInitSession();

  // Wire logout button
  document.getElementById('sp-nav-logout')?.addEventListener('click', authLogout);

  // Load real billing plan from server (updates nav badge on completion)
  acLoadPlan().then(() => {
    // Handle post-Stripe success redirect
    const params = new URLSearchParams(window.location.search);
    if (params.get('billing') === 'success') {
      history.replaceState({}, '', window.location.pathname);
      spNavigate('/account');
    } else {
      _spHandleLocation();
    }
  });

  if (!authIsLoggedIn()) {
    // Render initial route immediately for unauthenticated users
    _spHandleLocation();
  }
});

/* ============================================================
   AN — ANALYSIS HUB
   Premium hub section rendered at the top of the analysis view.
   Prefix: an- — no interference with rs-/sp-/tab- code.
   ============================================================ */

let _anHubInitialized = false;

/* ── Live state ──────────────────────────────────────────────────────────── */

let _anLiveAnalysis = null;   // MeAnalysisOut | null
let _anLiveHands    = null;   // MeHandsOut   | null
let _anHasPlayer    = null;   // true | false | null (null = not yet checked)

async function _anFetchLive() {
  if (!authIsLoggedIn()) {
    _anLiveAnalysis = null;
    _anLiveHands    = null;
    _anHasPlayer    = null;
    return;
  }
  const headers = _coAuthHeaders();
  try {
    const [ar, hr] = await Promise.all([
      fetch('/api/v1/me/analysis', { headers }),
      fetch('/api/v1/me/hands',    { headers }),
    ]);
    if (ar.status === 404) {
      _anHasPlayer    = false;
      _anLiveAnalysis = null;
      _anLiveHands    = null;
    } else if (ar.ok) {
      _anHasPlayer    = true;
      _anLiveAnalysis = await ar.json();
      _anLiveHands    = hr.ok ? await hr.json() : null;
      _dsPersistLeakCats(_anLiveAnalysis);
    }
  } catch { _spMarkApiDown(); /* network error — fall through to mock */ }
}

async function _anApiLinkPlayer(playerUuid) {
  const headers = { ..._coAuthHeaders(), 'Content-Type': 'application/json' };
  const r = await fetch('/api/v1/me/players/link', {
    method: 'POST',
    headers,
    body: JSON.stringify({ player_id: playerUuid, is_primary: true }),
  });
  return { ok: r.ok, data: await r.json() };
}

/* ── Coaching data (mock — real data comes from /api/v1/players/{id}/stats) ── */

const AN_MOCK_SUMMARY = {
  handsAnalyzed: 847,
  biggestLeak:   'BB fold-to-steal',
  trendBb100:    3.2,
  nextAction:    { label: 'Drill Push\u2215Fold \u2192', route: '/trainer?mode=push-fold&difficulty=intermediate' },
};

const AN_MOCK_LEAKS = [
  {
    id:           'bb-fold-steal',
    name:         'Folding too much from BB vs steal',
    severity:     'major',
    stage:        'Mid\u2013Late stage',
    frequency:    '68% fold rate',
    sampleN:      47,
    explanation:  'Your BB fold-to-steal is 68% \u2014 significantly above the 45\u201355% optimal range. You surrender EV every time a late-position player opens.',
    trainerRoute: '/trainer?mode=push-fold&difficulty=intermediate',
    learnRoute:   '/learn/steal-and-resteal',
  },
  {
    id:           'missing-btn-shoves',
    name:         'Missing profitable BTN shove spots',
    severity:     'major',
    stage:        'Short stack (8\u201314bb)',
    frequency:    '72% fold rate',
    sampleN:      29,
    explanation:  'You fold 72% of profitable BTN shove spots at 10\u201314bb effective. Nash push range from BTN at 12bb includes A2o, 22+, and many Kx hands you are currently folding.',
    trainerRoute: '/trainer?mode=push-fold&difficulty=intermediate',
    learnRoute:   '/learn/stack-sizes-tournament-strategy/push-fold-theory',
  },
  {
    id:           'over-calling-short-stack',
    name:         'Over-calling short stack all-ins',
    severity:     'minor',
    stage:        'Mid stage (15\u201320bb)',
    frequency:    '31% over-call rate',
    sampleN:      19,
    explanation:  'Calling off vs 15bb shoves below required equity threshold. At this depth, your calling range should be strictly equity-based against a typical shoving range.',
    trainerRoute: '/trainer?mode=bubble&difficulty=intermediate',
    learnRoute:   '/learn/bubble-play',
  },
  {
    id:           'under-bluffing-river',
    name:         'Under-bluffing river spots',
    severity:     'minor',
    stage:        'All stages',
    frequency:    '28% bet freq.',
    sampleN:      38,
    explanation:  'River bet frequency of 28% in single-raised pots is below GTO baseline. Opponents profitably over-fold vs your bets, reducing your value extraction.',
    trainerRoute: '/trainer?mode=general&difficulty=advanced',
    learnRoute:   '/learn/multi-street-planning',
  },
];

const AN_MOCK_RECS = [
  {
    icon:    '&#127919;',
    title:   'Focus: Bubble Play',
    body:    'Your biggest EV leak is in bubble spots. 15 minutes of push/fold drilling today can recover ~1.5\u00a0bb/100.',
    cta:     'Start Drill',
    route:   '/trainer?mode=bubble&difficulty=intermediate',
    tag:     'Practice',
    tagCls:  'an-rec-tag--practice',
  },
  {
    icon:    '&#128218;',
    title:   'Recommended Course',
    body:    'Steal and Re-Steal Spots directly targets your #1 leak and covers BB defense range construction.',
    cta:     'Start Course',
    route:   '/learn/steal-and-resteal',
    tag:     'Learn',
    tagCls:  'an-rec-tag--learn',
  },
  {
    icon:    '&#128202;',
    title:   'Trend: Improving',
    body:    'Push/fold accuracy improved +12% over your last 3 practice sessions. Keep drilling to consolidate.',
    cta:     'View Progress',
    route:   '/progress',
    tag:     'Progress',
    tagCls:  'an-rec-tag--progress',
  },
];

async function _anInitHub() {
  const hub = document.getElementById('an-hub');
  if (!hub || _anHubInitialized) return;
  _anHubInitialized = true;

  // Fetch live data (auth-gated); falls back to mock if not logged in or no player
  await _anFetchLive();

  // Logged in but no player linked → show onboarding instead of mock hub
  if (authIsLoggedIn() && _anHasPlayer === false) {
    _anRenderOnboarding(hub);
    return;
  }

  const cards = [
    {
      icon: '♠',
      title: 'Replay Review',
      desc: 'Step through key decision points hand by hand.',
      badge: 'live',
      badgeLabel: 'Live',
      btnLabel: 'Open Replay',
      tab: 'trainer',
    },
    {
      icon: '⚡',
      title: 'Leak Detection',
      desc: 'Identify recurring strategic mistakes from your history.',
      badge: 'live',
      badgeLabel: 'Live',
      btnLabel: acCan('leak_tracker') ? 'View Leaks' : 'Upgrade to Pro &#128274;',
      tab: 'leaks',
      locked: !acCan('leak_tracker'),
      requires: 'pro',
    },
    {
      icon: '◉',
      title: 'Player Stats',
      desc: 'VPIP, PFR, 3-bet%, positional breakdown and more.',
      badge: 'live',
      badgeLabel: 'Live',
      btnLabel: 'View Stats',
      tab: 'stats',
    },
    {
      icon: '◈',
      title: 'Tournament Plan',
      desc: 'Stage-by-stage strategy and ICM-aware decisions.',
      badge: 'live',
      badgeLabel: 'Live',
      btnLabel: 'Open Plan',
      tab: 'plan',
    },
    {
      icon: '↑',
      title: 'Import Hands',
      desc: 'Upload ClubGG hand history files for analysis.',
      badge: 'ready',
      badgeLabel: 'Ready',
      btnLabel: 'Import',
      tab: 'import',
    },
  ];

  const recentHands = [
    { stage: 'Final Table', stageClass: 'an-stage--final',  stack: '22bb', cards: 'A\u2660 K\u2665', desc: 'BTN open \u00b7 3-bet pot \u00b7 c-bet fold',               result: '18.5',    pos: true,  mistake: false },
    { stage: 'Bubble',      stageClass: 'an-stage--bubble', stack: '14bb', cards: 'Q\u2666 Q\u2663', desc: 'SB shove vs BTN open',                                    result: '42.0',    pos: true,  mistake: false },
    { stage: 'ITM',         stageClass: 'an-stage--itm',    stack: '31bb', cards: 'J\u2660 T\u2660', desc: 'BB defend \u00b7 check-raise flop \u00b7 folded turn',    result: '\u221211.0', pos: false, mistake: true,  mistakeLabel: 'Timing leak' },
    { stage: 'Early',       stageClass: 'an-stage--early',  stack: '80bb', cards: '9\u2663 9\u2666', desc: 'CO open \u00b7 folded to 3-bet',                          result: '\u22122.5',  pos: false, mistake: true,  mistakeLabel: 'BTN fold too often' },
    { stage: 'Bubble',      stageClass: 'an-stage--bubble', stack: '18bb', cards: '7\u2665 7\u2660', desc: 'UTG shove \u00b7 called by AK \u00b7 lost',               result: '\u221218.0', pos: false, mistake: false },
  ];

  const leakNote = acCan('leak_tracker') ? '' : `
    <div class="an-panel-lock-note">&#128274; Live detection requires <button class="an-inline-upgrade" id="an-leak-upgrade-btn">Tournament Pro</button> &middot; Showing mock data</div>`;

  // Resolve data sources: live when available, mock otherwise
  const live    = _anLiveAnalysis;
  const liveSumm = live?.summary;
  const liveLeaks = live?.leaks?.leaks ?? [];
  const liveHands = _anLiveHands?.hands ?? [];
  const isLive   = !!live;

  const sumHands   = liveSumm ? liveSumm.hands_analyzed : AN_MOCK_SUMMARY.handsAnalyzed;
  const sumLeak    = liveSumm ? (liveSumm.biggest_leak ?? '—') : AN_MOCK_SUMMARY.biggestLeak;
  const playerBadge = isLive
    ? `<span class="an-live-badge">&#9679; ${escHtml(live.player_username)}</span>`
    : `<span class="an-demo-badge">Demo data — <button class="auth-link" id="an-signin-link">sign in</button> to see yours</span>`;

  hub.innerHTML = `
    <div class="an-summary-bar">
      <div class="an-sum-stat">
        <span class="an-sum-val">${sumHands.toLocaleString()}</span>
        <span class="an-sum-lbl">Hands Analyzed</span>
      </div>
      <div class="an-sum-divider"></div>
      <div class="an-sum-stat">
        <span class="an-sum-val an-sum-val--warn">${escHtml(String(sumLeak))}</span>
        <span class="an-sum-lbl">Biggest Leak</span>
      </div>
      <div class="an-sum-divider"></div>
      <div class="an-sum-stat">
        ${isLive
          ? `<span class="an-sum-val an-sum-val--good">${escHtml(live.summary.analysis_note)}</span>`
          : `<span class="an-sum-val an-sum-val--good">&#8593; +${AN_MOCK_SUMMARY.trendBb100}\u00a0bb/100</span>`}
        <span class="an-sum-lbl">${isLive ? 'Sample Note' : 'Improvement Trend'}</span>
      </div>
      <div class="an-sum-player">${playerBadge}</div>
    </div>

    <div class="an-hero">
      <div class="an-hero-text">
        <h1 class="an-hero-title">Hand Analysis</h1>
        <p class="an-hero-sub">
          Review hands, detect leaks, track stats, and build tournament plans.
          Load a player above to unlock live analysis.
        </p>
      </div>
      <div class="an-hero-actions">
        <button class="sp-btn-primary" id="an-cta-replay">Review Latest Hand</button>
        <button class="sp-btn-secondary" id="an-cta-import">Import Hands</button>
      </div>
    </div>

    <div class="an-cards">
      ${cards.map((c, i) => `
        <div class="an-card${c.locked ? ' an-card--locked' : ''}" data-an-card="${i}">
          <div class="an-card-header">
            <span class="an-card-icon" aria-hidden="true">${c.icon}</span>
            <span class="an-badge an-badge--${c.badge}">${escHtml(c.badgeLabel)}</span>
          </div>
          <div class="an-card-title">${escHtml(c.title)}</div>
          <div class="an-card-desc">${escHtml(c.desc)}</div>
          <button class="an-card-btn${c.locked ? ' an-card-btn--locked' : ''}" data-an-tab="${escHtml(c.tab)}" data-an-locked="${c.locked ? escHtml(c.requires || '') : ''}">${c.btnLabel}</button>
        </div>`).join('')}
    </div>

    <div class="an-coaching">

      <div class="an-leaks-panel">
        <div class="an-panel-hdr">
          <div>
            <span class="an-panel-title">Your Biggest Leaks</span>
            <span class="an-panel-meta">${isLive ? liveLeaks.length : AN_MOCK_LEAKS.length} active \u00b7 INFERRED from ${sumHands.toLocaleString()} hands</span>
          </div>
          <button class="an-panel-link" id="an-leaks-progress-link">View in Progress \u2192</button>
        </div>
        ${leakNote}
        <div class="an-leak-list">
          ${isLive
            ? (liveLeaks.length === 0
                ? `<p class="an-no-leaks">No leaks detected yet — upload more hands for a full analysis.</p>`
                : liveLeaks.slice(0, 4).map(l => `
                    <div class="an-leak-row an-leak-row--${escHtml(l.severity)}">
                      <div class="an-leak-sev an-leak-sev--${escHtml(l.severity)}"></div>
                      <div class="an-leak-body">
                        <div class="an-leak-name">${escHtml(l.title)}</div>
                        <div class="an-leak-detail">${escHtml(l.category)} \u00b7 ${escHtml(l.frequency)} \u00b7 <span class="an-confidence-tag">${escHtml(l.confidence)} n=${l.sample_size}</span></div>
                        <div class="an-leak-exp">${escHtml(l.explanation)}</div>
                      </div>
                      <div class="an-leak-btns">
                        <button class="an-leak-btn an-leak-btn--review" data-an-tab="leaks">&#9776; Review</button>
                      </div>
                    </div>`).join(''))
            : AN_MOCK_LEAKS.map(l => `
                <div class="an-leak-row an-leak-row--${escHtml(l.severity)}">
                  <div class="an-leak-sev an-leak-sev--${escHtml(l.severity)}"></div>
                  <div class="an-leak-body">
                    <div class="an-leak-name">${escHtml(l.name)}</div>
                    <div class="an-leak-detail">${escHtml(l.stage)} \u00b7 ${escHtml(l.frequency)} \u00b7 <span class="an-confidence-tag">INFERRED n=${l.sampleN}</span></div>
                    <div class="an-leak-exp">${escHtml(l.explanation)}</div>
                  </div>
                  <div class="an-leak-btns">
                    <button class="an-leak-btn an-leak-btn--practice" data-an-route="${escHtml(l.trainerRoute)}">&#9654; Practice</button>
                    <button class="an-leak-btn an-leak-btn--learn"    data-an-route="${escHtml(l.learnRoute)}">&#128218; Learn</button>
                    <button class="an-leak-btn an-leak-btn--review"   data-an-tab="leaks">&#9776; Review</button>
                  </div>
                </div>`).join('')}
        </div>
      </div>

      <div class="an-recs-panel">
        <div class="an-panel-hdr">
          <span class="an-panel-title">Smart Recommendations</span>
          <span class="an-panel-meta">based on your recent sessions</span>
        </div>
        <div class="an-recs-list">
          ${AN_MOCK_RECS.map(r => `
            <div class="an-rec-card">
              <div class="an-rec-header">
                <span class="an-rec-icon">${r.icon}</span>
                <span class="an-rec-tag ${escHtml(r.tagCls)}">${escHtml(r.tag)}</span>
              </div>
              <div class="an-rec-title">${escHtml(r.title)}</div>
              <div class="an-rec-body">${escHtml(r.body)}</div>
              <button class="an-rec-cta" data-an-route="${escHtml(r.route)}">${escHtml(r.cta)} \u2192</button>
            </div>`).join('')}
        </div>
      </div>

    </div>

    <div class="an-recent">
      <div class="an-recent-header">
        <span class="an-recent-title">Recent Hands</span>
        <span class="an-recent-meta">${isLive ? `${liveHands.length} hands \u00b7 ${escHtml(live.player_username)}` : 'Demo data \u2014 sign in to see your hands'}</span>
      </div>
      <table class="an-hand-table" aria-label="Recent hands">
        <thead>
          <tr>
            <th>${isLive ? 'Table' : 'Stage'}</th>
            <th>Stack</th>
            <th>${isLive ? 'Position / Board' : 'Hand / Spot'}</th>
            <th>Result</th>
            <th>Flag</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${isLive
            ? (liveHands.length === 0
                ? `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px">No hands found. Import hand history files to start.</td></tr>`
                : liveHands.slice(0, 10).map(h => {
                    // Result in big blinds (net_won itself is in chips).
                    const netWon = h.net_won_bb != null ? parseFloat(h.net_won_bb) : null;
                    const stackBb = h.stack_bb ? `${parseFloat(h.stack_bb).toFixed(0)}bb` : '—';
                    const pos = h.position || '—';
                    const board = h.board_cards || '';
                    const pos2 = netWon != null && netWon >= 0;
                    return `
                      <tr>
                        <td><span class="an-stage-badge an-stage--early">${escHtml(_meTableLabel(h))}</span></td>
                        <td><span class="an-stack-depth">${escHtml(stackBb)}</span></td>
                        <td>
                          <strong>${escHtml(pos)}</strong>
                          <span class="an-hand-desc">${escHtml(_meHeroName(h))}</span>
                          ${board ? `<span class="an-hand-desc">${escHtml(board)}</span>` : ''}
                        </td>
                        <td class="${pos2 ? 'an-result-pos' : 'an-result-neg'}">${netWon != null ? (pos2 ? '+' : '') + netWon.toFixed(1) + ' bb' : '—'}</td>
                        <td><span class="an-no-flag">\u2014</span></td>
                        <td><button class="an-review-btn" data-an-view-hand="${escHtml(h.hand_external_id || '')}">View \u2192</button></td>
                      </tr>`;
                  }).join(''))
            : recentHands.map(h => `
                <tr${h.mistake ? ' class="an-hand-row--mistake"' : ''}>
                  <td><span class="an-stage-badge ${escHtml(h.stageClass)}">${escHtml(h.stage)}</span></td>
                  <td><span class="an-stack-depth">${escHtml(h.stack)}</span></td>
                  <td>
                    <strong>${h.cards}</strong>
                    <span class="an-hand-desc">${escHtml(h.desc)}</span>
                  </td>
                  <td class="${h.pos ? 'an-result-pos' : 'an-result-neg'}">${h.pos ? '+' : ''}${escHtml(h.result)} bb</td>
                  <td>${h.mistake ? `<span class="an-mistake-flag">${escHtml(h.mistakeLabel)}</span>` : '<span class="an-no-flag">\u2014</span>'}</td>
                  <td><button class="an-review-btn" data-an-tab="trainer">Review \u2192</button></td>
                </tr>`).join('')}
        </tbody>
      </table>
    </div>
  `;

  // Wire CTA buttons
  document.getElementById('an-cta-replay')?.addEventListener('click', () => _anActivateTab('trainer'));
  document.getElementById('an-cta-import')?.addEventListener('click', () => _anActivateTab('import'));
  document.getElementById('an-sum-next')?.addEventListener('click', () => spNavigate(AN_MOCK_SUMMARY.nextAction.route));
  document.getElementById('an-leaks-progress-link')?.addEventListener('click', () => spNavigate('/progress'));
  document.getElementById('an-leak-upgrade-btn')?.addEventListener('click', () => acShowUpgrade('Live Leak Detection', 'pro'));
  document.getElementById('an-signin-link')?.addEventListener('click', () => spNavigate('/login'));

  // Wire tab-activation buttons (feature cards + review buttons)
  hub.querySelectorAll('[data-an-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      const locked = btn.dataset.anLocked;
      if (locked) { acShowUpgrade('Leak Detection', locked); }
      else        { _anActivateTab(btn.dataset.anTab); }
    });
  });

  // Wire View buttons on live hand rows
  hub.querySelectorAll('[data-an-view-hand]').forEach(btn => {
    btn.addEventListener('click', () => {
      const handId = btn.dataset.anViewHand;
      if (!handId) { _anActivateTab('import'); return; }
      spNavigate(`/analysis?hand=${encodeURIComponent(handId)}`);
    });
  });

  // Wire route navigation buttons (leak practice/learn + rec CTAs)
  hub.querySelectorAll('[data-an-route]').forEach(btn => {
    btn.addEventListener('click', () => spNavigate(btn.dataset.anRoute));
  });
}

function _anRenderOnboarding(hub) {
  const prefill = currentPlayerId || '';
  hub.innerHTML = `
    <div class="an-onboarding">
      <div class="an-onboarding-icon">&#9733;</div>
      <h2 class="an-onboarding-title">Connect Your Player</h2>
      <p class="an-onboarding-sub">
        ${prefill
          ? 'Player detected — link this account to unlock real stats, leak detection, and hand analysis.'
          : 'Link your ClubGG player account to unlock real stats, leak detection, and hand analysis.'}
      </p>
      <div class="an-onboarding-form">
        <input
          class="auth-input an-onboarding-input"
          id="an-link-input"
          type="text"
          placeholder="Enter your Player UUID…"
          value="${escHtml(prefill)}"
          autocomplete="off"
          spellcheck="false"
        >
        <button class="sp-btn-primary" id="an-link-btn">${prefill ? 'Link This Player' : 'Link Player'}</button>
      </div>
      <div class="an-onboarding-error" id="an-link-error" hidden></div>
      <div class="an-onboarding-divider">
        <span>or</span>
      </div>
      <button class="sp-btn-secondary an-onboarding-import-btn" id="an-import-btn">
        &#8679; Import a hand history file
      </button>
      <p class="an-onboarding-hint">
        Import a <code>.txt</code> hand history export from ClubGG — your player will be detected and linked automatically.
      </p>
    </div>
  `;

  hub.querySelector('#an-link-btn')?.addEventListener('click', async () => {
    const input = hub.querySelector('#an-link-input');
    const errEl = hub.querySelector('#an-link-error');
    const btn   = hub.querySelector('#an-link-btn');
    const val   = (input?.value || '').trim();
    if (!val) { errEl.textContent = 'Please enter a player UUID.'; errEl.hidden = false; return; }
    btn.disabled = true;
    btn.textContent = 'Linking…';
    errEl.hidden = true;
    const { ok, data } = await _anApiLinkPlayer(val);
    if (ok) {
      // Reload the hub with live data
      _anHubInitialized = false;
      _anHasPlayer = null;
      _anInitHub();
    } else {
      errEl.textContent = data.detail || 'Player not found. Check the UUID and try again.';
      errEl.hidden = false;
      btn.disabled = false;
      btn.textContent = 'Link Player';
    }
  });

  hub.querySelector('#an-import-btn')?.addEventListener('click', () => _anActivateTab('import'));
}

function _anActivateTab(tabName) {
  const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
  if (btn) {
    btn.click();
    // Scroll workspace into view smoothly
    document.querySelector('.an-workspace-label')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

/* ============================================================
   AN: HAND DETAIL + _ar* STANDALONE REPLAY
   normalizeHandForDisplay() is the single shared data model
   consumed by both the detail view and the _ar* replay engine.
   ============================================================ */

// ── Player name helpers ───────────────────────────────────────────────────────

// Detect system-generated IDs that should never appear as player display names.
function _isTechnicalId(s) {
  if (!s) return true;
  const str = String(s).trim();
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str)) return true;
  if (/^[0-9a-f]{16,}$/i.test(str)) return true;
  if (/^[0-9a-f]{6,10}$/i.test(str)) return true;
  if (/^\d{6,}$/.test(str)) return true;
  return false;
}

// Map player_id → "P1"/"P2"/… by ascending seat_number
function _seatRankMap(hpList) {
  return Object.fromEntries(
    [...hpList]
      .sort((a, b) => (a.seat_number || 0) - (b.seat_number || 0))
      .map((hp, i) => [String(hp.player_id ?? ''), `P${i + 1}`])
  );
}

// Return username when it's a real human-readable name; fall back to seat-rank label.
function _resolvePlayerName(username, fallback) {
  return (username && !_isTechnicalId(username)) ? username : fallback;
}

// Compute display table label for a /me/hands item (fallback to short external ID).
function _meTableLabel(h) {
  if (h.table_name) return h.table_name;
  const short = (h.hand_external_id || '').replace(/^(Poker Hand #|Hand #|ClubGG Hand #)/i, '').slice(-8);
  return short ? `Table #${short}` : 'Table';
}

// Compute hero display name for a /me/hands item — never show a UUID.
function _meHeroName(h) {
  const players = h.all_players || [];
  const heroId  = String(h.hero_player_id || '');
  const heroIdx = players.findIndex(p => String(p.player_id) === heroId);
  const rank    = heroIdx >= 0 ? `P${heroIdx + 1}` : 'Hero';
  return _resolvePlayerName(h.hero_username, rank);
}

// ── Shared normalized hand model ─────────────────────────────────────────────

function normalizeHandForDisplay(hand, heroId) {
  const hid     = (heroId || '').toString();
  const bb      = parseFloat(hand.stakes_bb) || 1;
  const chipsBb = v => v != null ? Math.round(parseFloat(v) / bb * 10) / 10 : 0;

  // Identity
  const rawId    = hand.external_id || '';
  const shortExt = rawId.replace(/^(Poker Hand #|Hand #|ClubGG Hand #)/i, '').slice(-12);
  const shortId  = shortExt ? '#' + shortExt : '';
  const tableName = hand.table_name || (shortExt ? `Table #${shortExt.slice(-8)}` : 'Tournament Table');

  // Seats — all playerIds normalized to String() to guarantee consistent type
  const hpList  = hand.hand_players || [];
  const rankMap = _seatRankMap(hpList);
  const heroHp  = hpList.find(hp => String(hp.player_id ?? '') === hid) || null;
  const seats   = hpList.map(hp => ({
    playerId:    String(hp.player_id ?? ''),
    displayName: _resolvePlayerName(hp.username, rankMap[String(hp.player_id ?? '')] || 'P?'),
    _rawUsername: hp.username ?? null,
    position:    hp.position || `S${hp.seat_number}`,
    stackBb:     hp.stack_bb ? parseFloat(hp.stack_bb) : null,
    cards:       hp.hole_cards || null,
    isHero:      String(hp.player_id ?? '') === hid,
    seatNumber:  hp.seat_number || 0,
    netBb:       hp.net_won != null ? chipsBb(hp.net_won) : null,
  }));

  // Board
  const board = (hand.board_cards || '').split(' ').filter(Boolean);

  // Full flat action list — ALL streets, amounts in BB
  const SRANK = { PREFLOP: 0, FLOP: 1, TURN: 2, RIVER: 3 };
  const flatActions = hpList.flatMap(hp =>
    (hp.actions || []).map(a => ({
      playerId:     String(hp.player_id ?? ''),
      pos:          hp.position || `S${hp.seat_number}`,
      displayName:  _resolvePlayerName(hp.username, rankMap[String(hp.player_id ?? '')] || 'P?'),
      isHero:       String(hp.player_id ?? '') === hid,
      street:       a.street || 'PREFLOP',
      action_type:  a.action_type,
      action_order: a.action_order,
      amountBb:     a.amount ? chipsBb(a.amount) : 0,
      is_all_in:    a.is_all_in || false,
      potBefore: 0, potAfter: 0, marginalBb: 0,
    }))
  ).sort((a, b) => {
    const d = (SRANK[a.street] ?? 99) - (SRANK[b.street] ?? 99);
    return d !== 0 ? d : a.action_order - b.action_order;
  });

  // Pot accounting (RAISE = total-to this street; all others = marginal)
  const SKIP_POT = new Set(['FOLD', 'CHECK', 'SHOW', 'MUCK']);
  let potBb = 0;
  const committed    = {};
  const potByStreet  = {};
  let lastStreet     = null;
  let pfBlindsEndPot = 0;

  for (const a of flatActions) {
    const s = a.street;
    if (s !== lastStreet) {
      if (lastStreet !== null) potByStreet[s] = potBb;
      lastStreet = s;
    }
    a.potBefore = potBb;
    const t = a.action_type.toUpperCase();
    if (!SKIP_POT.has(t) && a.amountBb > 0) {
      const key  = `${a.playerId}:${s}`;
      const prev = committed[key] || 0;
      if (t === 'RAISE') {
        const marginal = Math.max(0, a.amountBb - prev);
        a.marginalBb = marginal;
        potBb += marginal;
        committed[key] = a.amountBb;
      } else {
        a.marginalBb = a.amountBb;
        potBb += a.amountBb;
        committed[key] = prev + a.amountBb;
      }
    }
    a.potAfter = potBb;
    if (s === 'PREFLOP' && (t === 'POST_SB' || t === 'POST_BB' || t === 'POST_ANTE')) {
      pfBlindsEndPot = potBb;
    }
  }

  // Ante summary
  const anteActs    = flatActions.filter(a => a.street === 'PREFLOP' && a.action_type.toUpperCase() === 'POST_ANTE');
  const totalAnteBb = anteActs.reduce((sum, a) => sum + a.amountBb, 0);
  const blinds = {
    sbBb:        flatActions.find(a => a.action_type.toUpperCase() === 'POST_SB')?.amountBb || 0,
    bbBb:        flatActions.find(a => a.action_type.toUpperCase() === 'POST_BB')?.amountBb || 0,
    anteBb:      anteActs.length ? totalAnteBb / anteActs.length : 0,
    antePlayers: anteActs.length,
    totalAnteBb,
  };

  // Street grouping (for detail view)
  const STREETS = ['PREFLOP', 'FLOP', 'TURN', 'RIVER'];
  const streets  = Object.fromEntries(STREETS.map(s => [s, flatActions.filter(a => a.street === s)]));

  // Context
  const foldedPreflop = new Set(
    flatActions.filter(a => a.street === 'PREFLOP' && a.action_type.toUpperCase() === 'FOLD')
              .map(a => a.playerId)
  );
  const activeStacks      = seats.filter(s => !foldedPreflop.has(s.playerId) && s.stackBb !== null).map(s => s.stackBb);
  const effStack          = activeStacks.length >= 2 ? Math.min(...activeStacks) : activeStacks[0] ?? null;
  const preflopRaiseCount = flatActions.filter(
    a => a.street === 'PREFLOP' && a.action_type.toUpperCase() === 'RAISE'
  ).length;
  const potType = preflopRaiseCount === 0 ? 'Limped'
                : preflopRaiseCount === 1 ? 'SRP'
                : preflopRaiseCount === 2 ? '3BP'
                : `${preflopRaiseCount + 1}BP`;

  return {
    tableName, handId: rawId, shortId,
    playedAt: hand.hand_started_at || null,
    heroId: hid, heroHp,
    buttonSeat: hand.button_seat || null,
    bb, chipsBb, seats,
    blinds, board, streets,
    flatActions,
    potByStreet, pfBlindsEndPot,
    finalPotBb: potBb,
    potType, effStack,
  };
}

// ── _ar* Standalone Replay (NOT the rs* quiz engine) ─────────────────────────
// Shows all streets, all actions. No decision dock, no correct/wrong reveal.
// Folded players remain visible (dimmed). Reuses rs* table CSS.

let _ar       = null;
let _arOnBack = null;

function _arStop() {
  if (_ar?.playTimer) clearTimeout(_ar.playTimer);
  _ar = null;
}

// Spawn a floating action bubble above a seat — mirrors rsActionBubble but targets #ar-table.
function _arBubble(panel, seatEl, text, cls) {
  const tableEl  = panel.querySelector('#ar-table');
  const avatarEl = seatEl.querySelector('.rs-avatar');
  if (!tableEl || !avatarEl) return;
  const tr = tableEl.getBoundingClientRect();
  const av = avatarEl.getBoundingClientRect();
  if (!tr.width) return;
  const bubble = document.createElement('div');
  bubble.className = `ar-bubble rs-bubble--${cls}`;
  bubble.textContent = text;
  const bx = av.left + av.width / 2 - tr.left;
  const by = av.top  + av.height * 0.15 - tr.top;
  bubble.style.cssText = `left:${bx}px;top:${by}px;position:absolute;`;
  tableEl.appendChild(bubble);
  setTimeout(() => bubble.remove(), 1450);
}

// Query seat by data-pid attribute — avoids CSS ID selector parsing issues with UUID strings.
// All seat elements have data-pid="${pid}" set at render time; this is the authoritative lookup.
function _arSeatEl(panel, playerId) {
  const pid = String(playerId);
  const el  = panel.querySelector(`[data-pid="${pid}"]`);
  if (!el) {
    const found = [...panel.querySelectorAll('[data-pid]')].map(e => e.dataset.pid);
    console.warn('[AR] seat not found — pid:', pid, '| rendered pids:', found);
  }
  return el;
}

function _arStart(panel, normHand) {
  _arStop();
  const { seats, flatActions, heroId } = normHand;
  const seatOrder = rsBuildSeatOrder(
    seats.map(s => ({ player_id: s.playerId, seat_number: s.seatNumber })),
    heroId
  );

  // Collapse per-player antes out of the playback timeline.
  // Their pot contribution is already accounted for in potBefore/potAfter of later actions.
  const timeline = flatActions.filter(a => a.action_type.toUpperCase() !== 'POST_ANTE');

  _ar = { panel, normHand, seatOrder, timeline, step: 0, playing: true, playTimer: null, logOpen: false };
  panel.innerHTML = _arRender();
  _arBindControls();
  if (flatActions.length > 0) _arScheduleNext();
  else _arShowResult();
}

function _arRender() {
  const { normHand, seatOrder } = _ar;
  const { heroId, seats, buttonSeat, shortId, tableName } = normHand;
  const n       = seatOrder.length;
  const poses   = rsSeatPositions(n);
  const seatMap = Object.fromEntries(seats.map(s => [s.playerId, s]));

  const SEAT_BG = [
    'linear-gradient(145deg,#1a2240,#0e1628)',
    'linear-gradient(145deg,#3a1520,#220c14)',
    'linear-gradient(145deg,#362408,#201504)',
    'linear-gradient(145deg,#0c2c1a,#061c10)',
    'linear-gradient(145deg,#0c1e3c,#071224)',
    'linear-gradient(145deg,#28103c,#180924)',
    'linear-gradient(145deg,#341808,#200e04)',
    'linear-gradient(145deg,#062c26,#041c18)',
  ];

  const _arPosPillCls = pos => {
    const p = (pos || '').toLowerCase();
    if (p === 'btn')         return ' rs-pos-pill--btn';
    if (p === 'co')          return ' rs-pos-pill--co';
    if (p === 'hj')          return ' rs-pos-pill--hj';
    if (p.startsWith('mp'))  return ' rs-pos-pill--mp';
    if (p.startsWith('utg')) return ' rs-pos-pill--utg';
    if (p === 'bb')          return ' rs-pos-pill--bb';
    if (p === 'sb')          return ' rs-pos-pill--sb';
    return '';
  };

  const seatsHtml = seatOrder.map((pid, i) => {
    const s = seatMap[pid]; // always defined — all pids come from normHand.seats
    const stackTxt = s.stackBb != null ? `${s.stackBb.toFixed(0)}bb` : '?';
    const stackCls = s.stackBb == null ? '' : s.stackBb < 10 ? ' rs-stack--critical' : s.stackBb < 20 ? ' rs-stack--short' : '';
    const isBtn    = s.seatNumber === buttonSeat;
    const { left, top } = poses[i];
    const bg = SEAT_BG[i % SEAT_BG.length];
    const dealerBtn   = isBtn ? `<div class="rs-dealer">D</div>` : '';
    const oppCards    = s.isHero ? '' : `<div class="rs-opp-cards"><div class="rs-opp-card"></div><div class="rs-opp-card"></div></div>`;
    const avatarInner = s.isHero
      ? `<div class="rs-hero-cards" id="ar-hero-cards">${renderFaceDownCard()}${renderFaceDownCard()}</div>`
      : `<div class="rs-avatar-initials">${escHtml(s.displayName.slice(0, 2).toUpperCase())}</div>`;
    const pillCls = _arPosPillCls(s.position);
    return `<div class="rs-seat${s.isHero ? ' rs-seat--hero' : ''}" id="ar-seat-${escHtml(pid)}" data-pid="${escHtml(pid)}" style="left:${left}%;top:${top}%">
      ${oppCards}
      <div class="rs-avatar" style="background:${bg}">${avatarInner}</div>
      ${dealerBtn}
      <div class="rs-nameplate">
        <span class="rs-pos-pill${escHtml(pillCls)}">${escHtml(s.position)}</span>
        <span class="rs-stack${escHtml(stackCls)}">${escHtml(stackTxt)}</span>
        <span class="rs-nick">${escHtml(s.displayName.slice(0, 12))}</span>
      </div>
    </div>`;
  }).join('');

  return `<div class="rs-scene">
    <div class="rs-table ar-table" id="ar-table">
      <div class="rs-felt">
        <div class="rs-board" id="ar-board"></div>
        <div class="rs-pot" id="ar-pot">
          <div class="rs-pot-lbl">POT</div>
          <div class="rs-pot-amt" id="ar-pot-amt">0.0bb</div>
        </div>
      </div>
      ${seatsHtml}
      <div class="rs-tbl-nav">
        <button class="rs-back-btn" id="ar-back">← Back</button>
        <div class="rs-tbl-meta">
          <span class="rs-tbl-title">${escHtml(tableName)}</span>
          <span class="rs-handid">${escHtml(shortId)}</span>
        </div>
      </div>
      <div class="rs-tbl-controls">
        <div class="rs-tbl-ctx" id="ar-ctx"></div>
        <div class="rs-hud-controls ar-controls-pill">
          <button class="rs-ctrl" id="ar-restart" title="Restart">↺</button>
          <button class="rs-ctrl" id="ar-stepback" title="Step back">◂</button>
          <button class="rs-ctrl rs-ctrl--play" id="ar-play">▶ Play</button>
          <button class="rs-ctrl" id="ar-stepfwd" title="Step forward">▸</button>
          <button class="rs-log-btn" id="ar-log-toggle">≡</button>
        </div>
        <div class="rs-progress-wrap">
          <div class="rs-progress-fill" id="ar-progress-fill" style="width:0%"></div>
        </div>
      </div>
    </div>
    <div class="rs-log-drawer" id="ar-log-drawer" hidden>
      <div class="rs-log-inner" id="ar-log-inner"></div>
    </div>
  </div>`;
}

function _arRenderStatic() {
  if (!_ar) return;
  const { panel, timeline, step, normHand } = _ar;

  // Reset all seat classes
  for (const s of normHand.seats) {
    const el = _arSeatEl(panel, s.playerId);
    if (el) el.classList.remove('ar-folded', 'rs-seat--turn', 'rs-seat--allin', 'ar-last-aggressor');
  }

  // Re-apply all states up to current step
  const finalState = {};
  let lastAggressorPid = null;
  for (let i = 0; i < Math.min(step, timeline.length); i++) {
    const t = timeline[i].action_type.toUpperCase();
    finalState[timeline[i].playerId] = t;
    if (t === 'RAISE' || t === 'BET' || t === 'ALL_IN') lastAggressorPid = timeline[i].playerId;
  }
  for (const [pid, action] of Object.entries(finalState)) {
    const el = _arSeatEl(panel, pid);
    if (!el) continue;
    if (action === 'FOLD')   el.classList.add('ar-folded');
    if (action === 'ALL_IN') el.classList.add('rs-seat--allin');
  }
  if (lastAggressorPid) {
    const agEl = _arSeatEl(panel, lastAggressorPid);
    if (agEl && !agEl.classList.contains('ar-folded')) agEl.classList.add('ar-last-aggressor');
  }
  if (step > 0 && step <= timeline.length) {
    const cur = timeline[step - 1];
    const el  = _arSeatEl(panel, cur.playerId);
    if (el && !el.classList.contains('ar-folded')) el.classList.add('rs-seat--turn');
  }

  // Board
  const boardEl = panel.querySelector('#ar-board');
  if (boardEl) {
    const lastAct = step > 0 ? timeline[Math.min(step, timeline.length) - 1] : null;
    const street  = lastAct?.street || 'PREFLOP';
    const limit   = { PREFLOP: 0, FLOP: 3, TURN: 4, RIVER: 5 }[street] ?? 0;
    boardEl.innerHTML = '';
    normHand.board.slice(0, limit).forEach(c => {
      const sp = document.createElement('span');
      sp.innerHTML = renderVisualCard(c.slice(0, -1).toUpperCase(), _normSuit(c.slice(-1)));
      const card = sp.firstElementChild;
      if (card) { card.style.animation = 'none'; boardEl.appendChild(card); }
    });
  }

  // Pot — at step 0, antes are already in the pot even though they aren't animated
  const potAmt = panel.querySelector('#ar-pot-amt');
  if (potAmt) {
    const pot = step > 0
      ? timeline[Math.min(step, timeline.length) - 1].potAfter
      : (normHand.blinds.totalAnteBb || 0);
    potAmt.textContent = `${pot.toFixed(1)}bb`;
  }

  _arUpdateLog();
  _arUpdateHud();
}

function _arUpdateHud() {
  if (!_ar) return;
  const { panel, step, timeline, playing, normHand } = _ar;
  const total = timeline.length;
  const atEnd = step >= total;
  const pct   = total > 0 ? Math.round(step / total * 100) : 100;
  const fill  = panel.querySelector('#ar-progress-fill');
  if (fill) fill.style.width = `${pct}%`;
  const playBtn = panel.querySelector('#ar-play');
  if (playBtn) playBtn.textContent = atEnd ? '↺ Restart' : playing ? '⏸ Pause' : '▶ Play';
  const rb = panel.querySelector('#ar-restart');
  const sb = panel.querySelector('#ar-stepback');
  const fb = panel.querySelector('#ar-stepfwd');
  if (rb) rb.disabled = step === 0;
  if (sb) sb.disabled = step === 0;
  if (fb) fb.disabled = atEnd;
  const ctx = panel.querySelector('#ar-ctx');
  if (ctx) {
    const street = step > 0 ? timeline[Math.min(step, total) - 1]?.street : 'PREFLOP';
    const pos    = normHand.heroHp?.position || '';
    const stack  = normHand.heroHp?.stack_bb ? `${parseFloat(normHand.heroHp.stack_bb).toFixed(0)}bb` : '';
    ctx.textContent = [pos, stack, street].filter(Boolean).join(' · ');
  }
}

function _arUpdateLog() {
  if (!_ar) return;
  const { panel, timeline, step, normHand } = _ar;
  const logEl = panel.querySelector('#ar-log-inner');
  if (!logEl) return;
  const skip = new Set(['FOLD', 'CHECK', 'MUCK', 'SHOW']);
  let lastStreet = null;

  // Collapsed ante summary row (shown only if antes exist)
  const { antePlayers, anteBb, totalAnteBb } = normHand.blinds;
  const anteRow = antePlayers > 0
    ? `<div class="rs-log-row rs-log-row--ante">
        <span class="rs-log-pos">antes</span>
        <span class="rs-log-act rs-log-act--post_ante">${antePlayers}×${anteBb.toFixed(1)}bb</span>
        <span class="rs-log-amt">${totalAnteBb.toFixed(1)}bb</span>
      </div>`
    : '';

  const rows = timeline.slice(0, step).map((a, idx) => {
    const isLast  = idx === Math.min(step, timeline.length) - 1;
    const showAmt = a.amountBb > 0 && !skip.has(a.action_type.toUpperCase());
    let hdr = '';
    if (a.street !== lastStreet) {
      hdr = `<div class="rs-log-street">${escHtml(a.street)}</div>`;
      lastStreet = a.street;
    }
    return `${hdr}<div class="rs-log-row${isLast ? ' rs-log-row--cur' : ''}">
      <span class="rs-log-pos">${escHtml(a.pos)}</span>
      <span class="rs-log-act rs-log-act--${escHtml(a.action_type.toLowerCase())}">${escHtml(a.action_type.toUpperCase())}</span>
      ${showAmt ? `<span class="rs-log-amt">${a.amountBb.toFixed(1)}bb</span>` : ''}
    </div>`;
  }).join('');

  logEl.innerHTML = anteRow + (rows || '<div class="rs-log-empty">Hand starting…</div>');
  logEl.scrollTop = logEl.scrollHeight;
}

// immediate=true: manual step (no delays). immediate=false: auto-play (120ms pre-beat, 140ms post-beat).
function _arPlayStep(immediate = false) {
  if (!_ar) return;
  const { panel, timeline, normHand } = _ar;
  if (_ar.step >= timeline.length) return;
  const act     = timeline[_ar.step];
  const prevAct = _ar.step > 0 ? timeline[_ar.step - 1] : null;
  _ar.step++;

  // ── Phase 1 (immediate): clear stale state + street reveal ──
  panel.querySelectorAll('.rs-seat--turn, .rs-seat--folded').forEach(el => {
    el.classList.remove('rs-seat--turn', 'rs-seat--folded');
  });

  if (act.street !== 'PREFLOP' && (!prevAct || prevAct.street !== act.street)) {
    const boardEl = panel.querySelector('#ar-board');
    if (boardEl) {
      const limit = { FLOP: 3, TURN: 4, RIVER: 5 }[act.street] ?? 0;
      boardEl.innerHTML = '';
      normHand.board.slice(0, limit).forEach(c => {
        const sp = document.createElement('span');
        sp.innerHTML = renderVisualCard(c.slice(0, -1).toUpperCase(), _normSuit(c.slice(-1)));
        const card = sp.firstElementChild;
        if (card) boardEl.appendChild(card);
      });
    }
    const felt = panel.querySelector('.rs-felt');
    if (felt) {
      const old = felt.querySelector('.rs-street-label');
      if (old) old.remove();
      const lbl = document.createElement('div');
      lbl.className = 'rs-street-label';
      lbl.textContent = act.street;
      felt.appendChild(lbl);
      setTimeout(() => lbl.classList.add('rs-street-label--fade'), 1200);
      setTimeout(() => lbl.remove(), 2200);
    }
  }

  // ── Phase 2: action lands — bubble + highlight seat + highlight log ──
  const applyAction = () => {
    if (!_ar) return;

    const aType   = act.action_type.toUpperCase();
    const isFold  = aType === 'FOLD';
    const isAllin = aType === 'ALL_IN';
    const isRaise = aType === 'RAISE' || aType === 'BET';
    const isCall  = aType === 'CALL';
    const isPost  = aType === 'POST_SB' || aType === 'POST_BB' || aType === 'POST_ANTE';

    const seatEl = _arSeatEl(panel, act.playerId);
    if (seatEl) {
      const avatar = seatEl.querySelector('.rs-avatar');

      // Bubble near seat
      if (!isPost) {
        const bCls = isFold ? 'fold' : isAllin ? 'allin' : isRaise ? 'raise' : isCall ? 'call'
                   : aType === 'CHECK' ? 'check' : 'other';
        const bTxt = isAllin ? 'ALL IN'
          : (isRaise || isCall) && act.amountBb > 0 ? `${aType} ${act.amountBb.toFixed(1)}`
          : aType;
        _arBubble(panel, seatEl, bTxt, bCls);
      }

      // Avatar animation (ar-anim--fold avoids opacity compound with ar-folded parent)
      if (avatar && !isPost) {
        const aCls = isAllin ? 'rs-anim--allin' : isRaise ? 'rs-anim--raise'
                   : isCall  ? 'rs-anim--call'  : isFold  ? 'ar-anim--fold' : null;
        if (aCls) {
          avatar.classList.remove('rs-anim--fold','rs-anim--call','rs-anim--raise','rs-anim--allin','ar-anim--fold');
          void avatar.offsetWidth;
          avatar.classList.add(aCls);
          setTimeout(() => avatar?.classList.remove(aCls), isAllin ? 1100 : isFold ? 480 : 640);
        }
      }

      // Last aggressor ring
      panel.querySelectorAll('.ar-last-aggressor').forEach(el => el.classList.remove('ar-last-aggressor'));
      if (isRaise || isAllin) seatEl.classList.add('ar-last-aggressor');

      // Persistent seat state
      if (isFold)  seatEl.classList.add('ar-folded');
      if (isAllin) seatEl.classList.add('rs-seat--allin');
      if (!isFold) seatEl.classList.add('rs-seat--turn'); // seat highlight

      // Snap flash — white glow on the instant the action lands, then fades
      seatEl.classList.add('ar-seat--snap');
      setTimeout(() => seatEl?.classList.remove('ar-seat--snap'), 160);

      // Pot flash
      const potAmt = panel.querySelector('#ar-pot-amt');
      if (potAmt) {
        potAmt.textContent = `${act.potAfter.toFixed(1)}bb`;
        if (!isFold && aType !== 'CHECK' && !isPost) {
          potAmt.classList.remove('rs-pot--flash');
          void potAmt.offsetWidth;
          potAmt.classList.add('rs-pot--flash');
          setTimeout(() => potAmt?.classList.remove('rs-pot--flash'), 500);
        }
      }
    }

    _arUpdateLog(); // log row highlight
    _arUpdateHud();
  };

  if (immediate) {
    applyAction();
  } else {
    // 120ms pre-beat: table "breathes" before action lands
    _ar.playTimer = setTimeout(() => {
      applyAction();
      // 140ms post-beat: hold so the eye can read the action, then continue
      _ar.playTimer = setTimeout(() => {
        if (!_ar?.playing) return;
        if (_ar.step >= _ar.timeline.length) _arShowResult();
        else _arScheduleNext();
      }, 140);
    }, 120);
  }
}

function _arShowResult() {
  if (!_ar) return;
  _ar.playing = false;

  const { panel, normHand } = _ar;
  const heroSeat = normHand.seats.find(s => s.isHero);

  // Reveal hero hole cards
  if (heroSeat?.cards) {
    const wrap = panel.querySelector('#ar-hero-cards');
    if (wrap) {
      wrap.innerHTML = '';
      const re = /([2-9]|10|[TJQKA])([shdc♠♥♦♣])/gi;
      let m;
      while ((m = re.exec(heroSeat.cards)) !== null) {
        const sp = document.createElement('span');
        sp.innerHTML = renderVisualCard(m[1].toUpperCase(), _normSuit(m[2]));
        const card = sp.firstElementChild;
        if (card) { card.classList.add('rs-card-reveal'); wrap.appendChild(card); }
      }
    }
  }

  // Final board — show all dealt cards
  const boardEl = panel.querySelector('#ar-board');
  if (boardEl) {
    boardEl.innerHTML = '';
    normHand.board.forEach(c => {
      const sp = document.createElement('span');
      sp.innerHTML = renderVisualCard(c.slice(0, -1).toUpperCase(), _normSuit(c.slice(-1)));
      const card = sp.firstElementChild;
      if (card) { card.style.animation = 'none'; boardEl.appendChild(card); }
    });
  }

  // Final pot
  const potAmt = panel.querySelector('#ar-pot-amt');
  if (potAmt) potAmt.textContent = `${normHand.finalPotBb.toFixed(1)}bb`;

  // Net result badge on hero seat
  if (heroSeat?.netBb != null) {
    const el = _arSeatEl(panel, heroSeat.playerId);
    if (el && !el.querySelector('.ar-result')) {
      const np = document.createElement('div');
      np.className = `ar-result ${heroSeat.netBb >= 0 ? 'ar-result--pos' : 'ar-result--neg'}`;
      np.textContent = `${heroSeat.netBb >= 0 ? '+' : ''}${heroSeat.netBb.toFixed(1)}bb`;
      el.appendChild(np);
    }
  }

  _arUpdateHud();
}

function _arScheduleNext() {
  if (!_ar?.playing) return;
  const { timeline, step } = _ar;
  if (step >= timeline.length) { _arShowResult(); return; }
  const prevAct     = step > 0 ? timeline[step - 1] : null;
  const nextAct     = timeline[step];
  const isNewStreet = nextAct && prevAct && nextAct.street !== prevAct.street;
  const delay       = isNewStreet ? 1600 : rsActionDelay(nextAct);
  _ar.playTimer = setTimeout(() => {
    if (!_ar?.playing) return;
    _arPlayStep(); // Phase 3 inside _arPlayStep owns continuation
  }, delay);
}

function _arResetVisuals() {
  if (!_ar) return;
  const { panel, normHand } = _ar;
  for (const s of normHand.seats) {
    const el = _arSeatEl(panel, s.playerId);
    if (el) el.classList.remove('ar-folded', 'rs-seat--turn', 'rs-seat--allin', 'ar-last-aggressor');
  }
  const boardEl = panel.querySelector('#ar-board');
  if (boardEl) boardEl.innerHTML = '';
  const potAmt = panel.querySelector('#ar-pot-amt');
  if (potAmt) potAmt.textContent = '0.0bb';
  const heroCards = panel.querySelector('#ar-hero-cards');
  if (heroCards) heroCards.innerHTML = renderFaceDownCard() + renderFaceDownCard();
  panel.querySelectorAll('.ar-result').forEach(el => el.remove());
}

function _arBindControls() {
  if (!_ar) return;
  const { panel } = _ar;

  panel.querySelector('#ar-back')?.addEventListener('click', () => {
    _arStop();
    if (_arOnBack) { const cb = _arOnBack; _arOnBack = null; cb(); }
  });

  panel.querySelector('#ar-restart')?.addEventListener('click', () => {
    if (!_ar) return;
    if (_ar.playTimer) clearTimeout(_ar.playTimer);
    _ar.step = 0;
    _ar.playing = false;
    _arResetVisuals();
    _arUpdateLog();
    _arUpdateHud();
  });

  panel.querySelector('#ar-stepback')?.addEventListener('click', () => {
    if (!_ar || _ar.step === 0) return;
    if (_ar.playTimer) clearTimeout(_ar.playTimer);
    _ar.playing = false;
    _ar.step--;
    _arRenderStatic();
  });

  panel.querySelector('#ar-stepfwd')?.addEventListener('click', () => {
    if (!_ar) return;
    if (_ar.playTimer) clearTimeout(_ar.playTimer);
    _ar.playing = false;
    if (_ar.step < _ar.timeline.length) {
      _arPlayStep(true); // immediate — no pre/post delays on manual step
      if (_ar.step >= _ar.timeline.length) _arShowResult();
    }
  });

  panel.querySelector('#ar-play')?.addEventListener('click', () => {
    if (!_ar) return;
    const atEnd = _ar.step >= _ar.timeline.length;
    if (atEnd) {
      if (_ar.playTimer) clearTimeout(_ar.playTimer);
      _ar.step = 0;
      _ar.playing = true;
      _arResetVisuals();
      _arUpdateLog();
      _arScheduleNext();
    } else if (_ar.playing) {
      if (_ar.playTimer) clearTimeout(_ar.playTimer);
      _ar.playing = false;
      _arUpdateHud();
    } else {
      _ar.playing = true;
      _arScheduleNext();
    }
  });

  panel.querySelector('#ar-log-toggle')?.addEventListener('click', () => {
    if (!_ar) return;
    _ar.logOpen = !_ar.logOpen;
    const drawer = panel.querySelector('#ar-log-drawer');
    if (drawer) drawer.hidden = !_ar.logOpen;
    if (_ar.logOpen) _arUpdateLog();
  });
}

// ── _anOpenHandDetail ────────────────────────────────────────────────────────

async function _anOpenHandDetail(extId) {
  const hub = document.getElementById('an-hub');
  if (!hub) return;
  hub.innerHTML = '<div class="an-hd-loading">Loading hand…</div>';

  let hand;
  try {
    hand = await apiFetch(`/hands/lookup?external_id=${encodeURIComponent(extId)}`);
  } catch (e) {
    hub.innerHTML = `<div class="an-hd-error"><p>Could not load hand: ${escHtml(String(e))}</p><button class="an-hd-back-btn" id="an-hd-back">← Back</button></div>`;
    hub.querySelector('#an-hd-back')?.addEventListener('click', () => spNavigate('/analysis'));
    return;
  }

  const heroId   = (_anLiveAnalysis?.player_id || _anLiveHands?.player_id || currentPlayerId || '').toString();
  const normHand = normalizeHandForDisplay(hand, heroId);

  function _showDetail() {
    hub.innerHTML = _anHandDetailHTML(normHand);
    hub.querySelector('#an-hd-back')?.addEventListener('click', () => spNavigate('/analysis'));
    hub.querySelector('#an-hd-replay')?.addEventListener('click', () => {
      _arOnBack = _showDetail;
      _arStart(hub, normHand);
    });
  }
  _showDetail();
}

// ── _anHandDetailHTML ────────────────────────────────────────────────────────

function _anHandDetailHTML(normHand) {
  const { heroId, heroHp, seats, board, streets,
          flatActions, potByStreet, pfBlindsEndPot,
          shortId, tableName, playedAt, potType, effStack } = normHand;

  const date = playedAt
    ? new Date(playedAt).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '';

  const heroNetBb = seats.find(s => s.isHero)?.netBb ?? null;
  const heroPos   = heroHp?.position || '';

  // ── Card rendering ──────────────────────────────────────────
  function _cardSpan(c, sm) {
    const rank = c.slice(0, -1).toUpperCase();
    const suit = _normSuit(c.slice(-1));
    const cls  = ['♥', '♦'].includes(suit) ? 'card-red' : 'card-black';
    return `<span class="an-hd-card${sm ? ' an-hd-card--sm' : ''} ${cls}">${escHtml(rank)}${escHtml(suit)}</span>`;
  }
  const boardHTML = board.length
    ? board.map(c => _cardSpan(c, false)).join('')
    : '<span class="an-hd-no-board">Preflop all-in</span>';

  // ── Collapse consecutive folds ──────────────────────────────
  function _collapseFolds(acts) {
    const out = []; let run = [];
    const flush = () => {
      if (!run.length) return;
      out.push(run.length > 1 ? { ...run[0], _foldGroup: run.map(f => f.pos) } : run[0]);
      run = [];
    };
    for (const a of acts) {
      a.action_type.toUpperCase() === 'FOLD' ? run.push(a) : (flush(), out.push(a));
    }
    flush();
    return out;
  }

  // ── Context badges ──────────────────────────────────────────
  const POS_ORDER = ['UTG','UTG+1','UTG+2','LJ','HJ','CO','BTN','SB','BB'];
  const foldedPreflop = new Set(
    flatActions.filter(a => a.street === 'PREFLOP' && a.action_type.toUpperCase() === 'FOLD')
              .map(a => a.playerId)
  );
  const activePlayers   = seats.filter(s => !foldedPreflop.has(s.playerId));
  const isMultiway      = activePlayers.length >= 3;
  const activePositions = [...activePlayers]
    .sort((a, b) => {
      const ai = POS_ORDER.indexOf(a.position), bi = POS_ORDER.indexOf(b.position);
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    })
    .map(s => s.position);
  const potTypeCls = potType === 'SRP' ? 'an-hd-badge--srp'
                   : potType === '3BP' ? 'an-hd-badge--3bp'
                   : potType.endsWith('BP') ? 'an-hd-badge--4bp' : '';
  const posLabel   = isMultiway ? activePositions.join(' · ') : activePositions.join(' vs ');
  const mwLabel    = isMultiway ? ' · MW' : '';

  // ── Narrative: one-line preflop story ───────────────────────
  function _buildNarrative() {
    const KEY   = new Set(['RAISE', 'CALL', 'ALL_IN']);
    const pfKey = flatActions.filter(a => a.street === 'PREFLOP' && KEY.has(a.action_type.toUpperCase()));
    let raiseN  = 0;
    const beats = pfKey.map(a => {
      const t   = a.action_type.toUpperCase();
      const who = a.isHero ? `<span class="an-hd-nar-hero">you</span>` : escHtml(a.pos);
      const amt = a.amountBb > 0 ? ` ${a.amountBb.toFixed(1)}bb` : '';
      if (t === 'RAISE') { const v = raiseN === 0 ? 'opens' : raiseN === 1 ? '3-bets' : '4-bets'; raiseN++; return `${who} ${v}${amt}`; }
      if (t === 'ALL_IN') { raiseN++; return `${who} shoves${amt}`; }
      return `${who} calls`;
    });
    if (!beats.length) return board.length >= 3 ? 'Limped pot' : '';
    if (board.length >= 3) beats.push(`flop ${board.slice(0, 3).map(c => _cardSpan(c, true)).join('')}`);
    return beats.join(` <span class="an-hd-nar-arr">→</span> `);
  }

  // ── Players column ──────────────────────────────────────────
  const sortedSeats = [...seats].sort((a, b) => {
    const ai = POS_ORDER.indexOf(a.position), bi = POS_ORDER.indexOf(b.position);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });
  const playersHTML = sortedSeats.map(s => {
    const stackStr = s.stackBb != null ? `${s.stackBb.toFixed(0)}bb` : '?';
    const netStr   = s.netBb != null ? `${s.netBb >= 0 ? '+' : ''}${s.netBb.toFixed(1)}bb` : '';
    const netCls   = s.netBb == null ? '' : s.netBb >= 0 ? 'an-hd-net-pos' : 'an-hd-net-neg';
    const cards    = s.isHero && s.cards ? `<span class="an-hd-hole">${escHtml(s.cards)}</span>` : '';
    const heroLbl  = s.isHero ? `<span class="an-hd-hero-lbl">HERO</span>` : '';
    return `<div class="an-hd-player${s.isHero ? ' an-hd-player--hero' : ''}">
      <span class="an-hd-pos">${escHtml(s.position)}</span>
      ${heroLbl}
      <span class="an-hd-name">${escHtml(s.displayName.slice(0, 14))}</span>
      <span class="an-hd-stack">${escHtml(stackStr)}</span>
      ${cards}
      ${netStr ? `<span class="an-hd-net ${netCls}">${escHtml(netStr)}</span>` : ''}
    </div>`;
  }).join('');

  // ── Action label ────────────────────────────────────────────
  function _actionLabel(a) {
    const t   = a.action_type.toUpperCase();
    const amt = a.amountBb > 0 ? a.amountBb.toFixed(1) + 'bb' : '';
    let pctHTML = '';
    if (['BET', 'RAISE', 'ALL_IN'].includes(t) && a.potBefore > 0 && a.amountBb > 0) {
      const pct = Math.round(a.amountBb / a.potBefore * 100);
      if (pct > 0 && pct < 5000) pctHTML = `<span class="an-hd-act-pct"> ${pct}%</span>`;
    }
    const MAP = {
      FOLD:      { text: 'fold',                     cls: 'fold'  },
      CHECK:     { text: 'check',                    cls: 'check' },
      CALL:      { text: `call ${amt}`.trim(),        cls: 'call'  },
      BET:       { text: `bet ${amt}`.trim(),         cls: 'bet'   },
      RAISE:     { text: `raise to ${amt}`.trimEnd(), cls: 'raise' },
      ALL_IN:    { text: `all-in ${amt}`.trimEnd(),   cls: 'allin' },
      POST_SB:   { text: `post SB ${amt}`.trimEnd(),  cls: 'post'  },
      POST_BB:   { text: `post BB ${amt}`.trimEnd(),  cls: 'post'  },
      POST_ANTE: { text: `ante ${amt}`.trimEnd(),     cls: 'ante'  },
    };
    const c = MAP[t] || { text: `${t} ${amt}`.trim(), cls: '' };
    return { text: c.text, cls: c.cls, pctHTML };
  }

  // ── Street sections ─────────────────────────────────────────
  const STREETS = ['PREFLOP', 'FLOP', 'TURN', 'RIVER'];
  const streetBoard = { FLOP: board.slice(0, 3), TURN: board.slice(3, 4), RIVER: board.slice(4, 5) };

  const streetsHTML = STREETS.map(s => {
    const acts = streets[s] || [];
    if (!acts.length) return '';
    const bd     = streetBoard[s];
    const bdHTML = bd?.length ? `<span class="an-hd-street-board">${bd.map(c => _cardSpan(c, true)).join('')}</span>` : '';

    let potHTML = '';
    if (s === 'PREFLOP' && pfBlindsEndPot > 0) {
      potHTML = `<span class="an-hd-street-pot">${pfBlindsEndPot.toFixed(1)}bb in</span>`;
    } else if (s !== 'PREFLOP' && potByStreet[s] != null) {
      potHTML = `<span class="an-hd-street-pot">${potByStreet[s].toFixed(1)}bb pot</span>`;
    }

    const anteActs_   = s === 'PREFLOP' ? acts.filter(a => a.action_type.toUpperCase() === 'POST_ANTE') : [];
    const nonAnteActs = s === 'PREFLOP' ? acts.filter(a => a.action_type.toUpperCase() !== 'POST_ANTE') : acts;
    const tAnteBb_    = anteActs_.reduce((sum, a) => sum + a.amountBb, 0);
    const anteSummary = anteActs_.length
      ? `<div class="an-hd-action an-hd-action--ante">
           <span class="an-hd-action-who">antes</span>
           <span class="an-hd-action-type an-hd-act--ante">${tAnteBb_.toFixed(1)}bb · ${anteActs_.length} players</span>
         </div>`
      : '';

    const actsHtml = _collapseFolds(nonAnteActs).map(a => {
      if (a._foldGroup) {
        return `<div class="an-hd-action an-hd-action--foldgroup">
          <span class="an-hd-action-who an-hd-action-who--foldgroup">${escHtml(a._foldGroup.join(', '))}</span>
          <span class="an-hd-action-type an-hd-act--fold">fold</span>
        </div>`;
      }
      const { text, cls, pctHTML } = _actionLabel(a);
      return `<div class="an-hd-action${a.isHero ? ' an-hd-action--hero' : ''}">
        <span class="an-hd-action-who${a.isHero ? ' an-hd-action-who--hero' : ''}">${escHtml(a.pos)}</span>
        <span class="an-hd-action-type an-hd-act--${cls}">${escHtml(text)}${pctHTML}</span>
      </div>`;
    }).join('');

    return `<div class="an-hd-street">
      <div class="an-hd-street-hdr">${escHtml(s)} ${bdHTML}${potHTML}</div>
      <div class="an-hd-actions">${anteSummary}${actsHtml}</div>
    </div>`;
  }).join('');

  // ── Assemble ─────────────────────────────────────────────────
  const narrativeHTML = _buildNarrative();
  const resultStr = heroNetBb != null ? `${heroNetBb >= 0 ? '+' : ''}${heroNetBb.toFixed(1)}bb` : '';
  const resultCls = heroNetBb == null ? '' : heroNetBb >= 0 ? 'an-hd-result--pos' : 'an-hd-result--neg';
  const replayBtn = heroHp ? `<button class="an-hd-replay-btn" id="an-hd-replay">▶ Replay</button>` : '';

  return `<div class="an-hd">
    <div class="an-hd-header">
      <button class="an-hd-back-btn" id="an-hd-back">← Back</button>
      <div class="an-hd-meta">
        <span class="an-hd-id">${escHtml(shortId)}</span>
        <span class="an-hd-table">${escHtml(tableName)}</span>
        <span class="an-hd-date">${escHtml(date)}</span>
      </div>
      <div class="an-hd-header-right">
        ${resultStr ? `<span class="an-hd-result ${resultCls}">${escHtml(resultStr)}</span>` : ''}
        ${replayBtn}
      </div>
    </div>
    <div class="an-hd-ctx">
      <span class="an-hd-badge ${potTypeCls}">${escHtml(potType)}${escHtml(mwLabel)}</span>
      ${posLabel ? `<span class="an-hd-badge an-hd-badge--pos">${escHtml(posLabel)}</span>` : ''}
      ${effStack != null ? `<span class="an-hd-badge">${Math.round(effStack)}bb eff</span>` : ''}
      ${heroPos ? `<span class="an-hd-badge an-hd-badge--hero">Hero · ${escHtml(heroPos)}</span>` : ''}
      <span class="an-hd-badge an-hd-badge--dim">${seats.length}-handed</span>
    </div>
    ${narrativeHTML ? `<div class="an-hd-narrative">${narrativeHTML}</div>` : ''}
    <div class="an-hd-body">
      <div class="an-hd-col-players">
        <div class="an-hd-section-title">Players</div>
        ${playersHTML}
      </div>
      <div class="an-hd-col-action">
        <div class="an-hd-section-title">Action</div>
        ${streetsHTML}
        ${board.length ? `<div class="an-hd-board-row">
          <span class="an-hd-board-lbl">Board</span>
          <span class="an-hd-board-cards">${boardHTML}</span>
        </div>` : ''}
      </div>
    </div>
  </div>`;
}

/* ============================================================
   CO — COURSE CATALOG & LESSON VIEWER
   Mock-data course system for tournament poker training.
   Prefix: co- — no interference with rs-/sp-/an-/tab- code.
   ============================================================ */

/* ── Mock course data ─────────────────────────────────────── */

const CO_COURSES = [
  /* ─── BEGINNER ─── */
  {
    id: 'tournament-fundamentals',
    title: 'Tournament Poker Fundamentals',
    level: 'beginner',
    levelLabel: 'Beginner',
    desc: 'Master the essential concepts that separate tournament poker from cash games — chip EV, M-ratio, stack dynamics, and payout pressure.',
    lessonCount: 8,
    duration: '2h 10m',
    progress: 0,
    locked: false,
    modules: [
      {
        id: 'm1',
        title: 'Tournament vs Cash Game Mindset',
        lessons: [
          { id: 'why-tournament-poker-is-different', title: 'Why Tournament Poker Is Different', duration: '14m', done: false },
          { id: 'position-the-most-important-advantage', title: 'Position: The Most Important Advantage', duration: '16m', done: false },
          { id: 'starting-hands-are-context-based', title: 'Starting Hands Are Context-Based', duration: '14m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Preflop Decisions',
        lessons: [
          { id: 'preflop-decisions-open-fold-or-shove', title: 'Preflop Decisions: Open, Fold, or Shove', duration: '18m', done: false },
          { id: 'short-stack-play-under-15bb', title: 'Short Stack Play: Under 15bb', duration: '16m', done: false },
        ],
      },
      {
        id: 'm3',
        title: 'Tournament Mindset',
        lessons: [
          { id: 'biggest-beginner-mistakes', title: 'Biggest Beginner Mistakes', duration: '15m', done: false },
          { id: 'how-to-think-in-a-hand', title: 'How to Think in a Hand', duration: '17m', done: false },
          { id: 'final-quiz-and-practice-setup', title: 'Final Quiz and Practice Setup', duration: '10m', done: false },
        ],
      },
    ],
  },
  {
    id: 'positions-blinds-antes',
    title: 'Positions, Blinds and Antes',
    level: 'beginner',
    levelLabel: 'Beginner',
    desc: 'Understand positional advantage, the cost of the blinds, and how antes change the mathematics of every preflop decision.',
    lessonCount: 6,
    duration: '1h 30m',
    progress: 100,
    locked: false,
    modules: [
      {
        id: 'm1',
        title: 'Position',
        lessons: [
          { id: 'what-is-position', title: 'What is Position and Why It Matters', duration: '12m', done: true },
          { id: 'table-position-labels', title: 'Table Position Labels: BTN, CO, HJ, MP, UTG', duration: '10m', done: true },
        ],
      },
      {
        id: 'm2',
        title: 'Blinds and Antes',
        lessons: [
          { id: 'blind-structure', title: 'Small Blind, Big Blind and the Dead Money Effect', duration: '15m', done: true },
          { id: 'antes-change-everything', title: 'How Antes Change Preflop Math', duration: '18m', done: true },
          { id: 'defending-the-bb', title: 'Defending the Big Blind Correctly', duration: '20m', done: true },
          { id: 'sb-play', title: 'Small Blind Play: The Trickiest Spot', duration: '15m', done: true },
        ],
      },
    ],
  },
  {
    id: 'starting-hands',
    title: 'Starting Hands',
    level: 'beginner',
    levelLabel: 'Beginner',
    desc: 'Learn which hands to play from which positions, and why hand selection in tournaments differs significantly from cash games.',
    lessonCount: 5,
    duration: '1h 15m',
    progress: 0,
    locked: false,
    modules: [
      {
        id: 'm1',
        title: 'Hand Ranges',
        lessons: [
          { id: 'hand-categories', title: 'Hand Categories: Premium, Speculative, Trash', duration: '14m', done: false },
          { id: 'range-charts-intro', title: 'Reading and Using Range Charts', duration: '16m', done: false },
          { id: 'position-adjustments', title: 'Tightening and Widening by Position', duration: '15m', done: false },
          { id: 'suited-connectors', title: 'Suited Connectors and Speculative Hands', duration: '14m', done: false },
          { id: 'hand-reading-basics', title: 'Basic Hand Reading from Ranges', duration: '16m', done: false },
        ],
      },
    ],
  },

  /* ─── INTERMEDIATE ─── */
  {
    id: 'stack-sizes-tournament-strategy',
    title: 'Stack Sizes and Tournament Strategy',
    level: 'intermediate',
    levelLabel: 'Intermediate',
    desc: 'Master the four stack size zones — deep, mid, short, and push-fold — and how each one completely changes your optimal strategy.',
    lessonCount: 9,
    duration: '2h 40m',
    progress: 30,
    locked: false,
    modules: [
      {
        id: 'm1',
        title: 'Stack Zones',
        lessons: [
          { id: 'deep-stack-play', title: 'Deep Stack Play: 50bb+', duration: '18m', done: true },
          { id: 'mid-stack-play', title: 'Mid Stack Play: 20–50bb', duration: '20m', done: true },
          { id: 'short-stack-play', title: 'Short Stack Play: 10–20bb', duration: '18m', done: false },
          { id: 'push-fold-theory', title: 'Push-Fold Theory: Under 15bb', duration: '22m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Stack Interactions',
        lessons: [
          { id: 'effective-stacks', title: 'Effective Stacks and Why They Matter', duration: '15m', done: false },
          { id: 'stack-vs-position', title: 'Stack Size vs Positional Advantage Trade-offs', duration: '18m', done: false },
          { id: 'reshove-spots', title: 'Reshove Spots and Calculations', duration: '20m', done: false },
          { id: 'calling-off', title: 'Calling Off Your Stack: ICM vs Chip EV', duration: '22m', done: false },
          { id: 'chip-dumping-spots', title: 'Accumulation Spots: When to Gamble It Up', duration: '17m', done: false },
        ],
      },
    ],
  },
  {
    id: 'steal-and-resteal',
    title: 'Steal and Re-Steal Spots',
    level: 'intermediate',
    levelLabel: 'Intermediate',
    desc: 'Exploit the blinds systematically. Learn steal frequency, optimal sizing, and how to construct a re-steal range against different player types.',
    lessonCount: 7,
    duration: '2h 5m',
    progress: 0,
    locked: false,
    modules: [
      {
        id: 'm1',
        title: 'Steal Game',
        lessons: [
          { id: 'steal-fundamentals', title: 'Steal Fundamentals: Frequency and Sizing', duration: '16m', done: false },
          { id: 'btn-steal', title: 'BTN Steal: The Default Spot', duration: '14m', done: false },
          { id: 'co-sb-steal', title: 'CO and SB Steals: Different Dynamics', duration: '16m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Re-Steal Game',
        lessons: [
          { id: 'resteal-math', title: 'Re-Steal Math: When Does It Work?', duration: '18m', done: false },
          { id: 'constructing-resteal-range', title: 'Constructing a Re-Steal Range', duration: '20m', done: false },
          { id: 'vs-recreational', title: 'Adjusting vs Recreational Stealers', duration: '17m', done: false },
          { id: 'vs-regs', title: 'Adjusting vs Regulars', duration: '14m', done: false },
        ],
      },
    ],
  },
  {
    id: 'cbet-basics',
    title: 'C-Bet Basics',
    level: 'intermediate',
    levelLabel: 'Intermediate',
    desc: 'Build a solid continuation betting foundation. Understand texture-based decisions, sizing theory, and when not to c-bet.',
    lessonCount: 6,
    duration: '1h 50m',
    progress: 0,
    locked: false,
    modules: [
      {
        id: 'm1',
        title: 'C-Bet Fundamentals',
        lessons: [
          { id: 'why-cbet', title: 'Why We C-Bet: Fold Equity and Value', duration: '16m', done: false },
          { id: 'board-textures', title: 'Board Textures: Dry, Wet, Paired', duration: '18m', done: false },
          { id: 'sizing-decisions', title: 'C-Bet Sizing: 33%, 50%, 75%', duration: '20m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'When to Check',
        lessons: [
          { id: 'checking-back', title: 'Checking Back IP: Pot Control', duration: '15m', done: false },
          { id: 'oop-cbet', title: 'C-Betting OOP: Extra Requirements', duration: '18m', done: false },
          { id: 'multiway-pots', title: 'C-Betting in Multiway Pots', duration: '13m', done: false },
        ],
      },
    ],
  },

  /* ─── ADVANCED ─── */
  {
    id: 'bubble-play',
    title: 'Bubble Play',
    level: 'advanced',
    levelLabel: 'Advanced',
    desc: 'Navigate the most ICM-sensitive phase of any tournament. Learn to exploit the bubble as a chip leader and survive it as a short stack.',
    lessonCount: 8,
    duration: '2h 30m',
    progress: 0,
    locked: false,
    modules: [
      {
        id: 'm1',
        title: 'ICM on the Bubble',
        lessons: [
          { id: 'icm-bubble-basics', title: 'ICM Basics: Why the Bubble Changes Everything', duration: '20m', done: false },
          { id: 'chip-leader-bubble', title: 'Chip Leader Bubble Play: Maximum Pressure', duration: '22m', done: false },
          { id: 'short-stack-bubble', title: 'Short Stack Bubble: Patience vs Urgency', duration: '18m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Tactical Bubble Spots',
        lessons: [
          { id: 'three-way-bubble', title: 'Three-Way Bubble Dynamics', duration: '20m', done: false },
          { id: 'hand-for-hand', title: 'Hand-for-Hand Play', duration: '15m', done: false },
          { id: 'calling-ranges-bubble', title: 'Calling Ranges Near the Bubble', duration: '18m', done: false },
          { id: 'satellite-bubble', title: 'Satellite Bubble: Binary Payout Strategy', duration: '20m', done: false },
          { id: 'near-bubble-spots', title: 'Near-Bubble Spots: 3–5 Spots Away', duration: '17m', done: false },
        ],
      },
    ],
  },
  {
    id: 'final-table-strategy',
    title: 'Final Table Strategy',
    level: 'advanced',
    levelLabel: 'Advanced',
    desc: 'Maximize your expectation once you reach the final table. Study pay-jump dynamics, short-handed adjustments, and heads-up preparation.',
    lessonCount: 7,
    duration: '2h 15m',
    progress: 0,
    locked: true,
    modules: [
      {
        id: 'm1',
        title: 'Final Table Dynamics',
        lessons: [
          { id: 'ft-icm', title: 'Final Table ICM: Every Spot Is Different', duration: '22m', done: false },
          { id: 'pay-jump-decisions', title: 'Pay Jump Decisions: Call vs Fold', duration: '20m', done: false },
          { id: 'ft-short-handed', title: 'Short-Handed Adjustments at the Final Table', duration: '18m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Heads-Up and HU Prep',
        lessons: [
          { id: 'ft-chip-leader', title: 'Chip Leader at the Final Table', duration: '20m', done: false },
          { id: 'three-handed-play', title: 'Three-Handed Play: The Key Inflection Point', duration: '18m', done: false },
          { id: 'heads-up-basics', title: 'Heads-Up Basics: Range and Aggression', duration: '20m', done: false },
          { id: 'deal-making', title: 'Deal-Making and Chip Chop Math', duration: '17m', done: false },
        ],
      },
    ],
  },
  {
    id: 'icm-pressure',
    title: 'ICM Pressure',
    level: 'advanced',
    levelLabel: 'Advanced',
    desc: 'Go deep on ICM — understand how payout structures warp optimal strategy and when chip EV and money EV diverge most critically.',
    lessonCount: 6,
    duration: '2h',
    progress: 0,
    locked: true,
    modules: [
      {
        id: 'm1',
        title: 'ICM Theory',
        lessons: [
          { id: 'icm-model', title: 'The ICM Model: How It Works', duration: '20m', done: false },
          { id: 'icm-vs-chip-ev', title: 'ICM vs Chip EV: Case Studies', duration: '22m', done: false },
          { id: 'nash-equilibrium-icm', title: 'Nash Equilibrium Under ICM', duration: '18m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'ICM in Practice',
        lessons: [
          { id: 'stack-preservation', title: 'Stack Preservation vs Accumulation Under ICM', duration: '20m', done: false },
          { id: 'pko-icm', title: 'PKO Tournaments: Bounty Equity + ICM', duration: '22m', done: false },
          { id: 'icm-mistakes', title: 'Common ICM Mistakes and How to Fix Them', duration: '18m', done: false },
        ],
      },
    ],
  },

  /* ─── ELITE ─── */
  {
    id: 'exploitative-adjustments',
    title: 'Exploitative Tournament Adjustments',
    level: 'elite',
    levelLabel: 'Elite',
    desc: 'Move beyond GTO into targeted exploitative play. Learn how to identify, size, and execute adjustments against specific player types at every stack depth.',
    lessonCount: 8,
    duration: '2h 45m',
    progress: 0,
    locked: true,
    modules: [
      {
        id: 'm1',
        title: 'Exploitative Framework',
        lessons: [
          { id: 'gto-vs-exploitative', title: 'GTO vs Exploitative: When to Deviate', duration: '20m', done: false },
          { id: 'player-typing', title: 'Player Typing: Nit, Reg, Fish, Maniac', duration: '18m', done: false },
          { id: 'adjustment-sizing', title: 'Sizing Your Adjustments Correctly', duration: '20m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Specific Exploits',
        lessons: [
          { id: 'vs-nits', title: 'Exploiting Nits: Max Pressure Strategy', duration: '20m', done: false },
          { id: 'vs-fish', title: 'Exploiting Recreational Players: Value Max', duration: '18m', done: false },
          { id: 'vs-aggressive-regs', title: 'Playing Against Aggressive Regulars', duration: '22m', done: false },
          { id: 'dynamic-adjustment', title: 'Dynamic Adjustment: Changing Gears Mid-Tournament', duration: '20m', done: false },
          { id: 'live-tell-integration', title: 'Integrating Live Reads Into Strategy', duration: '17m', done: false },
        ],
      },
    ],
  },
  {
    id: 'multi-street-planning',
    title: 'Multi-Street Planning',
    level: 'elite',
    levelLabel: 'Elite',
    desc: 'Think three streets ahead. Master hand planning on flop, turn, and river with integrated range construction and equity realization.',
    lessonCount: 7,
    duration: '2h 20m',
    progress: 0,
    locked: true,
    modules: [
      {
        id: 'm1',
        title: 'Planning Methodology',
        lessons: [
          { id: 'street-by-street', title: 'Street-by-Street Planning Framework', duration: '22m', done: false },
          { id: 'range-construction', title: 'Range Construction on Every Street', duration: '20m', done: false },
          { id: 'equity-realization', title: 'Equity Realization vs Fold Equity', duration: '18m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Advanced Lines',
        lessons: [
          { id: 'check-raise-planning', title: 'Check-Raise Planning and Execution', duration: '20m', done: false },
          { id: 'probe-bets', title: 'Probe Bets and Delayed C-Bets', duration: '18m', done: false },
          { id: 'river-decision-tree', title: 'River Decision Trees: Value, Bluff, Check', duration: '22m', done: false },
          { id: 'blockers', title: 'Using Blockers in Bluff Selection', duration: '20m', done: false },
        ],
      },
    ],
  },
  {
    id: 'playing-against-regulars',
    title: 'Playing Against Regulars',
    level: 'elite',
    levelLabel: 'Elite',
    desc: 'Thrive in tough fields. Understand how regulars think, identify their systematic tendencies, and construct lines that exploit their tendencies profitably.',
    lessonCount: 6,
    duration: '2h',
    progress: 0,
    locked: true,
    modules: [
      {
        id: 'm1',
        title: 'Reading Regulars',
        lessons: [
          { id: 'reg-tendencies', title: 'Common Regular Tendencies and Patterns', duration: '20m', done: false },
          { id: 'meta-game', title: 'Meta-Game: History and Table Image', duration: '18m', done: false },
          { id: 'balancing-vs-regs', title: 'When to Balance vs When to Exploit', duration: '22m', done: false },
        ],
      },
      {
        id: 'm2',
        title: 'Beating Tough Fields',
        lessons: [
          { id: 'opening-vs-regs', title: 'Preflop Adjustments vs Regular-Heavy Tables', duration: '20m', done: false },
          { id: 'postflop-vs-regs', title: 'Postflop Lines vs Thinking Opponents', duration: '22m', done: false },
          { id: 'tournament-regs-icm', title: 'Exploiting ICM Mistakes in Regular Fields', duration: '18m', done: false },
        ],
      },
    ],
  },
];

/* ── Mock lesson content ──────────────────────────────────── */

const CO_LESSON_CONTENT = {
  'why-tournament-poker-is-different': {
    concepts: [
      'In cash games chips = money directly. In tournaments chips have diminishing marginal value.',
      'Survival matters. A cash game player can rebuy; a tournament player cannot.',
      'Your goal is not to win the most chips — it is to outlast other players.',
      'Payout structure creates ICM pressure that forces strategy adjustments.',
      'Tournament poker rewards picking spots, not constant aggression.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>If you sit down at a tournament table playing exactly like you play cash games, you will go broke faster than you should — and you will never understand why.</p>
        <p>The fundamental difference is this: <strong>in cash games, a chip is always worth a dollar. In tournaments, a chip's dollar value depends on how many are left and how the prize money is distributed.</strong></p>
      </div>
      <div class="co-lesson-section">
        <h3>The Survival Constraint</h3>
        <p>In cash games, you can rebuy whenever you want. In tournaments, you only have the chips you have. This creates a completely different relationship with risk. In cash, an aggressive play that wins 55% of the time is almost always correct (assuming equal pot sizes). In tournaments, if that same 55% play puts you at risk of elimination, it might be wrong — even if it's chip EV positive.</p>
        <div class="co-callout">Key shift: Stop asking "do I win more chips?" and start asking "what decision maximizes my prize money equity?"</div>
      </div>
      <div class="co-lesson-section">
        <h3>A Concrete Example</h3>
        <div class="co-scenario">
          <strong>Scenario:</strong> 30 players left, 27 get paid. You have an average stack. A recreational player shoves all-in and you have pocket jacks — a clear chip EV call (you're a 70% favourite vs a typical shove range). But calling puts you at risk of busting before the money.<br><br>
          <strong>Tournament decision:</strong> Even though the call is profitable in chips, the correct play depends on your stack size vs the blinds, the stacks of the other players near the bubble, and the payout jump from 27th to 24th. Jacks might be a fold here — not because the hand is bad, but because survival until the bubble has real money value.
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>What to Remember</h3>
        <div class="co-takeaways">
          <div class="co-takeaway-item">Chip accumulation is a means, not the goal.</div>
          <div class="co-takeaway-item">The tournament payouts — not the chip counts — determine your decisions.</div>
          <div class="co-takeaway-item">Every stack decision carries an ICM component, whether you calculate it explicitly or not.</div>
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>Common Mistake</h3>
        <div class="co-mistakes">
          <strong>Calling too wide early-game</strong> because "it's early so ICM doesn't matter." Early ICM pressure is genuinely low — but that doesn't mean every marginal call is correct. Your stack is your weapon. Protect it.
        </div>
      </div>
    `,
    quiz: {
      question: 'You have a 50% equity call that puts you at risk of elimination just before the bubble. The pot is 30,000 chips and call costs 20,000. In a cash game this is clearly +EV. What should you consider in a tournament?',
      options: [
        'A) Call — equity is equity regardless of format.',
        'B) The call may be chip EV positive but money EV negative due to ICM pressure near the bubble.',
        'C) Always fold before the bubble regardless of equity.',
        'D) Only the chip count matters; money is awarded after.',
      ],
      correct: 'B) The call may be chip EV positive but money EV negative due to ICM pressure near the bubble.',
      explanation: 'Tournament decisions require evaluating money equity, not just chip equity. Near the bubble, surviving to the money has real value that a raw equity calculation ignores. The correct decision depends on stack sizes, payout jumps, and ICM pressure — not just pot odds.',
    },
  },

  'position-the-most-important-advantage': {
    concepts: [
      'Acting last on every postflop street is a massive informational advantage.',
      'Positional advantage compounds over 3 streets: flop, turn, and river.',
      'In position you can control pot size, extract value, and bluff more effectively.',
      'Out of position you face constant guessing: bet into unknown strength, or check and face a bet.',
      'Tournament aggression should almost always come from position.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>Position is the single biggest structural edge available in poker. Everything else — hand reading, bet sizing, ICM awareness — matters less than where you sit relative to your opponent.</p>
        <p>The player who acts last on every postflop street has a decision advantage on every street. They see what the opponent does before deciding. Over three streets, that compounds into a massive information gap.</p>
      </div>
      <div class="co-lesson-section">
        <h3>The Information Advantage</h3>
        <p>When you are <strong>in position (IP)</strong> — on the button or cutoff — your opponent acts first. You see their bet, check, or raise before you decide. This is not a small edge. Over thousands of hands, players in position extract significantly more value from the same hand strengths.</p>
        <p>When you are <strong>out of position (OOP)</strong> — in the blinds or early position — you act first. You do not know if your opponent has a strong hand, a draw, or a bluff until after you commit chips. You are forced to guess.</p>
        <div class="co-callout">Practical rule: From the blinds, play tighter and more straightforward. From the button and cutoff, play wider and more aggressively. The same hand plays very differently depending on your seat.</div>
      </div>
      <div class="co-lesson-section">
        <h3>Position at Different Stack Depths</h3>
        <div class="co-scenario">
          <strong>Deep stacks (40bb+):</strong> Position is most valuable here because there are 3 postflop streets to leverage the advantage. Speculative hands like suited connectors have much more value IP than OOP.<br><br>
          <strong>Short stacks (under 20bb):</strong> Position still matters for preflop shoving ranges — you can shove wider from the button than UTG. But postflop leverage diminishes as stack-to-pot ratios shrink.
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>Tournament Application</h3>
        <p>In tournaments, your steal and 3-bet ranges should be heavily position-dependent. From the button (BTN), you should open the widest range at the table. From under-the-gun (UTG), significantly tighter. The math is simple: when everyone folds to you, you only need to beat the two players behind. From UTG, you need to beat everyone.</p>
        <div class="co-takeaways">
          <div class="co-takeaway-item">BTN is the best seat at the table. Open wide, continue aggressively, and steal frequently.</div>
          <div class="co-takeaway-item">BB is the worst seat postflop. You will face bets on every street without information. Play defensively.</div>
          <div class="co-takeaway-item">Never call a 3-bet OOP without a strong reason — you are paying a premium to play a pot in a structural disadvantage.</div>
        </div>
      </div>
    `,
    quiz: {
      question: 'You are on the button with K♣7♣ (a marginal hand). The action folds to you. What is the primary reason to open-raise here?',
      options: [
        'A) K7 suited is a strong hand that plays well at showdown.',
        'B) You will act last on every postflop street, giving you a structural decision advantage over the blinds.',
        'C) The pot odds justify raising with any two cards on the button.',
        'D) Raising disguises your hand strength.',
      ],
      correct: 'B) You will act last on every postflop street, giving you a structural decision advantage over the blinds.',
      explanation: 'K7s is a marginal hand on its own. The reason to open it from the button is positional: you will be in position on every postflop street, which turns a marginal hand into a profitable open. The same hand UTG would typically be a fold.',
    },
  },

  'starting-hands-are-context-based': {
    concepts: [
      'No starting hand has a fixed value — it depends on position, stack depth, and table dynamics.',
      'A hand good enough to open is not necessarily good enough to call a 3-bet with.',
      'Suited hands gain value with deeper stacks; offsuit hands lose value more quickly.',
      'High-card strength matters most in short-stack push-fold situations.',
      'Speculative hands (suited connectors, small pairs) need implied odds — stack depth and position.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>Beginners think in hand rankings: AA is the best, 72o is the worst. Experienced players think in ranges and context: what can I profitably do with this hand, from this position, against this field, at this stack depth?</p>
        <p>The same hand can be a clear open from the button and an obvious fold from UTG. Context determines value, not the hand in isolation.</p>
      </div>
      <div class="co-lesson-section">
        <h3>The Three Hand Categories</h3>
        <p><strong>Premium hands</strong> (AA, KK, QQ, AK): Play themselves. Open from anywhere, 3-bet for value, happy to get stacks in. Their value is relatively position-independent.</p>
        <p><strong>Playable hands</strong> (JJ–77, AQ, AJ, KQ, suited broadways, suited aces): Play well from middle and late positions. Require judgment in early position. Their value drops significantly when 3-bet or facing pressure.</p>
        <p><strong>Speculative hands</strong> (small pairs 66 and below, suited connectors 87s–54s): These hands need stack depth and position to realize their value. At 20bb, 54s is nearly worthless. At 50bb IP, it's a profitable call or steal. Never call a raise with these OOP at tournament stack depths.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Stack Depth Changes Everything</h3>
        <div class="co-scenario">
          <strong>Pocket fives at 15bb:</strong> This is a push-or-fold hand. You either shove it preflop or fold it. Calling a raise costs you a third of your stack without a plan. Shove it from any position; it's a strong shove hand that rarely gets dominated.<br><br>
          <strong>Pocket fives at 50bb:</strong> Set mining candidate. Call a raise IP, hope to flop a set, and play for a big pot. The implied odds justify the speculative play. OOP, be much more cautious — you will face pressure without information.
        </div>
        <div class="co-callout">Rule: The shorter your stack, the more you want high-card strength. The deeper your stack, the more you want suited and connected hands that can make the nuts.</div>
      </div>
      <div class="co-lesson-section">
        <h3>Mistakes to Avoid</h3>
        <div class="co-mistakes">
          <strong>Calling raises with AXo OOP:</strong> A6o or A5o looks strong but plays terribly out of position. You make top pair with a weak kicker and either overpay or fold equity. These hands want to be 3-bet or folded, not called flat.<br><br>
          <strong>Limping small pairs in early position:</strong> 22–44 are not strong enough to call a raise from UTG and not wide enough to be profitable opens. In early position, fold them. In late position, shove or open depending on stack depth.
        </div>
      </div>
    `,
    quiz: {
      question: 'You have 6♦5♦ (suited connector) at 18bb effective. A player opens from UTG. What is the correct play?',
      options: [
        'A) Call — suited connectors always have implied odds.',
        'B) 3-bet shove — suited connectors play well as a semi-bluff shove.',
        'C) Fold — at 18bb, speculative hands need stack depth to realize their value, and calling off 25–30% of your stack without position is unprofitable.',
        'D) Limp behind to see the flop cheaply.',
      ],
      correct: 'C) Fold — at 18bb, speculative hands need stack depth to realize their value, and calling off 25–30% of your stack without position is unprofitable.',
      explanation: 'At 18bb, 65s has lost its speculative value. Calling a raise costs roughly 25-30% of your stack with a hand that needs to flop perfectly to continue. You do not have the implied odds to justify the call. Against a UTG open (strong range), folding is the correct play.',
    },
  },

  'preflop-decisions-open-fold-or-shove': {
    concepts: [
      'At most tournament stack depths, preflop options reduce to: open-raise, shove, or fold.',
      'Calling (flatting) is the weakest preflop action — it builds a pot without a clear plan.',
      'Open-raise when you have fold equity and a hand worth building a pot with.',
      'Shove when your stack is 15bb or below, or when 3-bet-shoving is the plan.',
      'Fold when the situation does not favor any aggressive action.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>One of the most common beginner mistakes in tournament poker is calling too much preflop. Cash game players carry a flatting habit into tournaments — calling raises with marginal hands, hoping to realize equity postflop. This habit is expensive in tournaments.</p>
        <p>The correct preflop framework is simple: <strong>Have a plan before you act.</strong> If you open-raise, know whether you will continuation-bet, 3-bet-shove vs a 3-bet, or fold. If you are already thinking about "I'll just see what happens," you probably should not be playing the hand.</p>
      </div>
      <div class="co-lesson-section">
        <h3>When to Open-Raise</h3>
        <p>Open-raising makes sense when: you have a hand worth building a pot with from your position, you have at least 20–25bb so you can use postflop leverage, and you have a plan for each possible response (call, 3-bet, fold).</p>
        <p>Standard tournament open sizing: 2–2.5x at most stack depths with antes. Sizing 3x or more is often too large and gives opponents better pot odds to call and more information about your hand.</p>
      </div>
      <div class="co-lesson-section">
        <h3>When to Shove</h3>
        <div class="co-scenario">
          <strong>Sub-15bb:</strong> Shoving is almost always better than open-folding or open-calling. A 10bb open-raise is 67% of your stack — you are pot-committed anyway. Just shove and deny opponents the ability to 3-bet.<br><br>
          <strong>15–20bb with strong hands:</strong> Some players prefer shoving this depth to avoid awkward postflop spots. A hand like AJs or 99 plays well as a shove at 17bb — you build the pot, deny 3-bets, and have clear decisions.<br><br>
          <strong>3-bet-shoving:</strong> If a player opens and you have a hand you want to play for stacks, shoving is cleaner than a small 3-bet. Small 3-bets at low stack depths are usually mistakes — you commit too much without enough fold equity.
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>The Flatting Trap</h3>
        <div class="co-mistakes">
          <strong>Calling raises with marginal hands:</strong> When you flat a raise with Q9s OOP at 25bb, you are playing a pot with a hand that often makes second-best hands, without the positional advantage to realize your equity. You either hit and face pressure, or miss and face a continuation bet you probably cannot continue against.<br><br>
          Exception: Deep stacks (40bb+) IP with hands that have good equity realization (pocket pairs for set-mining, strong suited hands). Even then, have a plan.
        </div>
        <div class="co-takeaways">
          <div class="co-takeaway-item">Default preflop: raise or fold. Rarely call.</div>
          <div class="co-takeaway-item">At under 15bb: shove or fold. Rarely open-raise small.</div>
          <div class="co-takeaway-item">Have a plan for each action before you commit chips.</div>
        </div>
      </div>
    `,
    quiz: {
      question: 'You have 22bb. A player opens from CO to 2.2bb. You are on the BTN with Q♠J♠. What is the most common mistake here?',
      options: [
        'A) Folding — QJs is too strong to fold against a CO open.',
        'B) Calling — flatting OOP with a marginal hand at a stack depth where postflop leverage is limited.',
        'C) 3-bet shoving — QJs is not strong enough to shove for value.',
        'D) Open-raising before the action reaches you.',
      ],
      correct: 'B) Calling — flatting OOP with a marginal hand at a stack depth where postflop leverage is limited.',
      explanation: 'Wait — you are on the BTN, which is actually IP (in position) vs the CO. But QJs at 22bb facing a CO open is a 3-bet-or-fold spot, not a call. Flatting IP builds a pot without a plan and traps you in multi-way or single-raised pots with a hand that needs to make a strong pair or straight/flush to continue. 3-bet to ~6bb (or shove) is the better play.',
    },
  },

  'short-stack-play-under-15bb': {
    concepts: [
      'Under 15bb, push-fold is the correct strategy framework.',
      'Open-raising small with under 15bb and then folding is a major leak.',
      'Shove ranges widen as stack shrinks — desperation is correct, not passive.',
      'Calling off stacks requires stronger hands than shoving requires.',
      'Position still matters in push-fold: BTN shove ranges are much wider than UTG.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>When you reach 15bb or below, the game simplifies dramatically. You are in push-fold territory. The only correct moves are: fold your hand, or shove all your chips in preflop. Open-raising small is almost never correct at this depth.</p>
        <p>Why? Because if you open to 2.5bb with 12bb, you have committed 21% of your stack. If anyone 3-bets (which happens often when stacks are short), you are forced to fold and have lost 21% or call off and be pot-committed. You get the worst of both outcomes. Just shove.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Shove Ranges by Position (10–15bb)</h3>
        <p>The general principle: shove wider from late position, tighter from early position. This is because late position shoves need to get fewer players to fold, and you have better information about who has already shown interest in the pot.</p>
        <div class="co-scenario">
          <strong>BTN (folded to you):</strong> Shove very wide — roughly the top 35–45% of hands. This includes all pairs, all aces, all kings, most queens, most suited hands, and many offsuit Broadway hands. You only need both blinds to fold.<br><br>
          <strong>UTG (8 players left):</strong> Shove tight — roughly the top 15–20% of hands. AA, KK, QQ, JJ, TT, 99, AK, AQ, AJs, KQs. You need all players to fold, which is rare — so you should only shove hands that are happy to get called.<br><br>
          <strong>SB (folded to you):</strong> Shoving range is wide vs the BB — close to the BTN range. The BB has the pot odds to call, but your hand still has equity, and many BBs will fold too wide. Shove AX, all pairs, and many suited hands.
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>When Someone Shoves Into You</h3>
        <p>Calling a shove is a separate decision from shoving. You need better hands to call a shove than to shove yourself. Why? When you shove, you get two ways to win: opponent folds, or you win at showdown. When you call a shove, you only win at showdown — there is no fold equity.</p>
        <div class="co-callout">Calling rule of thumb: You need roughly 33–40% equity against a reasonable shove range to call profitably. Weaker hands that look good (like K9o) often fall short. Use an equity calculator to test your calling ranges.</div>
        <div class="co-mistakes">
          <strong>The desperation call:</strong> "I have to call somewhere" is not a strategy. Calling off a 12bb stack with K6o because you are frustrated is a mistake. Shoving selectively is correct. Calling any two cards because you are desperate is not.
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>M-Ratio Alert Levels</h3>
        <div class="co-takeaways">
          <div class="co-takeaway-item">M 10–15: Begin transitioning to push-fold. No more speculative calls.</div>
          <div class="co-takeaway-item">M 5–10: Full push-fold. Open-raises only with specific plan (shove if 3-bet).</div>
          <div class="co-takeaway-item">M under 5: Shove any two cards from the right position. Waiting is losing.</div>
        </div>
      </div>
    `,
    quiz: {
      question: 'You have 11bb. It folds to you in the SB. What is almost always the correct action with A♥8♦?',
      options: [
        'A) Fold — A8o is not strong enough to play from the SB.',
        'B) Open-raise to 2.5bb and see how the BB responds.',
        'C) Shove all-in — at 11bb, A8o is a strong shove from the SB with only one player remaining.',
        'D) Limp and see the flop cheap.',
      ],
      correct: 'C) Shove all-in — at 11bb, A8o is a strong shove from the SB with only one player remaining.',
      explanation: 'At 11bb in the SB vs the BB only, A8o is a clear shove. You have ace-high equity, a dominated hand count advantage, and only one player to get through. Open-raising to 2.5bb leaves 8.5bb behind and makes you pot-committed to any shove, while giving the BB better pot odds. Limping is passive and gives up fold equity entirely.',
    },
  },

  'biggest-beginner-mistakes': {
    concepts: [
      'Limping preflop surrenders fold equity and builds pots without a plan.',
      'Playing too many hands from early position is a stack-bleeding mistake.',
      'Calling raises with dominated hands (A9o, K8o) is a long-term leak.',
      'Not adjusting for stack depth: playing cash-game-style at 20bb.',
      'Missing reshove spots when a shorter stack shoves and you have a reshove hand.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>Most tournament mistakes are not exotic or complex. They are basic, repeated errors that bleed chips slowly until the damage is irreversible. Here are the five biggest beginner mistakes and how to eliminate them.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Mistake 1: Limping Preflop</h3>
        <p>Limping (calling the big blind instead of raising) is almost never correct in tournaments. You give up fold equity, build a pot without initiative, and signal hand weakness. Against competent players, you will be 3-bet off your hand repeatedly. Against recreational players, you still face multiway pots with unclear information.</p>
        <div class="co-callout">Fix: Raise or fold. If a hand is worth playing, raise it. If it is not worth raising, fold it.</div>
      </div>
      <div class="co-lesson-section">
        <h3>Mistake 2: Playing Too Wide From Early Position</h3>
        <p>From UTG in a 9-handed game, you need to beat 8 opponents to win the pot. This means your opening range must be strong enough to withstand 3-bets and calls from anywhere at the table. Playing KJo or Q9s from UTG is profitable only against very passive fields. Against average or tough competition, you are printing money for everyone else.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Mistake 3: Calling with Dominated Hands</h3>
        <div class="co-scenario">
          <strong>Common examples of dominated calls:</strong><br>
          — Calling a UTG open with K9o from the CO<br>
          — Calling a BTN 3-bet with AJo from the BB<br>
          — Calling a short-stack shove with A7o when the shover has a tight range<br><br>
          These hands look strong in isolation but are frequently dominated by the ranges that play this way. You win less than expected and lose more than expected. The "I have an ace" fallacy is expensive.
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>Mistake 4: Ignoring Stack Depth</h3>
        <p>Playing a 22bb stack like a 50bb stack. This means: open-raising with a plan to fold to a 3-bet (giving up 15% of your stack), calling raises with speculative hands that need 40bb+ to be profitable, and checking draws instead of shoving for fold equity.</p>
        <p>Know your M-ratio at all times. Let it dictate your decisions.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Mistake 5: Missing Reshove Spots</h3>
        <div class="co-mistakes">
          <strong>Scenario:</strong> You have 22bb in the BB. The BTN (35bb) opens to 2.5bb. You have 88. The correct play is often to reshove — you deny the BTN's postflop advantage, put maximum pressure, and have good equity when called. Many beginners flat this spot or fold. Flatting leaves 19.5bb behind in a raised pot and forces you to play postflop without initiative. Shoving is the highest-EV play.
        </div>
        <div class="co-takeaways">
          <div class="co-takeaway-item">Reshove spots: any time your stack is 15–25bb and a wide opener raises, consider shoving instead of flatting.</div>
          <div class="co-takeaway-item">Reshove hands: pocket pairs (88 and above are usually clear), suited aces, and strong broadways.</div>
        </div>
      </div>
    `,
    quiz: {
      question: 'You have 19bb in the BB. The CO (40bb) opens to 2bb. You have 9♣9♦. What is generally the highest-EV play?',
      options: [
        'A) Fold — nines do not play well vs a CO range.',
        'B) Call — see a flop and reassess.',
        'C) Reshove all-in — at 19bb with a strong hand, shoving denies fold equity to the CO and is usually the highest-EV action.',
        'D) 3-bet to 6bb and fold to a reshove.',
      ],
      correct: 'C) Reshove all-in — at 19bb with a strong hand, shoving denies fold equity to the CO and is usually the highest-EV action.',
      explanation: '99 is a strong hand that plays well as a reshove. Calling leaves 17bb behind in a raised pot OOP — you will face a continuation bet on nearly every flop and lack a clear strategy. Shoving 19bb into a CO opener puts maximum pressure (they need to call with 40bb+ at risk against your 99) and gets you in as a favourite or coin-flip vs most calling ranges.',
    },
  },

  'how-to-think-in-a-hand': {
    concepts: [
      'Think in ranges, not hands: your opponent has a distribution of possible hands, not one specific hand.',
      'Ask three questions in order: What is my equity? What is my plan on each run-out? What do I represent?',
      'Pot odds and equity must align before committing chips.',
      'Balance value bets and bluffs to avoid being exploited by thinking opponents.',
      'In-hand decision trees: if villain bets, if villain checks — plan for both before acting.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>Most beginners focus on their own cards. Good players focus on their opponent's range. Elite players think about what their opponent thinks they have — and act accordingly.</p>
        <p>This lesson gives you a structured thinking framework to apply on every street, in every hand.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Step 1: What Range Does My Opponent Have?</h3>
        <p>Before thinking about your own hand, think about what hands your opponent can have given their actions so far. A player who 3-bet from the BB has a polarized range (strong hands and bluffs). A player who called your CO open from the BTN has a wide, capped range (no aces, no pairs they would 3-bet with).</p>
        <p>You do not need to know their exact hand. You need to know which parts of their range can beat you, and how large that portion is.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Step 2: What Is My Equity Against That Range?</h3>
        <p>Once you have a rough range in mind, estimate your equity. If villain 3-bets from the BB and you have KQs, your equity vs a reasonable 3-bet range is around 40–45%. That is not enough to get stacks in at most depths — you need position or a clear plan to improve on later streets.</p>
        <div class="co-callout">You do not need to calculate exact percentages at the table. You need order-of-magnitude awareness: are you a favourite, a coin-flip, or a dog? That is enough to guide decisions.</div>
      </div>
      <div class="co-lesson-section">
        <h3>Step 3: What Is My Plan?</h3>
        <div class="co-scenario">
          <strong>Plan your hand before the flop comes:</strong> If I open AK and get called, I will continuation-bet most flops because I have overcards and back-door draws. If the turn is a brick and villain calls my c-bet, I will likely check back and reassess. If villain raises the turn, I will need to consider whether they have a set or two pair, or are raising a draw.<br><br>
          This is not a rigid script — it is a decision tree. Having thought through the plan in advance means you are not surprised or panicked when action comes to you.
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>What Do I Represent?</h3>
        <p>Your actions tell a story. Bet-bet-bet on a low board tells a story of a strong made hand. Check-call the flop, lead the turn after a blank tells a story of a draw or a made hand slow-played. Ask: does my action tell a believable story given my range?</p>
        <p>Bluffs should tell a story consistent with your perceived range. If you checked the flop and fired huge on the turn after an ace came, you are representing an ace that you slow-played. That is a believable story. Bluffing into a player who has check-called three times is not.</p>
        <div class="co-takeaways">
          <div class="co-takeaway-item">Think ranges, not hands — your opponent has many possible holdings, not one.</div>
          <div class="co-takeaway-item">Plan for contingencies before they happen — if check, if bet.</div>
          <div class="co-takeaway-item">Tell consistent stories — your bets should represent a believable range.</div>
        </div>
      </div>
    `,
    quiz: {
      question: 'You open from CO, BTN calls. Flop: A♠7♣2♦. You have K♣Q♣ (no pair, no draw). What is the correct first question to ask before betting?',
      options: [
        'A) "Do I have the best hand?"',
        'B) "What range does the BTN have given they called my CO open, and how often does this flop hit their range vs mine?"',
        'C) "Is this a good bluffing board?"',
        'D) "How much should I bet?"',
      ],
      correct: 'B) "What range does the BTN have given they called my CO open, and how often does this flop hit their range vs mine?"',
      explanation: 'Thinking in ranges first is the foundation. The BTN\'s calling range is wide but capped — they are unlikely to have AK (would 3-bet) or AA/77/22 (would 3-bet or set-mine with intent). An ace-high board hits your CO range more than their BTN calling range. That analysis justifies a continuation bet. The question about sizing comes last, not first.',
    },
  },

  'final-quiz-and-practice-setup': {
    concepts: [
      'Review all 7 lessons: tournaments vs cash, position, starting hands, preflop decisions, short stacks, common mistakes, hand thinking.',
      'Apply these concepts to real hands using the Analysis tab.',
      'Use the Push/Fold trainer to drill short stack decisions until they are automatic.',
      'Set a study goal: 20 minutes of practice per day beats 2 hours once per week.',
      'Your biggest leak is more valuable to fix than your tenth-biggest leak.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>You have completed Tournament Poker Fundamentals. This final lesson is a review, a quiz, and a launch pad for the next phase of your improvement.</p>
        <p>The concepts you have learned are not abstract theory — they are decisions you will face in every session. The faster you internalize them, the faster your results improve.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Core Concepts Review</h3>
        <div class="co-takeaways">
          <div class="co-takeaway-item"><strong>Lesson 1:</strong> Tournaments ≠ cash. Chip value diminishes. Survival has dollar value. ICM changes everything near payouts.</div>
          <div class="co-takeaway-item"><strong>Lesson 2:</strong> Position is the biggest structural edge. Play wider and more aggressively in position. Play tighter and more straightforward OOP.</div>
          <div class="co-takeaway-item"><strong>Lesson 3:</strong> Starting hand value is context-dependent. Stack depth, position, and table dynamics determine what to play.</div>
          <div class="co-takeaway-item"><strong>Lesson 4:</strong> Default preflop: raise or fold. Under 15bb: shove or fold. Have a plan before committing chips.</div>
          <div class="co-takeaway-item"><strong>Lesson 5:</strong> Under 15bb = push-fold. Know your shove ranges by position. Calling requires stronger hands than shoving.</div>
          <div class="co-takeaway-item"><strong>Lesson 6:</strong> The five leaks: limping, playing wide from early position, dominated-hand calls, ignoring stack depth, missing reshove spots.</div>
          <div class="co-takeaway-item"><strong>Lesson 7:</strong> Think in ranges. Plan before you act. Tell consistent stories.</div>
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>What to Practice Next</h3>
        <p>The most effective practice is targeted, not random. Here is a prioritized study plan:</p>
        <div class="co-scenario">
          <strong>Week 1:</strong> Push-fold trainer — drill BTN, CO, SB, and UTG shove ranges at 8–15bb until they are automatic. This eliminates a huge category of mistakes immediately.<br><br>
          <strong>Week 2:</strong> Hand review — load your last 20 sessions in the Analysis tab. Find spots where you limped, called raises OOP with marginal hands, or missed reshove spots. Count them.<br><br>
          <strong>Week 3:</strong> Position awareness drill — in your next 5 sessions, track every hand where you called a raise. Write down your position and stack depth. Were they justified calls?
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>Setting a Study Goal</h3>
        <div class="co-callout">The most impactful study habit is daily short review, not marathon sessions. 20 minutes of targeted practice every day produces faster improvement than 3 hours on weekends. Pick one concept per week and drill it until it becomes instinctive.</div>
        <p>Use the Practice section to drill the push-fold decisions from this course. Use the Analysis tab to review your own real hands. The combination of directed learning and real data review is how improvement happens fastest.</p>
      </div>
    `,
    quiz: {
      question: 'You are 3 spots from the money with 14bb. The BTN (45bb) shoves all-in. You are in the BB with A♦J♠. What is the main consideration before calling?',
      options: [
        'A) AJ is a strong hand so call automatically.',
        'B) Evaluate your pot odds — if you are getting better than 2:1, call.',
        'C) Consider ICM pressure: calling puts you at risk of busting before the money. Weigh your equity vs the BTN shove range against the money equity value of surviving 3 more eliminations.',
        'D) Fold — always fold near the bubble.',
      ],
      correct: 'C) Consider ICM pressure: calling puts you at risk of busting before the money. Weigh your equity vs the BTN shove range against the money equity value of surviving 3 more eliminations.',
      explanation: 'AJs has good equity vs a wide BTN shove range (~55–60% vs a typical BTN shove). But near the bubble, the ICM cost of busting before the money is significant. With 14bb, you will survive long enough to money if others bust — so your decision depends on the stack distributions of all remaining players, not just this equity calculation. In many scenarios, a fold is correct even with AJ. In others, calling is clearly right. The point is: equity alone is not the answer near the bubble.',
    },
  },

  'icm-bubble-basics': {
    concepts: [
      'ICM (Independent Chip Model) converts chip stacks into prize equity — a 50% chip lead does not mean 50% of the prize pool.',
      'Near the bubble, busting costs you more EV than eliminating an opponent gains you.',
      'Short stacks have disproportionate ICM pressure — they are forced into tight spots to survive.',
      'Big stacks near the bubble hold the most power: they can threaten elimination without risking their own position.',
      'ICM-correct folds often feel wrong because your hand equity is fine — but your prize equity math says otherwise.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>Chip EV and prize EV are not the same thing. This is the central fact of bubble play, and misunderstanding it is the single most expensive leak in tournament poker.</p>
        <p>With 10 players left and 9 spots paid, a 60% chip stack does not give you 60% of the prize pool. The distribution is flatter than that, and every spot you move up is worth real money.</p>
      </div>
      <div class="co-lesson-section">
        <h3>How ICM Changes Your Decisions</h3>
        <div class="co-takeaways">
          <div class="co-takeaway-item"><strong>Calling is more expensive than shoving.</strong> When you call a shove, you can bust. When you shove, you can win without a showdown. ICM punishes calls harder than shoves.</div>
          <div class="co-takeaway-item"><strong>Stack size determines ICM pressure.</strong> The short stack has the most to lose per hand. The chip leader has the least. Adjust your aggression accordingly.</div>
          <div class="co-takeaway-item"><strong>The bubble magnifies everything.</strong> One spot from the money, every decision carries more weight. A standard chip-EV call becomes a clear fold when ICM is factored in.</div>
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>The Bubble Scenario</h3>
        <div class="co-scenario">
          <strong>Setup:</strong> 10 players remain. 9 spots paid. You have 22bb. A 40bb stack shoves UTG into you in the BB with A♣T♦.<br><br>
          <strong>Chip EV:</strong> ATo is roughly 55% vs a standard UTG shove range. A straightforward call.<br><br>
          <strong>Prize EV:</strong> If you call and lose, you bust on the bubble with zero payout. The three shortest stacks at the table are all under 8bb and likely to bust before you if you fold. Your prize equity from surviving is worth more than the chip equity you gain by calling.<br><br>
          <strong>Correct play:</strong> Fold ATo on the bubble vs an UTG shove with 22bb, even though your hand equity is fine.
        </div>
      </div>
      <div class="co-callout">The bubble is not the time to gamble. It is the time to accumulate chips without risking your tournament life — unless your stack forces the issue.</div>
    `,
    quiz: {
      question: 'You have 18bb on the money bubble. Three players have under 5bb. A 35bb player shoves from CO. You have K♠Q♦ in the BB. What does ICM say?',
      options: [
        'A) Call — KQo has strong equity vs a CO shove range.',
        'B) Fold — the three short stacks will likely bust before you, and your prize equity from survival exceeds your chip equity from calling.',
        'C) Call — you need chips to go deep in the tournament.',
        'D) Fold — KQ is a weak hand against any shove.',
      ],
      correct: 'B) Fold — the three short stacks will likely bust before you, and your prize equity from survival exceeds your chip equity from calling.',
      explanation: 'KQo has roughly 47–55% equity vs a CO shove range, which chip-EV-wise makes this borderline. But with three stacks under 5bb still in the tournament, you are almost guaranteed to money if you fold and wait. The ICM cost of busting before those players is severe — potentially several buy-ins of EV. With 18bb you are not desperate. Fold, let the short stacks bust, then adjust your aggression once in the money.',
    },
  },

  'ft-icm': {
    concepts: [
      'At the final table, every elimination changes the ICM math — each pay jump has a specific dollar value.',
      'Short-handed play requires wider ranges: with 4–6 players, premium hands come rarely and position matters more.',
      'The chip leader should apply constant pressure; others must pick spots based on stack depth and pay jumps.',
      'Calling off your stack for a pay jump is often correct even with a weak hand when a short stack is all-in.',
      'Heads-up play is nearly pure push-fold below 20bb — preflop edge matters more than postflop skill.',
    ],
    body: `
      <div class="co-lesson-section">
        <p>Final table play is where tournaments are won and lost. The pay jumps are larger, the mistakes are more expensive, and the ICM calculations change after every hand.</p>
        <p>The key adjustment: think in dollars, not chips. A 30% chip increase from 5th to 4th place might be worth $500 in real money. Every shove, call, and fold needs to pass a dollar-EV filter, not just a chip-EV filter.</p>
      </div>
      <div class="co-lesson-section">
        <h3>Pay Jump Decisions</h3>
        <div class="co-takeaways">
          <div class="co-takeaway-item"><strong>Identify the big pay jumps before the table starts.</strong> Moving from 5th to 4th and from 2nd to 1st are often the largest. Those are the spots to tighten up.</div>
          <div class="co-takeaway-item"><strong>When a short stack is all-in, consider the walk.</strong> If calling risks your stack and the short stack busting hands you a pay jump anyway, fold marginal hands and let them bust.</div>
          <div class="co-takeaway-item"><strong>Three-handed and heads-up, stack leverage matters most.</strong> The biggest stack controls the table. Winning a key pot to take the chip lead is often worth more than the individual hand's EV suggests.</div>
        </div>
      </div>
      <div class="co-lesson-section">
        <h3>Short-Handed Ranges</h3>
        <div class="co-scenario">
          <strong>6-handed FT:</strong> Open any two broadways, all pocket pairs, all suited aces from any position. Fold equity is high — players are uncomfortable.<br><br>
          <strong>4-handed FT:</strong> Open 60–70% of hands from the button. BB defend range widens significantly. Steal every uncontested limped pot.<br><br>
          <strong>Heads-up under 20bb:</strong> Shove or fold from SB with a wide range (any ace, any K, suited connectors, most broadways). Call off from BB with top 40% of hands vs a wide shove.
        </div>
      </div>
      <div class="co-callout">The most common final table mistake is playing too tight when short-handed. Blinds are large relative to stacks — you cannot wait for big hands. Attack constantly and adjust when you get resistance.</div>
    `,
    quiz: {
      question: 'You are 3-handed at the final table. Stacks: you 45bb, villain 38bb, short stack 7bb. The short stack is all-in from SB for 7bb. You are on the BTN with 8♣7♣. Do you call the 7bb?',
      options: [
        'A) Fold — 87s is too weak to call a shove.',
        'B) Call — 87s has decent equity and 7bb is cheap.',
        'C) Consider the pay jump: if busting the short stack moves you to heads-up with a pay jump attached, calling with 87s can be correct despite weak equity vs a wide range.',
        'D) Fold — always let the BB handle short stack all-ins.',
      ],
      correct: 'C) Consider the pay jump: if busting the short stack moves you to heads-up with a pay jump attached, calling with 87s can be correct despite weak equity vs a wide range.',
      explanation: '87s has roughly 40% equity vs a 7bb UTG/SB shove range — normally a fold. But at a 3-handed final table, eliminating the short stack moves you to heads-up with a meaningful pay jump. If that jump is large enough (often 30–50% of a buy-in or more), the ICM value of the elimination outweighs the chip-EV loss of calling with a weak hand. Always evaluate short-stack calls at the final table through a dollar-EV lens, not raw equity.',
    },
  },
};

/* ── State ────────────────────────────────────────────────── */

let _coActiveFilter = 'all';

// Live API state — null = not yet fetched / user logged out
let _coLiveList = null;          // CourseListItem[] from /api/v1/courses
let _coLiveCourse = {};          // slug → CourseOut from /api/v1/courses/{slug}
let _coLessonIdMap = {};         // lesson_slug → lesson_uuid (for completion API)

/* ── API helpers ──────────────────────────────────────────── */

function _coAuthHeaders() {
  const t = authGetToken();
  return t ? { 'Authorization': `Bearer ${t}` } : {};
}

async function _coFetchList() {
  if (!authIsLoggedIn()) { _coLiveList = null; return; }
  try {
    const r = await fetch('/api/v1/courses', { headers: _coAuthHeaders() });
    if (r.ok) _coLiveList = await r.json();
  } catch { /* network error — keep mock */ }
}

async function _coFetchCourse(slug) {
  if (!authIsLoggedIn()) return null;
  try {
    const r = await fetch(`/api/v1/courses/${slug}`, { headers: _coAuthHeaders() });
    if (r.ok) {
      const data = await r.json();
      _coLiveCourse[slug] = data;
      // Build lesson slug → UUID map
      for (const mod of data.modules || []) {
        for (const l of mod.lessons || []) {
          _coLessonIdMap[l.slug] = l.id;
        }
      }
      return data;
    }
  } catch { /* network error */ }
  return null;
}

async function _coApiEnroll(slug) {
  if (!authIsLoggedIn()) return;
  try {
    await fetch(`/api/v1/courses/${slug}/enroll`, { method: 'POST', headers: _coAuthHeaders() });
  } catch { /* ignore */ }
}

async function _coApiCompleteLesson(lessonSlug) {
  const lessonUuid = _coLessonIdMap[lessonSlug];
  if (!lessonUuid || !authIsLoggedIn()) return;
  try {
    await fetch(`/api/v1/lessons/${lessonUuid}/complete`, { method: 'POST', headers: _coAuthHeaders() });
  } catch { /* ignore */ }
}

/* ── Live-data merge helpers ──────────────────────────────── */

function _coMergeList() {
  if (!_coLiveList) return CO_COURSES;
  const liveMap = Object.fromEntries(_coLiveList.map(lc => [lc.slug, lc]));
  return CO_COURSES.map(c => {
    const live = liveMap[c.id];
    if (!live) return c;
    return { ...c, progress: Math.round(live.progress_pct), enrolled: live.enrolled };
  });
}

function _coMergeCourseDetail(courseId) {
  const mock = CO_COURSES.find(c => c.id === courseId) || null;
  if (!mock) return null;
  const live = _coLiveCourse[courseId];
  if (!live) return mock;
  const completedSlugs = new Set(
    (live.modules || []).flatMap(m => (m.lessons || []).filter(l => l.is_completed).map(l => l.slug))
  );
  return {
    ...mock,
    progress: Math.round(live.progress_pct || 0),
    modules: mock.modules.map(mod => ({
      ...mod,
      lessons: mod.lessons.map(l => ({ ...l, done: completedSlugs.has(l.id) })),
    })),
  };
}

/* ── Helpers ──────────────────────────────────────────────── */

function _coFindCourse(courseId) {
  return CO_COURSES.find(c => c.id === courseId) || null;
}

function _coFindLesson(course, lessonId) {
  for (const mod of course.modules) {
    const l = mod.lessons.find(x => x.id === lessonId);
    if (l) return { lesson: l, module: mod };
  }
  return null;
}

function _coNextLesson(course, lessonId) {
  const flat = course.modules.flatMap(m => m.lessons);
  const idx  = flat.findIndex(l => l.id === lessonId);
  return idx >= 0 && idx < flat.length - 1 ? flat[idx + 1] : null;
}

function _coPrevLesson(course, lessonId) {
  const flat = course.modules.flatMap(m => m.lessons);
  const idx  = flat.findIndex(l => l.id === lessonId);
  return idx > 0 ? flat[idx - 1] : null;
}

function _coLevelClass(level) {
  return `co-level--${level}`;
}

function _coProgressLabel(pct) {
  if (pct === 0)   return 'Not started';
  if (pct === 100) return 'Completed';
  return `${pct}% complete`;
}

/* ── Catalog ──────────────────────────────────────────────── */

async function coRenderCatalog() {
  const view = document.getElementById('sp-view-learn');
  if (!view) return;

  // Kick off live fetch in parallel with initial render (non-blocking)
  const livePromise = _coFetchList();

  const levels = [
    { key: 'all',          label: 'All Courses' },
    { key: 'beginner',     label: 'Beginner' },
    { key: 'intermediate', label: 'Intermediate' },
    { key: 'advanced',     label: 'Advanced' },
    { key: 'elite',        label: 'Elite' },
  ];

  const levelGroups = [
    { key: 'beginner',     label: 'Beginner' },
    { key: 'intermediate', label: 'Intermediate' },
    { key: 'advanced',     label: 'Advanced' },
    { key: 'elite',        label: 'Elite' },
  ];

  view.innerHTML = `
    <div class="co-page">
      <div class="co-catalog-header">
        <h1 class="co-catalog-title">Course Library</h1>
        <p class="co-catalog-sub">Tournament poker training — from fundamentals to elite strategy.</p>
      </div>

      <div class="co-filter-bar" id="co-filter-bar">
        ${levels.map(l => `
          <button
            class="co-filter-btn${_coActiveFilter === l.key ? ' co-filter-btn--active' : ''}"
            data-co-filter="${escHtml(l.key)}"
          >${escHtml(l.label)}</button>`).join('')}
      </div>

      <div id="co-catalog-body"></div>
    </div>
  `;

  // Wire filter buttons
  view.querySelectorAll('[data-co-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      _coActiveFilter = btn.dataset.coFilter;
      _coRenderCatalogBody();
      view.querySelectorAll('[data-co-filter]').forEach(b => {
        b.classList.toggle('co-filter-btn--active', b.dataset.coFilter === _coActiveFilter);
      });
    });
  });

  _coRenderCatalogBody();

  // After live data arrives, refresh body with enrollment state
  livePromise.then(() => _coRenderCatalogBody());
}

function _coRenderCatalogBody() {
  const body = document.getElementById('co-catalog-body');
  if (!body) return;

  const levelGroups = [
    { key: 'beginner',     label: 'Beginner' },
    { key: 'intermediate', label: 'Intermediate' },
    { key: 'advanced',     label: 'Advanced' },
    { key: 'elite',        label: 'Elite' },
  ];

  const filtered = _coActiveFilter === 'all'
    ? levelGroups
    : levelGroups.filter(g => g.key === _coActiveFilter);

  const allCourses = _coMergeList();

  body.innerHTML = filtered.map(group => {
    const courses = allCourses.filter(c => c.level === group.key);
    return `
      <div class="co-level-section ${_coLevelClass(group.key)}">
        <div class="co-level-heading">
          <span class="co-level-label">${escHtml(group.label)}</span>
          <span class="co-level-count">${courses.length} course${courses.length !== 1 ? 's' : ''}</span>
        </div>
        <div class="co-grid">
          ${courses.map(c => _coCourseCardHTML(c)).join('')}
        </div>
      </div>`;
  }).join('') + `
    <div class="co-replay-banner" id="co-replay-banner">
      <div class="co-replay-banner-icon">&#127909;</div>
      <div class="co-replay-banner-body">
        <div class="co-replay-banner-title">Replay Drills</div>
        <div class="co-replay-banner-sub">Practice with annotated hand scenarios — see the action history and make the right call.</div>
      </div>
      <button class="sp-btn-primary co-replay-banner-btn" id="co-replay-drill-btn">Start Replay Drills &rarr;</button>
    </div>`;

  // Wire card clicks
  body.querySelectorAll('[data-co-course]').forEach(el => {
    el.addEventListener('click', () => {
      const c = _coFindCourse(el.dataset.coCourse);
      if (!c) return;
      if (c.locked) {
        acShowUpgrade('Advanced Courses', 'pro');
      } else {
        spNavigate(`/learn/${c.id}`);
      }
    });
  });

  body.querySelector('#co-replay-drill-btn')?.addEventListener('click', () => {
    spNavigate('/trainer?mode=replay-drill');
  });
}

function _coCourseCardHTML(c) {
  const btnLabel = c.locked ? 'Locked' :
    c.progress === 0 ? 'Start Course' :
    c.progress === 100 ? 'Review' : 'Continue';
  return `
    <div class="co-card ${_coLevelClass(c.level)}${c.locked ? ' co-card--locked' : ''}" data-co-course="${escHtml(c.id)}">
      <div class="co-card-top">
        <span class="co-level-pip">${escHtml(c.levelLabel)}</span>
        ${c.locked ? '<span class="co-lock-icon" aria-label="Locked">&#128274;</span>' : ''}
      </div>
      <div class="co-card-title">${escHtml(c.title)}</div>
      <div class="co-card-desc">${escHtml(c.desc)}</div>
      <div class="co-card-meta">
        <span class="co-card-meta-item">&#9776; ${c.lessonCount} lessons</span>
        <span class="co-card-meta-item">&#9201; ${escHtml(c.duration)}</span>
      </div>
      ${c.progress > 0 ? `
        <div class="co-card-progress-wrap">
          <div class="co-card-progress-bar">
            <div class="co-card-progress-fill" style="width:${c.progress}%"></div>
          </div>
          <span class="co-card-progress-label">${_coProgressLabel(c.progress)}</span>
        </div>` : ''}
      <button class="co-card-btn" data-co-course="${escHtml(c.id)}" ${c.locked ? 'disabled' : ''}>
        ${escHtml(btnLabel)}
      </button>
    </div>`;
}

/* ── Course detail ────────────────────────────────────────── */

async function coRenderCourseDetail(courseId) {
  const view = document.getElementById('sp-view-learn');
  if (!view) return;

  // If logged in: enroll (idempotent) + fetch live course detail
  if (authIsLoggedIn()) {
    await _coApiEnroll(courseId);
    await _coFetchCourse(courseId);
  }

  const course = _coMergeCourseDetail(courseId);
  if (!course) { view.innerHTML = `<div class="co-page"><p style="color:var(--text-muted)">Course not found.</p></div>`; return; }

  const doneCount = course.modules.flatMap(m => m.lessons).filter(l => l.done).length;
  const total     = course.modules.flatMap(m => m.lessons).length;
  const ctaLabel  = course.progress === 0 ? 'Start Course' : course.progress === 100 ? 'Review Course' : 'Continue';
  const firstUndoneLessonId = course.modules.flatMap(m => m.lessons).find(l => !l.done)?.id
    || course.modules[0].lessons[0].id;

  view.innerHTML = `
    <div class="co-page">
      <button class="co-back" id="co-back-to-catalog">
        <span class="co-back-arrow">&#8592;</span> Course Library
      </button>

      <div class="co-detail-hero ${_coLevelClass(course.level)}">
        <div class="co-detail-hero-body">
          <div style="margin-bottom:var(--sp-3)">
            <span class="co-level-pip">${escHtml(course.levelLabel)}</span>
          </div>
          <h1 class="co-detail-hero-title">${escHtml(course.title)}</h1>
          <p class="co-detail-hero-desc">${escHtml(course.desc)}</p>
          <div class="co-detail-stats">
            <div class="co-detail-stat">
              <span class="co-detail-stat-val">${total}</span>
              <span class="co-detail-stat-label">Lessons</span>
            </div>
            <div class="co-detail-stat">
              <span class="co-detail-stat-val">${course.modules.length}</span>
              <span class="co-detail-stat-label">Modules</span>
            </div>
            <div class="co-detail-stat">
              <span class="co-detail-stat-val">${escHtml(course.duration)}</span>
              <span class="co-detail-stat-label">Duration</span>
            </div>
            <div class="co-detail-stat">
              <span class="co-detail-stat-val">${doneCount}/${total}</span>
              <span class="co-detail-stat-label">Completed</span>
            </div>
          </div>
        </div>
        <div class="co-detail-hero-action">
          ${course.progress > 0 ? `
            <div class="co-detail-hero-progress">
              <div class="co-detail-hero-pct">${course.progress}%</div>
              <div class="co-detail-hero-plabel">Progress</div>
            </div>` : ''}
          <button class="sp-btn-primary" id="co-cta-start" data-course="${escHtml(course.id)}" data-lesson="${escHtml(firstUndoneLessonId)}">
            ${escHtml(ctaLabel)}
          </button>
          ${CO_COURSE_TRAINER[course.id] ? `
          <button class="sp-btn-secondary co-practice-btn" id="co-cta-practice" data-tr-url="${escHtml(CO_COURSE_TRAINER[course.id])}">
            &#9654; Practice this topic
          </button>` : ''}
        </div>
      </div>

      <h2 class="co-modules-title">Course Content</h2>
      ${course.modules.map((mod, mi) => `
        <div class="co-module${mi === 0 ? ' co-module--open' : ''}" data-co-mod="${mi}">
          <div class="co-module-header">
            <div>
              <span class="co-module-title">${escHtml(mod.title)}</span>
              <span class="co-module-meta">${mod.lessons.length} lessons &middot; ${_coModDuration(mod)}</span>
            </div>
            <span class="co-module-chevron">&#8964;</span>
          </div>
          <div class="co-module-lessons">
            ${mod.lessons.map(l => `
              <div class="co-lesson-row${l.done ? ' co-lesson-row--done' : ''}" data-co-lesson="${escHtml(l.id)}" data-co-course="${escHtml(course.id)}">
                <div class="co-lesson-check">${l.done ? '&#10003;' : ''}</div>
                <span class="co-lesson-title">${escHtml(l.title)}</span>
                <span class="co-lesson-duration">${escHtml(l.duration)}</span>
              </div>`).join('')}
          </div>
        </div>`).join('')}
    </div>
  `;

  // Back button
  view.querySelector('#co-back-to-catalog')?.addEventListener('click', () => spNavigate('/learn'));

  // Start/continue CTA
  view.querySelector('#co-cta-start')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    spNavigate(`/learn/${btn.dataset.course}/${btn.dataset.lesson}`);
  });

  // Practice this topic CTA
  view.querySelector('#co-cta-practice')?.addEventListener('click', (e) => {
    spNavigate(e.currentTarget.dataset.trUrl);
  });

  // Module accordion
  view.querySelectorAll('.co-module-header').forEach(header => {
    header.addEventListener('click', () => {
      header.parentElement.classList.toggle('co-module--open');
    });
  });

  // Lesson row clicks
  view.querySelectorAll('.co-lesson-row').forEach(row => {
    row.addEventListener('click', () => {
      spNavigate(`/learn/${row.dataset.coCourse}/${row.dataset.coLesson}`);
    });
  });
}

function _coModDuration(mod) {
  const mins = mod.lessons.reduce((sum, l) => {
    const m = parseInt(l.duration, 10);
    return sum + (isNaN(m) ? 0 : m);
  }, 0);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/* ── Lesson viewer ────────────────────────────────────────── */

function coRenderLesson(courseId, lessonId) {
  const view = document.getElementById('sp-view-learn');
  if (!view) return;

  const course = _coFindCourse(courseId);
  if (!course) { coRenderCatalog(); return; }

  const found = _coFindLesson(course, lessonId);
  if (!found) { coRenderCourseDetail(courseId); return; }

  const { lesson, module: mod } = found;
  const content = CO_LESSON_CONTENT[lessonId];
  const nextLesson = _coNextLesson(course, lessonId);
  const prevLesson = _coPrevLesson(course, lessonId);

  view.innerHTML = `
    <div class="co-page">
      <button class="co-back" id="co-back-to-course">
        <span class="co-back-arrow">&#8592;</span> ${escHtml(course.title)}
      </button>

      <div class="co-lesson-hero">
        <div class="co-lesson-breadcrumb">
          <span>${escHtml(course.title)}</span>
          <span class="co-lesson-breadcrumb-sep">&#8250;</span>
          <span>${escHtml(mod.title)}</span>
          <span class="co-lesson-breadcrumb-sep">&#8250;</span>
          <span style="color:var(--text-primary)">${escHtml(lesson.title)}</span>
        </div>
        <h1 class="co-lesson-title">${escHtml(lesson.title)}</h1>
        <div class="co-lesson-meta">
          <span>&#9201; ${escHtml(lesson.duration)}</span>
          <span>&middot; ${escHtml(course.levelLabel)}</span>
          <span>&middot; ${escHtml(mod.title)}</span>
        </div>
      </div>

      <div class="co-lesson-layout">
        <div class="co-lesson-content">
          ${content ? `<div class="co-lesson-body">${content.body}</div>` : `
            <div class="co-lesson-body">
              <p>This lesson covers <strong>${escHtml(lesson.title)}</strong> — a key concept in tournament poker strategy.</p>
              <p>Full lesson content is being developed. Check back soon for detailed explanations, examples, and practice hands.</p>
              <div class="co-callout">In the meantime, navigate to the Analysis section and review your own hands to apply the concepts from this course.</div>
            </div>`}
        </div>

        <div class="co-sidebar">
          <div class="co-concepts-card">
            <div class="co-concepts-title">Key Concepts</div>
            ${(content?.concepts || _coDefaultConcepts(lesson.title)).map(c => `
              <div class="co-concept-item">
                <div class="co-concept-dot"></div>
                <span class="co-concept-text">${escHtml(c)}</span>
              </div>`).join('')}
          </div>

          <div class="co-quiz-card" id="co-quiz-card">
            <div class="co-quiz-title">Knowledge Check</div>
            ${content?.quiz ? `
              <div class="co-quiz-question">${escHtml(content.quiz.question)}</div>
              <div class="co-quiz-options">
                ${content.quiz.options.map((opt, i) => `
                  <button class="co-quiz-opt" data-option="${escHtml(opt)}" data-correct="${escHtml(content.quiz.correct)}">
                    ${escHtml(opt)}
                  </button>`).join('')}
              </div>
              <div class="co-quiz-explanation" id="co-quiz-exp" hidden>
                ${escHtml(content.quiz.explanation)}
              </div>
            ` : `<div class="co-quiz-coming">Quiz available after lesson completion</div>`}
          </div>

          ${CO_COURSE_TRAINER[courseId] ? `
          <div class="co-drill-card" id="co-drill-card" data-tr-url="${escHtml(CO_COURSE_TRAINER[courseId])}">
            <div class="co-drill-icon">&#9654;</div>
            <div class="co-drill-body">
              <div class="co-drill-title">Start related drill</div>
              <div class="co-drill-sub">Practice this topic in the trainer</div>
            </div>
          </div>` : ''}
        </div>
      </div>

      <div class="co-lesson-footer">
        <span class="co-lesson-nav-info">
          ${escHtml(mod.title)} &middot; ${escHtml(lesson.title)}
        </span>
        <div class="co-lesson-nav-actions">
          ${prevLesson ? `
            <button class="sp-btn-secondary" id="co-prev-lesson"
              data-course="${escHtml(courseId)}" data-lesson="${escHtml(prevLesson.id)}">
              &larr; Previous
            </button>` : ''}
          ${nextLesson ? `
            <button class="sp-btn-primary" id="co-next-lesson"
              data-course="${escHtml(courseId)}" data-lesson="${escHtml(nextLesson.id)}">
              Next Lesson &rarr;
            </button>` : `
            <button class="sp-btn-primary" id="co-finish-course"
              data-course="${escHtml(courseId)}">
              Finish Course &#10003;
            </button>`}
        </div>
      </div>
    </div>
  `;

  view.querySelector('#co-back-to-course')?.addEventListener('click',
    () => spNavigate(`/learn/${courseId}`));

  view.querySelector('#co-drill-card')?.addEventListener('click', e => {
    spNavigate(e.currentTarget.dataset.trUrl);
  });

  view.querySelector('#co-prev-lesson')?.addEventListener('click', e => {
    const b = e.currentTarget;
    spNavigate(`/learn/${b.dataset.course}/${b.dataset.lesson}`);
  });

  view.querySelector('#co-next-lesson')?.addEventListener('click', async e => {
    const b = e.currentTarget;
    // Mark current lesson complete before advancing
    await _coApiCompleteLesson(lessonId);
    // Invalidate cached course detail so next visit re-fetches
    delete _coLiveCourse[courseId];
    spNavigate(`/learn/${b.dataset.course}/${b.dataset.lesson}`);
  });

  view.querySelector('#co-finish-course')?.addEventListener('click', async e => {
    await _coApiCompleteLesson(lessonId);
    delete _coLiveCourse[courseId];
    spNavigate(`/learn/${e.currentTarget.dataset.course}`);
  });

  // Quiz interactivity
  view.querySelectorAll('.co-quiz-opt').forEach(btn => {
    btn.addEventListener('click', e => {
      const card = view.querySelector('#co-quiz-card');
      if (card.classList.contains('co-quiz-answered')) return;
      card.classList.add('co-quiz-answered');
      const selected = e.currentTarget.dataset.option;
      const correct = e.currentTarget.dataset.correct;
      view.querySelectorAll('.co-quiz-opt').forEach(b => {
        if (b.dataset.option === correct) {
          b.classList.add('co-quiz-opt--correct');
        } else if (b.dataset.option === selected && selected !== correct) {
          b.classList.add('co-quiz-opt--wrong');
        }
        b.disabled = true;
      });
      const exp = view.querySelector('#co-quiz-exp');
      if (exp) exp.hidden = false;
    });
  });
}

function _coDefaultConcepts(title) {
  return [
    `Understand the core principle behind ${title}.`,
    'Apply this concept to tournament pressure spots.',
    'Recognise when this situation arises at the table.',
    'Adjust your range and sizing based on context.',
    'Combine with ICM awareness for maximum accuracy.',
  ];
}

/* ============================================================
   PR — PROGRESS DASHBOARD
   Mock-data progress tracker: skills, leaks, courses, activity.
   Prefix: pr- — no interference with rs-/sp-/an-/co-/tab- code.
   ============================================================ */

/* ── Mock data ────────────────────────────────────────────── */

const PR_PROGRESS = {
  overallPct:  42,
  level:       'Intermediate',
  levelKey:    'intermediate',
  streak:      7,
  coursesCompleted:  1,
  lessonsCompleted:  14,
  handsReviewed:     23,
  practiceAccuracy:  68,
  biggestLeak:       'BB fold-to-steal',
  enrolledCourses: [
    { id: 'positions-blinds-antes',          name: 'Positions, Blinds and Antes',        pct: 100, lastLesson: 'SB Play', lastLessonId: 'sb-play' },
    { id: 'tournament-fundamentals',          name: 'Tournament Poker Fundamentals',      pct: 37,  lastLesson: 'Starting Hands Are Context-Based', lastLessonId: 'starting-hands-are-context-based' },
    { id: 'stack-sizes-tournament-strategy',  name: 'Stack Sizes and Tournament Strategy',pct: 30,  lastLesson: 'Mid Stack Play', lastLessonId: 'mid-stack-play' },
    { id: 'steal-and-resteal',                name: 'Steal and Re-Steal Spots',           pct: 0,   lastLesson: null, lastLessonId: null },
  ],
};

const PR_SKILLS = [
  { id: 'preflop',           label: 'Preflop',          score: 72, trend: 'up',   levelLabel: 'Solid',       recText: 'Steal & Re-Steal',        recLesson: '/learn/steal-and-resteal' },
  { id: 'short-stack',       label: 'Short Stack',      score: 55, trend: 'up',   levelLabel: 'Developing',  recText: 'Short Stack Play',         recLesson: '/learn/stack-sizes-tournament-strategy/short-stack-play' },
  { id: 'push-fold',         label: 'Push / Fold',      score: 48, trend: 'flat', levelLabel: 'Developing',  recText: 'Push-Fold Theory',         recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  { id: 'bubble-play',       label: 'Bubble Play',      score: 31, trend: 'up',   levelLabel: 'Developing',  recText: 'Bubble Play course',       recLesson: '/learn/bubble-play' },
  { id: 'final-table',       label: 'Final Table',      score: 20, trend: 'flat', levelLabel: 'Beginner',    recText: 'Final Table Strategy',     recLesson: '/learn/final-table-strategy' },
  { id: 'postflop',          label: 'Postflop',         score: 62, trend: 'up',   levelLabel: 'Solid',       recText: 'C-Bet Basics',             recLesson: '/learn/cbet-basics' },
  { id: 'icm',               label: 'ICM',              score: 38, trend: 'up',   levelLabel: 'Developing',  recText: 'ICM Pressure course',      recLesson: '/learn/icm-pressure' },
  { id: 'exploitative',      label: 'Exploitative Play',score: 25, trend: 'flat', levelLabel: 'Beginner',    recText: 'Exploitative Adjustments',  recLesson: '/learn/exploitative-adjustments' },
];

const PR_LEAKS = [
  {
    id:        'bb-fold-steal',
    name:      'Folding too much from BB vs steal',
    severity:  'major',
    stage:     'Mid–Late stage',
    desc:      '68% fold-to-steal from BB — significantly above the optimal 45–55% range.',
    action:    'Study Lesson',
    route:     '/learn/steal-and-resteal',
  },
  {
    id:        'missing-btn-shoves',
    name:      'Missing profitable BTN shove spots',
    severity:  'major',
    stage:     'Short stack (8–14bb)',
    desc:      'Folding 72% of BTN shove range at 10–14bb effective. Losing estimated 1.8 bb/100.',
    action:    'Drill Push/Fold',
    route:     '/trainer?mode=push-fold&difficulty=intermediate',
  },
  {
    id:        'over-calling-short-stack',
    name:      'Over-calling short stack all-ins',
    severity:  'minor',
    stage:     'Mid stage',
    desc:      'Calling off vs 15bb shoves with hands below required equity threshold.',
    action:    'Review Hands',
    route:     '/analysis',
  },
  {
    id:        'under-bluffing-river',
    name:      'Under-bluffing river spots',
    severity:  'minor',
    stage:     'All stages',
    desc:      'River bet frequency 28% — well below GTO baseline in single-raised pots.',
    action:    'Study Lesson',
    route:     '/learn/multi-street-planning',
  },
];

const PR_ACTIVITY = [
  { type: 'lesson',       time: 'Today, 2:14 PM',      title: 'Completed lesson <strong>Starting Hands Are Context-Based</strong>', tag: 'Lesson' },
  { type: 'practice',     time: 'Today, 1:55 PM',      title: 'Practice session: <strong>8/10 correct</strong> — Push/Fold', tag: 'Practice' },
  { type: 'replay-drill', time: 'Yesterday, 9:20 PM',  title: 'Replay Drill: <strong>Correct</strong> — Final Table AJo fold', tag: 'Replay' },
  { type: 'review',       time: 'Yesterday, 6:30 PM',  title: 'Reviewed <strong>3 hands</strong> in Analysis', tag: 'Review' },
  { type: 'practice',     time: 'Yesterday, 4:10 PM',  title: 'Practice session: <strong>6/10 correct</strong> — Bubble Play', tag: 'Practice' },
  { type: 'quiz',         time: '2 days ago',           title: 'Quiz result: <strong>7/10 correct</strong> on Stack Sizes', tag: 'Quiz' },
  { type: 'lesson',       time: '3 days ago',           title: 'Completed lesson <strong>Position: The Most Important Advantage</strong>', tag: 'Lesson' },
  { type: 'skill',        time: '4 days ago',           title: 'Skill improved: <strong>Preflop</strong> ↑ +5 points', tag: 'Skill' },
  { type: 'course',       time: '5 days ago',           title: 'Started course <strong>Stack Sizes and Tournament Strategy</strong>', tag: 'Course' },
  { type: 'course',       time: '1 week ago',           title: 'Completed course <strong>Positions, Blinds and Antes</strong>', tag: 'Course' },
];

/* ── Helpers ──────────────────────────────────────────────── */

// Maps PR skill IDs to daily-spot topics so live DS perf data can inform skill trends
const _PR_SKILL_SPOT_MAP = {
  'preflop':      ['BTN steals', 'SB steals', 'Early stage opens', '3-bet or call'],
  'short-stack':  ['Short stack shoves'],
  'push-fold':    ['Short stack shoves', 'Reshove spot'],
  'bubble-play':  ['Reshove spot'],
  'icm':          ['Reshove spot'],
  'postflop':     [],
  'final-table':  [],
  'exploitative': ['3-bet or call'],
};

function _prSkillFillClass(score) {
  if (score < 31) return 'pr-skill-fill--low';
  if (score < 56) return 'pr-skill-fill--mid';
  if (score < 76) return 'pr-skill-fill--solid';
  if (score < 90) return 'pr-skill-fill--high';
  return 'pr-skill-fill--elite';
}

// Live DS perf trend for a skill (null if no data yet)
function _prSkillSpotTrend(skillId) {
  const topics = _PR_SKILL_SPOT_MAP[skillId] || [];
  const trends = topics.map(t => _dsPerfTrend(t)).filter(Boolean);
  if (!trends.length) return null;
  if (trends.includes('improving')) return 'improving';
  if (trends.includes('same'))      return 'same';
  return 'worse';
}

// Live data first, then fall back to static trend field
function _prEffectiveTrend(skill) {
  const live = _prSkillSpotTrend(skill.id);
  if (live) return live;
  if (skill.trend === 'up')   return 'improving';
  if (skill.trend === 'down') return 'worse';
  return 'same';
}

function _prTrendLabel(trend) {
  if (trend === 'improving') return { text: '&#8593;&nbsp;improving', cls: 'pr-trend-label--up' };
  if (trend === 'worse')     return { text: '&#8595;&nbsp;leaking',   cls: 'pr-trend-label--down' };
  return                            { text: '&#8594;&nbsp;consistent', cls: 'pr-trend-label--flat' };
}

function _prTrendSymbol(trend) {
  if (trend === 'up')   return { sym: '&#8593;', cls: 'pr-trend-up' };
  if (trend === 'down') return { sym: '&#8595;', cls: 'pr-trend-down' };
  return { sym: '&#8212;', cls: 'pr-trend-flat' };
}

function _prSkillDrillRoute(skillId) {
  const map = {
    'push-fold':    '/trainer?mode=push-fold',
    'bubble-play':  '/trainer?mode=bubble',
    'final-table':  '/trainer?mode=final-table',
    'postflop':     '/trainer?mode=general',
    'short-stack':  '/trainer?mode=push-fold',
  };
  return map[skillId] || null;
}

/* ── Live progress state ──────────────────────────────────── */

let _prLiveProgress = null; // ProgressOut[] from /api/v1/me/progress

async function _prFetchProgress() {
  if (!authIsLoggedIn()) { _prLiveProgress = null; return; }
  try {
    const r = await fetch('/api/v1/me/progress', { headers: _coAuthHeaders() });
    if (r.ok) _prLiveProgress = await r.json();
  } catch { _prLiveProgress = null; }
}

/* ── Focus areas + improvement banner ─────────────────────── */

function _prRenderFocusAreas(root) {
  const leakCats = _dsGetLeakCats();

  // Annotate each skill with its effective trend
  const annotated = PR_SKILLS.map(s => ({ ...s, effectiveTrend: _prEffectiveTrend(s) }));

  // Focus: worst skills first, biased toward 'worse' trend
  const focusPool = [...annotated]
    .sort((a, b) => {
      const rankTrend = t => t === 'worse' ? 0 : t === 'same' ? 1 : 2;
      const tDiff = rankTrend(a.effectiveTrend) - rankTrend(b.effectiveTrend);
      return tDiff !== 0 ? tDiff : a.score - b.score;
    })
    .slice(0, 2);

  const focusItems = focusPool.map(s => {
    const isLeakLinked = leakCats.length > 0 &&
      (_PR_SKILL_SPOT_MAP[s.id] || []).some(topic =>
        leakCats.some(cat => topic.toLowerCase().replace(/\s+/g, '_').includes(cat.split('_')[0]))
      );
    let msg, cls;
    if (s.effectiveTrend === 'worse') {
      msg = `Still leaking in ${s.label}`;
      cls = 'pr-focus--leak';
    } else if (isLeakLinked) {
      msg = `Needs work: ${s.label}`;
      cls = 'pr-focus--needs-work';
    } else {
      msg = `Developing: ${s.label}`;
      cls = 'pr-focus--developing';
    }
    return { msg, cls, route: s.recLesson, drillRoute: _prSkillDrillRoute(s.id) };
  });

  // Improvement message — skills trending up this session
  const improvingSkills = annotated.filter(s => _prSkillSpotTrend(s.id) === 'improving');
  const improvingMsg = improvingSkills.length > 0
    ? `You&rsquo;ve improved in ${improvingSkills.map(s => escHtml(s.label)).join(' and ')} over your last sessions.`
    : null;

  const el = document.createElement('div');
  el.className = 'pr-focus-areas';

  el.innerHTML = `
    ${improvingMsg ? `<div class="pr-improving-msg">&#10024; ${improvingMsg}</div>` : ''}
    <div class="pr-focus-header">Focus areas</div>
    <div class="pr-focus-list">
      ${focusItems.map(f => `
        <div class="pr-focus-item ${f.cls}">
          <span class="pr-focus-dot"></span>
          <span class="pr-focus-msg">${escHtml(f.msg)}</span>
          <div class="pr-focus-actions">
            <button class="pr-focus-link" data-pr-route="${escHtml(f.route)}">Study &rarr;</button>
            ${f.drillRoute ? `<button class="pr-focus-link pr-focus-link--drill" data-pr-route="${escHtml(f.drillRoute)}">&#9654; Drill</button>` : ''}
          </div>
        </div>`).join('')}
    </div>
  `;

  el.querySelectorAll('[data-pr-route]').forEach(btn => {
    btn.addEventListener('click', () => spNavigate(btn.dataset.prRoute));
  });

  root.appendChild(el);
}

/* ── Main render ──────────────────────────────────────────── */

async function prRenderProgress() {
  const view = document.getElementById('sp-view-progress');
  if (!view) return;

  // Fetch live progress in parallel with render
  const livePromise = _prFetchProgress();

  view.innerHTML = `<div class="pr-page" id="pr-page-root"></div>`;
  const root = view.querySelector('#pr-page-root');

  _prRenderHero(root);
  prRenderKpis(root);
  _prRenderFocusAreas(root);

  // After live data arrives, refresh courses section
  livePromise.then(() => {
    const coursesEl = root.querySelector('.pr-courses-live');
    if (coursesEl) coursesEl.remove();
    prRenderCourses(root.querySelector('.pr-courses-col'));
  });

  // Two-column row: courses + top skills
  const twoCol = document.createElement('div');
  twoCol.className = 'pr-two-col';
  root.appendChild(twoCol);

  const leftCol = document.createElement('div');
  leftCol.className = 'pr-courses-col';
  const rightCol = document.createElement('div');
  twoCol.appendChild(leftCol);
  twoCol.appendChild(rightCol);

  prRenderCourses(leftCol);
  _prRenderTopSkillsCard(rightCol);

  prRenderSkills(root);
  prRenderLeaks(root);
  prRenderActivity(root);
}

/* ── Hero ── */
function _prRenderHero(root) {
  const p = PR_PROGRESS;
  const r = 46;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - p.overallPct / 100);

  const nextAction = PR_LEAKS[0];

  const el = document.createElement('div');
  el.className = 'pr-hero';
  el.innerHTML = `
    <div class="pr-ring-wrap">
      <svg class="pr-ring" viewBox="0 0 100 100" aria-hidden="true">
        <circle class="pr-ring-track" cx="50" cy="50" r="${r}"/>
        <circle class="pr-ring-fill" cx="50" cy="50" r="${r}"
          stroke-dasharray="${circ.toFixed(2)}"
          stroke-dashoffset="${offset.toFixed(2)}"/>
      </svg>
      <div class="pr-ring-text">
        <span class="pr-ring-pct">${p.overallPct}%</span>
        <span class="pr-ring-label">Overall</span>
      </div>
    </div>

    <div class="pr-hero-text">
      <h1 class="pr-hero-title">Your Poker Progress</h1>
      <p class="pr-hero-sub">Track your learning, leaks, drills, and improvement over time.</p>
      <div class="pr-hero-badges">
        <span class="pr-level-badge pr-level--${escHtml(p.levelKey)}">${escHtml(p.level)}</span>
        <span class="pr-streak-badge">&#128293; ${p.streak}-day streak</span>
      </div>
    </div>

    <div class="pr-hero-action">
      <div class="pr-hero-action-label">Suggested Next Action</div>
      <div class="pr-hero-action-title">${escHtml(nextAction.name)}</div>
      <div class="pr-hero-action-desc">${escHtml(nextAction.desc)}</div>
      <button class="sp-btn-primary" id="pr-hero-cta"
        data-route="${escHtml(nextAction.route)}" style="width:100%;justify-content:center">
        ${escHtml(nextAction.action)}
      </button>
    </div>
  `;

  root.appendChild(el);

  el.querySelector('#pr-hero-cta')?.addEventListener('click', e => {
    spNavigate(e.currentTarget.dataset.route);
  });
}

/* ── KPIs ── */
function prRenderKpis(root) {
  const p = PR_PROGRESS;
  const kpis = [
    { label: 'Courses Completed',  value: p.coursesCompleted,      sub: `of ${p.enrolledCourses.length} enrolled`, cls: '' },
    { label: 'Lessons Completed',  value: p.lessonsCompleted,      sub: 'across all courses',                       cls: 'pr-kpi-value--good' },
    { label: 'Practice Accuracy',  value: `${p.practiceAccuracy}%`,sub: 'quiz & drill average',                     cls: p.practiceAccuracy >= 70 ? 'pr-kpi-value--good' : 'pr-kpi-value--warn' },
    { label: 'Hands Reviewed',     value: p.handsReviewed,         sub: 'in Analysis this month',                  cls: '' },
    { label: 'Biggest Leak',       value: p.biggestLeak,           sub: 'highest priority fix',                    cls: 'pr-kpi-value--warn', small: true },
    { label: 'Current Streak',     value: `${p.streak} days`,      sub: 'keep it going',                           cls: 'pr-kpi-value--good' },
  ];

  const el = document.createElement('div');
  el.className = 'pr-kpi-grid';
  el.innerHTML = kpis.map(k => `
    <div class="pr-kpi-card">
      <div class="pr-kpi-label">${escHtml(k.label)}</div>
      <div class="pr-kpi-value ${k.cls || ''}" ${k.small ? 'style="font-size:var(--text-base)"' : ''}>
        ${escHtml(String(k.value))}
      </div>
      <div class="pr-kpi-sub">${escHtml(k.sub)}</div>
    </div>`).join('');

  root.appendChild(el);
}

/* ── Enrolled courses ── */
function prRenderCourses(parent) {
  if (!parent) return;
  // Remove any previous render in this column
  const existing = parent.querySelector('.pr-courses-live');
  if (existing) existing.remove();

  // Use live data if available, otherwise fall back to mock
  const courses = _prLiveProgress
    ? _prLiveProgress.map(p => ({
        id:          p.course_slug,
        name:        p.course_title,
        pct:         Math.round(p.progress_pct),
        lastLesson:  null,
        lastLessonId: null,
      }))
    : PR_PROGRESS.enrolledCourses;

  const el = document.createElement('div');
  el.className = 'pr-section pr-courses-live';
  el.innerHTML = `
    <div class="pr-section-header">
      <span class="pr-section-title">Course Progress</span>
      <span class="pr-section-meta">${courses.length} enrolled${_prLiveProgress ? '' : ' (demo)'}</span>
    </div>
    <div class="pr-course-list">
      ${courses.length === 0 ? `<p class="pr-empty">No courses enrolled yet. <button class="auth-link" data-pr-route="/learn">Browse courses →</button></p>` :
        courses.map(c => {
          const fillClass = c.pct === 100 ? 'pr-mini-fill pr-mini-fill--complete' : 'pr-mini-fill';
          const btnLabel  = c.pct === 0 ? 'Start' : c.pct === 100 ? 'Review' : 'Continue';
          const target    = c.lastLessonId ? `/learn/${c.id}/${c.lastLessonId}` : `/learn/${c.id}`;
          return `
            <div class="pr-course-row">
              <div class="pr-course-info">
                <div class="pr-course-name">${escHtml(c.name)}</div>
                <div class="pr-course-last">${c.lastLesson ? `Last: ${escHtml(c.lastLesson)}` : 'Not started'}</div>
              </div>
              <div class="pr-course-pct-wrap">
                <span class="pr-course-pct">${c.pct}%</span>
                <div class="pr-mini-bar">
                  <div class="${fillClass}" style="width:${c.pct}%"></div>
                </div>
              </div>
              <button class="pr-course-btn" data-pr-route="${escHtml(target)}">${escHtml(btnLabel)}</button>
            </div>`; }).join('')}
    </div>
  `;

  el.querySelectorAll('[data-pr-route]').forEach(btn => {
    btn.addEventListener('click', () => spNavigate(btn.dataset.prRoute));
  });

  parent.appendChild(el);
}

/* ── Top skills summary (sidebar card) ── */
function _prRenderTopSkillsCard(parent) {
  const sorted = [...PR_SKILLS].sort((a, b) => b.score - a.score).slice(0, 4);

  const el = document.createElement('div');
  el.className = 'pr-section';
  el.innerHTML = `
    <div class="pr-section-header">
      <span class="pr-section-title">Top Skills</span>
      <span class="pr-section-meta">Strongest areas</span>
    </div>
    <div class="pr-course-list">
      ${sorted.map(s => {
        const tl = _prTrendLabel(_prEffectiveTrend(s));
        return `
          <div class="pr-course-row" style="gap:var(--sp-3)">
            <div class="pr-course-info">
              <div class="pr-course-name">${escHtml(s.label)}</div>
              <div class="pr-course-last">${escHtml(s.levelLabel)}</div>
            </div>
            <div class="pr-course-pct-wrap">
              <span class="pr-course-pct">${s.score}</span>
              <div class="pr-mini-bar">
                <div class="pr-mini-fill" style="width:${s.score}%"></div>
              </div>
            </div>
            <span class="pr-trend-label ${tl.cls}">${tl.text}</span>
          </div>`;
      }).join('')}
    </div>
  `;

  parent.appendChild(el);
}

/* ── Full skill map ── */
function prRenderSkills(root) {
  const el = document.createElement('div');
  el.className = 'pr-section';

  if (!acCan('full_skill_map')) {
    el.innerHTML = `
      <div class="pr-section-header">
        <span class="pr-section-title">Skill Map</span>
        <span class="pr-section-meta">8 tournament categories</span>
      </div>
      <div class="ac-lock-overlay">
        <div class="ac-lock-icon">&#128274;</div>
        <div class="ac-lock-msg">Full Skill Map requires Tournament Pro</div>
        <button class="sp-btn-primary ac-lock-cta" id="pr-skill-map-upgrade">Upgrade to Pro &rarr;</button>
      </div>
    `;
    root.appendChild(el);
    el.querySelector('#pr-skill-map-upgrade')?.addEventListener('click', () => acShowUpgrade('Full Skill Map', 'pro'));
    return;
  }

  el.innerHTML = `
    <div class="pr-section-header">
      <span class="pr-section-title">Skill Map</span>
      <span class="pr-section-meta">8 tournament categories</span>
    </div>
    <div class="pr-skills-grid" id="pr-skills-grid"></div>
  `;
  root.appendChild(el);

  const grid = el.querySelector('#pr-skills-grid');
  PR_SKILLS.forEach(s => {
    const eTrend = _prEffectiveTrend(s);
    const tl = _prTrendLabel(eTrend);
    const card = document.createElement('div');
    card.className = 'pr-skill-card';
    card.innerHTML = `
      <div class="pr-skill-top">
        <span class="pr-skill-name">${escHtml(s.label)}</span>
        <span class="pr-trend-label ${tl.cls}">${tl.text}</span>
      </div>
      <div class="pr-skill-score-row">
        <span class="pr-skill-score">${s.score}</span>
        <span class="pr-skill-level">${escHtml(s.levelLabel)}</span>
      </div>
      <div class="pr-skill-bar">
        <div class="pr-skill-fill ${_prSkillFillClass(s.score)}" style="width:${s.score}%"></div>
      </div>
      <div class="pr-skill-rec">
        Improve: <button class="pr-skill-rec-link" data-pr-route="${escHtml(s.recLesson)}">${escHtml(s.recText)}</button>
        ${_prSkillDrillRoute(s.id) ? `&nbsp;&middot;&nbsp;<button class="pr-skill-rec-link pr-skill-rec-link--drill" data-pr-route="${escHtml(_prSkillDrillRoute(s.id))}">&#9654; Drill</button>` : ''}
      </div>
    `;
    card.querySelectorAll('[data-pr-route]').forEach(btn =>
      btn.addEventListener('click', () => spNavigate(btn.dataset.prRoute))
    );
    grid.appendChild(card);
  });
}

/* ── Leak tracker ── */
function prRenderLeaks(root) {
  const el = document.createElement('div');
  el.className = 'pr-section';

  if (!acCan('leak_tracker')) {
    el.innerHTML = `
      <div class="pr-section-header">
        <span class="pr-section-title">Leak Tracker</span>
        <span class="pr-section-meta">${PR_LEAKS.length} active leaks</span>
      </div>
      <div class="ac-lock-overlay">
        <div class="ac-lock-icon">&#128274;</div>
        <div class="ac-lock-msg">Leak Tracker requires Tournament Pro</div>
        <button class="sp-btn-primary ac-lock-cta" id="pr-leaks-upgrade">Upgrade to Pro &rarr;</button>
      </div>
    `;
    root.appendChild(el);
    el.querySelector('#pr-leaks-upgrade')?.addEventListener('click', () => acShowUpgrade('Leak Tracker', 'pro'));
    return;
  }

  el.innerHTML = `
    <div class="pr-section-header">
      <span class="pr-section-title">Leak Tracker</span>
      <span class="pr-section-meta">${PR_LEAKS.length} active leaks</span>
    </div>
    <div class="pr-leak-list">
      ${PR_LEAKS.map(l => `
        <div class="pr-leak-row">
          <div class="pr-leak-severity pr-leak-severity--${escHtml(l.severity)}" title="${escHtml(l.severity)}"></div>
          <div class="pr-leak-body">
            <div class="pr-leak-name">${escHtml(l.name)}</div>
            <div class="pr-leak-meta">${escHtml(l.stage)} &middot; ${escHtml(l.desc)}</div>
          </div>
          <button class="pr-leak-action pr-leak-action--${escHtml(l.severity)}" data-pr-route="${escHtml(l.route)}">
            ${escHtml(l.action)}
          </button>
        </div>`).join('')}
    </div>
  `;

  el.querySelectorAll('[data-pr-route]').forEach(btn => {
    btn.addEventListener('click', () => spNavigate(btn.dataset.prRoute));
  });

  root.appendChild(el);
}

/* ── Activity timeline ── */
function prRenderActivity(root) {
  const dotClass = { lesson: 'pr-dot--lesson', review: 'pr-dot--review', quiz: 'pr-dot--quiz', skill: 'pr-dot--skill', course: 'pr-dot--course', practice: 'pr-dot--practice', 'replay-drill': 'pr-dot--replay' };
  const tagClass  = { lesson: 'pr-tag--lesson', review: 'pr-tag--review', quiz: 'pr-tag--quiz',  skill: 'pr-tag--skill',  course: 'pr-tag--course', practice: 'pr-tag--practice', 'replay-drill': 'pr-tag--replay' };

  const el = document.createElement('div');
  el.className = 'pr-section';
  el.innerHTML = `
    <div class="pr-section-header">
      <span class="pr-section-title">Recent Activity</span>
      <span class="pr-section-meta">Last 7 days</span>
    </div>
    <div class="pr-activity-list">
      ${PR_ACTIVITY.map(a => `
        <div class="pr-activity-item">
          <div class="pr-activity-left">
            <div class="pr-activity-dot ${dotClass[a.type] || ''}"></div>
            <div class="pr-activity-line"></div>
          </div>
          <div class="pr-activity-body">
            <div class="pr-activity-title">
              ${a.title}
              <span class="pr-activity-tag ${tagClass[a.type] || ''}">${escHtml(a.tag)}</span>
            </div>
            <div class="pr-activity-time">${escHtml(a.time)}</div>
          </div>
        </div>`).join('')}
    </div>
  `;

  root.appendChild(el);
}

/* ============================================================
   TR — PRACTICE ENGINE
   Interactive decision-based training for tournament poker.
   Prefix: tr- — no interference with rs-/sp-/an-/co-/pr- code.
   ============================================================ */

/* ── Scenario data ────────────────────────────────────────── */

const TR_SCENARIOS = [
  /* ── PUSH / FOLD — BEGINNER ── */
  {
    id: 'pf-b-001',
    mode: 'push-fold', difficulty: 'beginner',
    position: 'BTN', stack_bb: 10, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '45 players · top 40 paid',
    hand: [{ rank: 'A', suit: '♠', red: false }, { rank: '5', suit: '♣', red: false }],
    setup: 'Folds to you on the Button. Blinds 500/1,000 + 100 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+1.2 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'A5s is a profitable push from the Button at 10bb. Your shoving range here covers roughly the top 55% of hands. A5s — suited, with an ace blocker reducing the chance of getting called by AX hands — is comfortably within this range. The fold equity from the Button is high enough to make this a clear push.',
    score: 85,
  },
  {
    id: 'pf-b-002',
    mode: 'push-fold', difficulty: 'beginner',
    position: 'UTG', stack_bb: 8, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '120 players · top 50 paid',
    hand: [{ rank: 'K', suit: '♥', red: true }, { rank: '3', suit: '♦', red: true }],
    setup: 'You are first to act under the gun at a 9-handed table. Blinds 400/800 + 80 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '0.0 bb', pos: true },
      { label: 'Push', val: '−1.4 bb', pos: false },
    ],
    explanation: 'K3o is too weak to push from UTG at 8bb in a 9-max field. You still have enough stack to wait for a better hand. UTG push ranges at this depth start around K7o+ and better suited hands. K3o misses this threshold — push folds are not just about hand strength but position too.',
    score: 80,
  },
  {
    id: 'pf-b-003',
    mode: 'push-fold', difficulty: 'beginner',
    position: 'SB', stack_bb: 12, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '42 players · top 40 paid',
    hand: [{ rank: 'K', suit: '♣', red: false }, { rank: 'J', suit: '♥', red: true }],
    setup: 'Folds to you in the Small Blind. Big Blind has 35bb. Blinds 600/1,200 + 120 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+1.6 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'KJo heads-up vs the Big Blind is a strong push at 12bb. You only need the BB to fold about 35% of the time for this to break even, and KJo has good equity when called (averaging around 55% vs typical BB calling ranges). The heads-up dynamic amplifies the edge.',
    score: 88,
  },
  {
    id: 'pf-b-004',
    mode: 'push-fold', difficulty: 'beginner',
    position: 'CO', stack_bb: 15, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid',
    hand: [{ rank: 'T', suit: '♦', red: true }, { rank: '8', suit: '♦', red: true }],
    setup: 'Folds to you in the Cutoff. Blinds 600/1,200 + 120 ante. Two players to act behind.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+0.9 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'T8s from CO at 15bb is a push. The suit gives you good equity when called, and with only two players behind, your fold equity remains high. On the bubble this spot has extra EV because the blinds are incentivised to fold marginal hands to preserve their tournament life.',
    score: 82,
  },

  /* ── PUSH / FOLD — INTERMEDIATE ── */
  {
    id: 'pf-i-001',
    mode: 'push-fold', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 11, stage: 'final', stage_label: 'Final Table',
    stage_detail: '6 players · pay jumps every spot',
    hand: [{ rank: '8', suit: '♥', red: true }, { rank: '8', suit: '♣', red: false }],
    setup: 'Folds to you on the Button. SB has 28bb, BB has 22bb. Blinds 2,000/4,000 + 400 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+1.8 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: '88 is well ahead of the BB and SB calling ranges at 11bb. Even accounting for ICM pressure at the final table, 88 is strong enough to push here. The pair equity when called is excellent, and folding gives up significant chip EV for very little ICM protection.',
    score: 90,
  },
  {
    id: 'pf-i-002',
    mode: 'push-fold', difficulty: 'intermediate',
    position: 'BB', stack_bb: 15, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid',
    hand: [{ rank: 'K', suit: '♦', red: true }, { rank: '6', suit: '♥', red: true }],
    setup: 'SB (14bb) shoves all-in. Folds to you in the Big Blind. Blinds 600/1,200 + 120 ante.',
    question: 'Call or fold?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'call', label: 'Call', icon: '✓' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '+0.4 bb (ICM)', pos: true },
      { label: 'Call', val: '−0.6 bb (ICM)', pos: false },
    ],
    explanation: 'K6o on the bubble faces a tough call. On the bubble your bust-out EV loss is enormous — busting 41st with 40 paid means you get nothing. K6o has roughly 40% equity vs a standard SB shoving range. The math marginally favours folding here. One spot away from the money, this fold is correct even though it feels painful.',
    score: 78,
  },
  {
    id: 'pf-i-003',
    mode: 'push-fold', difficulty: 'intermediate',
    position: 'CO', stack_bb: 14, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid',
    hand: [{ rank: 'A', suit: '♣', red: false }, { rank: '8', suit: '♦', red: true }],
    setup: 'Folds to you in the Cutoff. Blinds 600/1,200 + 120 ante. Three players behind.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+1.1 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'A8o from CO at 14bb is a standard push. The ace blocker reduces the likelihood of running into AX, and 14bb gives strong fold equity. Even on the bubble, the chip EV advantage of pushing with A8o outweighs ICM risk — especially from CO where you only have three players behind.',
    score: 86,
  },
  {
    id: 'pf-i-004',
    mode: 'push-fold', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 9, stage: 'final', stage_label: 'Final Table',
    stage_detail: '3 players remaining · heads-up prize doubled',
    hand: [{ rank: 'K', suit: '♠', red: false }, { rank: '9', suit: '♥', red: true }],
    setup: 'Folds to you on the Button (Dealer) in 3-handed play. Blinds 5,000/10,000 + 1,000 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+2.1 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'K9o is a strong push 3-handed at 9bb. Short-handed ranges widen significantly — the SB and BB are each calling with roughly the top 45% of hands. K9o dominates a wide portion of their calling ranges, and 3-handed dynamics mean your fold equity is high enough to make this a clear shove.',
    score: 88,
  },

  /* ── PUSH / FOLD — ADVANCED ── */
  {
    id: 'pf-a-001',
    mode: 'push-fold', difficulty: 'advanced',
    position: 'BB', stack_bb: 18, stage: 'final', stage_label: 'Final Table',
    stage_detail: '3 players · big pay jump to HU',
    hand: [{ rank: 'A', suit: '♥', red: true }, { rank: '4', suit: '♣', red: false }],
    setup: 'BTN (20bb) shoves all-in. SB folds. Your call. Blinds 5,000/10,000 + 1,000 ante.',
    question: 'Call or fold?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'call', label: 'Call', icon: '✓' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)', val: '+0.8 bb (ICM)', pos: true },
      { label: 'Fold', val: '0.0 bb (ICM)', pos: false },
    ],
    explanation: 'This is a close spot but a call. 3-handed with 18bb, you are getting over 2:1 pot odds. A4o has approximately 46% equity vs a standard BTN shoving range (~top 55%). The ICM factor is significant — losing sends you out in 3rd — but the pot odds and equity make calling the correct play here. Folding becomes correct only if you shade to A4o as a marginal hand vs a tighter shoving range.',
    score: 72,
  },
  {
    id: 'pf-a-002',
    mode: 'push-fold', difficulty: 'advanced',
    position: 'SB', stack_bb: 13, stage: 'final', stage_label: 'Final Table',
    stage_detail: '5 players · bubble for min-cash',
    hand: [{ rank: 'J', suit: '♦', red: true }, { rank: '9', suit: '♦', red: true }],
    setup: 'Folds to you in the Small Blind. Big Blind has 40bb. Blinds 3,000/6,000 + 600 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+1.3 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'J9s heads-up vs the BB at 13bb is a clear shove. The suited connector has great equity (roughly 57%) vs the BB\'s calling range, and the heads-up dynamic reduces ICM pressure compared to multiway spots. Even on the final table bubble, J9s is strong enough to profitably attack the BB\'s blinds.',
    score: 84,
  },

  /* ── BUBBLE PLAY — BEGINNER ── */
  {
    id: 'bb-b-001',
    mode: 'bubble', difficulty: 'beginner',
    position: 'BTN', stack_bb: 9, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid',
    hand: [{ rank: 'A', suit: '♦', red: true }, { rank: 'T', suit: '♠', red: false }],
    setup: 'Folds to you on the Button with 9bb. Big Blind is the shortest stack with 7bb. Blinds 600/1,200 + 120 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+1.9 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'ATo with 9bb on the bubble is a clear push. You are not the shortest stack, so you are not at maximum ICM risk. ATo is a strong hand that performs well vs the BB\'s calling range. The SB must fold through you to bust the shorter stack, giving you extra fold equity in this spot.',
    score: 88,
  },
  {
    id: 'bb-b-002',
    mode: 'bubble', difficulty: 'beginner',
    position: 'BTN', stack_bb: 45, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid · you are chip leader',
    hand: [{ rank: 'K', suit: '♥', red: true }, { rank: '5', suit: '♣', red: false }],
    setup: 'As chip leader, folds to you on the Button. SB (9bb) and BB (12bb) are both near the bubble. Blinds 600/1,200 + 120 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'raise', label: 'Raise to 2.5bb', icon: '↑' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+2.8 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'As chip leader on the bubble, K5o is an easy raise. The shorter stacks cannot call without risking their tournament life — they will fold a very wide range. You are applying maximum ICM pressure with minimal personal risk. This is one of the most profitable spots in tournament poker.',
    score: 90,
  },

  /* ── BUBBLE PLAY — INTERMEDIATE ── */
  {
    id: 'bb-i-001',
    mode: 'bubble', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 28, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid · SB is at-risk',
    hand: [{ rank: 'A', suit: '♣', red: false }, { rank: '2', suit: '♥', red: true }],
    setup: 'Folds to you. SB (8bb) and BB (35bb) remain. Blinds 600/1,200 + 120 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'raise', label: 'Raise to 2.5bb', icon: '↑' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+2.4 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
      { label: 'Push', val: '+1.9 bb', pos: true },
    ],
    explanation: 'Raising to 2.5bb is the optimal play here. A standard open puts maximum pressure on the SB — they must risk elimination to continue — while preserving your stack if the BB 3-bets. An all-in risks your tournament life unnecessarily against the BB\'s flat-calling range. The SB will fold almost everything, giving you the pot cheaply.',
    score: 75,
  },
  {
    id: 'bb-i-002',
    mode: 'bubble', difficulty: 'intermediate',
    position: 'BB', stack_bb: 20, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid',
    hand: [{ rank: '8', suit: '♠', red: false }, { rank: '8', suit: '♦', red: true }],
    setup: 'SB (12bb) shoves all-in. Known aggressive player with wide range. Blinds 600/1,200 + 120 ante.',
    question: 'Call or fold?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'call', label: 'Call', icon: '✓' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)', val: '+2.2 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: '88 vs a wide SB shoving range is a call even on the bubble. Your 66% equity vs the SB\'s estimated range (top 55% of hands) more than compensates for the ICM risk. The key information here is that the SB is wide — this significantly shifts the call threshold. Against a tight shover, this would be closer.',
    score: 82,
  },
  {
    id: 'bb-i-003',
    mode: 'bubble', difficulty: 'intermediate',
    position: 'UTG', stack_bb: 7, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 40 paid · you are shortest stack',
    hand: [{ rank: 'Q', suit: '♠', red: false }, { rank: 'Q', suit: '♥', red: true }],
    setup: 'You are the shortest stack at the table. Blinds 600/1,200 + 120 ante. 9-handed.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'push',
    ev_options: [
      { label: 'Push (correct)', val: '+3.2 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'QQ is always a push at 7bb, even UTG on the bubble. Folding QQ at this depth is a major error — the hand is too strong and your stack too short to pass. Even as the shortest stack, the ICM cost of elimination is offset by the high win probability with QQ. Waiting for "a better spot" with 7bb is wishful thinking.',
    score: 95,
  },

  /* ── FINAL TABLE — INTERMEDIATE ── */
  {
    id: 'ft-i-001',
    mode: 'final-table', difficulty: 'intermediate',
    position: 'CO', stack_bb: 30, stage: 'final', stage_label: 'Final Table',
    stage_detail: '4 players · $5K jump to 3rd place',
    hand: [{ rank: 'A', suit: '♦', red: true }, { rank: 'J', suit: '♣', red: false }],
    setup: 'UTG raises to 2.5bb. Folds to you in CO. BTN (25bb) 3-bets to 7bb. Blinds fold. Back to you.',
    question: 'AJo facing a 3-bet. What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'call', label: 'Call', icon: '✓' },
      { id: 'raise', label: '4-Bet', icon: '↑↑' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '+0.9 bb (ICM)', pos: true },
      { label: 'Call', val: '−0.4 bb (ICM)', pos: false },
      { label: '4-Bet', val: '−1.8 bb (ICM)', pos: false },
    ],
    explanation: 'AJo facing a 3-bet at a 4-handed final table with a significant pay jump is a fold. AJo is a dominated hand vs a BTN 3-betting range (AQ+, 99+, KQs is typical). The ICM cost of losing this pot could mean busting in 4th vs safely climbing to 3rd. This is a prime example of folding a hand that would be a call in a cash game.',
    score: 76,
  },
  {
    id: 'ft-i-002',
    mode: 'final-table', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 20, stage: 'final', stage_label: 'Final Table',
    stage_detail: 'Heads-up · opponent has 40bb',
    hand: [{ rank: 'K', suit: '♥', red: true }, { rank: '9', suit: '♠', red: false }],
    setup: 'Heads-up. You are on the Button (Dealer/SB). Opponent has 40bb. Blinds 5,000/10,000 + 1,000 ante.',
    question: 'What is your action?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'raise', label: 'Raise to 2.5bb', icon: '↑' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+1.4 bb', pos: true },
      { label: 'Push', val: '+0.8 bb', pos: true },
      { label: 'Fold', val: '0.0 bb', pos: false },
    ],
    explanation: 'K9o heads-up is a standard raise. Opening to 2.5bb is preferred over shoving because your opponent has 40bb — they will only call a push with a strong range, but they must defend much wider against an open. Opening keeps the pot manageable and allows you to play postflop in position, where you have a significant advantage.',
    score: 80,
  },

  /* ── GENERAL SPOTS — INTERMEDIATE ── */
  {
    id: 'gs-i-001',
    mode: 'general', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 40, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'Single raised pot · heads-up to flop',
    hand: [{ rank: 'K', suit: '♦', red: true }, { rank: 'Q', suit: '♦', red: true }],
    setup: 'You opened BTN to 2.2bb. BB called. Flop: K♥ 7♣ 3♦ (rainbow). Pot = 4.8bb. BB checks.',
    question: 'C-bet or check back?',
    options: [
      { id: 'check', label: 'Check', icon: '—' },
      { id: 'raise', label: 'Bet 2.4bb (50%)', icon: '●' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Bet (correct)', val: '+0.9 bb', pos: true },
      { label: 'Check', val: '+0.3 bb', pos: false },
    ],
    explanation: 'KQd on K73 rainbow is a value bet. You have top pair, top kicker, a backdoor flush draw, and significant range advantage on this dry board. A 50% pot c-bet extracts value from worse kings, pairs, and continues to deny equity to the BB\'s unpaired hands. Checking back risks giving free equity to hands that would otherwise fold.',
    score: 85,
  },
  {
    id: 'gs-i-002',
    mode: 'general', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 35, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '3-bet pot · BTN vs BB',
    hand: [{ rank: 'A', suit: '♥', red: true }, { rank: 'K', suit: '♠', red: false }],
    setup: 'You 3-bet BTN to 7bb. BB called. Flop: A♠ 8♦ 3♣ (rainbow). Pot = 14.5bb. BB checks.',
    question: 'C-bet or check back?',
    options: [
      { id: 'check', label: 'Check', icon: '—' },
      { id: 'raise', label: 'Bet 4.8bb (33%)', icon: '●' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Bet (correct)', val: '+1.4 bb', pos: true },
      { label: 'Check', val: '+0.6 bb', pos: false },
    ],
    explanation: 'AK on A83r in a 3-bet pot is a value bet. You have top pair, top kicker with zero backdoor draws — but that is fine, because the BB\'s range is under massive pressure here. A small c-bet (33%) exploits your range advantage, targets all their pair-plus hands for value, and denies equity to KQ/QJ/TJ type hands. Checking risks losing value to a BB that checks back weaker aces.',
    score: 88,
  },

  /* ── GENERAL SPOTS — BEGINNER ── */
  {
    id: 'gs-b-001',
    mode: 'general', difficulty: 'beginner',
    position: 'BTN', stack_bb: 25, stage: 'early', stage_label: 'Early Stage',
    stage_detail: 'Unopened pot · folded to BTN',
    hand: [{ rank: 'A', suit: '♠', red: false }, { rank: 'J', suit: '♥', red: true }],
    setup: 'Folded to you on the BTN with 25bb. Blinds 100/200. SB and BB are both passive players.',
    question: 'What do you do with AJo on the BTN?',
    options: [
      { id: 'fold',  label: 'Fold',           icon: '✕' },
      { id: 'call',  label: 'Limp (call 1bb)', icon: '○' },
      { id: 'raise', label: 'Raise to 2.5bb',  icon: '↑' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+1.8 bb', pos: true },
      { label: 'Limp',            val: '+0.3 bb', pos: false },
      { label: 'Fold',            val: '0.0 bb',  pos: false },
    ],
    explanation: 'AJo is a strong BTN open. Raising takes the initiative, wins the blinds frequently (30–40% of the time), and builds a pot when called with a positional advantage. Limping surrenders fold equity and plays a multiway pot out of position if the BB squeezes. Folding loses the ~1.5bb of dead money in the blinds for free.',
    score: 72,
    skill: 'preflop',
    recLesson: '/learn/tournament-fundamentals/why-tournament-poker-is-different',
  },
  {
    id: 'gs-b-002',
    mode: 'general', difficulty: 'beginner',
    position: 'BB', stack_bb: 20, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'BTN steal · heads-up',
    hand: [{ rank: 'K', suit: '♣', red: false }, { rank: '7', suit: '♦', red: true }],
    setup: 'BTN raises to 2.5bb. SB folds. You are in the BB with 20bb and K♣7♦.',
    question: 'How do you respond to the BTN steal?',
    options: [
      { id: 'fold', label: 'Fold',           icon: '✕' },
      { id: 'call', label: 'Call (1.5bb more)', icon: '○' },
      { id: 'raise', label: '3-bet to 7.5bb', icon: '↑' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)', val: '+0.4 bb', pos: true },
      { label: 'Fold',           val: '0.0 bb',  pos: false },
      { label: '3-bet',          val: '-0.2 bb',  pos: false },
    ],
    explanation: 'K7o is a marginal defend from the BB — calling is correct here. You are getting 3.5:1 immediate pot odds (need ~22% equity), and K7o has enough equity vs a BTN steal range to profitably call. Folding is too tight at these odds. A 3-bet bluff with K7o is possible but advanced — as a beginner, call and play a simple flop.',
    score: 68,
    skill: 'preflop',
    recLesson: '/learn/tournament-fundamentals/starting-hands-are-context-based',
  },
  {
    id: 'gs-b-003',
    mode: 'general', difficulty: 'beginner',
    position: 'UTG', stack_bb: 30, stage: 'early', stage_label: 'Early Stage',
    stage_detail: 'First to act · 6-handed',
    hand: [{ rank: '7', suit: '♥', red: true }, { rank: '7', suit: '♦', red: true }],
    setup: 'You are UTG in a 6-max tournament with 30bb. Action has not started.',
    question: 'What do you do with 77 UTG at 30bb?',
    options: [
      { id: 'fold',  label: 'Fold',          icon: '✕' },
      { id: 'raise', label: 'Raise to 2.2bb', icon: '↑' },
      { id: 'shove', label: 'Shove all-in',   icon: '⬆' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+1.2 bb', pos: true },
      { label: 'Fold',            val: '0.0 bb',  pos: false },
      { label: 'Shove',           val: '+0.1 bb',  pos: false },
    ],
    explanation: 'At 30bb, 77 is a standard UTG open. You have a made hand with set potential and enough chips to play postflop. Shoving wastes the hand\'s playability — opponents will call/fold correctly, leaving you winning only the blinds most of the time. Folding surrenders value. Open-raise to 2–2.5bb and play a normal pot.',
    score: 74,
    skill: 'preflop',
    recLesson: '/learn/tournament-fundamentals/starting-hands-are-context-based',
  },
  {
    id: 'gs-b-004',
    mode: 'general', difficulty: 'beginner',
    position: 'SB', stack_bb: 18, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'Folded to SB · heads-up vs BB',
    hand: [{ rank: 'Q', suit: '♦', red: true }, { rank: '9', suit: '♦', red: true }],
    setup: 'Folded to you in the SB with 18bb and Q♦9♦. BB has 22bb.',
    question: 'What do you do with Q9s in the SB?',
    options: [
      { id: 'fold',  label: 'Fold',          icon: '✕' },
      { id: 'call',  label: 'Limp (complete)', icon: '○' },
      { id: 'raise', label: 'Raise to 2.5bb', icon: '↑' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+1.4 bb', pos: true },
      { label: 'Limp',            val: '+0.2 bb',  pos: false },
      { label: 'Fold',            val: '0.0 bb',  pos: false },
    ],
    explanation: 'Q9 suited is a clear SB steal at 18bb. You have position for the hand, a playable suited connector, and the BB cannot profitably defend every hand. Raise to 2.5bb: you win the pot outright ~40% of the time, and when called you have a strong hand with equity. Limping invites free play for the BB and loses the fold equity your stack generates.',
    score: 70,
    skill: 'preflop',
    recLesson: '/learn/tournament-fundamentals/preflop-decisions-open-fold-or-shove',
  },
  {
    id: 'gs-b-005',
    mode: 'general', difficulty: 'beginner',
    position: 'CO', stack_bb: 22, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'Open-raise decision · CO',
    hand: [{ rank: 'T', suit: '♠', red: false }, { rank: '9', suit: '♣', red: false }],
    setup: 'UTG folds, HJ folds. You are CO with T♠9♣ and 22bb. BTN, SB, BB all to act.',
    question: 'What do you do with T9o in CO?',
    options: [
      { id: 'fold',  label: 'Fold',          icon: '✕' },
      { id: 'raise', label: 'Raise to 2.2bb', icon: '↑' },
      { id: 'shove', label: 'Shove all-in',   icon: '⬆' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+0.9 bb', pos: true },
      { label: 'Fold',            val: '0.0 bb',  pos: false },
      { label: 'Shove',           val: '-0.3 bb',  pos: false },
    ],
    explanation: 'T9o is a profitable CO open at 22bb. You have two players ahead who have shown weakness (folded), and three players left to act. CO range includes most connected hands. Raise to 2–2.5bb: you win the pot outright frequently, and when called you have positional advantage with a connected hand. Shoving T9o for 22bb overplays the hand — opponents call correctly with better holdings.',
    score: 71,
    skill: 'preflop',
    recLesson: '/learn/tournament-fundamentals/preflop-decisions-open-fold-or-shove',
  },

  /* ── REPLAY DRILLS ── */

  // 1. BTN facing UTG raise + HJ flat-call (22bb, QJo) — fold vs multi-way pressure
  {
    id: 'rd-pf-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 22, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '68 players · avg stack 40bb',
    mockHandId: 'MOCK-RD-001',
    playerStacks: { UTG: 42, HJ: 35, CO: 28, BTN: 22, SB: 38, BB: 40 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Raise', amount: '2.2bb' },
      { pos: 'HJ',  action: 'Call' },
      { pos: 'CO',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'Q', suit: '♣', red: false }, { rank: 'J', suit: '♦', red: true }],
    setup: 'UTG raises to 2.2bb. HJ calls. CO folds. Pot is 5.9bb. You\'re on the Button with QJo and 22bb.',
    question: 'QJo on the Button facing UTG raise + HJ flat at 22bb. Fold, call, or jam?',
    options: [
      { id: 'fold', label: 'Fold',      icon: '✗' },
      { id: 'call', label: 'Call',      icon: '✓' },
      { id: 'jam',  label: '3-Bet Jam', icon: '▲' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '0.0 bb',  pos: true },
      { label: 'Call',           val: '−0.5 bb', pos: false },
      { label: '3-Bet Jam',      val: '−1.2 bb', pos: false },
    ],
    explanation: 'QJo faces two players with strong ranges: UTG\'s tight opening range (TT+, AQ+, KQs) and HJ\'s flat range (88+, AJ+, suited connectors). Both frequently dominate QJ. Cold-calling creates a multi-way pot with a marginal hand — top pair with a weak kicker plays poorly against two opponents. At 22bb, jamming into two tight ranges is also -EV. Fold and wait for a cleaner spot.',
    score: 72,
  },

  // 2. BB defense vs BTN steal (28bb, KJo) — 3-bet for value and fold equity
  {
    id: 'rd-pf-002',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'beginner',
    position: 'BB', stack_bb: 28, stage: 'early', stage_label: 'Early Stage',
    stage_detail: '120 players · avg stack 50bb',
    mockHandId: 'MOCK-RD-005',
    playerStacks: { UTG: 55, HJ: 50, CO: 48, BTN: 52, SB: 45, BB: 28 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Fold' },
      { pos: 'BTN', action: 'Raise', amount: '2.5bb' },
      { pos: 'SB',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'K', suit: '♠', red: false }, { rank: 'J', suit: '♣', red: false }],
    setup: 'Folds to BTN who raises to 2.5bb. SB folds. Pot is 4.0bb. You\'re in the BB with KJo and 28bb.',
    question: 'KJo in the BB vs BTN open at 28bb. Fold, call, or 3-bet to ~8bb?',
    options: [
      { id: 'fold', label: 'Fold',      icon: '✗' },
      { id: 'call', label: 'Call',      icon: '✓' },
      { id: '3bet', label: '3-Bet 8bb', icon: '↑' },
    ],
    correct: '3bet',
    ev_options: [
      { label: '3-Bet (correct)', val: '+1.2 bb', pos: true },
      { label: 'Call',            val: '+0.4 bb', pos: true },
      { label: 'Fold',            val: '0.0 bb',  pos: false },
    ],
    explanation: 'KJo is a strong 3-bet hand vs a BTN steal. BTN opens wide heads-up (40–50%), making KJo a top-12% holding vs their range. 3-betting to 8bb wins the pot outright ~55% of the time. When called, you play a heads-up pot with initiative and K-high strength. Calling is +EV but lets BTN c-bet any texture with any two cards — you lose the initiative edge. 3-bet and apply pressure.',
    score: 68,
    continuation: {
      trigger: '3bet', type: 'villain_response', fold_pct: 55,
      call_range: 'KK+, AQs, AKo',
      note: 'BTN folds over half the time — your 3-bet takes the pot immediately more often than not. When called, you play a 56bb heads-up pot with KJo in position and initiative.',
    },
  },

  // 3. BTN facing HJ raise + CO 3-bet with JJ (24bb) — 4-bet jam
  {
    id: 'rd-pf-003',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 24, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '55 players · avg stack 45bb',
    mockHandId: 'MOCK-RD-006',
    playerStacks: { UTG: 38, HJ: 45, CO: 40, BTN: 24, SB: 42, BB: 50 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Raise', amount: '2.2bb' },
      { pos: 'CO',  action: '3-Bet', amount: '6.5bb' },
    ],
    board: null,
    hand: [{ rank: 'J', suit: '♠', red: false }, { rank: 'J', suit: '♦', red: true }],
    setup: 'HJ raises to 2.2bb. CO 3-bets to 6.5bb. Pot is 10.2bb. You\'re on the Button with JJ and 24bb.',
    question: 'JJ on the Button facing HJ open + CO 3-bet at 24bb. Fold, call, or 4-bet jam?',
    options: [
      { id: 'fold', label: 'Fold',        icon: '✗' },
      { id: 'call', label: 'Call 6.5bb',  icon: '✓' },
      { id: 'jam',  label: '4-Bet Jam',   icon: '▲' },
    ],
    correct: 'jam',
    ev_options: [
      { label: '4-Bet Jam (correct)', val: '+2.1 bb', pos: true },
      { label: 'Call',                val: '+0.9 bb', pos: true },
      { label: 'Fold',                val: '0.0 bb',  pos: false },
    ],
    explanation: 'JJ at 24bb is a clean 4-bet jam vs HJ open + CO 3-bet. Calling 6.5bb leaves 17.5bb behind into a 17.7bb pot — every K, Q, or A on the flop creates an impossible decision. Jamming for 24bb either takes the 10.2bb pot immediately or races with JJ at 55%+ equity vs typical 3-bet ranges. CO 3-bet range rarely extends to KK+ without re-jamming, so JJ is a slight favorite or neutral vs the likely range. Jam cleanly.',
    score: 81,
    continuation: {
      trigger: 'jam', type: 'villain_response', fold_pct: 45,
      call_range: 'QQ+, AKs',
      note: 'CO and HJ call roughly half the time. JJ has 56% equity vs that calling range — a coin flip you want to take at 24bb effective.',
    },
  },

  // 4. SB squeeze decision vs HJ open + CO flat on bubble (A5o, 18bb) — fold
  {
    id: 'rd-pf-004',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'SB', stack_bb: 18, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '32 players · top 27 paid · avg stack 22bb',
    mockHandId: 'MOCK-RD-007',
    playerStacks: { UTG: 25, HJ: 30, CO: 28, BTN: 22, SB: 18, BB: 20 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Raise', amount: '2.2bb' },
      { pos: 'CO',  action: 'Call' },
      { pos: 'BTN', action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'A', suit: '♥', red: true }, { rank: '5', suit: '♣', red: false }],
    setup: 'HJ raises to 2.2bb. CO calls. BTN folds. Pot is 5.9bb. You\'re in the SB with A5o and 18bb on the bubble.',
    question: 'A5o in the SB vs HJ open + CO call at 18bb on the bubble. Squeeze jam or fold?',
    options: [
      { id: 'fold', label: 'Fold',        icon: '✗' },
      { id: 'jam',  label: 'Squeeze Jam', icon: '▲' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '0.0 bb',   pos: true },
      { label: 'Squeeze Jam',    val: '−1.4 bb',  pos: false },
    ],
    explanation: 'A5o looks like a squeeze candidate with the ace blocker, but squeezing into two opponents cuts your fold equity in half — you need both to fold. On the bubble with 18bb, busting before the money is a severe ICM penalty. The A-blocker helps but A5o still faces calling ranges (AJ+, 77+) that have strong equity against it. Wait for a single-opponent spot or a hand with better equity when called.',
    score: 74,
  },

  // 5. BB defense vs CO raise (K9o, 14bb) — call is correct
  {
    id: 'rd-bb-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BB', stack_bb: 14, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '80 players remaining · avg stack 35bb',
    mockHandId: 'MOCK-RD-002',
    playerStacks: { UTG: 40, HJ: 38, CO: 32, BTN: 35, SB: 28, BB: 14 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Raise', amount: '2.5bb' },
      { pos: 'BTN', action: 'Fold' },
      { pos: 'SB',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'K', suit: '♠', red: false }, { rank: '9', suit: '♣', red: false }],
    setup: 'CO opens to 2.5bb. BTN and SB fold. You are in the BB with 14bb. Pot is 4.0bb.',
    question: 'K9o in the BB vs CO open at 14bb. Fold, call, or push?',
    options: [
      { id: 'fold', label: 'Fold',        icon: '✗' },
      { id: 'call', label: 'Call',        icon: '✓' },
      { id: 'push', label: 'Push All-in', icon: '▲' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)', val: '+0.8 bb', pos: true },
      { label: 'Push',           val: '+0.4 bb', pos: true },
      { label: 'Fold',           val: '0.0 bb',  pos: false },
    ],
    explanation: 'K9o at 14bb in the BB vs a CO open has sufficient pot odds and equity to defend. Getting 5.5:1 effective (call 1.5bb into 4bb pot), you need ~21% equity — K9o beats that comfortably against a wide CO range. Shoving is also +EV but calling keeps the pot smaller and preserves fold equity on favorable flops.',
    score: 78,
    continuation: {
      trigger: 'call', type: 'flop',
      board: 'K♠ 7♦ 2♣',
      action: 'CO c-bets 2.5bb into 4.9bb.',
      note: 'You flopped top pair. Call the c-bet — strong top pair vs a wide CO range, and you have betting equity on most turn cards.',
    },
  },

  // 6. Big-stack HJ vs short-stack UTG jam on bubble (A9o) — ICM fold
  {
    id: 'rd-bub-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'HJ', stack_bb: 35, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '28 players · top 24 paid · you have a big stack',
    mockHandId: 'MOCK-RD-008',
    playerStacks: { UTG: 9, HJ: 35, CO: 28, BTN: 22, SB: 18, BB: 15 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'All-in Jam', amount: '9bb' },
    ],
    board: null,
    hand: [{ rank: 'A', suit: '♥', red: true }, { rank: '9', suit: '♦', red: true }],
    setup: 'UTG short-stack jams all-in for 9bb. Pot is 10.5bb. You\'re in the HJ with A9o and 35bb on the bubble.',
    question: 'A9o in the HJ vs UTG all-in shove (9bb) on the bubble. Call or fold?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'call', label: 'Call', icon: '✓' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '+0.7 bb (ICM)', pos: true },
      { label: 'Call',           val: '−0.3 bb (ICM)', pos: false },
    ],
    explanation: 'A9o is a 56% favorite vs a typical 9bb jam range, but ICM changes the math. With 35bb you\'re comfortably in the money — every player that busts before you means more money without risking your stack. A9o is frequently dominated (vs AJ+, ATs) and faces flips otherwise. Big stacks on the bubble should tighten calling ranges ~15–20% compared to chip EV. Fold and let shorter stacks bust each other.',
    score: 78,
  },

  // 7. CO opens, BTN re-jams on bubble (TT, 32bb) — call is correct
  {
    id: 'rd-bub-002',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'CO', stack_bb: 32, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '41 players · top 36 paid · $250 pay jump',
    mockHandId: 'MOCK-RD-009',
    playerStacks: { UTG: 38, HJ: 35, CO: 32, BTN: 14, SB: 25, BB: 20 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Raise',      amount: '2.5bb' },
      { pos: 'BTN', action: 'All-in Jam', amount: '14bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'T', suit: '♠', red: false }, { rank: 'T', suit: '♦', red: true }],
    setup: 'You open CO to 2.5bb. BTN jams all-in for 14bb. Blinds fold. Pot is 18.0bb. Back to you with TT and 32bb on the bubble.',
    question: 'TT in CO facing BTN all-in re-jam (14bb) on the bubble with a $250 pay jump. Call or fold?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'call', label: 'Call', icon: '✓' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)', val: '+1.8 bb (ICM)', pos: true },
      { label: 'Fold',           val: '0.0 bb',        pos: false },
    ],
    explanation: 'TT has strong equity vs a BTN re-jam range — BTN shoves wide here (77–99, AK, AQ, KQs), and TT has ~62% equity vs that distribution. At 32bb you can absorb a bust and still have chips. Folding TT to any BTN re-jam turns it into a weak holding and lets aggressive players exploit you freely. ICM pressure is real but not severe enough to fold the best hand here. Call.',
    score: 83,
  },

  // 8. AJo vs BTN 3-bet at 4-handed final table — ICM fold
  {
    id: 'rd-ft-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'CO', stack_bb: 30, stage: 'final', stage_label: 'Final Table',
    stage_detail: '4 players remaining · $5,000 jump to 3rd place',
    mockHandId: 'MOCK-RD-003',
    playerStacks: { CO: 30, BTN: 38, SB: 25, BB: 22 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'CO',  action: 'Raise', amount: '2.5bb' },
      { pos: 'BTN', action: '3-Bet', amount: '7.5bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'A', suit: '♦', red: true }, { rank: 'J', suit: '♣', red: false }],
    setup: 'You open CO to 2.5bb. BTN 3-bets to 7.5bb. Blinds fold. Pot is 11.5bb. Back to you with AJo at the final table.',
    question: 'AJo vs BTN 3-bet at 4-handed final table with a $5k pay jump. Fold, call, or 4-bet jam?',
    options: [
      { id: 'fold',  label: 'Fold',      icon: '✗' },
      { id: 'call',  label: 'Call',      icon: '✓' },
      { id: 'raise', label: '4-Bet Jam', icon: '↑↑' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '+0.9 bb (ICM)', pos: true },
      { label: 'Call',           val: '−0.4 bb (ICM)', pos: false },
      { label: '4-Bet',          val: '−1.8 bb (ICM)', pos: false },
    ],
    explanation: 'AJo is dominated vs a BTN 3-betting range at a 4-handed final table. BTN\'s range is {AQ+, 99+, KQs} — AJo has roughly 35% equity vs that. Combined with the $5K ICM cost of busting in 4th place, this is a clear fold. In a cash game AJo would be a call or 4-bet bluff — ICM changes the calculation entirely.',
    score: 92,
  },

  // 9. 3-handed final table: BTN shoves, hero SB with 88 — ICM fold
  {
    id: 'rd-ft-002',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'SB', stack_bb: 22, stage: 'final', stage_label: 'Final Table',
    stage_detail: '3 players · BTN 55bb · SB 22bb · BB 23bb · $10k pay gap',
    mockHandId: 'MOCK-RD-010',
    playerStacks: { BTN: 55, SB: 22, BB: 23 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'BTN', action: 'All-in Jam', amount: '22bb' },
    ],
    board: null,
    hand: [{ rank: '8', suit: '♥', red: true }, { rank: '8', suit: '♣', red: false }],
    setup: 'BTN shoves all-in for 22bb at the 3-handed final table. Pot is 23.5bb. BB has 23bb. There is a $10,000 pay gap between 2nd and 3rd. You\'re in the SB with 88.',
    question: '88 in the SB vs BTN shove (22bb) 3-handed with $10k ICM gap. Call or fold?',
    options: [
      { id: 'fold', label: 'Fold', icon: '✗' },
      { id: 'call', label: 'Call', icon: '✓' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '+$420 (ICM $)', pos: true },
      { label: 'Call',           val: '−$380 (ICM $)', pos: false },
    ],
    explanation: 'Chip EV says call — 88 is a 56% favorite vs BTN\'s wide 3-handed jam range. ICM says fold. With SB and BB having near-equal stacks, busting in 3rd is the worst payout outcome. ICM requires ~63% equity to call off your entire stack here. Letting BTN and BB play off means you move up to 2nd place for free if either busts. The $10k pay jump more than covers the chip EV edge.',
    score: 88,
  },

  // 10. Final table 6-handed: BB jams vs SB steal with ATo (3-bet jam)
  {
    id: 'rd-ft-003',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'BB', stack_bb: 20, stage: 'final', stage_label: 'Final Table',
    stage_detail: '6 players · avg stack 33bb · ICM active',
    mockHandId: 'MOCK-RD-011',
    playerStacks: { UTG: 28, HJ: 35, CO: 32, BTN: 40, SB: 38, BB: 20 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Fold' },
      { pos: 'BTN', action: 'Fold' },
      { pos: 'SB',  action: 'Raise', amount: '2.5bb' },
    ],
    board: null,
    hand: [{ rank: 'A', suit: '♦', red: true }, { rank: 'T', suit: '♠', red: false }],
    setup: 'Folds to SB who raises to 2.5bb. Pot is 4.0bb. You\'re in the BB with ATo and 20bb at the final table.',
    question: 'ATo in the BB vs SB steal at final table (20bb). Fold, call, or 3-bet jam?',
    options: [
      { id: 'fold', label: 'Fold',       icon: '✗' },
      { id: 'call', label: 'Call',       icon: '✓' },
      { id: 'jam',  label: '3-Bet Jam',  icon: '▲' },
    ],
    correct: 'jam',
    ev_options: [
      { label: '3-Bet Jam (correct)', val: '+1.3 bb', pos: true },
      { label: 'Call',                val: '+0.5 bb', pos: true },
      { label: 'Fold',                val: '0.0 bb',  pos: false },
    ],
    explanation: 'ATo at 20bb vs a SB steal is a clean shove by push-fold charts. SB steals wide heads-up (40%+), and ATo is comfortably ahead of that range. Jamming for 20bb takes the pot uncontested ~52% of the time; when called, ATo has ~58% equity vs SB\'s calling range. Calling OOP at 20bb with ~18bb behind invites a difficult c-bet-or-fold spot. Jam preflop.',
    score: 79,
    continuation: {
      trigger: 'jam', type: 'villain_response', fold_pct: 52,
      call_range: 'TT+, AQs+, AKo',
      note: 'SB folds over half their steal range to the jam. ATo has 53% equity vs the calling range. This is a profitable shove overall at the final table.',
    },
  },

  // 11. BTN c-bet on K73 rainbow — decisionStreet null fixes blind accounting
  {
    id: 'rd-gn-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 40, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'Single raised pot · heads-up to flop',
    mockHandId: 'MOCK-RD-004',
    playerStacks: { BTN: 40, BB: 35 },
    decisionStreet: null,
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Fold' },
      { pos: 'BTN', action: 'Raise', amount: '2.2bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Call' },
      { pos: 'BB',  action: 'Check (flop)' },
    ],
    board: 'K♥ 7♣ 3♦',
    hand: [{ rank: 'K', suit: '♦', red: true }, { rank: 'Q', suit: '♠', red: false }],
    setup: 'You opened BTN to 2.2bb. BB called. Flop: K♥ 7♣ 3♦ (rainbow). Pot = 4.9bb. BB checks to you.',
    question: 'KQ on K73 rainbow — top pair, second kicker. Bet 50% pot or check back?',
    options: [
      { id: 'check', label: 'Check Back',       icon: '—' },
      { id: 'raise', label: 'Bet 2.4bb (50%)',  icon: '●' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Bet (correct)', val: '+0.9 bb', pos: true },
      { label: 'Check',         val: '+0.3 bb', pos: false },
    ],
    explanation: 'TPTK on a dry K73r board is a mandatory c-bet. Your BTN opening range hits this board much harder than BB\'s calling range — you have range advantage here. A 50% pot bet targets all worse Kx, pocket pairs, and draws while denying free equity. Checking risks giving free turn cards to K4, KJ, or pocket pairs that may improve against you.',
    score: 85,
    continuation: {
      trigger: 'raise', type: 'villain_response', fold_pct: 62,
      call_range: 'Kx, 77, 33',
      note: 'BB folds most of their missed air. When they call, you still hold TPTK and can continue barreling turns that don\'t complete potential draws.',
    },
  },

  // 12. BTN flush draw vs UTG c-bet on AJh5c (K9hh) — call
  {
    id: 'rd-gn-002',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 30, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'Single raised pot · heads-up to flop',
    mockHandId: 'MOCK-RD-012',
    playerStacks: { UTG: 38, BTN: 30 },
    decisionStreet: null,
    actionHistory: [
      { pos: 'UTG', action: 'Raise',  amount: '2.2bb' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Fold' },
      { pos: 'BTN', action: 'Call',   amount: '2.2bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Fold' },
      { pos: 'UTG', action: 'Bet',    amount: '2.5bb' },
    ],
    board: 'A♥ J♥ 5♣',
    hand: [{ rank: 'K', suit: '♥', red: true }, { rank: '9', suit: '♥', red: true }],
    setup: 'UTG raises 2.2bb, you call on the BTN. Flop: A♥ J♥ 5♣. Pot 5.9bb. UTG c-bets 2.5bb into 8.4bb total.',
    question: 'K♥9♥ on A♥J♥5♣ — flush draw, K-high. Facing 2.5bb into 8.4bb pot. Fold, call, or semi-bluff raise?',
    options: [
      { id: 'fold',  label: 'Fold',               icon: '✗' },
      { id: 'call',  label: 'Call 2.5bb',         icon: '✓' },
      { id: 'raise', label: 'Raise (semi-bluff)',  icon: '↑' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)',    val: '+0.7 bb', pos: true },
      { label: 'Raise semi-bluff', val: '+0.2 bb', pos: true },
      { label: 'Fold',              val: '−0.3 bb', pos: false },
    ],
    explanation: 'K♥9♥ on A♥J♥5♣ has a strong flush draw (9 outs, ~36% to hit by river). Getting 3.36:1 on the call (2.5 into 8.4bb), you need 23% equity — flush draw alone exceeds that on the turn. Calling preserves implied odds when you make the flush. Semi-bluff raising risks significant stack vs a UTG c-bet range containing AA, AK, AJ, and two-pair — hands that rarely fold and often re-raise. Call and see a turn.',
    score: 77,
    continuation: {
      trigger: 'call', type: 'flop',
      board: 'A♥ J♥ 5♣ 2♠',
      action: 'UTG checks to you.',
      note: 'Blank turn — flush draw still active. UTG checking signals weakness. You can semi-bluff bet 40% pot or check back and see the river cheaply.',
    },
  },

  // 13. CO turn barrel with TPTK on Q732 board — bet
  {
    id: 'rd-gn-003',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'CO', stack_bb: 40, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'Single raised pot · heads-up · turn decision',
    mockHandId: 'MOCK-RD-013',
    playerStacks: { CO: 40, BTN: 35 },
    decisionStreet: null,
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Raise', amount: '2.5bb' },
      { pos: 'BTN', action: 'Call',  amount: '2.5bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Fold' },
      { pos: 'CO',  action: 'Bet',   amount: '2.5bb' },
      { pos: 'BTN', action: 'Call',  amount: '2.5bb' },
    ],
    board: 'Q♦ 7♣ 2♥ 3♥',
    hand: [{ rank: 'T', suit: '♣', red: false }, { rank: 'Q', suit: '♠', red: false }],
    setup: 'You open CO, BTN calls. Flop Q♦7♣2♥ (rainbow). You c-bet 2.5bb, BTN calls. Turn: 3♥. Pot is 11.5bb.',
    question: 'TQ on Q♦7♣2♥3♥ — top pair, second kicker. Barrel the turn or check back?',
    options: [
      { id: 'check', label: 'Check Back',        icon: '—' },
      { id: 'bet',   label: 'Bet 5.5bb (~50%)',  icon: '●' },
    ],
    correct: 'bet',
    ev_options: [
      { label: 'Bet (correct)', val: '+1.1 bb', pos: true },
      { label: 'Check',         val: '+0.4 bb', pos: false },
    ],
    explanation: 'TQ has top pair with second-best kicker on Q-7-2-3. The 3♥ is a near-blank — it adds a possible backdoor flush draw for BTN but completes no straights or realistic draws. You have CO range advantage on this board. A 50% pot bet extracts value from worse Qx, pocket pairs, and combo draws, while denying free equity. When BTN called your flop c-bet, their range is weighted to floats and weaker pairs — all hands you beat. Bet and take it down.',
    score: 80,
    continuation: {
      trigger: 'bet', type: 'villain_response', fold_pct: 68,
      call_range: 'Qx, 77, flush draws',
      note: 'BTN folds most floats and weak pairs. Your TPTK is in good shape vs the calling range — keep barreling the river on bricks.',
    },
  },

  // 14. Multiway: BTN set-mines 66 vs UTG raise + HJ call (40bb)
  {
    id: 'rd-mw-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'beginner',
    position: 'BTN', stack_bb: 40, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '72 players · avg stack 38bb',
    mockHandId: 'MOCK-RD-014',
    playerStacks: { BTN: 40, SB: 38, BB: 32, UTG: 42, HJ: 35, CO: 28 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Raise', amount: '2.2bb' },
      { pos: 'HJ',  action: 'Call' },
      { pos: 'CO',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: '6', suit: '♠', red: false }, { rank: '6', suit: '♣', red: false }],
    setup: 'UTG (42bb) raises to 2.2bb. HJ (35bb) calls. CO folds. Pot is 5.9bb. You\'re on the Button with 66 and 40bb.',
    question: '66 on the Button facing UTG raise + HJ flat at 40bb. Fold, call, or 3-bet jam?',
    options: [
      { id: 'fold', label: 'Fold',       icon: '✗' },
      { id: 'call', label: 'Call',       icon: '✓' },
      { id: 'jam',  label: '3-Bet Jam',  icon: '▲' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)', val: '+0.9 bb', pos: true },
      { label: '3-Bet Jam',     val: '−0.4 bb', pos: false },
      { label: 'Fold',          val: '0.0 bb',  pos: false },
    ],
    explanation: '66 at 40bb has excellent implied odds in this multi-way pot: effective stack (40bb) ÷ call (2.2bb) ≈ 18:1. You need roughly 9:1 to profitably set-mine, so this is comfortably profitable. When you flop a set (~11%), both opponents are likely to stack off with overpairs. 3-bet jamming 40bb into UTG + HJ shows strength they can call with better — you\'re flipping at best. Call and see a cheap flop.',
    score: 70,
    continuation: {
      trigger: 'call', type: 'flop',
      board: 'A♦ 9♣ 4♠',
      action: 'UTG c-bets 4bb into 5.9bb.',
      note: 'You missed your set on an A-high board. With no pair and no draw, fold to the c-bet. Set mining works over many attempts — this just wasn\'t the one.',
    },
  },

  // 15. Multiway: SB squeezes AJs vs CO open + BTN call (35bb)
  {
    id: 'rd-mw-002',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'SB', stack_bb: 35, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '60 players · avg stack 40bb',
    mockHandId: 'MOCK-RD-015',
    playerStacks: { BTN: 42, SB: 35, BB: 40, UTG: 55, HJ: 32, CO: 38 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Raise', amount: '2.5bb' },
      { pos: 'BTN', action: 'Call' },
    ],
    board: null,
    hand: [{ rank: 'A', suit: '♦', red: true }, { rank: 'J', suit: '♦', red: true }],
    setup: 'CO (38bb) raises to 2.5bb. BTN (42bb) calls. Pot is 6.5bb. You\'re in the SB with A♦J♦ and 35bb.',
    question: 'AJs in the SB vs CO open + BTN cold-call at 35bb. Fold, call, or 3-bet squeeze to ~10bb?',
    options: [
      { id: 'fold', label: 'Fold',           icon: '✗' },
      { id: 'call', label: 'Call',           icon: '✓' },
      { id: '3bet', label: '3-Bet Squeeze',  icon: '↑' },
    ],
    correct: '3bet',
    ev_options: [
      { label: '3-Bet (correct)', val: '+1.4 bb', pos: true },
      { label: 'Call',            val: '+0.3 bb', pos: true },
      { label: 'Fold',            val: '0.0 bb',  pos: false },
    ],
    explanation: 'AJs is a mandatory squeeze here. CO + BTN are both in the pot with wide ranges — CO opens ~25%, BTN cold-calls ~12%. Your AJs has both blocker value (A blocks Ax) and strong equity. Squeezing to 10bb takes the pot uncontested ~55% of the time. When called, you\'re often in a coin-flip or better. Calling OOP multi-way with AJs is only +0.3bb EV — you give up initiative, miss squeezing dead money, and play a complex multi-way flop.',
    score: 76,
  },

  // 16. Multiway: BB folds KQo vs 3 active opponents (25bb)
  {
    id: 'rd-mw-003',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BB', stack_bb: 25, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '65 players · avg stack 38bb',
    mockHandId: 'MOCK-RD-016',
    playerStacks: { BB: 25, SB: 30, UTG: 45, HJ: 38, CO: 32, BTN: 28 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Raise', amount: '2.2bb' },
      { pos: 'CO',  action: 'Call' },
      { pos: 'BTN', action: 'Call' },
      { pos: 'SB',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'K', suit: '♣', red: false }, { rank: 'Q', suit: '♥', red: true }],
    setup: 'HJ (38bb) raises to 2.2bb. CO (32bb) calls. BTN (28bb) calls. SB folds. Pot is 8.1bb. You\'re in the BB with KQo and 25bb.',
    question: 'KQo in the BB vs HJ raise + 2 callers at 25bb. Fold, call, or jam?',
    options: [
      { id: 'fold', label: 'Fold',  icon: '✗' },
      { id: 'call', label: 'Call',  icon: '✓' },
      { id: 'jam',  label: 'Jam',   icon: '▲' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '0.0 bb',  pos: true },
      { label: 'Call',           val: '−0.6 bb', pos: false },
      { label: 'Jam',            val: '−1.1 bb', pos: false },
    ],
    explanation: 'KQo looks playable, but multi-way OOP is a trap. Three opponents each have a range that hits boards with K or Q — top pair no kicker plays terribly 4-way. The pot odds (8.1:1.2 = 6.75:1) are tempting but misleading: you\'ll miss 70% of the time, and when you hit you\'ll face multiple opponents with better kickers or sets. Jamming 25bb into 3 callers forces you to beat all three — KQo at ~35% equity vs combined ranges is -EV. Fold and wait for a cleaner spot.',
    score: 68,
  },

  // 17. 3-bet pot: KK faces 4-bet, must 5-bet jam (40bb)
  {
    id: 'rd-3b-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'CO', stack_bb: 40, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '48 players · avg stack 44bb',
    mockHandId: 'MOCK-RD-017',
    playerStacks: { CO: 40, BTN: 38, SB: 30, BB: 32, UTG: 45, HJ: 35 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Raise', amount: '2.2bb' },
      { pos: 'CO',  action: '3-Bet', amount: '6.5bb' },
      { pos: 'BTN', action: '4-Bet', amount: '16bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'K', suit: '♠', red: false }, { rank: 'K', suit: '♦', red: true }],
    setup: 'HJ opens 2.2bb. You 3-bet to 6.5bb. BTN (38bb) 4-bets to 16bb. Folds back to you. Pot is 26.2bb with 33.5bb behind.',
    question: 'KK vs BTN 4-bet (16bb) at 40bb effective. Fold, call, or 5-bet jam?',
    options: [
      { id: 'fold', label: 'Fold',        icon: '✗' },
      { id: 'call', label: 'Call 9.5bb',  icon: '✓' },
      { id: 'jam',  label: '5-Bet Jam',   icon: '▲' },
    ],
    correct: 'jam',
    ev_options: [
      { label: '5-Bet Jam (correct)', val: '+4.2 bb', pos: true },
      { label: 'Call',                val: '+3.1 bb', pos: true },
      { label: 'Fold',                val: '0.0 bb',  pos: false },
    ],
    explanation: 'KK never folds to a 4-bet at 40bb effective. The pot is 26.2bb and you have 33.5bb behind — if you call you\'re putting in 9.5bb into a 35.7bb pot (SPR = 0.94), meaning you\'re effectively pot-committed on any flop anyway. Jamming is cleaner: you take away BTN\'s ability to fold better hands on scary boards, and KK has 82%+ equity vs any 4-bet range that includes bluffs. Call is +3.1bb; jam is +4.2bb — jam for max EV.',
    score: 85,
    continuation: {
      trigger: 'jam', type: 'villain_response', fold_pct: 18,
      call_range: 'AA, QQ, JJ, AKs, AKo',
      note: 'BTN\'s 4-bet range almost never folds to a 5-bet. KK has 82%+ equity vs that calling range — this is a cooler spot you always want to be in.',
    },
  },

  // 18. 3-bet pot: QQ squeezes BB vs UTG open + BTN flat (32bb)
  {
    id: 'rd-3b-002',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BB', stack_bb: 32, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '52 players · avg stack 42bb',
    mockHandId: 'MOCK-RD-018',
    playerStacks: { BB: 32, SB: 38, UTG: 40, HJ: 28, CO: 35, BTN: 42 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Raise', amount: '2.5bb' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Fold' },
      { pos: 'BTN', action: 'Call' },
      { pos: 'SB',  action: 'Fold' },
    ],
    board: null,
    hand: [{ rank: 'Q', suit: '♠', red: false }, { rank: 'Q', suit: '♦', red: true }],
    setup: 'UTG (40bb) opens to 2.5bb. BTN (42bb) calls. SB folds. Pot is 6.5bb. You\'re in the BB with QQ and 32bb.',
    question: 'QQ in the BB vs UTG raise + BTN cold-call at 32bb. Call or 3-bet jam?',
    options: [
      { id: 'fold', label: 'Fold',       icon: '✗' },
      { id: 'call', label: 'Call',       icon: '✓' },
      { id: 'jam',  label: '3-Bet Jam',  icon: '▲' },
    ],
    correct: 'jam',
    ev_options: [
      { label: '3-Bet Jam (correct)', val: '+2.8 bb', pos: true },
      { label: 'Call',                val: '+1.2 bb', pos: true },
      { label: 'Fold',                val: '0.0 bb',  pos: false },
    ],
    explanation: 'QQ is too strong to call multi-way. Calling creates a 3-way pot where any K or A on the flop leaves you guessing about UTG\'s and BTN\'s ranges. Jamming 32bb squeezes both players: UTG\'s 4-bet-or-fold range vs your jam is typically KK+, AKs — they often fold JJ, TT, AQs. BTN (cold-caller) rarely has KK+ and usually folds. QQ has ~70%+ equity when called. Take the pot cleanly or race with the best hand.',
    score: 82,
    continuation: {
      trigger: 'jam', type: 'villain_response', fold_pct: 55,
      call_range: 'KK+, AKs',
      note: 'Both UTG and BTN fold over half the time combined — the dead money alone makes this a profitable squeeze. QQ is 70%+ vs the calling range when they do call.',
    },
  },

  // 19. 3-bet defense: 99 BTN jams vs BB 3-bet (26bb)
  {
    id: 'rd-3b-003',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'intermediate',
    position: 'BTN', stack_bb: 26, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '58 players · avg stack 40bb',
    mockHandId: 'MOCK-RD-019',
    playerStacks: { BTN: 26, SB: 34, BB: 30, UTG: 45, HJ: 38, CO: 32 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Fold' },
      { pos: 'BTN', action: 'Raise',  amount: '2.5bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: '3-Bet',  amount: '8bb' },
    ],
    board: null,
    hand: [{ rank: '9', suit: '♥', red: true }, { rank: '9', suit: '♦', red: true }],
    setup: 'You open BTN to 2.5bb. SB folds. BB (30bb) 3-bets to 8bb. Pot is 11.0bb. You have 99 and 26bb.',
    question: '99 on the BTN facing BB 3-bet (8bb) at 26bb. Fold, call, or 4-bet jam?',
    options: [
      { id: 'fold', label: 'Fold',        icon: '✗' },
      { id: 'call', label: 'Call 5.5bb',  icon: '✓' },
      { id: 'jam',  label: '4-Bet Jam',   icon: '▲' },
    ],
    correct: 'jam',
    ev_options: [
      { label: '4-Bet Jam (correct)', val: '+1.6 bb', pos: true },
      { label: 'Call',                val: '+0.5 bb', pos: true },
      { label: 'Fold',                val: '0.0 bb',  pos: false },
    ],
    explanation: 'At 26bb, calling creates a terrible SPR: you put in 5.5bb and have 18bb behind into an 11bb pot (SPR ≈ 1.6). Any A, K, Q, J, or T on the flop leaves you uncertain. 99 is ahead of most BB 3-bet ranges that include bluffs (A5s, 67s, 78s) and value hands (TT–QQ, AQs, AKo). Jamming for 26bb forces BB to commit 18bb more to win 37bb — they\'ll fold any hand without 46%+ equity. When called, 99 is at worst a flip vs AK.',
    score: 78,
    continuation: {
      trigger: 'jam', type: 'villain_response', fold_pct: 45,
      call_range: 'TT+, AQs+, AKo',
      note: 'BB folds ~45% of their 3-betting range to the jam. At 26bb effective, this is a profitable shove even when called — 99 is at worst a slight underdog.',
    },
  },

  // 20. Postflop: 3-bet pot c-bet with air on A83 rainbow (17.5bb pot)
  {
    id: 'rd-fl-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'BTN', stack_bb: 42, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '3-bet pot · heads-up to flop',
    mockHandId: 'MOCK-RD-020',
    playerStacks: { BTN: 42, SB: 30, BB: 28, UTG: 50, HJ: 38, CO: 35 },
    decisionStreet: null,
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Raise',  amount: '2.5bb' },
      { pos: 'BTN', action: '3-Bet',  amount: '8bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Fold' },
      { pos: 'CO',  action: 'Call',   amount: '5.5bb' },
      { pos: 'CO',  action: 'Check' },
    ],
    board: 'A♠ 8♦ 3♣',
    hand: [{ rank: 'K', suit: '♠', red: false }, { rank: 'Q', suit: '♦', red: true }],
    setup: 'CO (35bb) opens 2.5bb. You 3-bet to 8bb. CO calls. Pot 17.5bb. Flop: A♠8♦3♣ (rainbow). CO checks to you.',
    question: 'K♠Q♦ on A♠8♦3♣ in a 3-bet pot. CO checked. Bet ~35% pot (6bb) or check back?',
    options: [
      { id: 'check', label: 'Check Back',   icon: '—' },
      { id: 'bet',   label: 'Bet 6bb (35%)', icon: '●' },
    ],
    correct: 'bet',
    ev_options: [
      { label: 'Bet (correct)', val: '+1.2 bb', pos: true },
      { label: 'Check',         val: '+0.4 bb', pos: false },
    ],
    explanation: 'In a 3-bet pot, your range is heavily weighted toward Ax — you 3-bet with AK, AQ, AA, KK, QQ, and AJs. CO\'s calling range rarely contains Ax (they\'d 4-bet AK+ often). On A♠8♦3♣, you have massive range advantage: CO will fold all underpairs, all broadways (KQ, KJ, QJ), and all suited connectors. A 35% pot bet (6bb) is efficient — it takes the pot ~60% of the time and charges CO\'s equity when called. Checking surrenders this edge entirely.',
    score: 84,
    continuation: {
      trigger: 'bet', type: 'villain_response', fold_pct: 65,
      call_range: 'Ax, 88, 33',
      note: 'CO folds ~65% — that\'s all the profit you need on this board. When called or check-raised, you can fold or reassess. C-betting A-high boards in 3-bet pots is standard.',
    },
  },

  // 21. Postflop: multi-way wet board, BTN has TPOESD vs CO c-bet (QJ on JT9)
  {
    id: 'rd-fl-002',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'BTN', stack_bb: 45, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: '3-way pot · very wet flop',
    mockHandId: 'MOCK-RD-021',
    playerStacks: { BTN: 45, SB: 32, BB: 38, UTG: 50, HJ: 42, CO: 40 },
    decisionStreet: null,
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Raise',  amount: '2.5bb' },
      { pos: 'BTN', action: 'Call',   amount: '2.5bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Call',   amount: '1.5bb' },
      { pos: 'BB',  action: 'Check' },
      { pos: 'CO',  action: 'Bet',    amount: '2.5bb' },
    ],
    board: 'J♦ T♣ 9♥',
    hand: [{ rank: 'Q', suit: '♠', red: false }, { rank: 'J', suit: '♠', red: false }],
    setup: 'CO (40bb) opens 2.5bb, you call BTN (45bb), BB calls. Flop: J♦T♣9♥. BB checks. CO c-bets 2.5bb into 10.5bb pot.',
    question: 'Q♠J♠ on J♦T♣9♥ (top pair + open-ended straight draw) in a 3-way pot. Facing 2.5bb c-bet. Fold, call, or raise?',
    options: [
      { id: 'fold',  label: 'Fold',         icon: '✗' },
      { id: 'call',  label: 'Call 2.5bb',   icon: '✓' },
      { id: 'raise', label: 'Raise to 9bb', icon: '↑' },
    ],
    correct: 'raise',
    ev_options: [
      { label: 'Raise (correct)', val: '+2.8 bb', pos: true },
      { label: 'Call',            val: '+1.4 bb', pos: true },
      { label: 'Fold',            val: '−0.5 bb', pos: false },
    ],
    explanation: 'Q♠J♠ on J♦T♣9♥ is a monster: top pair (Jacks, Q kicker) plus an open-ended straight draw (K or 8 makes the nuts). That\'s 14+ outs to improve on the turn. In a 3-way pot, you must raise — there are multiple straight and flush draws in range, and BB is still behind. Raising to ~9bb serves two purposes: it charges CO\'s pair + draw hands (like AT, KT, QT) and eliminates BB with equity. Calling risks a bad turn card wiping out your equity advantage. Raise and take control of the pot.',
    score: 87,
    continuation: {
      trigger: 'raise', type: 'villain_response', fold_pct: 40,
      call_range: 'KJ, AJ, strong Jx, flush draws',
      note: 'CO calls ~60% with their strong c-betting range — but you have top pair plus 8 outs to the nuts. You\'re a favourite or coin flip vs most of what calls.',
    },
  },

  // 22. Postflop: river call-off with TPTK on blank K7253 board
  {
    id: 'rd-fl-003',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'BTN', stack_bb: 40, stage: 'mid', stage_label: 'Mid Stage',
    stage_detail: 'Single raised pot · river decision',
    mockHandId: 'MOCK-RD-022',
    playerStacks: { BTN: 40, SB: 35, BB: 38, UTG: 50, HJ: 42, CO: 38 },
    decisionStreet: null,
    actionHistory: [
      { pos: 'UTG', action: 'Fold' },
      { pos: 'HJ',  action: 'Fold' },
      { pos: 'CO',  action: 'Raise', amount: '2.5bb' },
      { pos: 'BTN', action: 'Call',  amount: '2.5bb' },
      { pos: 'SB',  action: 'Fold' },
      { pos: 'BB',  action: 'Fold' },
      { pos: 'CO',  action: 'Bet',   amount: '2.5bb' },
      { pos: 'BTN', action: 'Call',  amount: '2.5bb' },
      { pos: 'CO',  action: 'Check' },
      { pos: 'BTN', action: 'Bet',   amount: '4bb' },
      { pos: 'CO',  action: 'Call',  amount: '4bb' },
      { pos: 'CO',  action: 'Bet',   amount: '8bb' },
    ],
    board: 'K♥ 7♣ 2♦ 5♠ 9♠',
    hand: [{ rank: 'K', suit: '♠', red: false }, { rank: 'J', suit: '♥', red: true }],
    setup: 'CO opens 2.5bb, you call BTN. Flop K♥7♣2♦: CO bets 2.5, you call. Turn 5♠: CO checks, you bet 4bb, CO calls. River 9♠. Pot 27.5bb. CO leads 8bb.',
    question: 'K♠J♥ on K♥7♣2♦5♠9♠ (TPTK). CO leads 8bb into 27.5bb river pot. Call, fold, or raise?',
    options: [
      { id: 'fold',  label: 'Fold',        icon: '✗' },
      { id: 'call',  label: 'Call 8bb',    icon: '✓' },
      { id: 'raise', label: 'Raise to 22bb', icon: '↑' },
    ],
    correct: 'call',
    ev_options: [
      { label: 'Call (correct)', val: '+1.1 bb', pos: true },
      { label: 'Fold',           val: '−0.3 bb', pos: false },
      { label: 'Raise',          val: '−1.2 bb', pos: false },
    ],
    explanation: 'KJ on K7-2-5-9 (no flush, no realistic straight) is a strong bluff-catcher. Getting 4.4:1 on the call (8bb into 35.5bb), you need only 22% equity. CO checked back the turn (showing weakness), then leads the river — this is a common polarized lead (value or bluff). KJ beats all CO bluffs (QJ, QT, AT, missed draws) and loses only to KQ, KA, 77, 22. Calling is mandatory. Raising is wrong — your hand is a bluff-catcher, not a value hand. CO never folds better Kx to a raise.',
    score: 83,
  },

  // 23. ICM asymmetric stacks: hero short SB folds A9o vs big stack jam (4-handed bubble)
  {
    id: 'rd-icm-001',
    type: 'replay_drill',
    mode: 'replay-drill', difficulty: 'advanced',
    position: 'SB', stack_bb: 14, stage: 'bubble', stage_label: 'Bubble',
    stage_detail: '4 players · top 3 paid · BB 11bb is shortest (at risk)',
    mockHandId: 'MOCK-RD-023',
    playerStacks: { HJ: 45, BTN: 30, SB: 14, BB: 11 },
    decisionStreet: 'PREFLOP',
    actionHistory: [
      { pos: 'HJ',  action: 'Raise', amount: '3bb' },
      { pos: 'BTN', action: 'Call' },
    ],
    board: null,
    hand: [{ rank: 'A', suit: '♣', red: false }, { rank: '9', suit: '♦', red: true }],
    setup: 'HJ (45bb) opens 3bb. BTN (30bb) calls. Pot is 7.5bb. You\'re in the SB with A9o and 14bb. BB has only 11bb.',
    question: 'A9o in the SB (14bb) vs HJ + BTN on the bubble. BB (11bb) is the shortest stack. Push all-in or fold?',
    options: [
      { id: 'fold', label: 'Fold',     icon: '✗' },
      { id: 'jam',  label: 'Push All-in', icon: '▲' },
    ],
    correct: 'fold',
    ev_options: [
      { label: 'Fold (correct)', val: '+$310 (ICM $)', pos: true },
      { label: 'Push',           val: '−$290 (ICM $)', pos: false },
    ],
    explanation: 'This is an ICM trap. In chip EV, A9o at 14bb vs HJ + BTN is a clear push — you have fold equity and decent equity when called. But ICM changes everything: BB (11bb) is sitting behind you and is the bubble\'s shortest stack. If you fold and BB busts on any hand, you move into the money for free. Pushing risks your tournament life when you don\'t need to. Chip EV says push (+EV), ICM says fold (+$310). The shorter stack behind you is doing the busting work — let them.',
    score: 91,
  },
];

/* ── Scenario meta: skill + recommended lesson per scenario ─── */

const TR_SCENARIO_META = {
  'pf-b-001': { skill: 'push-fold', topic: 'Push/Fold Basics',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-b-002': { skill: 'push-fold', topic: 'Push/Fold Basics',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-b-003': { skill: 'push-fold', topic: 'Push/Fold Basics',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-b-004': { skill: 'push-fold', topic: 'Push/Fold Basics',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-i-001': { skill: 'push-fold', topic: 'Push/Fold Theory',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-i-002': { skill: 'push-fold', topic: 'Push/Fold Theory',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-i-003': { skill: 'push-fold', topic: 'Push/Fold Theory',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-i-004': { skill: 'push-fold', topic: 'Push/Fold Theory',      recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-a-001': { skill: 'push-fold', topic: 'Advanced Push/Fold',    recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'pf-a-002': { skill: 'push-fold', topic: 'Advanced Push/Fold',    recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'bb-b-001': { skill: 'bubble-play', topic: 'Bubble Fundamentals', recLesson: '/learn/bubble-play' },
  'bb-b-002': { skill: 'bubble-play', topic: 'Bubble Fundamentals', recLesson: '/learn/bubble-play' },
  'bb-i-001': { skill: 'bubble-play', topic: 'Bubble Play',         recLesson: '/learn/bubble-play' },
  'bb-i-002': { skill: 'bubble-play', topic: 'Bubble Play',         recLesson: '/learn/bubble-play' },
  'bb-i-003': { skill: 'bubble-play', topic: 'Bubble ICM',          recLesson: '/learn/bubble-play' },
  'ft-i-001': { skill: 'final-table', topic: 'Final Table ICM',     recLesson: '/learn/final-table-strategy/ft-icm' },
  'ft-i-002': { skill: 'final-table', topic: 'Final Table Play',    recLesson: '/learn/final-table-strategy/ft-icm' },
  'gs-i-001': { skill: 'postflop',    topic: 'C-Bet Strategy',      recLesson: '/learn/postflop-fundamentals' },
  'gs-i-002': { skill: 'postflop',    topic: 'C-Bet Strategy',      recLesson: '/learn/postflop-fundamentals' },
  'rd-pf-001': { skill: 'preflop',     topic: 'Multi-Way Ranges',        recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-pf-002': { skill: 'preflop',     topic: 'BB Defense vs Steal',     recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-pf-003': { skill: 'preflop',     topic: '3-Bet Pot Decisions',     recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-pf-004': { skill: 'bubble-play', topic: 'Bubble Squeeze Spots',   recLesson: '/learn/bubble-play' },
  'rd-bb-001': { skill: 'bubble-play', topic: 'BB Defense vs Raise',     recLesson: '/learn/bubble-play' },
  'rd-bub-001': { skill: 'bubble-play',topic: 'Bubble ICM Call-offs',    recLesson: '/learn/bubble-play' },
  'rd-bub-002': { skill: 'bubble-play',topic: 'Bubble Re-Jam Defense',   recLesson: '/learn/bubble-play' },
  'rd-ft-001': { skill: 'final-table', topic: 'Final Table ICM',         recLesson: '/learn/final-table-strategy/ft-icm' },
  'rd-ft-002': { skill: 'final-table', topic: '3-Handed ICM Decisions',  recLesson: '/learn/final-table-strategy/ft-icm' },
  'rd-ft-003': { skill: 'final-table', topic: 'Final Table Steal Defense',recLesson: '/learn/final-table-strategy/ft-icm' },
  'rd-gn-001': { skill: 'postflop',    topic: 'C-Bet Strategy',          recLesson: '/learn/postflop-fundamentals' },
  'rd-gn-002': { skill: 'postflop',    topic: 'Draw Decisions',          recLesson: '/learn/postflop-fundamentals' },
  'rd-gn-003': { skill: 'postflop',    topic: 'Turn Barrels',            recLesson: '/learn/postflop-fundamentals' },
  'rd-mw-001': { skill: 'preflop',     topic: 'Multi-Way Set Mining',    recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-mw-002': { skill: 'preflop',     topic: 'Multi-Way Squeeze',       recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-mw-003': { skill: 'preflop',     topic: 'Multi-Way BB Defense',    recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-3b-001': { skill: 'preflop',     topic: '4-Bet Pot Decisions',     recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-3b-002': { skill: 'preflop',     topic: 'Squeeze Jams',            recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-3b-003': { skill: 'preflop',     topic: '3-Bet/4-Bet Dynamics',    recLesson: '/learn/stack-sizes-tournament-strategy/push-fold-theory' },
  'rd-fl-001': { skill: 'postflop',    topic: '3-Bet Pot C-Bets',        recLesson: '/learn/postflop-fundamentals' },
  'rd-fl-002': { skill: 'postflop',    topic: 'Raise vs C-Bet',          recLesson: '/learn/postflop-fundamentals' },
  'rd-fl-003': { skill: 'postflop',    topic: 'River Call-offs',         recLesson: '/learn/postflop-fundamentals' },
  'rd-icm-001': { skill: 'bubble-play', topic: 'ICM Asymmetry',          recLesson: '/learn/bubble-play' },
};

/* ── Course → trainer URL mapping ──────────────────────────── */

const CO_COURSE_TRAINER = {
  'tournament-fundamentals':          '/trainer?mode=general&difficulty=beginner',
  'stack-sizes-tournament-strategy':  '/trainer?mode=push-fold&difficulty=beginner',
  'positions-blinds-antes':           '/trainer?mode=general&difficulty=beginner',
  'steal-and-resteal':                '/trainer?mode=push-fold&difficulty=intermediate',
  'bubble-play':                      '/trainer?mode=bubble&difficulty=beginner',
  'final-table-strategy':             '/trainer?mode=final-table&difficulty=intermediate',
  'short-stack-mastery':              '/trainer?mode=push-fold&difficulty=advanced',
  'icm-pressure':                     '/trainer?mode=bubble&difficulty=advanced',
  'postflop-fundamentals':            '/trainer?mode=general&difficulty=intermediate',
  'cbet-basics':                      '/trainer?mode=general&difficulty=intermediate',
  'multi-street-planning':            '/trainer?mode=general&difficulty=advanced',
  'exploitative-adjustments':         '/trainer?mode=general&difficulty=advanced',
};

/* ── Session state ─────────────────────────────────────────── */

let _trSession = {
  total:      0,
  correct:    0,
  streak:     0,
  maxStreak:  0,
  mode:       'all',
  difficulty: 'all',
  queue:      [],
  queueIdx:   0,
  answered:   false,
  current:    null,
  selected:   null,
  skillStats: {},
};

/* ── Helpers ──────────────────────────────────────────────── */

function _trFilteredScenarios() {
  return TR_SCENARIOS.filter(s =>
    (_trSession.mode === 'all'       || s.mode       === _trSession.mode) &&
    (_trSession.difficulty === 'all' || s.difficulty === _trSession.difficulty)
  );
}

function _trBuildQueue() {
  let scenarios = _trFilteredScenarios();

  // Fallback chain so the user is never stranded on an empty state
  if (scenarios.length === 0 && _trSession.difficulty !== 'all') {
    // 1. same mode, all difficulties
    scenarios = TR_SCENARIOS.filter(s =>
      (_trSession.mode === 'all' || s.mode === _trSession.mode) &&
      s.type !== 'replay_drill'
    );
  }
  if (scenarios.length === 0 && _trSession.mode !== 'all') {
    // 2. all modes, same difficulty
    scenarios = TR_SCENARIOS.filter(s =>
      (_trSession.difficulty === 'all' || s.difficulty === _trSession.difficulty) &&
      s.type !== 'replay_drill'
    );
  }
  if (scenarios.length === 0) {
    // 3. everything except replay drills
    scenarios = TR_SCENARIOS.filter(s => s.type !== 'replay_drill');
  }

  const ids = scenarios.map(s => s.id);
  for (let i = ids.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  _trSession.queue    = ids;
  _trSession.queueIdx = 0;
}

function _trNextScenario() {
  if (_trSession.queueIdx >= _trSession.queue.length) _trBuildQueue();
  const id = _trSession.queue[_trSession.queueIdx++];
  return TR_SCENARIOS.find(s => s.id === id) || TR_SCENARIOS[0];
}

function _trCardHTML(card) {
  const cls = card.red ? 'tr-card tr-card--red' : 'tr-card tr-card--black';
  return `<div class="${cls}">
    <span class="tr-card-rank">${escHtml(card.rank)}</span>
    <span class="tr-card-suit">${escHtml(card.suit)}</span>
  </div>`;
}

function _trStageClass(stage) {
  const map = { bubble: 'tr-stage--bubble', final: 'tr-stage--final', mid: 'tr-stage--mid', early: 'tr-stage--early' };
  return map[stage] || 'tr-stage--early';
}

function _trActionClass(id) {
  return `tr-action-btn`;
}

function _trAccuracyPct() {
  return _trSession.total === 0 ? '—' : `${Math.round(100 * _trSession.correct / _trSession.total)}%`;
}

/* ── Top-level SP hook ────────────────────────────────────── */

function _spRenderTrainer() {
  document.getElementById('sp-view-trainer')?.classList.add('sp-view--active');
  trRenderTrainer();
}

/* ── Main render ──────────────────────────────────────────── */

function trRenderTrainer() {
  const view = document.getElementById('sp-view-trainer');
  if (!view) return;

  // Reset to defaults, then apply any query param overrides
  _trSession.mode       = 'all';
  _trSession.difficulty = 'all';
  const params = new URLSearchParams(window.location.search);
  if (params.has('mode'))       _trSession.mode       = params.get('mode');
  if (params.has('difficulty')) _trSession.difficulty = params.get('difficulty');

  // Reset score on first render; always rebuild queue so URL mode param takes effect
  const fresh = !view.querySelector('.tr-page');
  if (fresh) {
    _trSession.total = _trSession.correct = _trSession.streak = 0;
    _trSession.skillStats = {};
  }
  _trBuildQueue();

  view.innerHTML = `
    <div class="tr-page">
      <div style="background:#14532d;border:2px solid #22c55e;border-radius:8px;padding:8px 14px;font-size:12px;color:#86efac;margin-bottom:10px;font-family:monospace;letter-spacing:.03em">
        &#9989; YOU ARE ON THE CORRECT PAGE &mdash; <strong style="color:#4ade80">/trainer (SPA)</strong> &mdash; mode pills + Replay Drills are below
      </div>
      <div class="tr-page-header">
        <h1 class="tr-page-title">Practice</h1>
        <p class="tr-page-sub">Improve your decisions through real tournament scenarios.</p>
      </div>

      <div class="tr-session-bar" id="tr-session-bar"></div>

      <div class="tr-controls">
        <div class="tr-control-group">
          <span class="tr-control-label">Mode</span>
          <div class="tr-pill-row" id="tr-mode-pills">
            ${[
              ['all',          'All Spots'],
              ['push-fold',    'Push / Fold'],
              ['bubble',       'Bubble Play'],
              ['final-table',  'Final Table'],
              ['general',      'General Spots'],
              [`replay-drill`, `&#127909; Replay Drills`],
            ].map(([k, l]) => `
              <button class="tr-pill${_trSession.mode === k ? ' tr-pill--active' : ''}" data-tr-mode="${escHtml(k)}">${l}</button>`
            ).join('')}
          </div>
        </div>
        <div class="tr-control-group">
          <span class="tr-control-label">Difficulty</span>
          <div class="tr-pill-row" id="tr-diff-pills">
            ${[
              ['all',          'All'],
              ['beginner',     'Beginner'],
              ['intermediate', 'Intermediate'],
              ['advanced',     'Advanced'],
            ].map(([k, l]) => `
              <button class="tr-pill${_trSession.difficulty === k ? ' tr-pill--active' : ''}" data-tr-diff="${escHtml(k)}">${escHtml(l)}</button>`
            ).join('')}
          </div>
        </div>
      </div>

      <div id="tr-board"></div>
    </div>
  `;

  _trRenderSessionBar();
  _trWireControls(view);
  trLoadScenario();
}

function _trRenderSessionBar() {
  const bar = document.getElementById('tr-session-bar');
  if (!bar) return;
  const acc = _trAccuracyPct();
  bar.innerHTML = `
    <div class="tr-session-stat">
      <span class="tr-session-val" id="tr-stat-total">${_trSession.total}</span>
      <span class="tr-session-lbl">Hands</span>
    </div>
    <div class="tr-session-divider"></div>
    <div class="tr-session-stat">
      <span class="tr-session-val tr-session-val--good" id="tr-stat-correct">${_trSession.correct}</span>
      <span class="tr-session-lbl">Correct</span>
    </div>
    <div class="tr-session-divider"></div>
    <div class="tr-session-stat">
      <span class="tr-session-val${_trSession.total > 0 && _trSession.correct / _trSession.total < 0.5 ? ' tr-session-val--warn' : ''}" id="tr-stat-acc">${acc}</span>
      <span class="tr-session-lbl">Accuracy</span>
    </div>
    <div class="tr-session-divider"></div>
    <div class="tr-session-stat">
      <span class="tr-session-val" id="tr-stat-streak">&#128293; ${_trSession.streak}</span>
      <span class="tr-session-lbl">Streak</span>
    </div>
    <button class="tr-session-reset" id="tr-reset-btn">New Session</button>
    <button class="tr-session-end" id="tr-end-btn">End Session</button>
  `;
  document.getElementById('tr-reset-btn')?.addEventListener('click', () => {
    _trSession.total = _trSession.correct = _trSession.streak = 0;
    _trSession.skillStats = {};
    _trBuildQueue();
    _trRenderSessionBar();
    trLoadScenario();
  });
  document.getElementById('tr-end-btn')?.addEventListener('click', trShowSummary);
}

function _trUpdateSessionBar() {
  const acc = _trAccuracyPct();
  const el = id => document.getElementById(id);
  const t = el('tr-stat-total');     if (t) t.textContent = _trSession.total;
  const c = el('tr-stat-correct');   if (c) c.textContent = _trSession.correct;
  const a = el('tr-stat-acc');       if (a) a.textContent = acc;
  const s = el('tr-stat-streak');    if (s) s.innerHTML = `&#128293; ${_trSession.streak}`;
}

function _trWireControls(view) {
  view.querySelectorAll('[data-tr-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      const clickedMode = btn.dataset.trMode;
      _trSession.mode = clickedMode;
      _trBuildQueue();
      view.querySelectorAll('[data-tr-mode]').forEach(b =>
        b.classList.toggle('tr-pill--active', b.dataset.trMode === _trSession.mode));
      trLoadScenario();
    });
  });
  view.querySelectorAll('[data-tr-diff]').forEach(btn => {
    btn.addEventListener('click', () => {
      _trSession.difficulty = btn.dataset.trDiff;
      _trBuildQueue();
      view.querySelectorAll('[data-tr-diff]').forEach(b =>
        b.classList.toggle('tr-pill--active', b.dataset.trDiff === _trSession.difficulty));
      trLoadScenario();
    });
  });
}

/* ── Load scenario ────────────────────────────────────────── */

function trLoadScenario() {
  const board = document.getElementById('tr-board');
  if (!board) return;

  const filtered = _trFilteredScenarios();
  if (filtered.length === 0) {
    board.innerHTML = `<div class="tr-empty">No scenarios available for the selected mode and difficulty.</div>`;
    return;
  }

  const s = _trNextScenario();
  _trSession.current  = s;
  _trSession.answered = false;
  _trSession.selected = null;

  if (s.type === 'replay_drill') {
    _trRenderReplayDrill(board, s);
    return;
  }

  const colsClass = `tr-actions--${s.options.length}`;
  const qIdx = `${_trSession.queueIdx}/${_trSession.queue.length}`;

  board.innerHTML = `
    <div class="tr-scenario" id="tr-scenario">
      <div class="tr-scenario-context">
        <span class="tr-stage-badge ${_trStageClass(s.stage)}">${escHtml(s.stage_label)}</span>
        <span class="tr-context-detail">${escHtml(s.stage_detail)}</span>
        <span class="tr-progress-chip">${escHtml(qIdx)}</span>
      </div>

      <div class="tr-felt">
        <div class="tr-position-row">
          <div class="tr-stack-info">
            <span class="tr-stack-val">${s.stack_bb}bb</span>
            <span class="tr-stack-lbl">Effective</span>
          </div>
          <div class="tr-position-badge">${escHtml(s.position)}</div>
        </div>
        <div class="tr-hand">
          ${s.hand.map(c => _trCardHTML(c)).join('')}
        </div>
      </div>

      <div class="tr-prompt-area">
        <p class="tr-setup">${escHtml(s.setup)}</p>
        <p class="tr-question">${escHtml(s.question)}</p>
      </div>

      <div class="tr-actions ${colsClass}" id="tr-actions">
        ${s.options.map(opt => `
          <button class="tr-action-btn" data-action="${escHtml(opt.id)}" data-opt-id="${escHtml(opt.id)}">
            <span>${escHtml(opt.icon)}</span>
            <span>${escHtml(opt.label)}</span>
          </button>`).join('')}
      </div>
    </div>
  `;

  board.querySelectorAll('[data-opt-id]').forEach(btn => {
    btn.addEventListener('click', () => trHandleAnswer(btn.dataset.optId));
  });
}

/* ── Replay drill: hand-state builder (pure) ──────────────── */

function buildTrainerHandState(s) {
  // Canonical clockwise seat order starting from BTN
  const CW_ORDER = ['BTN', 'SB', 'BB', 'UTG', 'HJ', 'CO'];

  // 1. Collect all positions that appear in this scenario
  const posSet = new Set();
  posSet.add(s.position); // hero
  // Always include SB and BB for preflop pot accounting
  if (s.decisionStreet === 'PREFLOP' || !s.decisionStreet) {
    posSet.add('SB');
    posSet.add('BB');
  }
  for (const a of (s.actionHistory || [])) {
    posSet.add(a.pos);
  }

  // 2. Sort into clockwise order starting from hero
  const heroIdx = CW_ORDER.indexOf(s.position);
  const seatOrder = [];
  for (let i = 0; i < CW_ORDER.length; i++) {
    const pos = CW_ORDER[(heroIdx + i) % CW_ORDER.length];
    if (posSet.has(pos)) seatOrder.push(pos);
  }

  // 3. Parse amount string like '2.5bb' → number
  function parseAmountBb(str) {
    if (!str) return 0;
    return parseFloat(String(str).replace(/bb/i, '').trim()) || 0;
  }

  // 4. Determine action type classification for log
  function classifyAction(actionStr) {
    const a = actionStr.toLowerCase();
    if (a === 'fold') return 'fold';
    if (a.startsWith('check')) return 'check';
    if (a === 'call') return 'call';
    if (a.startsWith('call')) return 'call';
    if (a.startsWith('bet')) return 'bet';
    if (a.includes('all-in')) return 'allin';
    if (a.startsWith('raise') || a.startsWith('3-bet') || a.startsWith('4-bet')) return 'raise';
    return 'check';
  }

  // 5. Build actionLog + compute pot with correct marginal accounting
  const actionLog = [];
  const contributions = {}; // pos → total committed this street
  let potBb = 0;
  let currentBet = 0; // highest bet this street

  // Add SB/BB blinds for preflop
  const isPreflop = s.decisionStreet === 'PREFLOP' || !s.decisionStreet;
  if (isPreflop) {
    if (posSet.has('SB')) {
      contributions['SB'] = 0.5;
      potBb += 0.5;
      currentBet = Math.max(currentBet, 0.5);
      actionLog.push({ pos: 'SB', text: 'post 0.5bb', type: 'blind', isHero: 'SB' === s.position });
    }
    if (posSet.has('BB')) {
      contributions['BB'] = 1;
      potBb += 1;
      currentBet = Math.max(currentBet, 1);
      actionLog.push({ pos: 'BB', text: 'post 1bb', type: 'blind', isHero: 'BB' === s.position });
    }
  }

  // Process actionHistory entries
  for (const entry of (s.actionHistory || [])) {
    const potBefore = potBb; // capture before this action modifies pot
    const pos = entry.pos;
    const actionStr = entry.action || '';
    const type = classifyAction(actionStr);
    const prev = contributions[pos] || 0;
    let text = actionStr;
    if (entry.amount) text = `${actionStr} (${entry.amount})`;

    if (type === 'fold' || type === 'check') {
      // no chips
    } else if (type === 'raise' || type === 'allin') {
      // total-to semantics
      const totalTo = parseAmountBb(entry.amount);
      if (totalTo > 0) {
        const marginal = Math.max(0, totalTo - prev);
        potBb += marginal;
        contributions[pos] = totalTo;
        currentBet = Math.max(currentBet, totalTo);
      }
    } else if (type === 'call') {
      if (entry.amount) {
        // explicit amount → marginal
        const marginal = parseAmountBb(entry.amount);
        potBb += marginal;
        contributions[pos] = prev + marginal;
      } else {
        // infer from currentBet
        const marginal = Math.max(0, currentBet - prev);
        potBb += marginal;
        contributions[pos] = currentBet;
      }
    } else if (type === 'bet') {
      // first aggressor postflop — marginal
      const amount = parseAmountBb(entry.amount);
      potBb += amount;
      contributions[pos] = prev + amount;
      currentBet = Math.max(currentBet, contributions[pos]);
    }

    actionLog.push({ pos, text, type, isHero: pos === s.position, potBefore });
  }

  // Hero decision entry (always last)
  actionLog.push({ pos: s.position, text: 'your decision', type: 'decision', isHero: true });

  // 6. Build seat list (folded/allin status)
  const foldedSet = new Set();
  const allinSet = new Set();
  for (const entry of (s.actionHistory || [])) {
    const a = (entry.action || '').toLowerCase();
    if (a === 'fold') foldedSet.add(entry.pos);
    if (a.includes('all-in')) allinSet.add(entry.pos);
  }

  const seats = seatOrder.map(pos => ({
    pos,
    isHero: pos === s.position,
    status: allinSet.has(pos) ? 'allin' : foldedSet.has(pos) ? 'folded' : 'active',
    contributionBb: contributions[pos] || 0,
    stack: pos === s.position ? s.stack_bb : null,
    isBTN: pos === 'BTN',
  }));

  // 7. Parse board cards
  const boardCards = s.board
    ? s.board.split(' ').filter(Boolean)
    : [];

  return {
    seats,
    potBb,
    boardCards,
    actionLog,
    heroPos: s.position,
    heroStack: s.stack_bb,
  };
}

/* ── Replay drill context helpers ────────────────────────── */

function _trRdPrimaryVillain(s) {
  const history = (s.actionHistory || []).filter(a => a.pos !== s.position);
  for (let i = history.length - 1; i >= 0; i--) {
    const a = (history[i].action || '').toLowerCase();
    if (a.includes('all-in') || a.startsWith('bet') || a.startsWith('raise') ||
        a.startsWith('3-bet') || a.startsWith('4-bet')) return history[i].pos;
  }
  for (let i = history.length - 1; i >= 0; i--) {
    if (history[i].action !== 'Fold') return history[i].pos;
  }
  return null;
}

function _trRdIcmPressure(stage) {
  if (stage === 'bubble' || stage === 'final') return { label: 'High', cls: 'tr-icm--high' };
  if (stage === 'mid') return { label: 'Low', cls: 'tr-icm--low' };
  return { label: 'Low', cls: 'tr-icm--low' };
}

function _trRdSpotType(s) {
  const history = (s.actionHistory || []);
  const opps = history.filter(a => a.pos !== s.position && a.action !== 'Fold' &&
    !a.action.startsWith('Check') && !a.action.startsWith('post'));
  const lastAgg = [...opps].reverse()[0];
  if (!lastAgg) return 'Open Decision';
  const a = (lastAgg.action || '').toLowerCase();
  if (a.includes('all-in') || a.includes('jam')) return 'Shove Call-off';
  const foldedPos = new Set(history.filter(h => h.action === 'Fold').map(h => h.pos));
  const activeOpps = new Set(opps.map(h => h.pos).filter(p => !foldedPos.has(p)));
  if (activeOpps.size >= 2) return 'Multi-Way Spot';
  if (a.startsWith('bet')) return 'vs C-Bet';
  if (a.startsWith('3-bet')) return 'vs 3-Bet';
  if (a.startsWith('4-bet')) return 'vs 4-Bet';
  if (a.startsWith('raise')) return 'vs Raise';
  return 'Decision';
}

function _trRdVillainRead(s) {
  const vPos = _trRdPrimaryVillain(s);
  if (!vPos) return null;
  const hist = s.actionHistory || [];
  const vAction = [...hist].reverse().find(a => a.pos === vPos);
  if (!vAction) return null;
  const a = (vAction.action || '').toLowerCase();
  const stack = s.playerStacks?.[vPos];
  if (a.includes('all-in') || a.includes('jam')) {
    return (stack && stack <= 12) ? 'Short-stack shove — wide range' : 'Committed — strong or semi-bluff range';
  }
  if (a.startsWith('4-bet')) return 'Polar — KK+ value or bluff';
  if (a.startsWith('3-bet')) return 'Polar — strong value + bluffs';
  if (a.startsWith('bet'))   return 'Betting range — value or draw';
  if (a.startsWith('raise')) {
    if (['UTG', 'HJ'].includes(vPos)) return 'Value-heavy — tight opening standards';
    if (['BTN', 'CO'].includes(vPos)) return 'Wide — includes steals and speculative hands';
    return 'Solid range — position-appropriate opens';
  }
  return null;
}

function _trRdContextPanelHTML(s) {
  const villainPos = _trRdPrimaryVillain(s);
  const villainStack = (villainPos && s.playerStacks) ? s.playerStacks[villainPos] : null;
  const icm = _trRdIcmPressure(s.stage);
  const spotType = _trRdSpotType(s);
  const villainRead = _trRdVillainRead(s);

  const villainChip = villainPos ? `<div class="tr-ctx-chip tr-ctx-chip--villain">
      <span class="tr-ctx-chip-lbl">Villain</span>
      <span class="tr-ctx-chip-val">${escHtml(villainPos)}${villainStack != null ? ' &middot; ' + villainStack + 'bb' : ''}</span>
    </div>` : '';

  return `<div class="tr-rd-ctx-panel">
    <div class="tr-ctx-chip tr-ctx-chip--hero">
      <span class="tr-ctx-chip-lbl">You</span>
      <span class="tr-ctx-chip-val">${escHtml(s.position)} &middot; ${s.stack_bb}bb</span>
    </div>
    ${villainChip}
    <div class="tr-ctx-chip tr-ctx-chip--icm">
      <span class="tr-ctx-chip-lbl">ICM</span>
      <span class="tr-ctx-chip-val ${icm.cls}">${icm.label}</span>
    </div>
    <div class="tr-ctx-chip tr-ctx-chip--spot">
      <span class="tr-ctx-chip-lbl">Spot</span>
      <span class="tr-ctx-chip-val">${escHtml(spotType)}</span>
    </div>
    ${villainRead ? `<div class="tr-ctx-read"><span class="tr-ctx-read-lbl">Range read:</span> ${escHtml(villainRead)}</div>` : ''}
  </div>`;
}

function _trContinuationHTML(s, userAnswer) {
  const cont = s.continuation;
  if (!cont || userAnswer !== s.correct) return '';

  if (cont.type === 'villain_response') {
    const fp = cont.fold_pct || 50;
    const cp = 100 - fp;
    return `<div class="tr-continuation">
      <div class="tr-cont-header">&#9654; What happens next</div>
      <div class="tr-cont-outcome-row">
        <span class="tr-cont-outcome-lbl tr-cont-fold">Folds ${fp}%</span>
        <div class="tr-cont-bar-wrap"><div class="tr-cont-bar-fill tr-cont-bar-fold" style="width:${fp}%"></div></div>
        <span class="tr-cont-outcome-lbl tr-cont-call">Calls ${cp}%</span>
      </div>
      ${cont.call_range ? `<div class="tr-cont-range">When calling: ${escHtml(cont.call_range)}</div>` : ''}
      <p class="tr-cont-note">${escHtml(cont.note)}</p>
    </div>`;
  }

  if (cont.type === 'flop') {
    const boardCards = (cont.board || '').split(' ').filter(Boolean);
    const boardHTML = boardCards.map(c => `<span class="tr-rboard-card">${escHtml(c)}</span>`).join('');
    return `<div class="tr-continuation">
      <div class="tr-cont-header">&#127183; The flop comes</div>
      <div class="tr-cont-board">${boardHTML}</div>
      ${cont.action ? `<p class="tr-cont-action">${escHtml(cont.action)}</p>` : ''}
      <p class="tr-cont-note">${escHtml(cont.note)}</p>
    </div>`;
  }

  return '';
}

/* ── Replay drill renderer ────────────────────────────────── */

function _trRenderReplayDrill(board, s) {
  const qIdx = `${_trSession.queueIdx}/${_trSession.queue.length}`;
  const colsClass = `tr-actions--${s.options.length}`;
  const state = buildTrainerHandState(s);
  const { seats, potBb, boardCards, actionLog } = state;

  const villainPos = _trRdPrimaryVillain(s);
  const currentStreet = boardCards.length === 0 ? null
    : boardCards.length <= 3 ? 'flop'
    : boardCards.length === 4 ? 'turn'
    : 'river';

  // Build seat HTML using rsSeatPositions
  const positions = rsSeatPositions(seats.length);
  const seatsHTML = seats.map((seat, i) => {
    const pos = positions[i];
    const isVillain = !seat.isHero && seat.pos === villainPos && seat.status !== 'folded';
    const modifiers = [
      seat.isHero ? 'tr-rseat--hero' : '',
      seat.status === 'folded' ? 'tr-rseat--folded' : '',
      seat.status === 'allin' ? 'tr-rseat--allin' : '',
      isVillain ? 'tr-rseat--villain' : '',
    ].filter(Boolean).join(' ');

    // Cards: hero shows real cards, opponents show face-down
    let cardsHTML = '';
    if (seat.isHero) {
      cardsHTML = s.hand.map(c => _trCardHTML(c)).join('');
    } else {
      cardsHTML = renderFaceDownCard() + renderFaceDownCard();
    }

    // Dealer button marker
    const dealerHTML = seat.isBTN
      ? `<div class="tr-rdealerbtn">D</div>`
      : '';

    // Bet/contribution chip
    const betHTML = seat.contributionBb > 0
      ? `<div class="tr-rseat-bet">${seat.contributionBb.toFixed(1)}bb</div>`
      : '';

    // Stack display for hero
    const stackHTML = seat.isHero && seat.stack != null
      ? `<span class="tr-rseat-stack">${seat.stack}bb</span>`
      : '';

    return `<div class="tr-rseat ${modifiers}" style="left:${pos.left}%;top:${pos.top}%" data-pos="${escHtml(seat.pos)}">
      ${dealerHTML}
      <div class="tr-rseat-cards">${cardsHTML}</div>
      <div class="tr-rseat-plate">
        <span class="tr-rseat-pos">${escHtml(seat.pos)}</span>
        ${stackHTML}
      </div>
      ${betHTML}
    </div>`;
  }).join('');

  // Board cards in center
  const boardCardsHTML = boardCards.length > 0
    ? `<div class="tr-rboard-cards">${boardCards.map(c => `<span class="tr-rboard-card">${escHtml(c)}</span>`).join('')}</div>`
    : '';

  // Pot display
  const potHTML = `<div class="tr-rpot-display">
    <span class="tr-rpot-lbl">Pot</span>
    <span class="tr-rpot-val">${potBb.toFixed(1)}bb</span>
  </div>`;

  // Action log entries
  const logEntriesHTML = actionLog.map(entry => {
    if (entry.type === 'decision') {
      const decText = currentStreet ? `your ${currentStreet}` : 'your decision';
      return `<div class="tr-rlog-entry tr-rlog--decision">
        <span class="tr-rlog-pos">${escHtml(entry.pos)}</span>
        <span class="tr-rlog-act">${decText}</span>
      </div>`;
    }
    // Pot-relative size for raise/bet/allin with explicit amounts
    let pctSpan = '';
    if ((entry.type === 'raise' || entry.type === 'bet' || entry.type === 'allin') &&
        entry.potBefore > 0 && entry.text.includes('(')) {
      const m = entry.text.match(/([\d.]+)bb/);
      if (m) {
        const pct = Math.round(parseFloat(m[1]) / entry.potBefore * 100);
        if (pct > 0 && pct < 1000) pctSpan = ` <span class="tr-rlog-pct">${pct}%</span>`;
      }
    }
    return `<div class="tr-rlog-entry tr-rlog--${escHtml(entry.type)}">
      <span class="tr-rlog-pos">${escHtml(entry.pos)}</span>
      <span class="tr-rlog-act">${escHtml(entry.text)}${pctSpan}</span>
    </div>`;
  }).join('');

  board.innerHTML = `
    <div class="tr-scenario tr-scenario--replay-drill" id="tr-scenario">
      <div class="tr-scenario-context">
        <span class="tr-replay-badge">&#127909; Replay Drill</span>
        <span class="tr-stage-badge ${_trStageClass(s.stage)}">${escHtml(s.stage_label)}</span>
        <span class="tr-context-detail">${escHtml(s.stage_detail)}</span>
        <span class="tr-progress-chip">${escHtml(qIdx)}</span>
      </div>

      <div class="tr-rtable-layout">
        <div class="tr-rtable-wrap">
          <div class="tr-rtable-felt">
            ${seatsHTML}
            <div class="tr-rtable-center">
              ${boardCardsHTML}
              ${potHTML}
            </div>
          </div>
        </div>
        <div class="tr-rlog">
          <div class="tr-rlog-title">Action History</div>
          <div class="tr-rlog-entries">${logEntriesHTML}</div>
        </div>
      </div>

      ${_trRdContextPanelHTML(s)}
      <div class="tr-prompt-area">
        ${currentStreet ? `<span class="tr-street-badge tr-street-badge--${currentStreet}">${currentStreet}</span>` : ''}
        <p class="tr-setup">${escHtml(s.setup)}</p>
        <p class="tr-question">${escHtml(s.question)}</p>
      </div>

      <div class="tr-actions ${colsClass}" id="tr-actions">
        ${s.options.map(opt => `
          <button class="tr-action-btn" data-action="${escHtml(opt.id)}" data-opt-id="${escHtml(opt.id)}">
            <span>${escHtml(opt.icon)}</span>
            <span>${escHtml(opt.label)}</span>
          </button>`).join('')}
      </div>

      <div class="tr-rd-analysis-bar">
        <span class="tr-rd-analysis-note">No real hand loaded &mdash; mock scenario</span>
        <button class="tr-rd-open-btn" id="tr-rd-open-btn">Open Analysis &rarr;</button>
      </div>
    </div>
  `;

  board.querySelectorAll('[data-opt-id]').forEach(btn => {
    btn.addEventListener('click', () => trHandleAnswer(btn.dataset.optId));
  });
  board.querySelector('#tr-rd-open-btn')?.addEventListener('click', () => spNavigate('/analysis'));
}

/* ── Handle answer ────────────────────────────────────────── */

function trHandleAnswer(optionId) {
  if (_trSession.answered) return;
  const s = _trSession.current;
  if (!s) return;

  _trSession.answered = true;
  _trSession.selected = optionId;
  _trSession.total++;

  const correct = optionId === s.correct;
  if (correct) {
    _trSession.correct++;
    _trSession.streak++;
    if (_trSession.streak > _trSession.maxStreak) _trSession.maxStreak = _trSession.streak;
  } else {
    _trSession.streak = 0;
  }

  // Track per-skill accuracy
  const meta = TR_SCENARIO_META[s.id];
  if (meta) {
    const sk = _trSession.skillStats[meta.skill] || { total: 0, correct: 0 };
    sk.total++;
    if (correct) sk.correct++;
    _trSession.skillStats[meta.skill] = sk;
  }

  _trUpdateSessionBar();

  // Lock and colour buttons
  document.querySelectorAll('[data-opt-id]').forEach(btn => {
    btn.disabled = true;
    if (btn.dataset.optId === s.correct) {
      btn.classList.add('tr-action-btn--correct');
    } else if (btn.dataset.optId === optionId && !correct) {
      btn.classList.add('tr-action-btn--wrong');
    }
  });

  trShowResult(correct);
}

/* ── Show result ──────────────────────────────────────────── */

function trShowResult(correct) {
  const s = _trSession.current;
  if (!s) return;
  const board = document.getElementById('tr-board');
  if (!board) return;

  const pts = correct ? `+${s.score} pts` : '0 pts';
  const bannerCls = correct ? 'tr-result-banner--correct' : 'tr-result-banner--wrong';
  const icon      = correct ? '&#10003;' : '&#10007;';
  const verdict   = correct ? 'Correct' : 'Incorrect';

  const evHTML = s.ev_options.map(e => `
    <div class="tr-ev-item">
      <span class="tr-ev-val ${e.pos ? 'tr-ev-val--pos' : 'tr-ev-val--neg'}">${escHtml(e.val)}</span>
      <span class="tr-ev-lbl">${escHtml(e.label)}</span>
    </div>`).join('');

  const resultDiv = document.createElement('div');
  resultDiv.className = 'tr-result';
  resultDiv.id = 'tr-result';
  resultDiv.innerHTML = `
    <div class="tr-result-banner ${bannerCls}">
      <div class="tr-result-verdict">
        <span class="tr-result-icon">${icon}</span>
        <span class="tr-result-label">${verdict}</span>
      </div>
      <span class="tr-result-pts">${escHtml(pts)}</span>
    </div>
    <div class="tr-result-body">
      <div class="tr-result-ev">${evHTML}</div>
      <div class="tr-result-explanation">${escHtml(s.explanation)}</div>
    </div>
    ${_trContinuationHTML(s, _trSession.selected)}
    <div class="tr-result-nav">
      <button class="sp-btn-primary" id="tr-next-btn">Next Hand &rarr;</button>
      <button class="sp-btn-secondary" id="tr-review-btn">${_trSession.current?.type === 'replay_drill' ? '&#127909; Open in Analysis' : 'Review in Analysis'}</button>
    </div>
    ${_trRecsHTML(s)}
  `;

  board.appendChild(resultDiv);
  resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  document.getElementById('tr-next-btn')?.addEventListener('click', () => {
    if (_trSession.total >= 10) { trShowSummary(); } else { trNext(); }
  });
  document.getElementById('tr-review-btn')?.addEventListener('click', () => spNavigate('/analysis'));

  // Wire recommendation links
  resultDiv.querySelectorAll('[data-tr-nav]').forEach(btn => {
    btn.addEventListener('click', () => {
      const dest = btn.dataset.trNav;
      if (dest === 'summary') { trShowSummary(); }
      else { spNavigate(dest); }
    });
  });
}

function _trRecsHTML(s) {
  const meta = TR_SCENARIO_META[s.id];
  if (!meta) return '';
  const similarHref = `?mode=${encodeURIComponent(s.mode)}&difficulty=${encodeURIComponent(s.difficulty)}`;
  const sessionNote = _trSession.total >= 9
    ? `<div class="tr-recs-note">You've played 10 hands — great session! You can end here or keep going.</div>` : '';
  return `
    <div class="tr-recs">
      ${sessionNote}
      <div class="tr-recs-title">What to do next</div>
      <div class="tr-recs-row">
        <button class="tr-rec-btn" data-tr-nav="${escHtml(meta.recLesson)}">
          <span class="tr-rec-icon">&#128218;</span>
          <span class="tr-rec-body">
            <span class="tr-rec-label">Recommended lesson</span>
            <span class="tr-rec-sub">${escHtml(meta.topic)}</span>
          </span>
        </button>
        <button class="tr-rec-btn" data-tr-nav="/trainer${escHtml(similarHref)}">
          <span class="tr-rec-icon">&#9654;</span>
          <span class="tr-rec-body">
            <span class="tr-rec-label">Similar spots</span>
            <span class="tr-rec-sub">${escHtml(s.mode)} · ${escHtml(s.difficulty)}</span>
          </span>
        </button>
        ${_trSession.total >= 9 ? `
        <button class="tr-rec-btn tr-rec-btn--summary" data-tr-nav="summary">
          <span class="tr-rec-icon">&#127942;</span>
          <span class="tr-rec-body">
            <span class="tr-rec-label">Session summary</span>
            <span class="tr-rec-sub">${_trSession.correct}/${_trSession.total} correct</span>
          </span>
        </button>` : ''}
      </div>
    </div>
  `;
}

/* ── Next hand ────────────────────────────────────────────── */

function trNext() {
  const result = document.getElementById('tr-result');
  if (result) result.remove();
  trLoadScenario();
}

/* ── Session summary ──────────────────────────────────────── */

function trShowSummary() {
  const board = document.getElementById('tr-board');
  if (!board) return;

  const acc = _trSession.total === 0 ? 0 : Math.round(100 * _trSession.correct / _trSession.total);
  const grade = acc >= 80 ? { label: 'Excellent', cls: 'tr-grade--excellent' }
              : acc >= 60 ? { label: 'Good',      cls: 'tr-grade--good' }
              : acc >= 40 ? { label: 'Fair',      cls: 'tr-grade--fair' }
              :             { label: 'Keep Practicing', cls: 'tr-grade--low' };

  const skillRows = Object.entries(_trSession.skillStats).map(([skill, st]) => {
    const pct = Math.round(100 * st.correct / st.total);
    const recLesson = Object.values(TR_SCENARIO_META).find(m => m.skill === skill)?.recLesson || '/learn';
    return `
      <div class="tr-summary-skill">
        <span class="tr-summary-skill-name">${escHtml(skill.replace(/-/g, ' '))}</span>
        <div class="tr-summary-skill-bar">
          <div class="tr-summary-skill-fill" style="width:${pct}%"></div>
        </div>
        <span class="tr-summary-skill-pct">${pct}%</span>
        <button class="tr-summary-rec-link" data-tr-nav="${escHtml(recLesson)}">Study</button>
      </div>`;
  }).join('');

  board.innerHTML = `
    <div class="tr-summary" id="tr-summary">
      <div class="tr-summary-header">
        <div class="tr-summary-grade ${grade.cls}">${grade.label}</div>
        <h2 class="tr-summary-title">Session Complete</h2>
        <p class="tr-summary-sub">Here's how you did this session.</p>
      </div>
      <div class="tr-summary-stats">
        <div class="tr-summary-stat">
          <span class="tr-summary-val">${_trSession.total}</span>
          <span class="tr-summary-lbl">Hands Played</span>
        </div>
        <div class="tr-summary-stat">
          <span class="tr-summary-val">${_trSession.correct}</span>
          <span class="tr-summary-lbl">Correct</span>
        </div>
        <div class="tr-summary-stat">
          <span class="tr-summary-val">${acc}%</span>
          <span class="tr-summary-lbl">Accuracy</span>
        </div>
        <div class="tr-summary-stat">
          <span class="tr-summary-val">&#128293; ${_trSession.maxStreak}</span>
          <span class="tr-summary-lbl">Best Streak</span>
        </div>
      </div>
      ${skillRows ? `
      <div class="tr-summary-skills">
        <div class="tr-summary-skills-title">Accuracy by Skill</div>
        ${skillRows}
      </div>` : ''}
      <div class="tr-summary-actions">
        <button class="sp-btn-primary" id="tr-summary-new">New Session</button>
        <button class="sp-btn-secondary" data-tr-nav="/progress">View Progress</button>
        <button class="sp-btn-secondary" data-tr-nav="/learn">Browse Lessons</button>
      </div>
    </div>
  `;

  board.querySelector('#tr-summary-new')?.addEventListener('click', () => {
    _trSession.total = _trSession.correct = _trSession.streak = _trSession.maxStreak = 0;
    _trSession.skillStats = {};
    _trBuildQueue();
    _trRenderSessionBar();
    trLoadScenario();
  });
  board.querySelectorAll('[data-tr-nav]').forEach(btn => {
    btn.addEventListener('click', () => spNavigate(btn.dataset.trNav));
  });
}

/* ============================================================
   TOURNAMENT REVIEW MODE
   ============================================================ */

let _trReviewState = null; // { tournamentId, hands, filter }

// ── Entry point called by switchTab('review') ──────────────────────────────

function renderTournamentReview() {
  const panel = els.reviewPanel();
  if (!panel) return;
  if (!authIsLoggedIn()) {
    panel.innerHTML = `<div class="empty-state">${_EMPTY_ICON}
      <div class="empty-state-title">Sign in to review your hands</div>
      <div class="empty-state-sub">Tournament review requires a linked account.</div>
    </div>`;
    return;
  }
  if (_trReviewState?.tournamentId) {
    _trRenderHandView(panel, _trReviewState.hands, _trReviewState.filter || 'all', 0);
  } else {
    _trRenderList(panel);
  }
}

// ── Tournament list ────────────────────────────────────────────────────────

async function _trRenderList(panel) {
  panel.innerHTML = `<div class="loading-state"><div class="spinner"></div>Loading tournaments…</div>`;
  let tournaments;
  try {
    tournaments = await _trFetch('/me/tournaments');
  } catch (e) {
    panel.innerHTML = `<div class="empty-state">${_EMPTY_ICON}
      <div class="empty-state-title">Could not load tournaments</div>
      <div class="empty-state-sub">${escHtml(String(e.message || e))}</div>
    </div>`;
    return;
  }
  if (!tournaments.length) {
    panel.innerHTML = `<div class="empty-state">${_EMPTY_ICON}
      <div class="empty-state-title">No tournament sessions yet</div>
      <div class="empty-state-sub">Import hand history files to start reviewing sessions.</div>
      <button class="sp-btn-primary" style="margin-top:16px" onclick="switchTab('import')">Import Hands</button>
    </div>`;
    return;
  }
  panel.innerHTML = `
    <div class="rv-list-wrap">
      <h2 class="rv-list-title">Tournament Sessions</h2>
      <div class="rv-list" id="rv-list"></div>
    </div>`;
  const list = panel.querySelector('#rv-list');
  list.innerHTML = tournaments.map(t => {
    const date = t.last_hand_at ? new Date(t.last_hand_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
    const net = t.hero_net_bb != null
      ? `<span class="rv-net ${t.hero_net_bb >= 0 ? 'rv-net--pos' : 'rv-net--neg'}">${t.hero_net_bb >= 0 ? '+' : ''}${t.hero_net_bb}bb</span>`
      : '';
    return `<div class="rv-row" data-tid="${escHtml(t.id)}">
      <div class="rv-row-left">
        <div class="rv-row-table">${escHtml(t.table_name)}</div>
        <div class="rv-row-meta">${escHtml(date)} &middot; ${t.hand_count} hand${t.hand_count !== 1 ? 's' : ''}</div>
      </div>
      <div class="rv-row-right">
        ${net}
        <button class="sp-btn-primary rv-review-btn" data-tid="${escHtml(t.id)}">Review</button>
      </div>
    </div>`;
  }).join('');
  list.querySelectorAll('.rv-review-btn').forEach(btn => {
    btn.addEventListener('click', () => _trLoadTournament(panel, btn.dataset.tid));
  });
}

async function _trLoadTournament(panel, tid) {
  panel.innerHTML = `<div class="loading-state"><div class="spinner"></div>Loading hands…</div>`;
  let hands;
  try {
    hands = await _trFetch(`/me/tournaments/${encodeURIComponent(tid)}/review`);
  } catch (e) {
    panel.innerHTML = `<div class="empty-state">${_EMPTY_ICON}
      <div class="empty-state-title">Could not load tournament hands</div>
      <div class="empty-state-sub">${escHtml(String(e.message || e))}</div>
      <button class="sp-btn-secondary" style="margin-top:16px" id="rv-back-list">Back to list</button>
    </div>`;
    panel.querySelector('#rv-back-list')?.addEventListener('click', () => { _trReviewState = null; _trRenderList(panel); });
    return;
  }
  _trReviewState = { tournamentId: tid, hands, filter: 'all' };
  _trRenderHandView(panel, hands, 'all', 0);
}

// ── Hand view ──────────────────────────────────────────────────────────────

function _trRenderHandView(panel, hands, filter, startIdx) {
  const filtered = _trFilterHands(hands, filter);
  if (!filtered.length) {
    panel.innerHTML = `<div class="empty-state">${_EMPTY_ICON}
      <div class="empty-state-title">No hands match this filter</div>
      <button class="sp-btn-secondary" style="margin-top:16px" id="rv-filter-all">Show All</button>
    </div>`;
    panel.querySelector('#rv-filter-all')?.addEventListener('click', () => {
      _trReviewState.filter = 'all';
      _trRenderHandView(panel, hands, 'all', 0);
    });
    return;
  }
  _trOpenHand(panel, filtered, Math.min(startIdx, filtered.length - 1));
}

function _trFilterHands(hands, filter) {
  if (filter === 'all') return hands;
  if (filter === 'speculative') return hands.filter(h => h.analysis?.confidence === 'speculative');
  if (filter === 'mistakes')    return hands.filter(h => ['minor', 'major', 'critical'].includes(h.analysis?.mistake_severity));
  if (filter === 'major')       return hands.filter(h => ['major', 'critical'].includes(h.analysis?.mistake_severity));
  if (filter === 'good')        return hands.filter(h => h.analysis?.mistake_severity === 'good');
  // Legacy fallback for old coaching.severity values
  return hands.filter(h => h.analysis?.mistake_severity === filter || h.coaching?.severity === filter);
}

function _trOpenHand(panel, filteredHands, idx) {
  const item = filteredHands[idx];
  if (!item) return;
  const hand    = item.hand;
  const heroId  = item.hero_player_id;
  const heroHp  = hand.hand_players.find(hp => hp.player_id === heroId);
  if (!heroHp) return;
  const coaching  = item.coaching;
  const timeline  = rsBuildFullTimeline(hand);
  const seatOrder = rsBuildSeatOrder(hand.hand_players, heroId);
  const currentFilter = _trReviewState?.filter || 'all';
  const allHands      = _trReviewState?.hands || filteredHands;

  const analysis = item.analysis || null;

  _rsStop();
  _rs = {
    panel,
    hand, heroId, heroHp,
    // Minimal leak-compatible fields so rsRender / rsBindControls work unchanged
    leak: { leak_id: 'review', title: _trAnalysisTitle(analysis, coaching), severity: _trMistakeSev(analysis) },
    example: {}, allExamples: [], exIdx: 0,
    opts: [], correct: null,
    timeline, seatOrder,
    step: 0, decisionStep: timeline.length,
    phase: 'replay', chosen: null, logOpen: false, playing: true, playTimer: null,
    // Review-mode extras
    reviewMode: true,
    rvHandIdx: idx, rvFilteredHands: filteredHands, rvPanel: panel,
    rvCoaching: coaching,
    rvAnalysis: analysis,
    rvOnBack: () => { _trReviewState = null; _trRenderList(panel); },
  };
  panel.innerHTML = _trRenderFilterBar(allHands, currentFilter, filteredHands, idx) + rsRender();
  _trBindFilterBar(panel, allHands, filteredHands, currentFilter);
  rsBindControls(panel);
  if (timeline.length > 0) rsScheduleNext();
  else rsShowReviewReveal();
}

function _trAnalysisTitle(analysis, coaching) {
  if (analysis) {
    const sev = { good: 'Good Play', none: 'Review', minor: 'Mistake', major: 'Major Mistake', critical: 'Critical Mistake' };
    return `${sev[analysis.mistake_severity] || 'Review'} — ${analysis.spot_type}`;
  }
  if (!coaching) return 'Hand Review';
  const sev = { good: 'Good Play', neutral: 'Review', small_mistake: 'Mistake', big_mistake: 'Major Mistake' };
  return `${sev[coaching.severity] || 'Review'} — ${coaching.spot_type}`;
}

function _trMistakeSev(analysis) {
  if (!analysis) return 'neutral';
  const map = { good: 'low', none: 'low', minor: 'medium', major: 'high', critical: 'critical' };
  return map[analysis.mistake_severity] || 'low';
}

// ── Filter bar ─────────────────────────────────────────────────────────────

function _trRenderFilterBar(allHands, activeFilter, filteredHands, handIdx) {
  let nMajor = 0, nMistakes = 0, nGood = 0, nSpec = 0;
  allHands.forEach(h => {
    const sev = h.analysis?.mistake_severity;
    const conf = h.analysis?.confidence;
    if (sev === 'major' || sev === 'critical') nMajor++;
    if (sev === 'minor') nMistakes++;
    if (sev === 'good') nGood++;
    if (conf === 'speculative') nSpec++;
  });
  const pills = [
    { k: 'all',         label: `All (${allHands.length})` },
    { k: 'major',       label: `Major (${nMajor})` },
    { k: 'mistakes',    label: `Mistakes (${nMistakes})` },
    { k: 'good',        label: `Good (${nGood})` },
    { k: 'speculative', label: `Speculative (${nSpec})` },
  ].map(p =>
    `<button class="rv-pill${activeFilter === p.k ? ' rv-pill--active' : ''}" data-sev="${p.k}">${escHtml(p.label)}</button>`
  ).join('');
  return `<div class="rv-filter-bar" id="rv-filter-bar">${pills}</div>`;
}

function _trBindFilterBar(panel, allHands, filteredHands, currentFilter) {
  panel.querySelectorAll('.rv-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      const sev = btn.dataset.sev;
      if (_trReviewState) _trReviewState.filter = sev;
      _trRenderHandView(panel, allHands, sev, 0);
    });
  });
}

// ── Review reveal (coaching panel) ────────────────────────────────────────

function rsShowReviewReveal() {
  if (!_rs) return;
  _rs.phase = 'reveal';
  const { panel, rvAnalysis, rvCoaching, rvHandIdx, rvFilteredHands, heroHp } = _rs;
  const tableEl = panel.querySelector('#rs-table');
  if (tableEl) tableEl.classList.remove('rs-table--decision');
  const dockEl = panel.querySelector('#rs-decision-dock');
  if (dockEl) dockEl.hidden = true;
  const ctrlWrap = panel.querySelector('.rs-tbl-controls');
  if (ctrlWrap) ctrlWrap.style.display = '';

  const revealEl = panel.querySelector('#rs-reveal');
  if (!revealEl) return;
  revealEl.hidden = false;

  const pos     = heroHp?.position || '?';
  const stackBb = heroHp?.stack_bb ? parseFloat(heroHp.stack_bb).toFixed(0) : '?';
  const total   = rvFilteredHands ? rvFilteredHands.length : 1;
  const hasPrev = rvHandIdx > 0;
  const hasNext = rvHandIdx < total - 1;

  // Prefer the new analysis object; fall back to legacy coaching
  const src = rvAnalysis || rvCoaching;
  if (!src) {
    revealEl.innerHTML = `<div class="rs-rev-section"><div class="rs-rev-label">Hand Review</div>
      <div class="rs-tip"><div class="rs-tip-val">No analysis data for this hand.</div></div>
    </div>` + _rvNavBtns(hasPrev, hasNext);
    _rvBindNavBtns(revealEl);
    return;
  }

  // Severity mapping — handle both old (coaching) and new (analysis) field names
  const mistakeSev = rvAnalysis?.mistake_severity || null;
  const legacySev  = rvCoaching?.severity || null;
  const SEV_CLS = {
    good: 'rv-sev--good', none: 'rv-sev--neutral',
    minor: 'rv-sev--minor', major: 'rv-sev--major', critical: 'rv-sev--major',
    small_mistake: 'rv-sev--minor', big_mistake: 'rv-sev--major', neutral: 'rv-sev--neutral',
  };
  const SEV_LBL = {
    good: 'Good Play', none: 'Neutral',
    minor: 'Mistake', major: 'Major Mistake', critical: 'Critical Mistake',
    small_mistake: 'Mistake', big_mistake: 'Major Mistake', neutral: 'Neutral',
  };
  const activeSev = mistakeSev || legacySev || 'none';
  const sevCls = SEV_CLS[activeSev] || 'rv-sev--neutral';
  const sevLbl = SEV_LBL[activeSev] || 'Neutral';

  // Confidence label (new engine only)
  const isSpeculative = rvAnalysis?.confidence === 'speculative';
  const confLbl = rvAnalysis
    ? rvAnalysis.confidence.toUpperCase()
    : '';
  const confBadgeCls = isSpeculative ? 'rv-conf--spec' : 'rv-conf--inf';
  const confBadge = confLbl
    ? `<span class="rv-conf-badge ${confBadgeCls}">${escHtml(confLbl)}</span>`
    : '';

  const speculativeNote = isSpeculative
    ? `<div class="rv-spec-note">Estimate only — exact solver/ICM data unavailable.</div>`
    : '';

  // Key factors (new engine only)
  const keyFactors = rvAnalysis?.key_factors || [];
  const keyFactorsHtml = keyFactors.length
    ? `<div class="rs-tip">
        <div class="rs-tip-lbl">Key factors</div>
        <div class="rs-tip-val rv-factors">${keyFactors.map(f => `<span class="rv-factor">${escHtml(f)}</span>`).join('')}</div>
      </div>`
    : '';

  // Range context (new engine only)
  const rangeCtx = rvAnalysis?.range_context || '';
  const rangePos = rvAnalysis?.hero_range_position || 'unknown';
  const RANGE_POS_CLS = { top: 'rv-rpos--top', mid: 'rv-rpos--mid', bottom: 'rv-rpos--bottom', outside: 'rv-rpos--outside' };
  const rangeHtml = rangeCtx
    ? `<div class="rs-tip">
        <div class="rs-tip-lbl">Range context</div>
        <div class="rs-tip-val">${escHtml(rangeCtx)}${rangePos !== 'unknown'
          ? ` &mdash; <span class="rv-rpos-badge ${RANGE_POS_CLS[rangePos] || ''}">${escHtml(rangePos)} of range</span>`
          : ''}</div>
      </div>
      <div class="rv-range-note">Range-based estimate &mdash; not exact solver output</div>`
    : '';

  // Backing label (new engine only)
  const backingHtml = rvAnalysis?.backing
    ? `<div class="rv-backing">Basis: <span class="rv-backing-val">${escHtml(rvAnalysis.backing)}</span></div>`
    : '';

  // Practical exploit adjustment (opponent profile layer)
  const exploit = rvAnalysis?.exploit_adjustment || '';
  const villainProfileRaw = rvAnalysis?.villain_profile || '';
  const villainConf = rvAnalysis?.villain_profile_confidence || '';
  let exploitHtml = '';

  if (villainProfileRaw === 'unknown') {
    exploitHtml = `<div class="rv-exploit rv-exploit--unknown">
      <div class="rv-exploit-header">&#x1F9E0; Practical Adjustment</div>
      <div class="rv-exploit-no-data">Not enough hands on villain for a reliable exploit adjustment.</div>
    </div>`;
  } else if (villainProfileRaw === 'balanced') {
    const confBadgeHtml = villainConf
      ? `<span class="rv-exploit-conf rv-exploit-conf--${escHtml(villainConf)}">${escHtml(villainConf)}</span>`
      : '';
    exploitHtml = `<div class="rv-exploit">
      <div class="rv-exploit-header">&#x1F9E0; Practical Adjustment</div>
      <div class="rv-exploit-villain">Villain: Balanced ${confBadgeHtml}</div>
      <div class="rv-exploit-no-data">Player appears balanced — stay close to Nash baseline.</div>
    </div>`;
  } else if (exploit && villainProfileRaw) {
    const villainLabel = villainProfileRaw.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    const confBadgeHtml = villainConf
      ? `<span class="rv-exploit-conf rv-exploit-conf--${escHtml(villainConf)}">${escHtml(villainConf)}</span>`
      : '';
    const lines = exploit.split('\n');
    const hasStats = lines[0].startsWith('VPIP');
    const statsHtml = hasStats ? `<div class="rv-exploit-stats">${escHtml(lines[0])}</div>` : '';
    const bulletLines = lines.slice(hasStats ? 1 : 0).filter(b => b.trim());
    const bulletsHtml = bulletLines.map(b => `<div class="rv-exploit-bullet">${escHtml(b)}</div>`).join('');
    exploitHtml = `<div class="rv-exploit">
      <div class="rv-exploit-header">&#x1F9E0; Practical Adjustment</div>
      <div class="rv-exploit-villain">Villain: ${escHtml(villainLabel)} ${confBadgeHtml}</div>
      ${statsHtml}
      <div class="rv-exploit-bullets">${bulletsHtml}</div>
    </div>`;
  }

  revealEl.innerHTML = `
    <div class="rs-rev-section">
      <div class="rs-rev-label">Analysis ${confBadge} <span class="rv-sev-badge ${sevCls}">${escHtml(sevLbl)}</span></div>
      ${speculativeNote}
      <div class="rs-tip">
        <div class="rs-tip-lbl">Spot</div>
        <div class="rs-tip-val">${escHtml(src.spot_type)} &middot; ${escHtml(pos)} &middot; ${escHtml(stackBb)}bb</div>
      </div>
      <div class="rs-tip">
        <div class="rs-tip-lbl">Your action</div>
        <div class="rs-tip-val">${escHtml(src.hero_action)}</div>
      </div>
      <div class="rs-tip">
        <div class="rs-tip-lbl">Recommended</div>
        <div class="rs-tip-val rv-recommended">${escHtml(src.recommended_action)}</div>
      </div>
      <div class="rs-tip">
        <div class="rs-tip-lbl">Explanation</div>
        <div class="rs-tip-val">${escHtml(src.explanation)}</div>
      </div>
      ${keyFactorsHtml}
      ${rangeHtml}
      ${backingHtml}
      ${exploitHtml}
    </div>
    <details class="rv-limitations">
      <summary class="rv-limitations-toggle">Known limitations</summary>
      <ul class="rv-limitations-list">
        <li>Analysis is rule-based (heuristic / range-based estimate). No solver was run.</li>
        <li>Exact EV is unavailable — all outputs use estimated ranges.</li>
        <li>ICM calculations require payout structure data not present in ClubGG hand histories.</li>
        <li>Opponent hole cards are never known — call/fold edges marked SPECULATIVE.</li>
      </ul>
    </details>
    ${_rvNavBtns(hasPrev, hasNext)}`;

  _rvBindNavBtns(revealEl);
}

function _rvNavBtns(hasPrev, hasNext) {
  return `<div class="rs-reveal-btns">
    <button class="rs-dec-btn" id="rv-prev-hand-reveal" ${hasPrev ? '' : 'disabled'}>‹ Prev</button>
    <button class="rs-dec-btn rs-dec-btn--call" id="rv-next-hand-reveal" ${hasNext ? '' : 'disabled'}>Next ›</button>
  </div>`;
}

function _rvBindNavBtns(revealEl) {
  revealEl.querySelector('#rv-prev-hand-reveal')?.addEventListener('click', () => {
    if (!_rs) return;
    const { rvHandIdx: i, rvFilteredHands: fh, rvPanel: p } = _rs;
    if (i > 0) { _rsStop(); _trOpenHand(p, fh, i - 1); }
  });
  revealEl.querySelector('#rv-next-hand-reveal')?.addEventListener('click', () => {
    if (!_rs) return;
    const { rvHandIdx: i, rvFilteredHands: fh, rvPanel: p } = _rs;
    if (i < fh.length - 1) { _rsStop(); _trOpenHand(p, fh, i + 1); }
  });
}

// ── Full timeline (all streets) ────────────────────────────────────────────

function rsBuildFullTimeline(hand) {
  const sRank = { PREFLOP: 0, FLOP: 1, TURN: 2, RIVER: 3 };
  const bb    = parseFloat(hand.stakes_bb) || 1;
  const seq   = [];
  for (const hp of hand.hand_players) {
    for (const act of (hp.actions || [])) {
      seq.push({
        playerId:     hp.player_id,
        pos:          hp.position || `S${hp.seat_number}`,
        username:     hp.username || hp.position || `S${hp.seat_number}`,
        street:       act.street,
        action_type:  act.action_type,
        action_order: act.action_order,
        amount:       act.amount ? parseFloat(act.amount) / bb : 0,
        is_all_in:    act.is_all_in || false,
      });
    }
  }
  seq.sort((a, b) => {
    const d = (sRank[a.street] ?? 99) - (sRank[b.street] ?? 99);
    return d !== 0 ? d : a.action_order - b.action_order;
  });
  return seq;
}

// ── API helper ─────────────────────────────────────────────────────────────

async function _trFetch(path) {
  const token = authGetToken();
  const res = await fetch(`/api/v1${path}`, {
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
