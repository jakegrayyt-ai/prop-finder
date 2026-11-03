(() => {
  'use strict';

  // Top 10 player props for today's games, from the same board.json and model as the props board.
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const STATS = {
    nba: { pts: 'points', reb: 'rebounds', ast: 'assists', '3pm': 'threes', pra: 'pts + reb + ast', stl: 'steals', blk: 'blocks', stocks: 'steals + blocks', dd: 'double-double', td3: 'triple-double' },
    nfl: { pass_yds: 'passing yards', pass_tds: 'passing TDs', pass_cmp: 'completions', pass_att: 'pass attempts', ints: 'interceptions', rush_yds: 'rushing yards', rush_att: 'rush attempts', rec_yds: 'receiving yards', rec: 'receptions', rush_rec_yds: 'rush + rec yards', tds: 'touchdowns', rec_long: 'longest reception (yds)', rush_long: 'longest rush (yds)' },
    nhl: { goals: 'goals', points: 'points', assists: 'assists', saves: 'saves' },
  };
  const BINARY = new Set(['dd', 'td3']);
  const POS_LABEL = { G: 'guards', F: 'forwards', C: 'centers', QB: 'QBs', RB: 'running backs', WR: 'receivers', TE: 'tight ends', D: 'defensemen' };
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

  // What a prop has to pass to be a pick (the board shows everything; this list is the cream)
  const N = 10, PER_GAME = 3, MIN_PRICE = 0.20, MAX_PRICE = 0.80, MIN_VOL = 10;
  const BLOCK = new Set(['Questionable', 'Doubtful', 'Out', 'Day-To-Day', 'Injured Reserve', 'Suspension', 'Check news', 'Wide spread',
    'No trades yet', 'Small sample', 'Left last game hurt', 'First game this season', 'Long layoff', 'Role change', 'Live']);

  const rate = (h) => (h && h[1] ? h[0] / h[1] : null);
  const pct = (x) => (x == null ? '—' : Math.round(x * 100) + '%');
  const cents = (x) => (x == null ? '—' : Math.round(x * 100) + '¢');
  const fmtNum = (v) => (v == null ? '—' : Number.isInteger(v) ? String(v) : (Math.round(v * 10) / 10).toString());
  const signed = (x, d = 1) => (Math.abs(x) < 0.5 * 10 ** -d ? '' : x > 0 ? '+' : '−') + Math.abs(x).toFixed(d);
  const ordinal = (n) => { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
  const label = (r) => (STATS[r.lg] || {})[r.stat] || r.stat;
  const todayET = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
  const isLive = (G) => !!G && (G.state === 'in' || (G.state !== 'post' && !!G.start && Date.parse(G.start) <= Date.now()));

  function posGroup(lg, pos, stat) {
    const p = String(pos || '').toUpperCase();
    if (stat === 'saves') return 'G';
    if (lg === 'nba') return p.startsWith('C') ? 'C' : ['G', 'PG', 'SG'].includes(p) ? 'G' : 'F';
    if (lg === 'nfl') return p === 'FB' ? 'RB' : p;
    if (lg === 'nhl') return p === 'G' ? 'G' : p === 'D' ? 'D' : 'F';
    return p;
  }

  function kalshiUrl(ticker) {
    const parts = ticker.split('-');
    return `https://kalshi.com/markets/${parts[0].toLowerCase()}/${SLUGS[parts[0]] || 'event'}/${parts.slice(0, 2).join('-').toLowerCase()}`;
  }

  function when(G) {
    const d = new Date(G.start);
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function ago(iso) {
    const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const h = Math.floor(mins / 60);
    return h < 24 ? `${h} hr ${mins % 60} min ago` : `${Math.floor(h / 24)} days ago`;
  }

  function roundTop(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }

  function strip(vals, line, hurtIdx, under) {
    const n0 = Math.min(vals.length, 10);
    const hurt = new Set((hurtIdx || []).map((i) => n0 - 1 - i));
    const v = vals.slice(0, 10).reverse();
    const W = 100, H = 30, bw = 8, gap = 2;
    const max = Math.max(line * 1.35, ...v, 1);
    const thr = H - ((line - 0.5) / max) * (H - 2);
    let x = W - v.length * (bw + gap) + gap, s = '';
    v.forEach((val, i) => {
      const h = Math.max(2, (Math.max(0, val) / max) * (H - 2));
      const won = under ? val < line : val >= line;
      const fill = hurt.has(i) ? 'var(--ink-3)' : `var(--${won ? 'hit' : 'miss'})`;
      s += `<path d="${roundTop(x, H - h, bw, h, 2)}" fill="${fill}"${hurt.has(i) ? ' opacity=".55"' : ''}/>`;
      x += bw + gap;
    });
    const hits = v.filter((x2, i) => !hurt.has(i) && (under ? x2 < line : x2 >= line)).length;
    const lab = `Last ${v.length} games: this pick would have won ${hits} times (green)`;
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${lab}"><title>${lab}</title>${s}<line x1="0" x2="${W}" y1="${thr}" y2="${thr}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 2" opacity=".75"/></svg>`;
  }

  // ------------------------------------------------------------ choosing
  function choose(D) {
    const today = todayET();
    const all = D.props.filter((r) => !r.kind);
    const todays = all.filter((r) => (D.games[r.gid] || {}).date === today);
    const open = todays.filter((r) => !isLive(D.games[r.gid]));
    const cands = [];
    for (const r of open) {
      if (r.be == null || r.be <= 0 || r.conf === 'low' || (r.k.vol || 0) < MIN_VOL) continue;
      if (r.flags.some((f) => BLOCK.has(f) || f.startsWith('Missed last'))) continue;
      const P = D.players[r.pid] || {};
      if (P.inj && P.inj.status) continue;
      const yes = r.best === 'yes';
      const price = yes ? r.k.ya : r.k.yb != null && r.k.yb > 0 ? Math.round((1 - r.k.yb) * 100) / 100 : null;
      if (price == null || price < MIN_PRICE || price > MAX_PRICE) continue;
      // recent games and this season have to point the same way as the model
      const agree = (h, min) => (h && h[1] >= min ? (yes ? rate(h) >= r.mid : rate(h) <= r.mid) : h && h[1] < min);
      if (!agree(r.h.l10, 5) || !agree(r.h.szn, 5)) continue;
      cands.push({ r, P, G: D.games[r.gid], price, yes });
    }
    const best = new Map();
    for (const c of cands) {
      const cur = best.get(c.r.pid);
      if (!cur || c.r.be > cur.r.be) best.set(c.r.pid, c);
    }
    const perGame = new Map(), picks = [];
    for (const c of [...best.values()].sort((a, b) => b.r.be - a.r.be || (b.r.conf === 'high') - (a.r.conf === 'high'))) {
      const n = perGame.get(c.r.gid) || 0;
      if (n >= PER_GAME) continue;
      perGame.set(c.r.gid, n + 1);
      picks.push(c);
      if (picks.length === N) break;
    }
    return { picks, todays: todays.length, open: open.length, cands: cands.length, today };
  }

  // ------------------------------------------------------------ rendering
  function betText(c) {
    const r = c.r, lab = label(r);
    if (BINARY.has(r.stat)) return c.yes ? `gets a ${lab}` : `no ${lab}`;
    return c.yes ? `${r.line}+ ${lab}` : `under ${fmtNum(r.line - 0.5)} ${lab}`;
  }

  function why(c, det) {
    const r = c.r, lab = label(r), out = [];
    const hit = (h) => (c.yes ? h[0] : h[1] - h[0]);
    const verb = c.yes ? (BINARY.has(r.stat) ? 'had one' : `reached ${r.line}+`)
      : BINARY.has(r.stat) ? 'didn’t get one' : r.line === 1 ? 'had none' : `stayed under ${fmtNum(r.line - 0.5)}`;
    const l10 = r.h.l10, szn = r.h.szn;
    if (l10 && l10[1]) out.push(`${verb[0].toUpperCase() + verb.slice(1)} in ${hit(l10)} of his last ${l10[1]}` + (szn && szn[1] ? `, ${hit(szn)} of ${szn[1]} this season` : ''));
    const h2h = r.h.h2h;
    if (h2h && h2h[1] >= 2) out.push(`${hit(h2h)} of ${h2h[1]} against ${esc(r.opp)}`);
    const mYes = r.p, kYes = r.mid;
    out.push(c.yes ? `Model: ${pct(mYes)} chance, Kalshi’s price says ${pct(kYes)}` : `Model: ${pct(1 - mYes)} chance he stays under, Kalshi’s price says ${pct(1 - kYes)}`);
    if (det && det.mu && det.mu.mu != null && !BINARY.has(r.stat)) {
      let s = `Projects about ${fmtNum(det.mu.mu)} ${lab}`;
      const m = det.matchup;
      if (m && m.rank && m.of) {
        const to = r.stat === 'saves' ? 'to opposing goalies' : `to ${POS_LABEL[posGroup(r.lg, c.P.pos, r.stat)] || 'his position'}`;
        const opp = esc(r.opp);
        s += m.rank <= 3 ? `. ${opp} allows the ${m.rank === 1 ? '' : ordinal(m.rank) + ' '}most ${lab} ${to}`
          : m.rank > m.of - 3 ? `. ${opp} allows the ${m.rank === m.of ? '' : ordinal(m.of - m.rank + 1) + ' '}fewest ${lab} ${to}`
            : `. ${opp} ranks ${ordinal(m.rank)} of ${m.of} in ${lab} allowed ${to} (1st allows the most)`;
      }
      out.push(s);
    }
    const run = Math.abs(r.strk || 0);
    if (run >= 3 && (r.strk > 0) === c.yes) {
      out.push(c.yes ? `Reached it in each of his last ${run} games` : r.line === 1 && !BINARY.has(r.stat) ? `None in each of his last ${run} games` : `Under in each of his last ${run} games`);
    }
    return out;
  }

  function cardHTML(c, i, det) {
    const r = c.r, P = c.P, G = c.G;
    const vs = r.home ? 'vs' : '@';
    const fee = 0.07 * c.price * (1 - c.price);
    const conf = r.conf === 'high' ? 3 : 2;
    return `<li class="pick">
      <div class="rk" aria-hidden="true">${i + 1}</div>
      <div class="pk-main">
        <div class="pk-who"><span class="pname">${esc(P.name)}</span><span class="meta"><span class="lg">${esc(P.team || '')}</span> ${esc(P.pos || '')} · ${r.lg.toUpperCase()} · ${vs} ${esc(r.opp)}, ${esc(when(G))}</span></div>
        <div class="pk-bet"><span class="pk-side ${c.yes ? 'yes' : 'no'}">Buy ${c.yes ? 'Yes' : 'No'}</span><b>${esc(betText(c))}</b><span class="pk-px">at ${cents(c.price)}</span></div>
        <ul class="pk-why">${why(c, det).map((t) => `<li>${t}</li>`).join('')}</ul>
      </div>
      <div class="pk-end">
        <div class="pk-edge"><span class="edge pos">${signed(r.be * 100)}¢</span><small>expected per $1, after the ${(fee * 100).toFixed(1)}¢ fee</small></div>
        <div class="c-strip">${strip(r.last10 || [], r.line, r.x10, !c.yes)}</div>
        <span class="conf c${conf}" role="img" aria-label="${conf === 3 ? 'High' : 'Medium'} confidence" title="${conf === 3 ? 'High' : 'Medium'} confidence"><i></i><i></i><i></i></span>
        <div class="pk-links"><a href="./#p=${encodeURIComponent(r.id)}">Full breakdown</a><a href="${esc(kalshiUrl(r.id))}" target="_blank" rel="noopener">Kalshi</a></div>
      </div>
    </li>`;
  }

  let D = null;
  const details = new Map();

  async function loadDetails(picks) {
    await Promise.all(picks.map(async (c) => {
      if (details.has(c.r.id)) return;
      try {
        const res = await fetch(`data/p/${c.r.pid}.json?v=` + Math.floor(Date.now() / 120000));
        if (!res.ok) return;
        const pf = await res.json();
        details.set(c.r.id, (pf.props || {})[c.r.id] || null);
      } catch (e) { /* the card works without it */ }
    }));
  }

  function render() {
    const R = choose(D);
    const day = new Date(R.today + 'T12:00:00').toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
    $('#pk-sub').textContent = R.picks.length
      ? `${day}. The ${R.picks.length === N ? N : R.picks.length} best edges out of ${R.open.toLocaleString()} player props for games that haven’t started yet.`
      : day + '.';
    $('#picks').innerHTML = R.picks.map((c, i) => cardHTML(c, i, details.get(c.r.id))).join('');
    const empty = $('#empty');
    empty.hidden = R.picks.length > 0;
    if (!R.picks.length) {
      empty.textContent = !R.todays ? 'Kalshi hasn’t posted player props for today’s games yet. They usually go up on game day.'
        : !R.open ? 'Today’s games have all started. Tomorrow’s picks show up once Kalshi posts those props.'
          : 'No prop for today’s games passes every check right now. The board still has all of them.';
    }
    if (R.picks.length < N && R.picks.length) $('#pk-sub').textContent += ` Only ${R.picks.length} pass every check right now.`;
    return R;
  }

  function renderUpdated() {
    if (!D) return;
    const el = $('#updated');
    const mins = (Date.now() - Date.parse(D.updated)) / 60000;
    el.textContent = `Updated ${ago(D.updated)}` + (mins > 75 ? '. Prices may be out of date' : '');
    el.classList.toggle('stale', mins > 75);
  }

  async function load() {
    try {
      const res = await fetch('data/board.json?v=' + Math.floor(Date.now() / 120000));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      D = await res.json();
    } catch (e) {
      $('#updated').textContent = 'Couldn’t load the props. Refresh the page to try again.';
      return;
    }
    const R = render();
    renderUpdated();
    await loadDetails(R.picks);
    render();
  }

  load();
  setInterval(renderUpdated, 60000);
  setInterval(load, 10 * 60000);   // the board updates every 10 to 60 minutes
})();
