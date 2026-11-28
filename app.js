(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const LEAGUES = [['all', 'All'], ['nba', 'NBA'], ['nfl', 'NFL'], ['nhl', 'NHL']];
  const TEAM_BETS = { win: 'Moneyline', margin: 'Spread', tpts: 'Team total', total: 'Game total' };
  const STATS = {
    nba: { pts: 'Points', reb: 'Rebounds', ast: 'Assists', '3pm': 'Threes', pra: 'Pts + Reb + Ast', stl: 'Steals', blk: 'Blocks', stocks: 'Steals + Blocks', dd: 'Double-double', td3: 'Triple-double', ...TEAM_BETS },
    nfl: { pass_yds: 'Passing yards', pass_tds: 'Passing TDs', pass_cmp: 'Completions', pass_att: 'Pass attempts', ints: 'Interceptions', rush_yds: 'Rushing yards', rush_att: 'Rush attempts', rec_yds: 'Receiving yards', rec: 'Receptions', rush_rec_yds: 'Rush + rec yards', tds: 'Touchdowns', rec_long: 'Longest reception', rush_long: 'Longest rush', ...TEAM_BETS },
    nhl: { goals: 'Goals', points: 'Points', assists: 'Assists', saves: 'Saves', ...TEAM_BETS },
  };
  const SHORT = {
    pra: 'PRA', stocks: 'Stl + Blk', pass_yds: 'Pass yds', rush_yds: 'Rush yds', rec_yds: 'Rec yds',
    rush_rec_yds: 'Rush + rec yds', pass_att: 'Pass att', rush_att: 'Rush att', rec_long: 'Longest rec', rush_long: 'Longest rush',
    ints: 'INTs', pass_tds: 'Pass TDs', tds: 'TDs', pass_cmp: 'Completions',
  };
  const BINARY = new Set(['dd', 'td3']);
  const UNIT = { nba: 'points', nfl: 'points', nhl: 'goals' };
  // Every other sport Kalshi lists (more.json): game markets only, history from Kalshi's own settled markets.
  const GROUP_CHIPS = [['cfb', 'College football'], ['cbb', 'College basketball'], ['soccer', 'Soccer'], ['tennis', 'Tennis'],
    ['fights', 'UFC & boxing'], ['esports', 'Esports'], ['hoops', 'Basketball'], ['hockey', 'Hockey'], ['football', 'Football'],
    ['baseball', 'Baseball'], ['cricket', 'Cricket'], ['other', 'Other']];
  const GENERIC = { win: 'Moneyline', draw: 'Draw', margin: 'Spread', tpts: 'Team total', total: 'Game total', btts: 'Both teams score' };
  const isK = (r) => r.src === 'k';
  const unitOf = (r) => r.u || UNIT[r.lg] || 'points';
  const lgLabel = (r) => ((D.lgmeta || {})[r.lg] || {}).label || r.lg.toUpperCase();
  const KINDS = [['all', 'Players and teams'], ['player', 'Player props'], ['team', 'Team bets']];
  const SLUGS = {
    KXNBAPTS: 'nba-player-points', KXNBAREB: 'nba-player-rebounds', KXNBAAST: 'nba-player-assists', KXNBA3PT: 'nba-player-threes',
    KXNBAPRA: 'nba-player-points-rebounds-assists', KXNBASTL: 'nba-player-steals', KXNBABLK: 'nba-player-blocks',
    KXNBASTOCK: 'nba-player-steals-blocks', KXNBA2D: 'nba-player-double-double', KXNBA3D: 'nba-player-triple-double',
    KXNFLPASSYDS: 'pro-football-passing-yards', KXNFLPASSTDS: 'pro-football-player-passing-touchdowns',
    KXNFLPASSCOMP: 'pro-football-passing-completions', KXNFLPASSATT: 'pro-football-passing-attempts',
    KXNFLPASSINT: 'pro-football-passing-interceptions', KXNFLRSHYDS: 'pro-football-rushing-yards',
    KXNFLRSHATT: 'pro-football-rushing-attempts', KXNFLRECYDS: 'pro-football-receiving-yards',
    KXNFLREC: 'pro-football-player-receptions', KXNFLRRYDS: 'pro-football-rush-and-receiving-yards',
    KXNFLTD: 'pro-football-touchdowns', KXNFLLONGREC: 'longest-reception', KXNFLLONGRSH: 'longest-rush',
    KXNHLGOAL: 'nhl-goalscorer', KXNHLPTS: 'pro-hockey-points', KXNHLAST: 'pro-hockey-assists', KXNHLSAVE: 'goaltender-saves',
    KXNBAGAME: 'nba-game', KXNBASPREAD: 'nba-spread', KXNBATOTAL: 'nba-total', KXNBATEAMTOTAL: 'nba-team-total',
    KXNFLGAME: 'nfl-game', KXNFLSPREAD: 'pro-football-spread', KXNFLTOTAL: 'pro-football-total-points',
    KXNFLTEAMTOTAL: 'pro-football-team-total-points', KXNHLGAME: 'nhl-game', KXNHLSPREAD: 'nhl-spread',
    KXNHLTOTAL: 'nhl-total-goals', KXNHLTEAMTOTAL: 'nhl-team-goals-scored-during-game',
  };
  const VOLUME = { min: 'Minutes', toi: 'Ice time', targets: 'Targets', rush_att: 'Carries', pass_att: 'Pass attempts', touches: 'Touches' };
  const POS_LABEL = { G: 'guards', F: 'forwards', C: 'centers', QB: 'QBs', RB: 'running backs', WR: 'receivers', TE: 'tight ends', D: 'defensemen' };
  const LOG_COLS = {
    nba: [['min', 'MIN'], ['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'], ['3pm', '3PM'], ['stl', 'STL'], ['blk', 'BLK'], ['pra', 'PRA']],
    nfl: [['pass_cmp', 'CMP'], ['pass_att', 'ATT'], ['pass_yds', 'Pass yds'], ['pass_tds', 'Pass TD'], ['ints', 'INT'], ['rush_att', 'Car'], ['rush_yds', 'Rush yds'], ['rush_long', 'Long rush'], ['rec', 'Rec'], ['targets', 'Tgt'], ['rec_yds', 'Rec yds'], ['rec_long', 'Long rec'], ['tds', 'TD']],
    nhl: [['toi', 'TOI'], ['goals', 'G'], ['assists', 'A'], ['points', 'PTS'], ['sog', 'SOG'], ['saves', 'SV'], ['sa', 'SA'], ['ga', 'GA']],
  };
  const RANGES = [['l5', 'L5'], ['l10', 'L10'], ['l20', 'L20'], ['szn', 'Season'], ['prev', 'Last season'], ['h2h', 'H2H']];
  const SHOW_FLAGS = new Set(['Live', 'Check news', 'First game this season', 'Long layoff', 'Role change', 'Small sample', 'Wide spread', 'Left last game hurt', 'Key player out', 'Back-to-back']);
  const showFlag = (f) => SHOW_FLAGS.has(f) || f.startsWith('Missed last');
  const injuryFlag = (f) => f === 'Left last game hurt' || f === 'Key player out' || f.startsWith('Missed last');
  const isHurt = (g) => !!(g && g.inj && g.inj.kind === 'hurt');
  const PAGE = 100;

  // Team bets: Kalshi's moneylines, spreads ("wins by over 8.5" = -8.5), game totals and team totals.
  // Their line is the whole number that wins (9 = by 9 or more), like a prop's "25+".
  const isTeam = (r) => !!r.kind;                        // 'team' or 'game' (a game total)
  const kindOk = (r) => S.kind === 'all' || (S.kind === 'team') === (isTeam(r) && r.kind !== 'player');
  const half = (line) => fmtNum(line - 0.5);
  // a win is a margin of 1 or more; Kalshi-history games without a known margin use +1 / -1 / 0 for win, loss, draw
  const valOf = (g, stat) => (stat === 'win' ? (g.s.margin ?? g.s.wl) : g.s[stat]);
  const signedNum = (v) => (v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + fmtNum(Math.abs(v)));
  function lineTxt(r) {
    if (r.stat === 'win') return 'Win';
    if (r.stat === 'draw') return 'Draw';
    if (r.stat === 'btts') return 'Both score';
    if (r.stat === 'margin') return '−' + half(r.line);
    if (r.stat === 'tpts' || r.stat === 'total') return 'O ' + half(r.line);
    return BINARY.has(r.stat) ? 'Yes' : r.line + '+';
  }

  // ------------------------------------------------------------ state
  const DEFAULTS = { league: 'all', kind: 'all', stat: 'all', game: 'all', q: '', sort: 'edge', best: true, hideLow: false };
  const S = Object.assign({}, DEFAULTS, readPrefs(), { limit: PAGE });
  function readPrefs() {
    try { return JSON.parse(localStorage.getItem('pf:prefs') || '{}'); } catch (e) { return {}; }
  }
  function savePrefs() {
    try {
      const { league, kind, stat, sort, best, hideLow } = S;
      localStorage.setItem('pf:prefs', JSON.stringify({ league, kind, stat, sort, best, hideLow }));
    } catch (e) { /* storage unavailable */ }
  }

  let D = null;
  const byId = new Map();
  const pfCache = new Map();
  let lastFocus = null;
  let drawerState = null;

  // ------------------------------------------------------------ formatting
  const rate = (h) => (h && h[1] ? h[0] / h[1] : null);
  const pct = (x) => (x == null ? '—' : Math.round(x * 100) + '%');
  const cents = (x) => (x == null ? '—' : Math.round(x * 100) + '¢');
  const fmtNum = (v) => (v == null ? '—' : Number.isInteger(v) ? String(v) : (Math.round(v * 10) / 10).toString());
  const signed = (x, d = 1) => (Math.abs(x) < 0.5 * 10 ** -d ? '' : x > 0 ? '+' : '−') + Math.abs(x).toFixed(d);
  const norm = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const ordinal = (n) => { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
  const md = (iso) => { if (!iso) return ''; const [, m, d] = iso.split('-'); return `${+m}/${+d}`; };
  const statLabel = (lg, st, r) => {
    const x = (STATS[lg] || {})[st];
    if (x) return x;
    if (r && r.sl) return r.sl;                 // props for the other sports carry their own label
    const u = r && r.u;
    if (st === 'total' && (u === 'maps' || u === 'games')) return `Total ${u}`;
    if (st === 'margin' && (u === 'maps' || u === 'games')) return `${u === 'maps' ? 'Map' : 'Game'} spread`;
    if (st === 'win' && u === 'games') return 'Match winner';
    return GENERIC[st] || st;
  };
  const priceOk = (x) => x != null && x > 0 && x < 1;

  function kalshiUrl(ticker) {
    const parts = ticker.split('-');
    const series = parts[0];
    const ev = parts.slice(0, 2).join('-');
    return `https://kalshi.com/markets/${series.toLowerCase()}/${SLUGS[series] || 'event'}/${ev.toLowerCase()}`;
  }

  function posGroup(lg, pos) {
    const p = String(pos || '').toUpperCase();
    if (lg === 'nba') return p.startsWith('C') ? 'C' : ['G', 'PG', 'SG'].includes(p) ? 'G' : 'F';
    if (lg === 'nfl') return p === 'FB' ? 'RB' : p;
    if (lg === 'nhl') return p === 'G' ? 'G' : p === 'D' ? 'D' : 'F';
    return p;
  }

  // ESPN's state is from the last update; a game whose start time has passed since then is live too.
  const isLive = (G) => !!G && (G.state === 'in' || (G.state !== 'post' && !!G.start && Date.parse(G.start) <= Date.now()));

  function fmtWhen(G) {
    if (!G || !G.start) return '';
    if (isLive(G)) return 'Live now';
    const d = new Date(G.start);
    const now = new Date();
    const time = (G.est ? 'about ' : '') + d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) return time;
    const tmr = new Date(now.getTime() + 864e5);
    if (d.toDateString() === tmr.toDateString()) return 'Tomorrow ' + time;
    return d.toLocaleDateString([], { weekday: 'short' }) + ' ' + time;
  }

  function ago(iso) {
    const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const h = Math.floor(mins / 60);
    return h < 24 ? `${h} hr ${mins % 60} min ago` : `${Math.floor(h / 24)} days ago`;
  }

  // ------------------------------------------------------------ load
  async function load() {
    let res;
    try {
      res = await fetch('data/board.json?v=' + Math.floor(Date.now() / 120000));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      D = await res.json();
    } catch (e) {
      $('#updated').textContent = 'Couldn’t load the props. Refresh the page to try again.';
      $('#empty').hidden = false;
      $('#empty').textContent = 'The prop data didn’t load. If this keeps happening, the update job on GitHub may have failed.';
      return;
    }
    prepare();
    renderLeagues();
    renderSelects();
    bind();
    render();
    renderUpdated();
    setInterval(renderUpdated, 60000);
    route();
    loadMore();
  }

  async function loadMore() {
    let more;
    try {
      const res = await fetch('data/more.json?v=' + Math.floor(Date.now() / 120000));
      if (!res.ok) return;
      more = await res.json();
    } catch (e) { return; }
    D.groups = more.groups || {};
    D.lgmeta = more.leagues || {};
    Object.assign(D.games, more.games || {});
    Object.assign(D.players, more.players || {});
    const rows = more.props || [];
    prepare(rows);
    D.props.push(...rows);
    renderLeagues();
    renderSelects();
    render();
    if (!drawerState) route();
  }

  function prepare(rows) {
    if (!rows) { rows = D.props; if (!rows.some(isTeam)) S.kind = 'all'; }
    for (const r of rows) {
      r.P = D.players[r.pid] || { name: 'Unknown' };
      r.G = D.games[r.gid] || {};
      r.grp = r.grp || r.lg;
      r.label = statLabel(r.lg, r.stat, r);
      r.short = SHORT[r.stat] || r.label;
      r.k.na = r.k.yb != null && r.k.yb > 0 ? Math.round((1 - r.k.yb) * 100) / 100 : null;
      r.k.nb = r.k.ya != null && r.k.ya < 1 ? Math.round((1 - r.k.ya) * 100) / 100 : null;
      // search matches the player or team, its full team name, and the opponent's abbreviation
      const full = r.kind === 'game' ? `${r.G.home_name || ''} ${r.G.away_name || ''} ${r.G.home || ''} ${r.G.away || ''}`
        : (r.home ? r.G.home_name : r.G.away_name) || '';
      r._q = norm(`${r.P.name} ${r.P.team || ''} ${r.opp || ''} ${full}` + (isK(r) ? ` ${lgLabel(r)}` : ''));
      r.t = Date.parse(r.G.start) || 0;
      byId.set(r.id, r);
    }
  }

  function renderUpdated() {
    if (!D) return;
    const el = $('#updated');
    const mins = (Date.now() - Date.parse(D.updated)) / 60000;
    el.textContent = `Updated ${ago(D.updated)}`;
    el.classList.toggle('stale', mins > 75);
    if (mins > 75) el.textContent += '. Prices may be out of date';
  }

  // ------------------------------------------------------------ controls
  function renderLeagues() {
    const rs = D.props.filter(kindOk);
    const counts = { all: rs.length };
    for (const r of rs) counts[r.grp] = (counts[r.grp] || 0) + 1;
    if (S.league !== 'all' && !counts[S.league] && (D.groups || S.league in { nba: 1, nfl: 1, nhl: 1 })) S.league = 'all';
    $('#leagues').innerHTML = LEAGUES.concat(GROUP_CHIPS).filter(([k]) => k === 'all' || counts[k] || k === S.league)
      .map(([k, name]) => `<button type="button" data-lg="${k}" aria-pressed="${S.league === k}">${name}<span class="ct">${counts[k] || 0}</span></button>`).join('');
  }

  function renderSelects() {
    $('#kind').closest('label').hidden = !D.props.some(isTeam);
    $('#kind').innerHTML = KINDS.map(([k, n]) => `<option value="${k}"${S.kind === k ? ' selected' : ''}>${n}</option>`).join('');
    const inLg = D.props.filter((r) => (S.league === 'all' || r.grp === S.league) && kindOk(r));
    const stats = new Map();
    for (const r of inLg) stats.set(r.grp + ':' + r.stat, r);
    const order = (r) => (LEAGUES.concat(GROUP_CHIPS).findIndex(([k]) => k === r.grp) + 100) % 100;
    const statOpts = [...stats.values()].sort((a, b) => order(a) - order(b) || isTeam(a) - isTeam(b) || a.label.localeCompare(b.label));
    const grpName = (r) => (LEAGUES.concat(GROUP_CHIPS).find(([k]) => k === r.grp) || [, r.grp.toUpperCase()])[1];
    if (S.stat !== 'all' && !statOpts.some((r) => r.stat === S.stat)) S.stat = 'all';
    $('#stat').innerHTML = `<option value="all">${S.kind === 'team' ? 'All types' : 'All stats'}</option>` + statOpts.map((r) =>
      `<option value="${esc(r.stat)}"${S.stat === r.stat ? ' selected' : ''}>${S.league === 'all' ? esc(grpName(r)) + ' ' : ''}${esc(isK(r) ? GENERIC[r.stat] || r.label : r.label)}</option>`).join('');
    const games = new Map();
    for (const r of inLg) if (!games.has(r.gid)) games.set(r.gid, r);
    const gameOpts = [...games.values()].sort((a, b) => a.t - b.t);
    if (S.game !== 'all' && !games.has(S.game)) S.game = 'all';
    $('#game').innerHTML = '<option value="all">All games</option>' + gameOpts.map((r) =>
      `<option value="${esc(r.gid)}"${S.game === r.gid ? ' selected' : ''}>${esc(isK(r) ? `${r.G.away_name} ${r.G.sep} ${r.G.home_name}` : `${r.G.away} @ ${r.G.home}`)}, ${esc(fmtWhen(r.G))}</option>`).join('');
    $('#sort').value = S.sort;
    $('#best').checked = S.best;
    $('#hideLow').checked = S.hideLow;
    $('#q').value = S.q;
  }

  function bind() {
    $('#leagues').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-lg]');
      if (!b) return;
      S.league = b.dataset.lg; S.game = 'all'; S.limit = PAGE;
      for (const x of $('#leagues').querySelectorAll('button')) x.setAttribute('aria-pressed', String(x === b));
      renderSelects(); render(); savePrefs();
    });
    $('#kind').addEventListener('change', (e) => { S.kind = e.target.value; S.game = 'all'; S.limit = PAGE; renderLeagues(); renderSelects(); render(); savePrefs(); });
    $('#stat').addEventListener('change', (e) => { S.stat = e.target.value; S.limit = PAGE; render(); savePrefs(); });
    $('#game').addEventListener('change', (e) => { S.game = e.target.value; S.limit = PAGE; render(); });
    $('#sort').addEventListener('change', (e) => { S.sort = e.target.value; S.limit = PAGE; render(); savePrefs(); });
    $('#best').addEventListener('change', (e) => { S.best = e.target.checked; S.limit = PAGE; render(); savePrefs(); });
    $('#hideLow').addEventListener('change', (e) => { S.hideLow = e.target.checked; S.limit = PAGE; render(); savePrefs(); });
    let t;
    $('#q').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { S.q = norm(e.target.value.trim()); S.limit = PAGE; render(); }, 120); });
    $('#more').addEventListener('click', () => { S.limit += PAGE; render(true); });
    $('.row.head').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-sort]');
      if (!b) return;
      S.sort = b.dataset.sort; $('#sort').value = ['l5', 'l20', 'h2h', 'venue'].includes(S.sort) ? 'edge' : S.sort;
      S.limit = PAGE; render(); savePrefs();
    });
    $('#rows').addEventListener('click', (e) => {
      const row = e.target.closest('.prop-row');
      if (row) openProp(row.dataset.id, row);
    });
    $('#rows').addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const row = e.target.closest('.prop-row');
      if (row) { e.preventDefault(); openProp(row.dataset.id, row); }
    });
    $('#scrim').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#drawer').hidden) closeDrawer(); });
    window.addEventListener('popstate', route);
    let rt;
    window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { if (drawerState) renderChartOnly(); setHeadOffset(); }, 150); });
    setHeadOffset();
  }

  function setHeadOffset() {
    const h = $('.top').getBoundingClientRect().height;
    document.documentElement.style.setProperty('--head-h', Math.round(h) + 'px');
  }

  // ------------------------------------------------------------ board
  function sortKey(r) {
    switch (S.sort) {
      case 'gap': return r.p == null || r.mid == null ? -1 : Math.abs(r.p - r.mid);
      case 'l5': return rate(r.h.l5) ?? -1;
      case 'l10': return rate(r.h.l10) ?? -1;
      case 'l20': return rate(r.h.l20) ?? -1;
      case 'szn': return rate(r.h.szn) ?? -1;
      case 'h2h': return rate(r.h.h2h) ?? -1;
      case 'venue': return rate(r.h[r.home ? 'home' : 'away']) ?? -1;
      case 'streak': return r.strk ?? -99;
      case 'volume': return r.k.vol || 0;
      case 'time': return -r.t;
      default: return isLive(r.G) ? -8 : r.be ?? -9;   // a pre-game edge means nothing once the game is on
    }
  }

  function bestLineScore(r) {
    if (r.be != null) return r.be;
    return r.mid == null ? -9 : -Math.abs(r.mid - 0.5) - 1;
  }

  function filtered() {
    let rs = D.props.filter((r) =>
      (S.league === 'all' || r.grp === S.league) && kindOk(r) &&
      (S.stat === 'all' || r.stat === S.stat) &&
      (S.game === 'all' || r.gid === S.game) &&
      (!S.q || r._q.includes(S.q)) &&
      (!S.hideLow || r.conf !== 'low') &&
      r.G.state !== 'post');
    if (S.best) {
      const best = new Map();
      for (const r of rs) {
        const k = r.pid + '|' + r.stat + '|' + r.gid;
        const cur = best.get(k);
        if (!cur || bestLineScore(r) > bestLineScore(cur)) best.set(k, r);
      }
      rs = [...best.values()];
    }
    rs.sort((a, b) => sortKey(b) - sortKey(a) || (b.be ?? -9) - (a.be ?? -9));
    return rs;
  }

  function hrClass(h, mid) {
    const r = rate(h);
    if (r == null || h[1] < 3 || mid == null) return r == null ? 'na' : '';
    const d = r - mid;
    return d >= 0.05 ? 'good' : d <= -0.05 ? 'bad' : '';
  }

  function chip(h, mid, lbl, extra = '') {
    const r = rate(h);
    const cls = hrClass(h, mid);
    const body = r == null ? '—' : pct(r);
    const n = h && h[1] ? `<small>${h[0]}/${h[1]}</small>` : '<small>&nbsp;</small>';
    return `<div class="c-hr${extra}" role="cell"><span class="lbl">${lbl}</span><span class="hr ${cls}">${body}${n}</span></div>`;
  }

  // Value range for bars. Props start at zero. Margins dip below zero for losses. Team and game totals in the
  // NBA and NFL (100+ points) start near the lowest game, so the gap to the line shows; the drawer chart labels its axis.
  function barRange(stat, vals, line, headroom) {
    const mn = Math.min(...vals, line - 0.5), mx = Math.max(...vals, line - 0.5, 1);
    if ((stat === 'tpts' || stat === 'total') && mx >= 20) {
      const pad = Math.max(1, (mx - mn) * 0.2);
      return { lo: Math.max(0, mn - pad), hi: mx + pad * 0.5, base: Math.max(0, mn - pad) };
    }
    const hi = Math.max(mx, headroom ? line * headroom : 0);
    const lo = mn < 0 ? mn - (hi - mn) * 0.06 : 0;
    return { lo, hi, base: 0 };
  }

  function stripSVG(vals, line, hurtIdx, stat) {
    const n0 = Math.min(vals.length, 10);
    const hurt = new Set((hurtIdx || []).map((i) => n0 - 1 - i));   // indexes after the reverse below
    const v = vals.slice(0, 10).reverse();
    const W = 100, H = 30, bw = 8, gap = 2;
    const R = barRange(stat, v.length ? v : [0], line, 1.35);
    const y = (val) => H - ((val - R.lo) / (R.hi - R.lo || 1)) * (H - 2);
    const y0 = y(R.base);
    const thr = y(line - 0.5);
    let x = W - v.length * (bw + gap) + gap;
    let s = '';
    v.forEach((val, i) => {
      const yv = y(val), h = Math.max(2, Math.abs(y0 - yv));
      const fill = hurt.has(i) ? 'var(--ink-3)' : `var(--${val >= line ? 'hit' : 'miss'})`;
      const d = val >= R.base ? roundTop(x, Math.min(yv, y0 - 2), bw, h, 2) : roundBottom(x, y0, bw, h, 2);
      s += `<path d="${d}" fill="${fill}"${hurt.has(i) ? ' opacity=".55"' : ''}/>`;
      x += bw + gap;
    });
    const counted = v.filter((_, i) => !hurt.has(i));
    const hits = counted.filter((x2) => x2 >= line).length;
    const label = v.length ? `Last ${v.length}: hit ${hits} of ${counted.length}` + (hurt.size ? `. ${hurt.size} game${hurt.size > 1 ? 's' : ''} he left hurt, not counted (grey)` : '') : 'No games yet';
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}"><title>${label}</title>${s}` +
      (R.lo < 0 ? `<line x1="0" x2="${W}" y1="${y0}" y2="${y0}" stroke="var(--line-2)" stroke-width="1"/>` : '') +
      `<line x1="0" x2="${W}" y1="${thr}" y2="${thr}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 2" opacity=".75"/></svg>`;
  }

  function roundTop(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }

  function roundBottom(x, y, w, h, r) {   // a bar hanging down from y (a loss on a margin chart)
    r = Math.min(r, w / 2, h);
    return `M${x},${y}V${y + h - r}Q${x},${y + h} ${x + r},${y + h}H${x + w - r}Q${x + w},${y + h} ${x + w},${y + h - r}V${y}Z`;
  }

  function confHTML(c) {
    const n = c === 'high' ? 3 : c === 'med' ? 2 : 1;
    const word = c === 'high' ? 'High' : c === 'med' ? 'Medium' : 'Low';
    return `<span class="conf c${n}" role="img" aria-label="${word} confidence" title="${word} confidence"><i></i><i></i><i></i></span>`;
  }

  function injFlag(inj) {
    if (!inj || !inj.status) return '';
    const out = /out|reserve|susp/i.test(inj.status);
    return `<span class="flag ${out ? 'out' : 'inj'}">${esc(inj.status)}</span>`;
  }

  function rowHTML(r) {
    const P = r.P, G = r.G, k = r.k;
    const vs = r.home ? 'vs' : '@';
    const flags = r.flags.filter(showFlag).sort((a, b) => injuryFlag(b) - injuryFlag(a)).slice(0, 2)
      .map((f) => `<span class="flag${injuryFlag(f) ? ' inj' : ''}">${esc(f)}</span>`).join('');
    const yes = priceOk(k.ya) ? `<b>${cents(k.ya)}</b>` : '—';
    const no = priceOk(k.na) ? `<b>${cents(k.na)}</b>` : '—';
    const venue = r.home ? 'home' : 'away';
    const st = r.strk || 0;
    const streak = st ? `<span class="${st > 0 ? 'up' : 'down'}">${st > 0 ? '+' : '−'}${Math.abs(st)}</span>` : '0';
    const live = isLive(G);
    const edge = live ? '<span class="edge live">Live</span>' : r.be == null ? '<span class="edge neg">—</span>'
      : `<span class="edge ${r.be > 0 ? 'pos' : 'neg'}">${signed(r.be * 100)}¢</span>`;
    const side = r.best && !live ? `<span class="side">${r.best === 'yes' ? 'Buy yes' : 'Buy no'} ${confHTML(r.conf)}</span>` : '';
    const dim = r.conf === 'low' ? ' dim' : '';
    const game = r.kind === 'game';
    let who = game
      ? `<span><span class="lg">${esc(G.away || '')} @ ${esc(G.home || '')}</span></span><span>${esc(fmtWhen(G))}</span>`
      : `<span><span class="lg">${esc(P.team || '')}</span> ${esc(P.pos || '')}</span><span>${vs} ${esc(r.opp)}, ${esc(fmtWhen(G))}</span>`;
    if (isK(r)) {
      const oppName = r.opp === G.away ? G.away_name : G.home_name;
      const at = r.home === false ? '@' : 'vs';
      who = `<span><span class="lg">${esc(lgLabel(r))}</span>${r.kind === 'player' && P.team ? ` ${esc(P.team)}` : ''}</span><span>${game ? '' : `${at} ${esc(oppName || r.opp)}, `}${esc(fmtWhen(G))}</span>`;
    }
    const margin = r.stat === 'win' || r.stat === 'margin';
    const venueChip = isK(r) && r.home == null ? chip(null, r.mid, 'Venue').replace('class="c-hr"', 'class="c-hr" title="Kalshi doesn’t say who’s at home for this sport"')
      : game ? chip(r.h.home, r.mid, 'Venue').replace('class="c-hr"', 'class="c-hr" title="Home team at home and away team on the road"')
        : chip(r.h[venue], r.mid, r.home ? 'Home' : 'Away');
    return `<div class="row prop-row${dim}" role="row" tabindex="0" data-id="${esc(r.id)}" aria-label="${esc(P.name)} ${esc(lineTxt(r))} ${esc(r.label)}">
      <div class="c-player" role="cell"><span class="pname">${esc(P.name)}</span>
        <div class="meta">${who}${injFlag(P.inj)}${flags}</div></div>
      <div class="c-prop" role="cell"><span class="line">${esc(lineTxt(r))}</span><span class="stat">${esc(r.short)}</span></div>
      <div class="c-kalshi" role="cell"><span class="px"><span>Yes</span> ${yes}</span><span class="px"><span>No</span> ${no}</span></div>
      <div class="c-strip" role="cell">${stripSVG(r.last10 || [], r.line, r.x10, r.stat)}</div>
      <div class="chips">
        ${chip(r.h.l5, r.mid, 'L5')}${chip(r.h.l10, r.mid, 'L10')}${chip(r.h.l20, r.mid, 'L20', ' wide')}${chip(r.h.szn, r.mid, 'Season')}${chip(r.h.h2h, r.mid, 'H2H')}${venueChip}
        <div class="c-streak" role="cell"><span class="lbl">Streak</span>${streak}</div>
      </div>
      <div class="c-avg" role="cell">${margin ? signedNum(r.avg10) : fmtNum(r.avg10)}<small title="${margin ? 'Average margin, last 10' : 'L10 average minus the line'}">${r.diff == null ? (r.stat === 'win' && r.avg10 != null ? 'margin' : '') : signed(r.diff)}</small></div>
      <div class="c-model" role="cell">${pct(r.p)}<small>market ${pct(r.mid)}</small></div>
      <div class="c-edge" role="cell">${edge}${side}</div>
    </div>`;
  }

  function render(append) {
    const rs = filtered();
    const shown = rs.slice(0, S.limit);
    $('#rows').innerHTML = shown.map(rowHTML).join('');
    for (const b of document.querySelectorAll('.row.head button[data-sort]')) b.setAttribute('aria-pressed', String(b.dataset.sort === S.sort));
    $('#more').hidden = rs.length <= S.limit;
    $('#more').textContent = `Show more (${rs.length - shown.length} left)`;
    const empty = $('#empty');
    empty.hidden = rs.length > 0;
    if (!rs.length) {
      empty.textContent = D.props.length ? 'Nothing matches these filters. Clear the search or pick another stat or game.'
        : 'Kalshi has no open player props or team bets right now. Lines usually go up on game day.';
    }
    if (!append) $('#board').setAttribute('aria-rowcount', String(rs.length));
  }

  // ------------------------------------------------------------ drawer
  function route() {
    const m = location.hash.match(/^#p=(.+)$/);
    if (m) {
      const id = decodeURIComponent(m[1]);
      if (byId.has(id)) { openProp(id, null, true); return; }
    }
    if (!$('#drawer').hidden) closeDrawer(true);
  }

  async function openProp(id, fromEl, fromRoute) {
    const r = byId.get(id);
    if (!r) return;
    if (fromEl) lastFocus = fromEl;
    if (!fromRoute && location.hash !== '#p=' + encodeURIComponent(id)) history.pushState(null, '', '#p=' + encodeURIComponent(id));
    drawerState = { r, stat: r.stat, line: r.line, range: 'l10', venue: 'all', pf: null };
    $('#scrim').hidden = false;
    $('#drawer').hidden = false;
    document.body.style.overflow = 'hidden';
    renderDrawer();
    $('#drawer').scrollTop = 0;
    $('#d-close') && $('#d-close').focus();
    try {
      let pf = pfCache.get(r.pid);
      if (!pf) {
        const res = await fetch(`data/p/${r.pid}.json?v=` + Math.floor(Date.now() / 120000));
        if (!res.ok) throw new Error('HTTP ' + res.status);
        pf = await res.json();
        pfCache.set(r.pid, pf);
      }
      if (drawerState && drawerState.r === r) { drawerState.pf = pf; renderDrawer(); }
    } catch (e) {
      if (drawerState && drawerState.r === r) { drawerState.err = true; renderDrawer(); }
    }
  }

  function closeDrawer(fromRoute) {
    $('#drawer').hidden = true;
    $('#scrim').hidden = true;
    $('#tip').hidden = true;
    document.body.style.overflow = '';
    drawerState = null;
    if (fromRoute !== true && location.hash.startsWith('#p=')) history.pushState(null, '', location.pathname + location.search);
    if (lastFocus && document.body.contains(lastFocus)) lastFocus.focus();
  }

  function currentProp() {
    const st = drawerState;
    const ladder = siblings(st.r, st.stat);
    return ladder.find((x) => x.line === st.line) || ladder[0] || st.r;
  }

  function siblings(r, stat) {
    const out = [];
    for (const x of byId.values()) if (x.pid === r.pid && x.gid === r.gid && x.stat === stat) out.push(x);
    return out.sort((a, b) => a.line - b.line);
  }

  function gamesFor(pf, r, range, venue, stat) {
    if (!pf) return [];
    let gs = pf.games.filter((g) => g.s && valOf(g, stat) != null && (g.date || '') < (r.G.date || '9999'));
    if (venue !== 'all') gs = gs.filter((g) => (venue === 'home') === !!g.home);
    if (range === 'l5') gs = gs.slice(0, 5);
    else if (range === 'l10') gs = gs.slice(0, 10);
    else if (range === 'l20') gs = gs.slice(0, 20);
    else if (range === 'szn') gs = gs.filter((g) => g.season === 'cur');
    else if (range === 'prev') gs = gs.filter((g) => g.season === 'prev');
    else if (range === 'h2h') gs = gs.filter((g) => g.opp === r.opp);
    return gs.slice().reverse();
  }

  function renderDrawer() {
    const st = drawerState;
    if (!st) return;
    const r0 = st.r, P = r0.P, G = r0.G;
    const r = currentProp();
    const order = ['win', 'draw', 'margin', 'tpts', 'total', 'btts'];
    const stats = [...new Set([...byId.values()].filter((x) => x.pid === r0.pid && x.gid === r0.gid).map((x) => x.stat))]
      .sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
    const ladder = siblings(r0, st.stat);
    const vs = r0.home ? 'vs' : '@';
    const team = isTeam(r0), game = r0.kind === 'game';
    const injNote = P.inj && P.inj.status ? `<div class="d-inj"><b>${esc(P.inj.status)}.</b> ${esc(P.inj.note || '')}</div>` : '';
    const total = G.total ? `Total ${fmtNum(G.total)}` : '';
    const espnLine = [G.line || '', total].filter(Boolean).join(', ');
    const sub = game ? `<span>${esc(G.away || '')} @ ${esc(G.home || '')}</span><span>${r0.lg.toUpperCase()} game total</span>`
      : team ? `<span>${esc(P.team || '')}</span><span>${r0.lg.toUpperCase()} team bets</span>`
        : `<span>${esc(P.team || '')} ${esc(P.pos || '')}</span><span>${r0.lg.toUpperCase()}</span>`;
    const where = game ? `<span><b>${esc(G.away || '')} @ ${esc(G.home || '')}</b>, ${esc(fmtWhen(G))}</span>`
      : `<span><b>${vs} ${esc(r0.opp)}</b>, ${esc(fmtWhen(G))}</span>`;
    let lineInfo = team ? (espnLine ? `Betting line: ${espnLine}` : '') : [total, G.line || ''].filter(Boolean).join(', ');
    let sub2 = sub, whereTop = where;
    if (isK(r0)) {   // the other sports: Kalshi's names and listing order, no ESPN line
      const meta = `<span>${esc(lgLabel(r0))}</span><span>${esc(GROUP_CHIPS.find(([k]) => k === r0.grp)?.[1] || '')}</span>`;
      const oppName = r0.opp === G.away ? G.away_name : G.home_name;
      sub2 = meta;
      whereTop = game ? `<span><b>${esc(G.away_name)} ${esc(G.sep)} ${esc(G.home_name)}</b>, ${esc(fmtWhen(G))}</span>`
        : `<span><b>${r0.home === false ? '@' : 'vs'} ${esc(oppName || r0.opp)}</b>, ${esc(fmtWhen(G))}</span>`;
      lineInfo = '';
    }

    let html = `<div class="d-top"><div><h2 id="d-name">${esc(P.name)}</h2>
        <div class="d-sub">${sub2}</div></div>
        <button class="close" id="d-close" type="button" aria-label="Close"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13"/></svg></button></div>
      <div class="d-game">${whereTop}<span>${esc(lineInfo)}</span></div>
      ${injNote}
      <div class="tabs" role="group" aria-label="${team ? 'Bet' : 'Stat'}">${stats.map((s) => `<button type="button" data-stat="${esc(s)}" aria-pressed="${s === st.stat}">${esc(statLabel(r0.lg, s, r0))}</button>`).join('')}</div>
      <div class="ladder-pick" role="group" aria-label="Kalshi line">${ladder.map((x) => `<button type="button" data-line="${x.line}" aria-pressed="${x.line === r.line}">${esc(lineTxt(x))}<small>${priceOk(x.k.ya) ? cents(x.k.ya) : '—'}</small></button>`).join('')}</div>
      ${team ? `<p class="note means">${meansHTML(r)}</p>` : ''}`;

    if (!st.pf) {
      html += st.err ? `<p class="note">Couldn’t load ${team ? 'the results' : 'this player’s game log'}. Close this panel and try again.</p>` : '<p class="note">Loading game log…</p>';
      $('#d-inner').innerHTML = html;
      bindDrawer();
      return;
    }

    const gs = gamesFor(st.pf, r, st.range, st.venue, st.stat);
    const nHurt = gs.filter(isHurt).length;
    const vals = gs.filter((g) => !isHurt(g)).map((g) => valOf(g, st.stat));
    const hits = vals.filter((v) => v >= r.line).length;
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    const sorted = vals.slice().sort((a, b) => a - b);
    const med = sorted.length ? (sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2) : null;
    const rangeName = (RANGES.find(([k]) => k === st.range) || [])[1];
    const ranges = isK(r0) ? RANGES.filter(([k]) => k !== 'prev') : RANGES;   // Kalshi's history is this season only
    const venues = game || (isK(r0) && r0.home == null) ? '' : `<div class="seg" role="group" aria-label="Venue">${[['all', 'All'], ['home', 'Home'], ['away', 'Away']].map(([k, n]) => `<button type="button" data-venue="${k}" aria-pressed="${k === st.venue}">${n}</button>`).join('')}</div>`;
    const where2 = `${esc(rangeName)}${st.venue !== 'all' ? ', ' + st.venue : ''}${game ? ', both teams’ games' : ''}`;
    const margin = r.stat === 'win' || r.stat === 'margin';
    const avgTxt = avg == null ? null : Math.round(avg * 10) / 10;
    let subTxt = margin ? `Average margin ${signedNum(avgTxt)}, median ${signedNum(med)}` : `Average ${fmtNum(avgTxt)}, median ${fmtNum(med)}`;
    if (r.stat === 'draw' || r.stat === 'btts') subTxt = '';
    else if (r.stat === 'win' && isK(r) && !gs.some((g) => g.s.margin != null)) {   // only wins and losses are known
      const w = gs.filter((g) => g.res === 'W').length, l = gs.filter((g) => g.res === 'L').length, d = gs.filter((g) => g.res === 'D').length;
      subTxt = `Record ${w}-${l}${d ? '-' + d : ''}`;
    }
    const heroLab = team ? `${teamHitText(r, hits, vals.length)} (${where2})`
      : `hit ${BINARY.has(r.stat) ? '' : r.line + '+ '}${esc(statLabel(r.lg, st.stat).toLowerCase())} in ${hits} of ${vals.length} games (${where2})${nHurt ? `, not counting ${nHurt} game${nHurt > 1 ? 's' : ''} he left hurt` : ''}`;
    const legend = team ? teamLegend(r)
      : `<span><i class="lh"></i>Hit</span><span><i class="lm"></i>Missed</span>${nHurt ? '<span><i class="lx"></i>Left hurt, not counted</span>' : ''}<span><i class="ll"></i>${BINARY.has(r.stat) ? 'Yes' : r.line + '+'} line</span>`;

    html += `<div class="seg-row">
        <div class="seg" role="group" aria-label="Games">${ranges.map(([k, n]) => `<button type="button" data-range="${k}" aria-pressed="${k === st.range}">${n}</button>`).join('')}</div>
        ${venues}
      </div>
      <div class="hero"><span class="big">${vals.length ? pct(hits / vals.length) : '—'}</span>
        <span class="lab">${heroLab}</span>
        <span class="sub">${subTxt}</span></div>
      <div class="chart" id="chart"></div>
      <div class="legend">${legend}</div>`;

    html += ladderHTML(ladder, r);
    html += team ? teamModelHTML(r, st.pf) : modelHTML(r, st.pf);
    html += team ? teamContextHTML(r, st.pf) : contextHTML(r, st.pf);
    html += team ? teamLogHTML(st.pf, r, st.stat) : logHTML(st.pf, r, st.stat);
    html += `<div class="cta"><a href="${esc(kalshiUrl(r.id))}" target="_blank" rel="noopener">Open on Kalshi</a></div>
      <p class="note">${isLive(G) ? 'This game has started, so these prices and the edge are from before the start and don’t apply now. ' : ''}Prices here are from the last update, ${esc(ago(D.updated))}. Check the live price on Kalshi before you trade. ${isK(r) ? 'Kalshi settles on the official result; read the market’s rules on Kalshi for overtime, retirements and cancellations. These results come from Kalshi’s own settled markets, which start in late summer.' : team ? 'Kalshi settles team bets on the final score, overtime included.' : 'If a player doesn’t play, Kalshi settles the market at a fair price instead of yes or no.'}</p>`;
    const hadFocus = $('#drawer').contains(document.activeElement) || document.activeElement === document.body;
    $('#d-inner').innerHTML = html;
    renderChartOnly(gs);
    bindDrawer();
    if (hadFocus && !$('#drawer').contains(document.activeElement)) $('#d-close').focus({ preventScroll: true });
  }

  function renderChartOnly(gs) {
    const st = drawerState;
    if (!st || !st.pf) return;
    const r = currentProp();
    gs = gs || gamesFor(st.pf, r, st.range, st.venue, st.stat);
    const el = $('#chart');
    if (!el) return;
    el.innerHTML = chartSVG(gs, st.stat, r.line, el.clientWidth || 600);
    el.onmousemove = el.onfocusin = (e) => {
      const g = e.target.closest('g.b');
      if (!g) { $('#tip').hidden = true; return; }
      const game = gs[+g.dataset.i];
      showTip(e, game, st.stat, r);
    };
    el.onmouseleave = el.onfocusout = () => { $('#tip').hidden = true; };
  }

  function showTip(e, game, stat, r) {
    const tip = $('#tip');
    const v = valOf(game, stat);
    if (isTeam(r)) {
      const s = game.s, u = unitOf(r), ot = game.ot ? ` ${game.ot}` : '';
      const opp = esc(game.oppn || game.opp);
      const bits = [];
      if (s.margin != null) bits.push(`Margin ${signedNum(s.margin)}`);
      if (s.total != null) bits.push(`${fmtNum(s.total)} total ${u}`);
      if (s.btts != null) bits.push(s.btts ? 'Both scored' : 'Not both scored');
      const verdict = v >= r.line ? '(hit)' : '(missed)';
      const head = r.kind === 'game'
        ? `<b>${r.stat === 'total' ? `${fmtNum(s.total)} total ${u}` : esc(game.res + ' ' + (game.score || ''))}</b> ${verdict}<br>${esc(game.team || '')} ${game.at === false ? '@' : 'vs'} ${opp}, ${md(game.date)}<br><span class="muted">${esc(game.team || '')} ${esc(game.res)} ${esc(game.score || '')}${ot}</span>`
        : `<b>${esc(game.res)} ${esc(game.score || '')}${ot}</b> ${verdict}<br>${game.home === false || (!isK(r) && !game.home) ? '@' : 'vs'} ${opp}, ${md(game.date)}${bits.length ? `<br><span class="muted">${bits.join(', ')}</span>` : ''}`;
      tip.innerHTML = head + (game.post ? '<br><span class="muted">Playoffs</span>' : '') + (game.season === 'prev' ? '<br><span class="muted">Last season</span>' : '');
    } else {
      const vol = r.lg === 'nba' ? `${fmtNum(game.s.min)} min` : r.lg === 'nhl' ? `${fmtNum(game.s.toi)} min TOI` : '';
      tip.innerHTML = `<b>${fmtNum(v)} ${esc(statLabel(r.lg, stat).toLowerCase())}</b> ${isHurt(game) ? '(left hurt, not counted)' : v >= r.line ? '(hit)' : '(missed)'}<br>` +
        `${game.home ? 'vs' : '@'} ${esc(game.opp)}, ${md(game.date)}${game.res ? `, ${esc(game.res)} ${esc(game.score || '')}` : ''}` +
        (vol ? `<br><span class="muted">${vol}</span>` : '') + (game.post ? '<br><span class="muted">Playoffs</span>' : '') +
        (game.inj ? `<br><span class="${isHurt(game) ? 'warn' : 'muted'}">${esc(game.inj.why)}</span>` : '');
    }
    tip.hidden = false;
    let x, y;
    if (e.type === 'focusin') {
      const b = e.target.getBoundingClientRect();
      x = b.left + b.width / 2; y = b.top;
    } else { x = e.clientX; y = e.clientY; }
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x - w / 2)) + 'px';
    tip.style.top = Math.max(8, y - h - 12) + 'px';
  }

  function niceStep(max, integer) {
    const raw = Math.max(max, 1e-6) / 4;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const m = raw / p;
    let s = (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
    if (integer) s = Math.max(1, Math.round(s));
    return s;
  }

  function chartSVG(gs, stat, line, width) {
    const n = gs.length;
    if (!n) return '<p class="note">No games in this range yet.</p>';
    const r0 = drawerState.r, team = isTeam(r0);
    const H = window.innerWidth <= 760 ? 200 : 230;
    const top = 22, bottom = n <= 12 ? 36 : 22, left = 34, right = 6;
    const plotW = Math.max(120, width - left - right), plotH = H - top - bottom;
    const vals = gs.map((g) => valOf(g, stat));
    const R = barRange(stat, vals, line, 0);
    const step = niceStep((R.hi - R.lo) * 1.1, true);
    const ymin = R.lo < 0 ? Math.floor((R.lo * 1.05) / step) * step : R.base > 0 ? Math.floor(R.lo / step) * step : 0;
    const ymax = Math.ceil((R.hi + (R.hi - ymin) * 0.08) / step) * step;
    const y = (v) => top + plotH - ((Math.max(ymin, v) - ymin) / (ymax - ymin)) * plotH;
    const base = R.base > 0 ? ymin : 0, y0 = y(base);   // totals start at the axis floor, everything else at zero
    const slot = plotW / n;
    const bw = Math.max(3, Math.min(24, slot - 2));
    const thrY = y(line - 0.5);
    const thrLab = !team ? (BINARY.has(stat) ? 'Yes' : line + '+') : stat === 'win' ? 'Win' : stat === 'draw' || stat === 'btts' ? 'Yes' : half(line);
    let labels = '';
    let s = `<svg viewBox="0 0 ${width} ${H}" width="${width}" height="${H}" role="img" aria-label="${esc(statLabel(r0.lg, stat))} by game, ${vals.filter((v) => v >= line).length} of ${n} ${team ? 'hit ' + esc(lineTxt(currentProp())) : 'at or above ' + line}">`;
    for (let t = ymin; t <= ymax + 1e-9; t += step) {
      const yy = y(t);
      s += `<line class="grid${t === 0 && ymin < 0 ? ' zero' : ''}" x1="${left}" x2="${width - right}" y1="${yy}" y2="${yy}"/>`;
      if (Math.abs(yy - thrY) > 11) s += `<text class="axis" x="${left - 6}" y="${yy + 4}" text-anchor="end">${team && stat !== 'tpts' && stat !== 'total' ? signedNum(t) : fmtNum(t)}</text>`;
    }
    gs.forEach((g, i) => {
      const v = vals[i];
      const cx = left + slot * i + slot / 2;
      const yv = y(v), h = Math.max(2, Math.abs(y0 - yv));
      const hit = v >= line;
      const cls = isHurt(g) ? 'hurt' : hit ? 'hit' : 'miss';
      const up = v >= base;
      s += `<g class="b" data-i="${i}"><path class="bar ${cls}" d="${up ? roundTop(cx - bw / 2, Math.min(yv, y0 - 2), bw, h, 4) : roundBottom(cx - bw / 2, y0, bw, h, 4)}"/>`;
      const shown = team && (stat === 'win' || stat === 'margin') ? signedNum(v) : fmtNum(v);
      if (n <= 16) labels += `<text class="val" x="${cx}" y="${up ? Math.min(yv, y0 - 2) - 5 : y0 + h + 12}" text-anchor="middle">${shown}</text>`;
      const who = r0.kind === 'game' ? esc(g.team || '') : `${g.home === false || (!isK(r0) && !g.home) ? '@' : ''}${esc(g.opp)}`;
      if (n <= 12) {
        s += `<text class="axis" x="${cx}" y="${H - bottom + 15}" text-anchor="middle">${who}</text>`;
        s += `<text class="axis" x="${cx}" y="${H - bottom + 29}" text-anchor="middle">${md(g.date)}</text>`;
      }
      const vsTxt = r0.kind === 'game' ? `${esc(g.team || '')} ${g.at === false ? 'at' : 'vs'} ${esc(g.opp)}` : `${g.home === false || (!isK(r0) && !g.home) ? 'at' : 'vs'} ${esc(g.opp)}`;
      s += `<rect class="hitbox" x="${left + slot * i}" y="${top - 18}" width="${slot}" height="${plotH + bottom + 18}" tabindex="0" aria-label="${shown} ${vsTxt} on ${md(g.date)}, ${isHurt(g) ? 'left hurt, not counted' : hit ? 'hit' : 'missed'}"/></g>`;
    });
    if (n > 12) {
      const k = Math.ceil(n / 7);
      gs.forEach((g, i) => { if ((n - 1 - i) % k === 0) s += `<text class="axis" x="${left + slot * i + slot / 2}" y="${H - 6}" text-anchor="middle">${md(g.date)}</text>`; });
    }
    s += `<line class="thr" x1="${left}" x2="${width - right}" y1="${thrY}" y2="${thrY}"/>`;
    s += `<text class="thr-lab" x="${left - 6}" y="${thrY + 4}" text-anchor="end">${thrLab}</text>`;
    return s + `<g aria-hidden="true">${labels}</g></svg>`;
  }

  function ladderHTML(ladder, cur) {
    if (!ladder.length) return '';
    const rows = ladder.map((x) => {
      const edge = x.be == null ? '—' : `<span class="${x.be > 0 ? 'pos' : 'neg'}">${signed(x.be * 100)}¢ ${x.best === 'yes' ? 'yes' : 'no'}</span>`;
      return `<tr class="${x === cur ? 'is-sel' : ''}" data-line="${x.line}"><td>${esc(lineTxt(x))}</td><td>${priceOk(x.k.ya) ? cents(x.k.ya) : '—'}</td><td>${priceOk(x.k.na) ? cents(x.k.na) : '—'}</td>` +
        `<td>${pct(x.p)}</td><td>${pct(rate(x.h.l10))}</td><td>${pct(rate(x.h.szn))}</td><td>${edge}</td></tr>`;
    }).join('');
    return `<div class="sec"><h3>Every Kalshi line for this ${isTeam(cur) ? 'bet' : 'stat'}</h3><div class="scroll-x"><table class="tbl">
      <thead><tr><th>Line</th><th>Yes costs</th><th>No costs</th><th>Model</th><th>L10</th><th>Season</th><th>Edge</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  // ------------------------------------------------------------ team bets in the drawer
  function teamName(r) {
    if (r.kind === 'game') return '';
    const n = r.P.name || r.P.team || '';
    return n;
  }

  function kMeans(r) {   // the other sports: Kalshi's names, no "the" ("Arsenal wins")
    const t = esc(teamName(r)), u = unitOf(r), soccer = r.grp === 'soccer';
    if (r.sl) {
      const what = esc(r.sl.toLowerCase()), no = r.line - 1 === 0 ? 'none' : `${r.line - 1} or fewer`;
      if (r.kind === 'game') return `<b>Yes</b> if the game has ${r.line} or more ${what} between both teams. <b>No</b> if ${no}.`;
      return `<b>Yes</b> if ${t} gets ${r.line} or more ${what}. <b>No</b> if ${no}.${r.kind === 'player' ? ' Kalshi’s rules cover what happens if he doesn’t play.' : ''}`;
    }
    if (r.stat === 'win') return `<b>Yes</b> if ${t} wins. <b>No</b> if ${t} loses${soccer ? ' or draws' : ''}.`;
    if (r.stat === 'draw') return '<b>Yes</b> if it ends in a draw after 90 minutes plus stoppage time. <b>No</b> if either team wins.';
    if (r.stat === 'btts') return '<b>Yes</b> if both teams score. <b>No</b> if at least one doesn’t.';
    if (r.stat === 'margin') return `<b>Yes</b> if ${t} wins by ${r.line} or more ${u} (−${half(r.line)}). <b>No</b> if ${t} loses or wins by ${r.line - 1} or less.`;
    if (r.stat === 'tpts') return `<b>Yes</b> if ${t} scores ${r.line} or more ${u} (over ${half(r.line)}). <b>No</b> if ${r.line - 1} or fewer.`;
    return `<b>Yes</b> if the game has ${r.line} or more total ${u} (over ${half(r.line)}). <b>No</b> if ${r.line - 1} or fewer.`;
  }

  function meansHTML(r) {
    if (isK(r)) return kMeans(r);
    const t = esc(teamName(r)), u = UNIT[r.lg], G = r.G;
    const other = r.home ? G.away : G.home;
    if (r.stat === 'win') return `<b>Yes</b> if the ${t} win, overtime included. <b>No</b> if they lose.${r.lg === 'nfl' ? ' A tie pays 50¢ either way.' : ''}`;
    if (r.stat === 'margin') return `<b>Yes</b> if the ${t} win by ${r.line} or more (−${half(r.line)}). <b>No</b> if they lose or win by ${r.line - 1} or less, the same as ${esc(other || 'the other team')} +${half(r.line)}.`;
    if (r.stat === 'tpts') return `<b>Yes</b> if the ${t} score ${r.line} or more ${u} (over ${half(r.line)}). <b>No</b> if they score ${r.line - 1} or fewer.`;
    return `<b>Yes</b> if both teams score ${r.line} or more ${u} combined (over ${half(r.line)}). <b>No</b> if ${r.line - 1} or fewer.`;
  }

  function teamHitText(r, hits, n) {
    const u = unitOf(r);
    if (r.sl) return `got ${r.line}+ ${r.sl.toLowerCase()} in ${hits} of ${n} games`;
    if (r.stat === 'win') return `won ${hits} of ${n} games`;
    if (r.stat === 'draw') return `ended in a draw in ${hits} of ${n} games`;
    if (r.stat === 'btts') return `both teams scored in ${hits} of ${n} games`;
    if (r.stat === 'margin') return `won by ${r.line}+ (covered −${half(r.line)}) in ${hits} of ${n} games`;
    if (r.stat === 'tpts') return `scored ${r.line}+ ${u} (over ${half(r.line)}) in ${hits} of ${n} games`;
    return `went over ${half(r.line)} total ${u} in ${hits} of ${n} games`;
  }

  function teamLegend(r) {
    const [a, b, l] = r.stat === 'draw' ? ['Draw', 'Not a draw', 'Yes'] : r.stat === 'btts' ? ['Both scored', 'Not both', 'Yes']
      : r.stat === 'win' ? ['Won', 'Lost', 'Won by 1+']
      : r.stat === 'margin' ? ['Covered', 'Didn’t cover', `Won by ${half(r.line)}`]
        : ['Over', 'Under', `${half(r.line)} line`];
    return `<span><i class="lh"></i>${a}</span><span><i class="lm"></i>${b}</span><span><i class="ll"></i>${l}</span>`;
  }

  function teamModelHTML(r, pf) {
    const det = (pf.props || {})[r.id];
    if (!det || r.p == null) return `<div class="sec"><h3>How the model sees it</h3><p>Not enough games to model this one yet.</p></div>`;
    const li = (det.steps || []).map(([a, b, c]) => `<li><span>${esc(a)}${c ? `<br><small class="note">${esc(c)}</small>` : ''}</span><b>${esc(b)}</b></li>`).join('');
    const yesFee = priceOk(r.k.ya) ? 0.07 * r.k.ya * (1 - r.k.ya) : null;
    const noFee = priceOk(r.k.na) ? 0.07 * r.k.na * (1 - r.k.na) : null;
    let edgeLine = '';
    if (r.best === 'yes' && yesFee != null) edgeLine = `Buying yes at ${cents(r.k.ya)} plus about ${(yesFee * 100).toFixed(1)}¢ fee: ${signed(r.e.yes * 100)}¢ expected per $1 contract`;
    else if (r.best === 'no' && noFee != null) edgeLine = `Buying no at ${cents(r.k.na)} plus about ${(noFee * 100).toFixed(1)}¢ fee: ${signed(r.e.no * 100)}¢ expected per $1 contract`;
    const gap = r.p != null && r.mid != null ? r.p - r.mid : null;
    const elo = det.m === 'elo';
    const blendWhy = det.k == null ? '' : elo
      ? `Moves ${Math.round(det.k * 100)}% of the way from Kalshi’s price toward the ratings, less for long shots, for sides with few results and when the ratings have predicted this league poorly. They only know who won, not injuries or lineups, so the price does most of the work.`
      : isK(r)
      ? `Moves ${Math.round(det.k * 100)}% of the way from Kalshi’s price toward the trend estimate, less for long shots. Past results alone say little about tonight, so the price does most of the work.`
      : r.flags.includes('Check news')
      ? `The stats and the market disagree by ${Math.round(Math.abs(gap) * 100)} points. With team bets that usually means something the scores don’t show, like a star out or resting, so this barely moves off Kalshi’s price.`
      : `Moves ${Math.round(det.k * 100)}% of the way from Kalshi’s price toward the stats model. Team bets are Kalshi’s busiest markets, so the price already knows most of what the scores know.`;
    const blendLi = r.pb == null ? '' : `<li><span>Used for the edge<br><small class="note">${esc(blendWhy)}</small></span><b>${pct(r.pb)}</b></li>`;
    return `<div class="sec"><h3>How the model sees it</h3><ul class="steps">${li}
      <li class="total"><span>${elo ? 'Ratings model' : isK(r) ? 'Trend model' : 'Stats model'}: chance of yes (${esc(lineTxt(r))})</span><b>${pct(r.p)}</b></li>
      <li><span>Kalshi’s price implies</span><b>${pct(r.mid)}</b></li>${blendLi}</ul>
      ${edgeLine ? `<p class="note">${esc(edgeLine)}. ${r.be > 0 ? 'Positive means the model thinks this side is underpriced.' : 'Negative means neither side looks underpriced after the fee.'}</p>` : ''}
      ${r.flags.length ? `<p class="note">Heads up: ${esc(r.flags.join(', ').toLowerCase())}${det.key_out && det.key_out.length ? ` (${esc(det.key_out.join(', '))})` : ''}.</p>` : ''}</div>`;
  }

  function kContextHTML(r, pf) {
    const k = r.k;
    const n = (pf.games || []).filter((g) => (g.date || '') < (r.G.date || '9999')).length;
    const first = (pf.games || []).slice(-1)[0];
    const cards = [
      ['Kalshi market', k.vol ? `${Math.round(k.vol).toLocaleString()} traded` : 'No trades yet',
        priceOk(k.ya) && priceOk(k.yb) ? `Bid ${cents(k.yb)}, ask ${cents(k.ya)}` : 'One side has no orders'],
      ['History', `${n} game${n === 1 ? '' : 's'}`, first ? `On Kalshi since ${md(first.date)}` : 'None settled on Kalshi yet'],
    ];
    return `<div class="sec"><h3>Context</h3><div class="ctx">${cards.map(([a, b, c]) => `<div><span>${esc(a)}</span><b>${esc(b)}</b><small>${esc(c)}</small></div>`).join('')}</div></div>`;
  }

  function kLogHTML(pf, r, stat) {
    const games = pf.games.filter((g) => (g.date || '') < (r.G.date || '9999')).slice(0, 20);
    if (!games.length) return `<div class="sec"><h3>Results</h3><p class="note">No settled games on Kalshi yet for ${r.kind === 'game' ? 'either team' : r.kind === 'player' ? 'this player' : 'this team'}.</p></div>`;
    const game = r.kind === 'game', u = unitOf(r);
    const colName = { win: 'Margin', margin: 'Margin', tpts: u === 'points' ? 'PTS' : 'Scored', total: 'Total', draw: 'Draw', btts: 'Both scored' }[stat] || r.sl || stat;
    const body = games.map((g) => {
      const v = valOf(g, stat);
      const known = v != null;
      const hit = known && v >= r.line;
      const txt = !known ? '—' : stat === 'draw' || stat === 'btts' ? (v ? 'Yes' : 'No') : stat === 'win' && g.s.margin == null ? '' : (stat === 'win' || stat === 'margin') ? signedNum(v) : fmtNum(v);
      const dot = known ? `<span class="dot ${hit ? 'hit' : 'miss'}" role="img" aria-label="${hit ? 'hit' : 'missed'}"></span>` : '';
      const vs = g.home === true || g.at === true ? 'vs' : g.home === false || g.at === false ? '@' : 'vs';
      return `<tr><td>${md(g.date)}</td>${game ? `<td>${esc(g.team || '')}</td>` : ''}<td>${vs} ${esc(g.oppn || g.opp)}</td><td>${esc(g.res || '')} ${esc(g.score || '')}</td><td class="on">${txt}${dot}</td></tr>`;
    }).join('');
    const head = `<tr><th>Date</th>${game ? '<th>Team</th>' : ''}<th>Opp</th><th>Result</th><th>${esc(colName)}</th></tr>`;
    return `<div class="sec"><h3>${game ? 'Both teams’ games' : 'Results'}</h3><p class="note">Last ${games.length} games settled on Kalshi${game ? ', a meeting between them counted once' : ''}. The dot marks whether this bet would have won. A dash means Kalshi didn’t list that kind of bet for the game.</p><div class="scroll-x"><table class="tbl">${head}${body}</table></div></div>`;
  }

  function teamContextHTML(r, pf) {
    if (isK(r)) return kContextHTML(r, pf);
    const det = (pf.props || {})[r.id] || {};
    const G = r.G, cards = [];
    const restTxt = (d) => (d == null ? '—' : d === 1 ? 'Back-to-back' : `${d} days`);
    const tA = r.kind === 'game' ? G.home : r.P.team, tB = r.kind === 'game' ? G.away : r.opp;
    cards.push([`${tA} rest`, restTxt(det.rest), 'Days since their last game']);
    cards.push([`${tB} rest`, restTxt(det.rest_o), 'Days since their last game']);
    const k = r.k;
    cards.push(['Kalshi market', k.vol ? `${Math.round(k.vol).toLocaleString()} traded` : 'No trades yet',
      priceOk(k.ya) && priceOk(k.yb) ? `Bid ${cents(k.yb)}, ask ${cents(k.ya)}` : 'One side has no orders']);
    let html = `<div class="sec"><h3>Context</h3><div class="ctx">${cards.map(([a, b, c]) => `<div><span>${esc(a)}</span><b>${esc(b)}</b><small>${esc(c)}</small></div>`).join('')}</div></div>`;
    const inj = pf.injuries || {};
    const teams = [tA, tB].filter((t) => t && inj[t]);
    if (teams.length) {
      const list = (t) => {
        const xs = inj[t] || [];
        if (!xs.length) return '<p class="note">Nobody listed.</p>';
        return `<ul class="injl">${xs.map((x) => `<li class="${x.key ? 'is-key' : ''}"><span><b>${esc(x.name)}</b> ${esc(x.pos || '')}${x.key ? ' <span class="flag inj">Key player</span>' : ''}<small>${esc(x.use)}${x.missed ? `, missed the last ${x.missed === 1 ? 'game' : x.missed + ' games'}` : ''}</small></span>` +
          `<span class="st ${x.out ? 'out' : ''}">${esc(x.status)}${x.type ? `<small>${esc(x.type)}</small>` : ''}</span></li>`).join('')}</ul>`;
      };
      html += `<div class="sec"><h3>Injury report</h3><div class="injt">${teams.map((t) => `<div><h4>${esc(t)}</h4>${list(t)}</div>`).join('')}</div>
        <p class="note">From ESPN. Key players are the ones with big minutes or production this season. Past results include games they played, so a key player out tonight can make a team’s trends look better than tonight’s lineup.</p></div>`;
    }
    return html;
  }

  function teamLogHTML(pf, r, stat) {
    if (isK(r)) return kLogHTML(pf, r, stat);
    const games = pf.games.filter((g) => (g.date || '') < (r.G.date || '9999')).slice(0, 20);
    if (!games.length) return '';
    const game = r.kind === 'game';
    const on = stat === 'win' ? 'margin' : stat;
    const cols = game ? [['total', 'Total']] : [['tpts', r.lg === 'nhl' ? 'GF' : 'PTS'], ['opp_pts', r.lg === 'nhl' ? 'GA' : 'OPP'], ['margin', 'Margin'], ['total', 'Total']];
    const head = `<tr><th>Date</th>${game ? '<th>Team</th>' : ''}<th>Opp</th><th>Result</th>${cols.map(([, n]) => `<th>${esc(n)}</th>`).join('')}</tr>`;
    const body = games.map((g) => {
      const tds = cols.map(([k]) => {
        const v = g.s[k];
        const txt = k === 'margin' ? signedNum(v) : fmtNum(v);
        if (k !== on) return `<td>${txt}</td>`;
        const hit = valOf(g, stat) >= r.line;
        return `<td class="on">${txt}<span class="dot ${hit ? 'hit' : 'miss'}" role="img" aria-label="${hit ? 'hit' : 'missed'}"></span></td>`;
      }).join('');
      const vs = game ? (g.at ? 'vs' : '@') : (g.home ? 'vs' : '@');
      return `<tr><td>${md(g.date)}${g.season === 'prev' ? ' ’' + String(Number((g.date || '').slice(2, 4))) : ''}</td>${game ? `<td>${esc(g.team || '')}</td>` : ''}<td>${vs} ${esc(g.opp)}</td><td>${esc(g.res || '')} ${esc(g.score || '')}${g.ot ? ' ' + esc(g.ot) : ''}</td>${tds}</tr>`;
    }).join('');
    const what = game ? `the game went over ${half(r.line)}` : r.stat === 'win' ? 'they won' : r.stat === 'margin' ? `they covered −${half(r.line)}` : `they went over ${half(r.line)}`;
    return `<div class="sec"><h3>${game ? 'Both teams’ games' : 'Results'}</h3><p class="note">Last ${games.length} games${game ? ' of either team, a meeting between them counted once' : ''}. The dot marks whether ${what}. Scores are ${game ? 'the team listed first' : 'theirs'} first.</p><div class="scroll-x"><table class="tbl">${head}${body}</table></div></div>`;
  }

  function modelHTML(r, pf) {
    const det = (pf.props || {})[r.id];
    if (!det || r.p == null) return `<div class="sec"><h3>How the model sees it</h3><p>Not enough games to model this one yet.</p></div>`;
    const label = statLabel(r.lg, r.stat).toLowerCase();
    const mu = det.mu || {};
    const items = [];
    if (BINARY.has(r.stat)) {
      items.push(['How often he gets one', `${pct(mu.base)}`, `${mu.n_cur} games this season, ${mu.n_prev} last season`]);
    } else {
      items.push(['Typical game', `${fmtNum(mu.base)}`, `This season with recent games counted more, blended with last season (${mu.n_cur} + ${mu.n_prev} games)`]);
      for (const [lab, f] of det.factors || []) {
        let why = '';
        if (lab === 'Matchup' && det.matchup) {
          const m = det.matchup, grp = posGroup(r.lg, r.stat === 'saves' ? 'G' : r.P.pos);
          const who = r.stat === 'saves' ? 'saves to opposing goalies' : `${label} to ${POS_LABEL[grp] || 'this position'}`;
          why = `${r.opp} gives up ${fmtNum(m.allowed)} ${who} per game, ${ordinal(m.rank)} most of ${m.of} (league average ${fmtNum(m.avg)})`;
        } else if (lab === 'Home/away') why = r.home ? 'His numbers at home vs overall' : 'His numbers on the road vs overall';
        else if (lab === 'Game total') why = `Betting total ${fmtNum(det.total)} vs ${fmtNum(det.lg_total)} league average`;
        else if (lab === 'Back-to-back') why = 'Second game in two days';
        items.push([lab, `${signed((f - 1) * 100)}%`, why]);
      }
      items.push(['Projection', `${fmtNum(mu.mu)}`, `Spread of about ±${fmtNum(mu.sd)} game to game`]);
    }
    const lineTxt = BINARY.has(r.stat) ? 'Chance of yes' : `Chance of ${r.line}+`;
    const yesFee = priceOk(r.k.ya) ? 0.07 * r.k.ya * (1 - r.k.ya) : null;
    const noFee = priceOk(r.k.na) ? 0.07 * r.k.na * (1 - r.k.na) : null;
    let edgeLine = '';
    if (r.best === 'yes' && yesFee != null) edgeLine = `Buying yes at ${cents(r.k.ya)} plus about ${(yesFee * 100).toFixed(1)}¢ fee: ${signed(r.e.yes * 100)}¢ expected per $1 contract`;
    else if (r.best === 'no' && noFee != null) edgeLine = `Buying no at ${cents(r.k.na)} plus about ${(noFee * 100).toFixed(1)}¢ fee: ${signed(r.e.no * 100)}¢ expected per $1 contract`;
    const li = items.map(([a, b, c]) => `<li><span>${esc(a)}${c ? `<br><small class="note">${esc(c)}</small>` : ''}</span><b>${esc(b)}</b></li>`).join('');
    const gap = r.p != null && r.mid != null ? r.p - r.mid : null;
    const bigGap = r.flags.includes('Check news');
    const blendWhy = det.k == null ? '' : bigGap
      ? `The stats and the market disagree by ${Math.round(Math.abs(gap) * 100)} points. A gap that big usually means news the box scores don’t have yet, like an injury or a lineup change, so this barely moves off Kalshi’s price.`
      : `Moves ${Math.round(det.k * 100)}% of the way from Kalshi’s price toward the stats model. The market already knows most of what the stats know.`;
    const blendLi = r.pb == null ? '' : `<li><span>Used for the edge<br><small class="note">${esc(blendWhy)}</small></span><b>${pct(r.pb)}</b></li>`;
    return `<div class="sec"><h3>How the model sees it</h3><ul class="steps">${li}
      <li class="total"><span>Stats model: ${esc(lineTxt.toLowerCase())}</span><b>${pct(r.p)}</b></li>
      <li><span>Kalshi’s price implies</span><b>${pct(r.mid)}</b></li>${blendLi}</ul>
      ${edgeLine ? `<p class="note">${esc(edgeLine)}. ${r.be > 0 ? 'Positive means the model thinks this side is underpriced.' : 'Negative means neither side looks underpriced after the fee.'}</p>` : ''}
      ${r.flags.length ? `<p class="note">Heads up: ${esc(r.flags.join(', ').toLowerCase())}.</p>` : ''}</div>`;
  }

  function contextHTML(r, pf) {
    const det = (pf.props || {})[r.id] || {};
    const cards = [];
    if (det.rest != null) cards.push(['Rest', det.b2b ? 'Back-to-back' : `${det.rest} days`, det.b2b ? 'Played yesterday' : 'Since his last game']);
    if (det.vol) cards.push([VOLUME[det.vol.key] || 'Usage', `${fmtNum(det.vol.l3)} last 3`, `${fmtNum(det.vol.szn)} this season`]);
    if (det.matchup) {
      const m = det.matchup;
      cards.push(['Opponent', `${ordinal(m.rank)} most allowed`, `Out of ${m.of}, from ${m.n} games`]);
    }
    const k = r.k;
    cards.push(['Kalshi market', k.vol ? `${Math.round(k.vol).toLocaleString()} traded` : 'No trades yet',
      priceOk(k.ya) && priceOk(k.yb) ? `Bid ${cents(k.yb)}, ask ${cents(k.ya)}` : 'One side has no orders']);
    return `<div class="sec"><h3>Context</h3><div class="ctx">${cards.map(([a, b, c]) => `<div><span>${esc(a)}</span><b>${esc(b)}</b><small>${esc(c)}</small></div>`).join('')}</div></div>`;
  }

  function logHTML(pf, r, stat) {
    const games = pf.games.filter((g) => (g.date || '') < (r.G.date || '9999')).slice(0, 20);
    if (!games.length) return '';
    const cols = (LOG_COLS[r.lg] || []).filter(([k]) => games.some((g) => g.s && g.s[k] != null));
    const head = `<tr><th>Date</th><th>Opp</th><th>Result</th>${cols.map(([k, n]) => `<th>${esc(n)}</th>`).join('')}</tr>`;
    const body = games.map((g) => {
      const tds = cols.map(([k]) => {
        const v = g.s[k];
        if (k !== stat) return `<td>${fmtNum(v)}</td>`;
        const hit = v != null && v >= r.line;
        const cls = isHurt(g) ? 'hurt' : hit ? 'hit' : 'miss';
        return `<td class="on">${fmtNum(v)}<span class="dot ${cls}" role="img" aria-label="${isHurt(g) ? 'left hurt, not counted' : hit ? 'hit' : 'missed'}"></span></td>`;
      }).join('');
      const note = g.inj ? `<tr class="injrow${isHurt(g) ? ' hurt' : ''}"><td colspan="${3 + cols.length}">${esc(g.inj.why)}</td></tr>` : '';
      return `<tr${g.inj ? ' class="has-note"' : ''}><td>${md(g.date)}${g.season === 'prev' ? ' ’' + String(Number((g.date || '').slice(2, 4))) : ''}</td><td>${g.home ? 'vs' : '@'} ${esc(g.opp)}</td><td>${esc(g.res || '')} ${esc(g.score || '')}</td>${tds}</tr>${note}`;
    }).join('');
    const nHurt = games.filter(isHurt).length;
    return `<div class="sec"><h3>Game log</h3><p class="note">Last ${games.length} games. The dot marks whether he reached ${BINARY.has(stat) ? 'it' : r.line + '+'}.${nHurt ? ` Grey dots are games he left early hurt: they aren’t counted in his hit rates or the model, because a game he left in the first quarter says little about tonight. Kalshi still settles on his stats if he plays at all, so an early exit counts as a miss there.` : ''}</p><div class="scroll-x"><table class="tbl">${head}${body}</table></div></div>`;
  }

  function bindDrawer() {
    const inner = $('#d-inner');
    inner.onclick = (e) => {
      const st = drawerState;
      if (!st) return;
      if (e.target.closest('#d-close')) { closeDrawer(); return; }
      const sb = e.target.closest('button[data-stat]');
      if (sb) {
        st.stat = sb.dataset.stat;
        const lad = siblings(st.r, st.stat);
        const best = lad.slice().sort((a, b) => bestLineScore(b) - bestLineScore(a))[0];
        st.line = best ? best.line : (lad[0] || {}).line;
        renderDrawer(); return;
      }
      const lb = e.target.closest('[data-line]');
      if (lb) { st.line = +lb.dataset.line; renderDrawer(); return; }
      const rb = e.target.closest('button[data-range]');
      if (rb) { st.range = rb.dataset.range; renderDrawer(); return; }
      const vb = e.target.closest('button[data-venue]');
      if (vb) { st.venue = vb.dataset.venue; renderDrawer(); }
    };
  }

  load();
})();
