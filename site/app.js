(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const LEAGUES = [['all', 'All'], ['nba', 'NBA'], ['nfl', 'NFL'], ['nhl', 'NHL']];
  const STATS = {
    nba: { pts: 'Points', reb: 'Rebounds', ast: 'Assists', '3pm': 'Threes', pra: 'Pts + Reb + Ast', stl: 'Steals', blk: 'Blocks', stocks: 'Steals + Blocks', dd: 'Double-double', td3: 'Triple-double' },
    nfl: { pass_yds: 'Passing yards', pass_tds: 'Passing TDs', pass_cmp: 'Completions', pass_att: 'Pass attempts', ints: 'Interceptions', rush_yds: 'Rushing yards', rush_att: 'Rush attempts', rec_yds: 'Receiving yards', rec: 'Receptions', rush_rec_yds: 'Rush + rec yards', tds: 'Touchdowns', rec_long: 'Longest reception', rush_long: 'Longest rush' },
    nhl: { goals: 'Goals', points: 'Points', assists: 'Assists', saves: 'Saves' },
  };
  const SHORT = {
    pra: 'PRA', stocks: 'Stl + Blk', pass_yds: 'Pass yds', rush_yds: 'Rush yds', rec_yds: 'Rec yds',
    rush_rec_yds: 'Rush + rec yds', pass_att: 'Pass att', rush_att: 'Rush att', rec_long: 'Longest rec', rush_long: 'Longest rush',
  };
  const BINARY = new Set(['dd', 'td3']);
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
  };
  const VOLUME = { min: 'Minutes', toi: 'Ice time', targets: 'Targets', rush_att: 'Carries', pass_att: 'Pass attempts', touches: 'Touches' };
  const POS_LABEL = { G: 'guards', F: 'forwards', C: 'centers', QB: 'QBs', RB: 'running backs', WR: 'receivers', TE: 'tight ends', D: 'defensemen' };
  const LOG_COLS = {
    nba: [['min', 'MIN'], ['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'], ['3pm', '3PM'], ['stl', 'STL'], ['blk', 'BLK'], ['pra', 'PRA']],
    nfl: [['pass_cmp', 'CMP'], ['pass_att', 'ATT'], ['pass_yds', 'Pass yds'], ['pass_tds', 'Pass TD'], ['ints', 'INT'], ['rush_att', 'Car'], ['rush_yds', 'Rush yds'], ['rush_long', 'Long rush'], ['rec', 'Rec'], ['targets', 'Tgt'], ['rec_yds', 'Rec yds'], ['rec_long', 'Long rec'], ['tds', 'TD']],
    nhl: [['toi', 'TOI'], ['goals', 'G'], ['assists', 'A'], ['points', 'PTS'], ['sog', 'SOG'], ['saves', 'SV'], ['sa', 'SA'], ['ga', 'GA']],
  };
  const RANGES = [['l5', 'L5'], ['l10', 'L10'], ['l20', 'L20'], ['szn', 'Season'], ['prev', 'Last season'], ['h2h', 'H2H']];
  const SHOW_FLAGS = new Set(['Live', 'Check news', 'Role change', 'Small sample', 'Wide spread']);
  const PAGE = 100;

  // ------------------------------------------------------------ state
  const DEFAULTS = { league: 'all', stat: 'all', game: 'all', q: '', sort: 'edge', best: true, hideLow: false };
  const S = Object.assign({}, DEFAULTS, readPrefs(), { limit: PAGE });
  function readPrefs() {
    try { return JSON.parse(localStorage.getItem('pf:prefs') || '{}'); } catch (e) { return {}; }
  }
  function savePrefs() {
    try {
      const { league, stat, sort, best, hideLow } = S;
      localStorage.setItem('pf:prefs', JSON.stringify({ league, stat, sort, best, hideLow }));
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
  const signed = (x, d = 1) => (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d);
  const norm = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const ordinal = (n) => { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
  const md = (iso) => { if (!iso) return ''; const [, m, d] = iso.split('-'); return `${+m}/${+d}`; };
  const statLabel = (lg, st) => (STATS[lg] || {})[st] || st;
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

  function fmtWhen(G) {
    if (!G || !G.start) return '';
    if (G.state === 'in') return 'Live now';
    const d = new Date(G.start);
    const now = new Date();
    const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
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
  }

  function prepare() {
    for (const r of D.props) {
      r.P = D.players[r.pid] || { name: 'Unknown' };
      r.G = D.games[r.gid] || {};
      r.label = statLabel(r.lg, r.stat);
      r.short = SHORT[r.stat] || r.label;
      r.k.na = r.k.yb != null && r.k.yb > 0 ? Math.round((1 - r.k.yb) * 100) / 100 : null;
      r.k.nb = r.k.ya != null && r.k.ya < 1 ? Math.round((1 - r.k.ya) * 100) / 100 : null;
      r._q = norm(`${r.P.name} ${r.P.team || ''} ${r.opp || ''}`);
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
    const counts = { all: D.props.length };
    for (const r of D.props) counts[r.lg] = (counts[r.lg] || 0) + 1;
    $('#leagues').innerHTML = LEAGUES.filter(([k]) => k === 'all' || counts[k])
      .map(([k, name]) => `<button type="button" data-lg="${k}" aria-pressed="${S.league === k}">${name}<span class="ct">${counts[k] || 0}</span></button>`).join('');
    if (S.league !== 'all' && !counts[S.league]) S.league = 'all';
  }

  function renderSelects() {
    const inLg = D.props.filter((r) => S.league === 'all' || r.lg === S.league);
    const stats = new Map();
    for (const r of inLg) stats.set(r.lg + ':' + r.stat, r);
    const statOpts = [...stats.values()].sort((a, b) => a.lg.localeCompare(b.lg) || a.label.localeCompare(b.label));
    if (S.stat !== 'all' && !statOpts.some((r) => r.stat === S.stat)) S.stat = 'all';
    $('#stat').innerHTML = '<option value="all">All stats</option>' + statOpts.map((r) =>
      `<option value="${esc(r.stat)}"${S.stat === r.stat ? ' selected' : ''}>${S.league === 'all' ? r.lg.toUpperCase() + ' ' : ''}${esc(r.label)}</option>`).join('');
    const games = new Map();
    for (const r of inLg) if (!games.has(r.gid)) games.set(r.gid, r);
    const gameOpts = [...games.values()].sort((a, b) => a.t - b.t);
    if (S.game !== 'all' && !games.has(S.game)) S.game = 'all';
    $('#game').innerHTML = '<option value="all">All games</option>' + gameOpts.map((r) =>
      `<option value="${esc(r.gid)}"${S.game === r.gid ? ' selected' : ''}>${esc(r.G.away)} @ ${esc(r.G.home)}, ${esc(fmtWhen(r.G))}</option>`).join('');
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
      default: return r.be ?? -9;
    }
  }

  function bestLineScore(r) {
    if (r.be != null) return r.be;
    return r.mid == null ? -9 : -Math.abs(r.mid - 0.5) - 1;
  }

  function filtered() {
    let rs = D.props.filter((r) =>
      (S.league === 'all' || r.lg === S.league) &&
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

  function stripSVG(vals, line) {
    const v = vals.slice(0, 10).reverse();
    const W = 100, H = 30, bw = 8, gap = 2;
    const max = Math.max(line * 1.35, ...v, 1);
    const thr = H - ((line - 0.5) / max) * (H - 2);
    let x = W - v.length * (bw + gap) + gap;
    let s = '';
    for (const val of v) {
      const h = Math.max(2, (Math.max(0, val) / max) * (H - 2));
      s += `<path d="${roundTop(x, H - h, bw, h, 2)}" fill="var(--${val >= line ? 'hit' : 'miss'})"/>`;
      x += bw + gap;
    }
    const hits = v.filter((x2) => x2 >= line).length;
    const label = v.length ? `Last ${v.length}: hit ${hits} of ${v.length}` : 'No games yet';
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}"><title>${label}</title>${s}` +
      `<line x1="0" x2="${W}" y1="${thr}" y2="${thr}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 2" opacity=".75"/></svg>`;
  }

  function roundTop(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
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
    const flags = r.flags.filter((f) => SHOW_FLAGS.has(f)).slice(0, 2).map((f) => `<span class="flag">${esc(f)}</span>`).join('');
    const yes = priceOk(k.ya) ? `<b>${cents(k.ya)}</b>` : '—';
    const no = priceOk(k.na) ? `<b>${cents(k.na)}</b>` : '—';
    const venue = r.home ? 'home' : 'away';
    const st = r.strk || 0;
    const streak = st ? `<span class="${st > 0 ? 'up' : 'down'}">${st > 0 ? '+' : '−'}${Math.abs(st)}</span>` : '0';
    const live = G.state === 'in';
    const edge = live ? '<span class="edge live">Live</span>' : r.be == null ? '<span class="edge neg">—</span>'
      : `<span class="edge ${r.be > 0 ? 'pos' : 'neg'}">${signed(r.be * 100)}¢</span>`;
    const side = r.best ? `<span class="side">${r.best === 'yes' ? 'Buy yes' : 'Buy no'} ${confHTML(r.conf)}</span>` : '';
    const dim = r.conf === 'low' ? ' dim' : '';
    return `<div class="row prop-row${dim}" role="row" tabindex="0" data-id="${esc(r.id)}" aria-label="${esc(P.name)} ${r.line}+ ${esc(r.label)}">
      <div class="c-player" role="cell"><span class="pname">${esc(P.name)}</span>
        <div class="meta"><span><span class="lg">${esc(P.team || '')}</span> ${esc(P.pos || '')}</span><span>${vs} ${esc(r.opp)}, ${esc(fmtWhen(G))}</span>${injFlag(P.inj)}${flags}</div></div>
      <div class="c-prop" role="cell"><span class="line">${BINARY.has(r.stat) ? 'Yes' : r.line + '+'}</span><span class="stat">${esc(r.short)}</span></div>
      <div class="c-kalshi" role="cell"><span class="px"><span>Yes</span> ${yes}</span><span class="px"><span>No</span> ${no}</span></div>
      <div class="c-strip" role="cell">${stripSVG(r.last10 || [], r.line)}</div>
      <div class="chips">
        ${chip(r.h.l5, r.mid, 'L5')}${chip(r.h.l10, r.mid, 'L10')}${chip(r.h.l20, r.mid, 'L20', ' wide')}${chip(r.h.szn, r.mid, 'Season')}${chip(r.h.h2h, r.mid, 'H2H')}${chip(r.h[venue], r.mid, r.home ? 'Home' : 'Away')}
        <div class="c-streak" role="cell"><span class="lbl">Streak</span>${streak}</div>
      </div>
      <div class="c-avg" role="cell">${fmtNum(r.avg10)}<small>${r.diff == null ? '' : signed(r.diff) + ' vs line'}</small></div>
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
    $('#more').textContent = `Show more props (${rs.length - shown.length} left)`;
    const empty = $('#empty');
    empty.hidden = rs.length > 0;
    if (!rs.length) {
      empty.textContent = D.props.length ? 'No props match these filters. Clear the search or pick another stat or game.'
        : 'Kalshi has no open player props right now. Lines usually go up on game day.';
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
    let gs = pf.games.filter((g) => g.s && g.s[stat] != null && (g.date || '') < (r.G.date || '9999'));
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
    const stats = [...new Set([...byId.values()].filter((x) => x.pid === r0.pid && x.gid === r0.gid).map((x) => x.stat))];
    const ladder = siblings(r0, st.stat);
    const vs = r0.home ? 'vs' : '@';
    const injNote = P.inj && P.inj.status ? `<div class="d-inj"><b>${esc(P.inj.status)}.</b> ${esc(P.inj.note || '')}</div>` : '';
    const total = G.total ? `Total ${fmtNum(G.total)}` : '';
    const lineTxt = G.line ? G.line : '';

    let html = `<div class="d-top"><div><h2 id="d-name">${esc(P.name)}</h2>
        <div class="d-sub"><span>${esc(P.team || '')} ${esc(P.pos || '')}</span><span>${r0.lg.toUpperCase()}</span></div></div>
        <button class="close" id="d-close" type="button" aria-label="Close"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13"/></svg></button></div>
      <div class="d-game"><span><b>${vs} ${esc(r0.opp)}</b>, ${esc(fmtWhen(G))}</span><span>${esc([total, lineTxt].filter(Boolean).join(', '))}</span></div>
      ${injNote}
      <div class="tabs" role="group" aria-label="Stat">${stats.map((s) => `<button type="button" data-stat="${esc(s)}" aria-pressed="${s === st.stat}">${esc(statLabel(r0.lg, s))}</button>`).join('')}</div>
      <div class="ladder-pick" role="group" aria-label="Kalshi line">${ladder.map((x) => `<button type="button" data-line="${x.line}" aria-pressed="${x.line === r.line}">${BINARY.has(x.stat) ? 'Yes' : x.line + '+'}<small>${priceOk(x.k.ya) ? cents(x.k.ya) : '—'}</small></button>`).join('')}</div>`;

    if (!st.pf) {
      html += st.err ? '<p class="note">Couldn’t load this player’s game log. Close this panel and try again.</p>' : '<p class="note">Loading game log…</p>';
      $('#d-inner').innerHTML = html;
      bindDrawer();
      return;
    }

    const gs = gamesFor(st.pf, r, st.range, st.venue, st.stat);
    const vals = gs.map((g) => g.s[st.stat]);
    const hits = vals.filter((v) => v >= r.line).length;
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    const sorted = vals.slice().sort((a, b) => a - b);
    const med = sorted.length ? (sorted.length % 2 ? sorted[(sorted.length - 1) / 2] : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2) : null;
    const rangeName = (RANGES.find(([k]) => k === st.range) || [])[1];

    html += `<div class="seg-row">
        <div class="seg" role="group" aria-label="Games">${RANGES.map(([k, n]) => `<button type="button" data-range="${k}" aria-pressed="${k === st.range}">${n}</button>`).join('')}</div>
        <div class="seg" role="group" aria-label="Venue">${[['all', 'All'], ['home', 'Home'], ['away', 'Away']].map(([k, n]) => `<button type="button" data-venue="${k}" aria-pressed="${k === st.venue}">${n}</button>`).join('')}</div>
      </div>
      <div class="hero"><span class="big">${vals.length ? pct(hits / vals.length) : '—'}</span>
        <span class="lab">hit ${BINARY.has(r.stat) ? '' : r.line + '+ '}${esc(statLabel(r.lg, st.stat).toLowerCase())} in ${hits} of ${vals.length} games (${esc(rangeName)}${st.venue !== 'all' ? ', ' + st.venue : ''})</span>
        <span class="sub">Average ${fmtNum(avg == null ? null : Math.round(avg * 10) / 10)}, median ${fmtNum(med)}</span></div>
      <div class="chart" id="chart"></div>
      <div class="legend"><span><i class="lh"></i>Hit</span><span><i class="lm"></i>Missed</span><span><i class="ll"></i>${BINARY.has(r.stat) ? 'Yes' : r.line + '+'} line</span></div>`;

    html += ladderHTML(ladder, r);
    html += modelHTML(r, st.pf);
    html += contextHTML(r, st.pf);
    html += logHTML(st.pf, r, st.stat);
    html += `<div class="cta"><a href="${esc(kalshiUrl(r.id))}" target="_blank" rel="noopener">Open on Kalshi</a></div>
      <p class="note">Prices here can be up to about 20 minutes old. Check the live price on Kalshi before you trade. If a player doesn’t play, Kalshi settles the market at a fair price instead of yes or no.</p>`;
    $('#d-inner').innerHTML = html;
    renderChartOnly(gs);
    bindDrawer();
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
    const v = game.s[stat];
    const vol = r.lg === 'nba' ? `${fmtNum(game.s.min)} min` : r.lg === 'nhl' ? `${fmtNum(game.s.toi)} min TOI` : '';
    tip.innerHTML = `<b>${fmtNum(v)} ${esc(statLabel(r.lg, stat).toLowerCase())}</b> ${v >= r.line ? '(hit)' : '(missed)'}<br>` +
      `${game.home ? 'vs' : '@'} ${esc(game.opp)}, ${md(game.date)}${game.res ? `, ${esc(game.res)} ${esc(game.score || '')}` : ''}` +
      (vol ? `<br><span class="muted">${vol}</span>` : '') + (game.post ? '<br><span class="muted">Playoffs</span>' : '');
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
    const H = window.innerWidth <= 760 ? 200 : 230;
    const top = 22, bottom = n <= 12 ? 36 : 22, left = 34, right = 6;
    const plotW = Math.max(120, width - left - right), plotH = H - top - bottom;
    const vals = gs.map((g) => g.s[stat]);
    const maxV = Math.max(line, ...vals, 1);
    const step = niceStep(maxV * 1.1, true);
    const ymax = Math.ceil((maxV * 1.1) / step) * step;
    const y = (v) => top + plotH - (Math.max(0, v) / ymax) * plotH;
    const slot = plotW / n;
    const bw = Math.max(3, Math.min(24, slot - 2));
    const thrY = y(line - 0.5);
    let s = `<svg viewBox="0 0 ${width} ${H}" width="${width}" height="${H}" role="img" aria-label="${esc(statLabel(drawerState.r.lg, stat))} by game, ${vals.filter((v) => v >= line).length} of ${n} at or above ${line}">`;
    for (let t = 0; t <= ymax + 1e-9; t += step) {
      const yy = y(t);
      s += `<line class="grid" x1="${left}" x2="${width - right}" y1="${yy}" y2="${yy}"/>`;
      if (Math.abs(yy - thrY) > 11) s += `<text class="axis" x="${left - 6}" y="${yy + 4}" text-anchor="end">${fmtNum(t)}</text>`;
    }
    gs.forEach((g, i) => {
      const v = vals[i];
      const cx = left + slot * i + slot / 2;
      const h = Math.max(2, (Math.max(0, v) / ymax) * plotH);
      const yy = top + plotH - h;
      const hit = v >= line;
      s += `<g class="b" data-i="${i}"><path class="bar ${hit ? 'hit' : 'miss'}" d="${roundTop(cx - bw / 2, yy, bw, h, 4)}"/>`;
      if (n <= 16) s += `<text class="val" x="${cx}" y="${yy - 5}" text-anchor="middle">${fmtNum(v)}</text>`;
      if (n <= 12) {
        s += `<text class="axis" x="${cx}" y="${H - bottom + 15}" text-anchor="middle">${g.home ? '' : '@'}${esc(g.opp)}</text>`;
        s += `<text class="axis" x="${cx}" y="${H - bottom + 29}" text-anchor="middle">${md(g.date)}</text>`;
      }
      s += `<rect class="hitbox" x="${left + slot * i}" y="${top - 18}" width="${slot}" height="${plotH + bottom + 18}" tabindex="0" aria-label="${fmtNum(v)} ${g.home ? 'vs' : 'at'} ${esc(g.opp)} on ${md(g.date)}, ${hit ? 'hit' : 'missed'}"/></g>`;
    });
    if (n > 12) {
      const k = Math.ceil(n / 7);
      gs.forEach((g, i) => { if ((n - 1 - i) % k === 0) s += `<text class="axis" x="${left + slot * i + slot / 2}" y="${H - 6}" text-anchor="middle">${md(g.date)}</text>`; });
    }
    s += `<line class="thr" x1="${left}" x2="${width - right}" y1="${thrY}" y2="${thrY}"/>`;
    s += `<text class="thr-lab" x="${left - 6}" y="${thrY + 4}" text-anchor="end">${BINARY.has(stat) ? 'Yes' : line + '+'}</text>`;
    return s + '</svg>';
  }

  function ladderHTML(ladder, cur) {
    if (!ladder.length) return '';
    const rows = ladder.map((x) => {
      const edge = x.be == null ? '—' : `<span class="${x.be > 0 ? 'pos' : 'neg'}">${signed(x.be * 100)}¢ ${x.best === 'yes' ? 'yes' : 'no'}</span>`;
      return `<tr class="${x === cur ? 'is-sel' : ''}" data-line="${x.line}"><td>${BINARY.has(x.stat) ? 'Yes' : x.line + '+'}</td><td>${priceOk(x.k.ya) ? cents(x.k.ya) : '—'}</td><td>${priceOk(x.k.na) ? cents(x.k.na) : '—'}</td>` +
        `<td>${pct(x.p)}</td><td>${pct(rate(x.h.l10))}</td><td>${pct(rate(x.h.szn))}</td><td>${edge}</td></tr>`;
    }).join('');
    return `<div class="sec"><h3>Every Kalshi line for this stat</h3><div class="scroll-x"><table class="tbl">
      <thead><tr><th>Line</th><th>Yes costs</th><th>No costs</th><th>Model</th><th>L10</th><th>Season</th><th>Edge</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
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
        return `<td class="on">${fmtNum(v)}<span class="dot ${hit ? 'hit' : 'miss'}" role="img" aria-label="${hit ? 'hit' : 'missed'}"></span></td>`;
      }).join('');
      return `<tr><td>${md(g.date)}${g.season === 'prev' ? ' ’' + String(Number((g.date || '').slice(2, 4))) : ''}</td><td>${g.home ? 'vs' : '@'} ${esc(g.opp)}</td><td>${esc(g.res || '')} ${esc(g.score || '')}</td>${tds}</tr>`;
    }).join('');
    return `<div class="sec"><h3>Game log</h3><p class="note">Last ${games.length} games. The dot marks whether he reached ${BINARY.has(stat) ? 'it' : r.line + '+'}.</p><div class="scroll-x"><table class="tbl">${head}${body}</table></div></div>`;
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
