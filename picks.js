(() => {
  'use strict';

  // Top 10 picks for today's games: NBA, NFL and NHL player props and team bets (board.json) plus the game markets
  // for every other sport on Kalshi (more.json), from the same data and models as the props board.
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
    KXNBAGAME: 'nba-game', KXNBASPREAD: 'nba-spread', KXNBATOTAL: 'nba-total', KXNBATEAMTOTAL: 'nba-team-total',
    KXNFLGAME: 'pro-football-game', KXNFLSPREAD: 'pro-football-spread', KXNFLTOTAL: 'pro-football-total',
    KXNFLTEAMTOTAL: 'pro-football-team-total', KXNHLGAME: 'nhl-game', KXNHLSPREAD: 'nhl-spread', KXNHLTOTAL: 'nhl-total',
    KXNHLTEAMTOTAL: 'nhl-team-goals-scored-during-game',
  };
  const CORE_UNIT = { nba: 'points', nfl: 'points', nhl: 'goals' };

  // The sport tabs. College is football and basketball; everything outside the named tabs is under More.
  const SPORTS = [['all', 'All sports'], ['nba', 'NBA'], ['nfl', 'NFL'], ['nhl', 'NHL'], ['tennis', 'Tennis'], ['esports', 'Esports'],
    ['soccer', 'Soccer'], ['college', 'College'], ['more', 'More sports']];
  const SPORT_WORD = { all: '', nba: 'NBA', nfl: 'NFL', nhl: 'NHL', tennis: 'tennis', esports: 'esports', soccer: 'soccer', college: 'college', more: '' };
  const CHIP_GROUPS = { tennis: ['tennis'], esports: ['esports'], soccer: ['soccer'], college: ['cfb', 'cbb'] };
  const GROUP_WORD = { tennis: 'tennis', esports: 'esports', soccer: 'soccer', cfb: 'college football', cbb: 'college basketball',
    hoops: 'basketball', hockey: 'hockey', football: 'football', baseball: 'baseball', cricket: 'cricket', fights: 'fight', other: '' };
  const sportOf = (r) => (r.src !== 'k' ? r.lg
    : ['tennis', 'esports', 'soccer'].includes(r.grp) ? r.grp : r.grp === 'cfb' || r.grp === 'cbb' ? 'college' : 'more');

  // What a bet has to pass to be a pick (the board shows everything; this list is the cream)
  const N = 10, PER_GAME = 3, PER_GAME_BETS = 2, PER_SPORT_ALL = 4;
  const MIN_EDGE = 0.001, MIN_PRICE = 0.20, MAX_PRICE = 0.80, MIN_VOL = 10, MIN_RATED = 8;
  const BLOCK = new Set(['Questionable', 'Doubtful', 'Out', 'Day-To-Day', 'Injured Reserve', 'Suspension', 'Check news', 'Wide spread',
    'No trades yet', 'Small sample', 'Left last game hurt', 'First game this season', 'Long layoff', 'Role change', 'Live']);

  const rate = (h) => (h && h[1] ? h[0] / h[1] : null);
  const pct = (x) => (x == null ? '—' : Math.round(x * 100) + '%');
  const cents = (x) => (x == null ? '—' : Math.round(x * 100) + '¢');
  const fmtNum = (v) => (v == null ? '—' : Number.isInteger(v) ? String(v) : (Math.round(v * 10) / 10).toString());
  const half = (line) => fmtNum(line - 0.5);
  const signed = (x, d = 1) => (Math.abs(x) < 0.5 * 10 ** -d ? '' : x > 0 ? '+' : '−') + Math.abs(x).toFixed(d);
  const ordinal = (n) => { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
  const label = (r) => (STATS[r.lg] || {})[r.stat] || r.stat;
  const etDay = (d) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(d);
  const todayET = () => etDay(new Date());
  const dayOf = (G) => (G.start && !G.est ? etDay(new Date(G.start)) : G.date);
  const isLive = (G) => !!G && (G.state === 'in' || (G.state !== 'post' && !!G.start && Date.parse(G.start) <= Date.now()));
  const isProp = (r) => !r.kind;
  const isK = (r) => r.src === 'k';
  const unitOf = (r) => r.u || CORE_UNIT[r.lg] || 'points';
  const matchWord = (r) => (r.grp === 'tennis' || r.grp === 'esports' || r.grp === 'fights' ? 'matches' : 'games');
  const histWord = (r) => (isK(r) ? 'since late summer' : 'this season');

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
    const t = new Date(G.start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    return G.est ? `about ${t}` : t;
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

  // Last 10: one bar per game, green when this pick would have won. Yes/no bets (winner, draw, both score) get
  // even bars; the rest are drawn to scale against the line.
  function strip(r, under) {
    const vals = r.last10 || [], line = r.line;
    const binary = ['win', 'draw', 'btts'].includes(r.stat) || BINARY.has(r.stat);
    const n0 = Math.min(vals.length, 10);
    const hurt = new Set((r.x10 || []).map((i) => n0 - 1 - i));
    const v = vals.slice(0, 10).reverse();
    const W = 100, H = 30, bw = 8, gap = 2;
    const max = Math.max(line * 1.35, ...v, 1);
    const thr = H - ((line - 0.5) / max) * (H - 2);
    let x = W - v.length * (bw + gap) + gap, s = '', hits = 0;
    v.forEach((val, i) => {
      const won = under ? val < line : val >= line;
      if (won && !hurt.has(i)) hits++;
      const h = binary ? (won ? H - 4 : H * 0.45) : Math.max(2, (Math.max(0, val) / max) * (H - 2));
      const fill = hurt.has(i) ? 'var(--ink-3)' : `var(--${won ? 'hit' : 'miss'})`;
      s += `<path d="${roundTop(x, H - h, bw, h, 2)}" fill="${fill}"${hurt.has(i) ? ' opacity=".55"' : ''}/>`;
      x += bw + gap;
    });
    const lab = `Last ${v.length} ${matchWord(r)}: this pick would have won ${hits} times (green)`;
    const mark = binary ? '' : `<line x1="0" x2="${W}" y1="${thr}" y2="${thr}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 2" opacity=".75"/>`;
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${lab}"><title>${lab}</title>${s}${mark}</svg>`;
  }

  // ------------------------------------------------------------ names
  function oppName(r, G) {
    if (!G) return r.opp;
    if (r.opp === G.away) return G.away_name || r.opp;
    if (r.opp === G.home) return G.home_name || r.opp;
    return r.opp;
  }

  function lgName(r) {
    return isK(r) ? (((D.leagues || {})[r.lg] || {}).label || r.lg.toUpperCase()) : r.lg.toUpperCase();
  }

  const solo = (r) => r.grp === 'tennis' || r.grp === 'fights';
  const shortName = (r, s) => {   // "Mika Brunold" -> "Brunold" in tennis and fights; teams keep their full name
    const parts = String(s || '').trim().split(/\s+/);
    return solo(r) && parts.length >= 2 && !/\//.test(s) ? parts[parts.length - 1] : String(s || '');
  };

  // ------------------------------------------------------------ choosing
  function sidePrice(r, yes) {
    return yes ? r.k.ya : r.k.yb != null && r.k.yb > 0 ? Math.round((1 - r.k.yb) * 100) / 100 : null;
  }

  function candidates(D) {
    const today = todayET(), now = Date.now();
    const counts = {}, cands = [];
    const bump = (s, f) => { (counts[s] ||= { todays: 0, open: 0 })[f]++; (counts.all ||= { todays: 0, open: 0 })[f]++; };
    for (const r of D.props) {
      const G = D.games[r.gid];
      if (!G || dayOf(G) !== today) continue;
      const sport = sportOf(r);
      bump(sport, 'todays');
      if (isLive(G) || (G.est && G.start && Date.parse(G.start) - now < 30 * 60000)) continue;   // estimated starts get a buffer
      bump(sport, 'open');
      if (r.be == null || r.be < MIN_EDGE || r.conf === 'low' || (r.k.vol || 0) < MIN_VOL) continue;
      if (r.flags.some((f) => BLOCK.has(f) || f.startsWith('Missed last'))) continue;
      const P = D.players[r.pid] || {};
      if (isProp(r) && P.inj && P.inj.status) continue;
      const yes = r.best === 'yes';
      const price = sidePrice(r, yes);
      if (price == null || price < MIN_PRICE || price > MAX_PRICE) continue;
      if (r.el) {
        // rated head to head: the ratings already weigh who each side beat, so ask for enough results instead
        if (Math.min(r.el[2], r.el[3]) < MIN_RATED) continue;
      } else {
        // recent games and the season so far have to point the same way as the model
        const agree = (h, min) => (h && h[1] >= min ? (yes ? rate(h) >= r.mid : rate(h) <= r.mid) : h && h[1] < min);
        if (!agree(r.h.l10, 5) || !agree(r.h.szn, 5)) continue;
      }
      cands.push({ r, P, G, price, yes, sport });
    }
    return { cands, counts, today };
  }

  function choose(C, sport) {
    const pool = C.cands.filter((c) => sport === 'all' || c.sport === sport).sort((a, b) => b.r.be - a.r.be);
    const seenPid = new Set(), seenBet = new Set(), perGame = new Map(), perSport = new Map(), picks = [];
    for (const c of pool) {
      const r = c.r;
      // one line per player or team; one moneyline, spread and total per game (yes on one side = no on the other)
      const solo = isProp(r) || r.kind === 'player';
      const fam = solo ? null : `${r.gid}|${r.stat === 'win' || r.stat === 'draw' ? 'ml' : r.stat === 'tpts' || r.sl ? 'tt' + r.pid + r.stat : r.stat}`;
      if (seenPid.has(r.pid) || (fam && seenBet.has(fam))) continue;
      const g = perGame.get(r.gid) || { all: 0, bets: 0 };
      if (g.all >= PER_GAME || (!solo && g.bets >= PER_GAME_BETS)) continue;
      if (sport === 'all' && (perSport.get(c.sport) || 0) >= PER_SPORT_ALL) continue;
      seenPid.add(r.pid);
      if (fam) seenBet.add(fam);
      perGame.set(r.gid, { all: g.all + 1, bets: g.bets + (solo ? 0 : 1) });
      perSport.set(c.sport, (perSport.get(c.sport) || 0) + 1);
      picks.push(c);
      if (picks.length === N) break;
    }
    return picks;
  }

  // ------------------------------------------------------------ what the bet is
  function propBet(c) {
    const r = c.r, lab = label(r);
    if (BINARY.has(r.stat)) return c.yes ? `gets a ${lab}` : `no ${lab}`;
    return c.yes ? `${r.line}+ ${lab}` : `under ${fmtNum(r.line - 0.5)} ${lab}`;
  }

  // The outcome a Yes pays on, and the outcome this pick pays on
  function teamBet(c) {
    const r = c.r, G = c.G, u = unitOf(r), name = c.P.name || r.opp;
    const opp = oppName(r, G);
    const three = threeWay.has(r.gid) || r.grp === 'soccer';    // a draw is the third outcome
    const s = isK(r) ? 's' : '';                 // "Arsenal wins", "the Celtics win"
    const nt = isK(r) ? 'doesn’t' : 'don’t';
    switch (r.stat) {
      case 'win': return { yesTxt: `${name} win${s}`, txt: c.yes ? `${name} win${s}` : three ? `${name} ${nt} win` : `${opp} win${s}`,
        note: !c.yes && three ? `a draw or a ${opp} win pays` : !isK(r) && r.lg === 'nfl' ? 'a tie pays 50¢' : '' };
      case 'margin': return { yesTxt: `${name} win${s} by ${r.line}+`, txt: c.yes ? `${name} win${s} by ${r.line}+ ${u}` : `${name} ${nt} win by ${r.line}+ ${u}`,
        note: c.yes ? `−${half(r.line)}` : `${opp} +${half(r.line)}` };
      case 'tpts': return { yesTxt: `${name} ${r.line}+`, txt: c.yes ? `${name} ${r.line}+ ${u}` : `${name} under ${half(r.line)} ${u}`, note: '' };
      case 'total': return { yesTxt: `over ${half(r.line)}`, txt: `${c.yes ? 'Over' : 'Under'} ${half(r.line)} ${u}`, note: '' };
      case 'btts': return { yesTxt: 'both score', txt: c.yes ? 'Both teams score' : 'Not both teams score', note: '' };
      case 'draw': return { yesTxt: 'draw', txt: c.yes ? 'It’s a draw' : 'No draw', note: c.yes ? '' : 'either team winning pays' };
      default: {
        const L = (r.sl || r.stat).toLowerCase();
        const who = r.kind === 'game' ? '' : `${name} `;
        return { yesTxt: `${who}${r.line}+ ${L}`, txt: c.yes ? `${who}${r.line}+ ${L}` : `${who}under ${half(r.line)} ${L}`, note: '' };
      }
    }
  }

  // ------------------------------------------------------------ why
  function propWhy(c, det) {
    const r = c.r, lab = label(r), out = [];
    const hit = (h) => (c.yes ? h[0] : h[1] - h[0]);
    const verb = c.yes ? (BINARY.has(r.stat) ? 'had one' : `reached ${r.line}+`)
      : BINARY.has(r.stat) ? 'didn’t get one' : r.line === 1 ? 'had none' : `stayed under ${fmtNum(r.line - 0.5)}`;
    const l10 = r.h.l10, szn = r.h.szn;
    if (l10 && l10[1]) out.push(`${verb[0].toUpperCase() + verb.slice(1)} in ${hit(l10)} of his last ${l10[1]}` + (szn && szn[1] ? `, ${hit(szn)} of ${szn[1]} this season` : ''));
    const h2h = r.h.h2h;
    if (h2h && h2h[1] >= 2) out.push(`${hit(h2h)} of ${h2h[1]} against ${esc(r.opp)}`);
    out.push(c.yes ? `Model: ${pct(r.p)} chance, Kalshi’s price says ${pct(r.mid)}` : `Model: ${pct(1 - r.p)} chance he stays under, Kalshi’s price says ${pct(1 - r.mid)}`);
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

  // "Won 9 of the last 10" for this pick's side of a team or game bet
  function recordText(r, yes, h, tail) {
    const n = h[1], hit = yes ? h[0] : n - h[0], u = unitOf(r), line = r.line;
    const of = `${hit} of the last ${n}`;
    switch (r.stat) {
      case 'win': return (yes ? `Won ${of}` : r.grp === 'soccer' ? `Didn’t win ${of}` : `Lost ${of}`) + tail;
      case 'margin': return (yes ? `Won by ${line}+ ${u} in ${of}` : `Didn’t win by ${line}+ in ${of}`) + tail;
      case 'tpts': return (yes ? `Scored ${line}+ in ${of}` : `Scored under ${half(line)} in ${of}`) + tail;
      case 'total': return `${yes ? 'Over' : 'Under'} ${half(line)} in ${of}${r.kind === 'game' ? ' of the two teams’ games' : ''}` + tail;
      case 'btts': return `${yes ? 'Both teams scored' : 'At least one team was shut out'} in ${of}` + tail;
      case 'draw': return `${yes ? 'Ended level' : 'Had a winner'} in ${of}` + tail;
      default: {
        const L = (r.sl || r.stat).toLowerCase();
        return `${yes ? `${line}+` : `Under ${half(line)}`} ${L} in ${of}${r.kind === 'game' ? ' of the two teams’ games' : ''}` + tail;
      }
    }
  }

  function teamWhy(c) {
    const r = c.r, out = [], yes = c.yes;
    const name = esc(shortName(r, c.P.name)), opp = esc(shortName(r, oppName(r, c.G)));
    const side = (x) => (yes ? x : 1 - x);
    if (r.el) {
      const [ra, rb, na, nb] = r.el;
      out.push(`Ratings: ${pct(side(r.p))} chance, Kalshi’s price says ${pct(side(r.mid))}`);
      out.push(`Rated ${ra}, ${opp} ${rb} (from ${na} and ${nb} results on Kalshi)`);
    } else {
      out.push(`${isK(r) ? 'Trend model' : 'Model'}: ${pct(side(r.p))} chance, Kalshi’s price says ${pct(side(r.mid))}`);
    }
    const l10 = r.h.l10, szn = r.h.szn;
    if (l10 && l10[1]) {
      const sz = szn && szn[1] > l10[1] ? `, ${yes ? szn[0] : szn[1] - szn[0]} of ${szn[1]} ${histWord(r)}` : '';
      const who = r.kind === 'game' ? '' : `${name}: `;
      out.push(who + recordText(r, yes, l10, sz));
    }
    const h2h = r.h.h2h;
    if (h2h && h2h[1] >= 2 && r.kind !== 'game') {
      const hit = yes ? h2h[0] : h2h[1] - h2h[0];
      out.push(r.stat === 'win' ? `${yes ? 'Won' : 'Lost'} ${hit} of ${h2h[1]} against ${opp}` : `${hit} of ${h2h[1]} against ${opp}`);
    }
    const run = Math.abs(r.strk || 0);
    if (run >= 3 && (r.strk > 0) === yes && r.stat === 'win' && r.kind !== 'game') {
      out.push(`${yes ? 'Won' : 'Lost'} the last ${run} in a row`);
    }
    if (!isK(r) && r.avg10 != null && (r.stat === 'margin' || r.stat === 'tpts' || r.stat === 'total')) {
      out.push(`Last 10 average: ${r.stat === 'margin' ? signed(r.avg10) : fmtNum(r.avg10)} ${unitOf(r)}`);
    }
    return out;
  }

  function cardHTML(c, i, det) {
    const r = c.r, P = c.P, G = c.G;
    const fee = 0.07 * c.price * (1 - c.price);
    const conf = r.conf === 'high' ? 3 : 2;
    let who, bet, why, px = `at ${cents(c.price)}`;
    if (isProp(r)) {
      who = `<span class="pname">${esc(P.name)}</span><span class="meta"><span class="lg">${esc(P.team || '')}</span> ${esc(P.pos || '')} · ${r.lg.toUpperCase()} · ${r.home ? 'vs' : '@'} ${esc(r.opp)}, ${esc(when(G))}</span>`;
      bet = esc(propBet(c));
      why = propWhy(c, det);
    } else {
      const t = teamBet(c);
      const vs = r.home === true ? 'vs' : r.home === false ? '@' : 'vs';
      const against = r.kind === 'game' ? '' : ` · ${vs} ${esc(oppName(r, G))}`;
      who = `<span class="pname">${esc(P.name)}</span><span class="meta"><span class="lg">${esc(lgName(r))}</span>${r.kind === 'player' && P.team ? ` ${esc(P.team)}` : ''}${against}, ${esc(when(G))}</span>`;
      bet = esc(t.txt);
      if (!c.yes) px += ` · No on “${esc(t.yesTxt)}”`;
      if (t.note) px += ` (${esc(t.note)})`;
      why = teamWhy(c);
    }
    return `<li class="pick">
      <div class="rk" aria-hidden="true">${i + 1}</div>
      <div class="pk-main">
        <div class="pk-who">${who}</div>
        <div class="pk-bet"><span class="pk-side ${c.yes ? 'yes' : 'no'}">Buy ${c.yes ? 'Yes' : 'No'}</span><b>${bet}</b><span class="pk-px">${px}</span></div>
        <ul class="pk-why">${why.map((t) => `<li>${t}</li>`).join('')}</ul>
      </div>
      <div class="pk-end">
        <div class="pk-edge"><span class="edge pos">${signed(r.be * 100)}¢</span><small>expected per $1, after the ${(fee * 100).toFixed(1)}¢ fee</small></div>
        <div class="c-strip">${strip(r, !c.yes)}</div>
        <span class="conf c${conf}" role="img" aria-label="${conf === 3 ? 'High' : 'Medium'} confidence" title="${conf === 3 ? 'High' : 'Medium'} confidence"><i></i><i></i><i></i></span>
        <div class="pk-links"><a href="./#p=${encodeURIComponent(r.id)}">Full breakdown</a><a href="${esc(kalshiUrl(r.id))}" target="_blank" rel="noopener">Kalshi</a></div>
      </div>
    </li>`;
  }

  // ------------------------------------------------------------ page
  let D = null, C = null, threeWay = new Set();
  const details = new Map();
  const validSport = (s) => SPORTS.some(([k]) => k === s);
  let sport = validSport(location.hash.slice(1)) ? location.hash.slice(1) : 'all';

  async function loadDetails(picks) {
    await Promise.all(picks.filter((c) => isProp(c.r)).map(async (c) => {
      if (details.has(c.r.id)) return;
      try {
        const res = await fetch(`data/p/${c.r.pid}.json?v=` + Math.floor(Date.now() / 120000));
        if (!res.ok) return;
        const pf = await res.json();
        details.set(c.r.id, (pf.props || {})[c.r.id] || null);
      } catch (e) { /* the card works without it */ }
    }));
  }

  // The daily test of the ratings against Kalshi's pre-match prices, for the sport this tab covers (backtest.py)
  function testNote(sport) {
    const T = (D && D.tests) || {};
    const named = Object.values(CHIP_GROUPS).flat();
    const groups = sport === 'more' ? Object.keys(T).filter((g) => !named.includes(g)) : CHIP_GROUPS[sport] || [];
    const best = groups.filter((g) => T[g] && T[g].n).sort((a, b) => T[b].n - T[a].n)[0];
    if (!best) return '';
    const v = T[best], word = GROUP_WORD[best] ?? best;
    const unit = best === 'tennis' || best === 'esports' || best === 'fights' ? 'matches' : 'games';
    let t = `Tested on ${v.n.toLocaleString()} ${word ? word + ' ' : ''}${unit} from the last ${v.days} days: `
      + (v.mkt <= v.rat ? 'Kalshi’s price before the start called the winner better than the ratings did'
        : 'the ratings called the winner better than Kalshi’s price before the start');
    const b = v.bets || {};
    if (b.n >= 30) {
      const c = Math.abs(b.per_bet * 100).toFixed(1);
      t += Math.abs(b.per_bet) > 2 * b.se
        ? `, and betting every edge the ratings showed would have ${b.per_bet < 0 ? 'lost' : 'made'} ${c}¢ per $1 over ${b.n.toLocaleString()} bets`
        : `, and betting every edge the ratings showed would have come out about even (${b.per_bet < 0 ? '−' : '+'}${c}¢ per $1 over ${b.n.toLocaleString()} bets, within the noise)`;
    }
    t += '.';
    if (v.m != null && v.m < 0.1) t += ' So winner bets here go by Kalshi’s price alone, and only make this list if something else gives them an edge.';
    else if (v.m != null) t += ' The edge leans on the ratings only a little, which came out about even, so they keep that small say.';
    return t;
  }

  function renderTabs() {
    $('#sports').innerHTML = SPORTS.map(([k, name]) => {
      const n = choose(C, k).length;
      if (k !== 'all' && k !== sport && !n && !((C.counts[k] || {}).todays)) return '';
      return `<button type="button" data-sport="${k}" aria-pressed="${k === sport}">${esc(name)}<span class="ct">${n}</span></button>`;
    }).join('');
  }

  function render() {
    C = candidates(D);
    const picks = choose(C, sport);
    const cnt = C.counts[sport] || { todays: 0, open: 0 };
    const word = SPORT_WORD[sport];
    const day = new Date(C.today + 'T12:00:00').toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
    $('#pk-title').textContent = `Top 10 ${word ? word + ' ' : ''}picks today`;
    let sub = day + '.';
    const n = picks.length;
    if (n) {
      sub += ` ${n === 1 ? 'The best edge' : `The ${n} best edges`} out of ${cnt.open.toLocaleString()} ${word ? word + ' ' : ''}bets for games that haven’t started yet.`;
      if (sport === 'all') sub += ` At most ${PER_SPORT_ALL} from one sport.`;
      if (n < N) sub += n === 1 ? ' It’s the only one that passes every check right now.' : ` Only ${n} pass every check right now.`;
    }
    $('#pk-sub').textContent = sub;
    const note = ['all', 'nba', 'nfl', 'nhl'].includes(sport) ? '' : testNote(sport);
    $('#pk-test').textContent = note;
    $('#pk-test').hidden = !note;
    $('#picks').innerHTML = picks.map((c, i) => cardHTML(c, i, details.get(c.r.id))).join('');
    const empty = $('#empty');
    empty.hidden = picks.length > 0;
    if (!picks.length) {
      const w = word ? word + ' ' : '';
      empty.textContent = !cnt.todays ? `Kalshi has nothing posted for today’s ${w}games yet.`
        : !cnt.open ? `Today’s ${w}games have all started. Tomorrow’s picks show up once Kalshi posts those markets.`
          : `No ${w}bet for today’s games passes every check right now. The board still has all of them.`;
    }
    renderTabs();
    return picks;
  }

  function renderUpdated() {
    if (!D) return;
    const el = $('#updated');
    const mins = (Date.now() - Date.parse(D.updated)) / 60000;
    el.textContent = `Updated ${ago(D.updated)}` + (mins > 75 ? '. Prices may be out of date' : '');
    el.classList.toggle('stale', mins > 75);
  }

  async function getJSON(path) {
    const res = await fetch(`${path}?v=` + Math.floor(Date.now() / 120000));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  }

  async function load() {
    let board, more = null;
    try {
      [board, more] = await Promise.all([getJSON('data/board.json'), getJSON('data/more.json').catch(() => null)]);
    } catch (e) {
      $('#updated').textContent = 'Couldn’t load the picks. Refresh the page to try again.';
      return;
    }
    D = { updated: board.updated, props: board.props, games: { ...board.games }, players: { ...board.players }, leagues: {}, tests: {} };
    if (more) {
      D.props = D.props.concat(more.props || []);
      Object.assign(D.games, more.games || {});
      Object.assign(D.players, more.players || {});
      D.leagues = more.leagues || {};
      D.tests = more.tests || {};
    }
    threeWay = new Set(D.props.filter((r) => r.stat === 'draw').map((r) => r.gid));
    const picks = render();
    renderUpdated();
    await loadDetails(picks);
    render();
  }

  $('#sports').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-sport]');
    if (!b || !D) return;
    sport = b.dataset.sport;
    history.replaceState(null, '', sport === 'all' ? location.pathname + location.search : '#' + sport);
    const picks = render();
    await loadDetails(picks);
    render();
  });
  window.addEventListener('hashchange', () => {
    const s = location.hash.slice(1) || 'all';
    if (validSport(s) && s !== sport && D) { sport = s; render(); }
  });

  load();
  setInterval(renderUpdated, 60000);
  setInterval(load, 10 * 60000);   // the data updates every 10 to 60 minutes
})();
