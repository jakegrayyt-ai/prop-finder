(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const PM = 'https://gateway.polymarket.us';
  const ACTIONS = 'https://github.com/jakegrayyt-ai/prop-finder/actions/workflows/update.yml';
  // Sport groups for the chips. Each card still names its own league ("Premier League", "ITF tennis"...).
  const GROUPS = [['all', 'All'], ['nfl', 'NFL'], ['nba', 'NBA'], ['nhl', 'NHL'], ['cfb', 'College football'],
    ['cbb', 'College basketball'], ['wcbb', 'Women’s college basketball'], ['soccer', 'Soccer'], ['tennis', 'Tennis'],
    ['fights', 'UFC & boxing'], ['esports', 'Esports'], ['hoops', 'Basketball, other leagues'], ['hockey', 'Hockey, other leagues'],
    ['baseball', 'Baseball'], ['cricket', 'Cricket']];
  const OLD = { nfl: 'nfl', nba: 'nba', nhl: 'nhl', cfb: 'cfb', cbb: 'cbb', atp: 'tennis', wta: 'tennis' };
  const groupOf = (lg) => ((D.leagues || {})[lg] || {}).group || OLD[lg] || lg;
  const leagueName = (lg) => ((D.leagues || {})[lg] || {}).label || lg.toUpperCase();
  const PAGE = 40;
  const FRESH_MIN = 15;     // a Kalshi price older than this can't confirm an arbitrage
  const MOVE = 0.02;        // Polymarket moving this much since the scan means Kalshi has probably moved too
  const S = { league: 'all', kind: 'all', onlyArb: false, stake: 100, limit: PAGE };
  let D = null;
  let liveAt = null;
  let liveFailed = false;

  try {
    const saved = JSON.parse(localStorage.getItem('pf:arb') || '{}');
    if (saved.stake > 0) S.stake = saved.stake;
    if (saved.kind) S.kind = saved.kind;
  } catch (e) { /* storage unavailable */ }
  const save = () => { try { localStorage.setItem('pf:arb', JSON.stringify({ stake: S.stake, kind: S.kind })); } catch (e) { /* ignore */ } };

  // ------------------------------------------------------------ money math
  const kFee = (p, n) => Math.ceil(0.07 * n * p * (1 - p) * 100 - 1e-9) / 100;
  const pmFee = (p, coef, n) => Math.ceil((coef || 0.07) * n * p * (1 - p) * 100 - 1e-9) / 100;
  const cents = (x) => (x == null ? '—' : (Math.round(x * 1000) / 10).toString().replace(/\.0$/, '') + '¢');
  const dollars = (x) => '$' + (Math.round(x * 100) / 100).toFixed(2);
  const okPrice = (x) => x != null && Number.isFinite(x) && x > 0.005 && x < 0.995;

  function recompute(o) {
    const cost100 = 100 * (o.k.price + o.p.price) + kFee(o.k.price, 100) + pmFee(o.p.price, o.p.fee_coef, 100);
    o.per = cost100 / 100;
    o.profit100 = 100 - cost100;
  }

  function plan(o, stake) {
    const cost = (n) => n * (o.k.price + o.p.price) + kFee(o.k.price, n) + pmFee(o.p.price, o.p.fee_coef, n);
    let n = Math.max(0, Math.floor(stake / (o.k.price + o.p.price + 0.04)));
    while (n > 0 && cost(n) > stake) n--;
    while (cost(n + 1) <= stake && n < 1e6) n++;
    return {
      n, total: cost(n), profit: n - cost(n),
      kSpend: n * o.k.price + kFee(o.k.price, n), pSpend: n * o.p.price + pmFee(o.p.price, o.p.fee_coef, n),
    };
  }

  const kAgeMin = () => (Date.now() - D.kAt) / 60000;
  // null = unknown. 0 is real: the live Polymarket book has nothing left at this price.
  const minSize = (o) => {
    const s = [o.k.size, o.p.size].filter((x) => x != null && Number.isFinite(x));
    return s.length ? Math.min(...s) : null;
  };

  // Is this pair still an arbitrage we can stand behind?
  //  arb   - under $1, Kalshi price is recent, Polymarket hasn't moved since, and there's size
  //  maybe - was under $1 at the scan, but one of those checks fails: look before trading
  //  close - costs $1 or more
  //  gone  - Polymarket has no price on that side any more
  function judge(o) {
    if (o.p.gone) return { s: 'gone', why: [] };
    if (o.per >= 1) return { s: 'close', why: [] };
    const why = [];
    const age = kAgeMin();
    if (age > FRESH_MIN) why.push(`Kalshi’s price is from ${Math.round(age)} minutes ago, and this page can’t re-check Kalshi. Open it and look.`);
    if (o.p.move != null && Math.abs(o.p.move) >= MOVE - 1e-9) {
      why.push(`Polymarket has moved ${cents(Math.abs(o.p.move))} since the scan, so Kalshi has probably moved too.`);
    }
    const n = minSize(o);
    if (n != null && n <= 0) why.push('Nothing is left at one of these prices right now.');
    else if (n != null && n < 1) why.push('Less than 1 contract is available at one of these prices.');
    return { s: why.length ? 'maybe' : 'arb', why };
  }

  // Games drop off a couple of minutes before they start. Tennis start times are estimates, so 20 minutes early.
  const startMs = (o) => { const t = Date.parse(o.startLive || o.start); return Number.isFinite(t) ? t : null; };
  const started = (o) => { const t = startMs(o); return t != null && t <= Date.now() + (groupOf(o.lg) === 'tennis' ? 20 : 2) * 60000; };
  const visible = () => D.opps.filter((o) => !started(o));

  // ------------------------------------------------------------ formatting
  function fmtWhen(iso) {
    if (!iso) return '';
    const d = new Date(iso), now = new Date();
    const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) return 'Today ' + time;
    const tmr = new Date(now.getTime() + 864e5);
    if (d.toDateString() === tmr.toDateString()) return 'Tomorrow ' + time;
    const yst = new Date(now.getTime() - 864e5);
    if (d.toDateString() === yst.toDateString()) return 'Yesterday ' + time;
    return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ', ' + time;
  }

  function ago(ts) {
    const mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
    return mins < 1 ? 'just now' : mins < 60 ? `${mins} min ago` : `${Math.floor(mins / 60)} hr ${mins % 60} min ago`;
  }

  const sizeTxt = (n, live) => (n == null || !Number.isFinite(n) ? 'Size unknown'
    : n <= 0 ? 'Nothing left at this price'
      : n < 1 ? 'Less than 1 contract available'
      : `${Math.floor(n).toLocaleString()} available${live ? '' : ' at the scan'}`);
  const kindTxt = (o) => (o.kind === 'Player prop' ? `Player prop, ${o.line}` : o.line == null ? o.kind : `${o.kind} ${o.line}`);

  // ------------------------------------------------------------ render
  function filtered() {
    return visible().filter((o) => (S.league === 'all' || groupOf(o.lg) === S.league) && (S.kind === 'all' || o.kind === S.kind) &&
      (!S.onlyArb || ['arb', 'maybe'].includes(judge(o).s))).sort((a, b) => rank(a) - rank(b) || a.per - b.per);
  }
  const rank = (o) => ({ arb: 0, maybe: 1, close: 2, gone: 3 }[judge(o).s]);

  function renderSummary() {
    const c = D.counts || {};
    const games = Object.values(c).reduce((a, v) => a + (v.matched || 0), 0);
    const byGroup = {};
    for (const [lg, v] of Object.entries(c)) byGroup[groupOf(lg)] = (byGroup[groupOf(lg)] || 0) + (v.matched || 0);
    const checked = Object.values(D.checked || {}).reduce((a, v) => a + v, 0);
    const vis = visible();
    const hidden = D.opps.length - vis.length;
    const arbs = vis.filter((o) => judge(o).s === 'arb').length;
    const maybes = vis.filter((o) => judge(o).s === 'maybe').length;
    const priced = vis.filter((o) => !o.p.gone);
    const best = priced.length ? priced.reduce((m, o) => Math.min(m, o.per), 9) : null;
    const age = kAgeMin();
    let lead;
    if (arbs) {
      lead = `<b class="pos">${arbs} arbitrage ${arbs === 1 ? 'opportunity' : 'opportunities'}</b> right now.`
        + (maybes ? ` ${maybes} more ${maybes === 1 ? 'needs' : 'need'} a re-check first.` : '');
    } else if (maybes) {
      lead = `<b class="warn">${maybes} possible arbitrage ${maybes === 1 ? 'pair' : 'pairs'} to re-check.</b> ${maybes === 1 ? 'It was' : 'They were'} under $1 at the last scan, but the prices can’t be confirmed from here. Each card says why.`;
    } else {
      lead = `<b>No arbitrage right now.</b> That’s normal. The two sites usually stay within a few cents of each other, and both charge fees.`
        + (best != null && best < 9 ? ` The closest pair costs ${cents(best)} per $1 payout.` : '');
    }
    const stale = age > 20
      ? `<p class="sub stale-note">The last scan was ${Math.round(age)} minutes ago. GitHub runs it when it has room, usually every 10 to 60 minutes. You can <a href="${ACTIONS}" target="_blank" rel="noopener">start one now on GitHub</a> (Run workflow, about 3 minutes).</p>`
      : '';
    $('#summary').innerHTML = `<p class="lead">${lead}</p>${stale}
      <p class="sub">${checked ? `Checked ${checked.toLocaleString()} opposite-bet pairs across ` : 'Compared '}${games.toLocaleString()} upcoming games listed on both Kalshi and Polymarket US.${hidden ? ` ${hidden} ${hidden === 1 ? 'pair is' : 'pairs are'} hidden because the game has started or is about to.` : ''}</p>
      <ul class="arb-counts">${GROUPS.slice(1).map(([g, n]) => { const m = byGroup[g] || 0; return m ? `<li><b>${m.toLocaleString()}</b> ${esc(n)}</li>` : ''; }).join('')}</ul>`;
  }

  function renderLeagues() {
    const vis = visible();
    const n = { all: vis.length };
    for (const o of vis) n[groupOf(o.lg)] = (n[groupOf(o.lg)] || 0) + 1;
    $('#leagues').innerHTML = GROUPS.filter(([k]) => k === 'all' || n[k] || S.league === k)
      .map(([k, name]) => `<button type="button" data-lg="${k}" aria-pressed="${S.league === k}">${esc(name)}<span class="ct">${n[k] || 0}</span></button>`).join('');
  }

  function renderUpdated() {
    const el = $('#updated');
    if (!D) return;
    el.textContent = `Kalshi prices from ${ago(D.kAt)}. ` + (liveAt ? `Polymarket re-checked ${ago(liveAt)}.` : liveFailed ? 'Polymarket from the same scan.' : 'Checking Polymarket…');
    el.classList.toggle('stale', kAgeMin() > FRESH_MIN);
  }

  function pmNow(o) {
    if (!o.p.checked) return `Price from the scan, ${ago(D.pAt)}.`;
    if (o.p.gone) return 'Polymarket has no price on this side right now.';
    const when = `Re-checked ${ago(o.p.checked)}`;
    if (o.p.move == null || Math.abs(o.p.move) < 0.005) return `${when}: no change.`;
    const dir = o.p.move > 0 ? 'up' : 'down';
    const used = o.p.move < 0 ? ' The math keeps the scan price because Kalshi has probably moved too.' : '';
    return `${when}: Polymarket moved ${dir} ${cents(Math.abs(o.p.move))} since the scan.${used}`;
  }

  function card(o) {
    const j = judge(o);
    const pl = plan(o, S.stake);
    const maxN = minSize(o) != null ? Math.floor(minSize(o)) : null;
    const capped = maxN != null && pl.n > maxN;
    const kSide = o.k.side === 'yes' ? 'Yes' : 'No';
    const kFee100 = kFee(o.k.price, 100) / 100, pFee100 = pmFee(o.p.price, o.p.fee_coef, 100) / 100;
    const kOld = kAgeMin() > FRESH_MIN;
    let result;
    if (j.s === 'arb') result = `<span class="res pos">Locks in ${cents(1 - o.per)} per contract</span>`;
    else if (j.s === 'maybe') result = `<span class="res warn">${cents(1 - o.per)} under $1 at the scan. Re-check before trading</span>`;
    else if (j.s === 'gone') result = '<span class="res neg">Polymarket no longer has this price</span>';
    else result = `<span class="res neg">${cents(o.per - 1)} short of break-even</span>`;
    const planTxt = pl.n > 0
      ? `With ${dollars(S.stake)}: buy ${pl.n.toLocaleString()} of each side (${dollars(pl.kSpend)} on Kalshi, ${dollars(pl.pSpend)} on Polymarket US, fees included). One side pays ${dollars(pl.n)}, for a ${pl.profit >= 0 ? 'profit' : 'loss'} of ${dollars(Math.abs(pl.profit))}.`
      : 'Raise the amount to see a full plan.';
    const cls = { arb: ' is-arb', maybe: ' is-maybe', gone: ' is-gone', close: '' }[j.s];
    const moved = o.moved_from
      ? `<p class="note">Rescheduled. Polymarket first listed it for ${esc(fmtWhen(o.moved_from))}. Kalshi’s page may still show the old date.</p>` : '';
    return `<article class="arb${cls}">
      <div class="arb-head"><span class="lgtag">${esc(leagueName(o.lg))}</span><span>${esc(kindTxt(o))}</span><span class="when">${esc(fmtWhen(o.startLive || o.start))}</span></div>
      <h2 class="arb-game">${esc(o.game)}</h2>
      <div class="legs">
        <div class="leg">
          <span class="site">Kalshi</span>
          <div class="buy"><b>Buy ${kSide}</b><span class="px">${cents(o.k.price)}</span></div>
          <p class="mk">${o.k.title ? `${kSide} on “${esc(o.k.title)}”` : ''}</p>
          <p class="means">Means: ${esc(o.k.label)}</p>
          <p class="meta2${kOld ? ' old' : ''}">Price from the scan, ${esc(ago(D.kAt))}.</p>
          <p class="meta2">Fee about ${cents(kFee100)}. ${esc(sizeTxt(o.k.size, false))}</p>
          <a class="go" href="${esc(o.k.url)}" target="_blank" rel="noopener">Open on Kalshi</a>
        </div>
        <div class="leg">
          <span class="site">Polymarket US</span>
          <div class="buy"><b>Buy ${esc(o.p.btn || o.p.label)}</b><span class="px">${cents(o.p.price)}</span></div>
          <p class="mk">${esc(o.p.market)}</p>
          ${o.p.means ? `<p class="means">Means: ${esc(o.p.means)}</p>` : ''}
          <p class="meta2${o.p.move != null && Math.abs(o.p.move) >= MOVE - 1e-9 ? ' old' : ''}">${esc(pmNow(o))}</p>
          <p class="meta2">Fee about ${cents(pFee100)}. ${esc(sizeTxt(o.p.size, !!o.p.sizeAt))}</p>
          <p class="go muted">Find this market in the Polymarket US app.</p>
        </div>
      </div>
      <div class="arb-math">
        <div class="tot"><span>Both sides cost</span><b>${(o.per * 100).toFixed(2)}¢</b><span>per $1 payout, fees included</span></div>
        ${result}
      </div>
      ${j.why.length ? `<ul class="why">${j.why.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
      ${j.s === 'gone' ? '' : `<p class="plan">${esc(planTxt)}${capped && maxN >= 1 ? ` Only about ${maxN.toLocaleString()} contracts are available at these prices, so you can’t do the full amount.` : ''}</p>`}
      ${moved}
      ${o.note ? `<p class="note">${esc(o.note)}</p>` : ''}
    </article>`;
  }

  function render() {
    const rs = filtered();
    const shown = rs.slice(0, S.limit);
    const list = $('#list');
    if (!rs.length) {
      list.innerHTML = `<p class="empty">${S.onlyArb ? 'No arbitrage right now. Turn off “Only show arbitrage” to see the closest pairs.' : 'No pairs within 2¢ of break-even for this filter.'}</p>`;
    } else {
      list.innerHTML = shown.map(card).join('');
    }
    $('#more').hidden = rs.length <= S.limit;
    $('#more').textContent = `Show more (${rs.length - shown.length} left)`;
    for (const b of document.querySelectorAll('#leagues button')) b.setAttribute('aria-pressed', String(b.dataset.lg === S.league));
  }

  function renderAll() {
    renderSummary();
    renderLeagues();
    render();
    renderUpdated();
  }

  // ------------------------------------------------------------ live polymarket
  // Polymarket US allows browser requests; Kalshi doesn't. So only Polymarket is re-checked here, and a newer
  // Polymarket price is never allowed to make a pair look better than the scan did: Kalshi has likely moved too.
  async function fetchQuotes(slugs) {
    const quotes = {};
    for (let i = 0; i < slugs.length; i += 60) {
      const chunk = slugs.slice(i, i + 60);
      const qs = chunk.map((s) => 'slug=' + encodeURIComponent(s)).join('&') + '&limit=' + chunk.length;
      const res = await fetch(`${PM}/v1/markets?${qs}`, { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      for (const s of chunk) quotes[s] = null;           // asked for and not returned = not listed now
      for (const m of data.markets || []) {
        const open = !m.closed && (!m.status || m.status === 'MARKET_STATUS_OPEN');
        quotes[m.slug] = open ? {
          bid: parseFloat((m.bestBidQuote || {}).value), ask: parseFloat((m.bestAskQuote || {}).value), start: m.gameStartTime || null,
        } : null;
      }
    }
    return quotes;
  }

  // Walk the book: the best bid or ask is often a dust order (0.01 of a contract) that can't be traded.
  async function refreshBook(o) {
    try {
      const res = await fetch(`${PM}/v1/markets/${encodeURIComponent(o.p.slug)}/book`, { cache: 'no-store' });
      if (!res.ok) return;
      const md = (await res.json()).marketData || {};
      const lv = (rows) => (rows || []).map((r) => [parseFloat((r.px || {}).value), parseFloat(r.qty)]).filter(([p, q]) => p > 0 && q > 0);
      const long = o.p.side === 'long';
      const levels = long ? lv(md.offers).sort((a, b) => a[0] - b[0]) : lv(md.bids).sort((a, b) => b[0] - a[0]);
      const cost = (p) => (long ? p : 1 - p);
      let cum = 0, fill = null;
      for (const [p, q] of levels) { cum += q; if (cum >= 1 - 1e-9) { fill = cost(p); break; } }
      o.p.sizeAt = Date.now();
      if (fill == null) { o.p.size = cum; return; }                 // under 1 contract on the whole book
      o.p.size = levels.filter(([p]) => cost(p) <= fill + 1e-9).reduce((a, [, q]) => a + q, 0);
      if (fill > o.p.price + 1e-9) {     // 1 full contract costs more now than the scan said
        o.p.price = Math.round(fill * 10000) / 10000;
        recompute(o);
      }
    } catch (e) { /* keep the scan's size */ }
  }

  async function refreshPM() {
    if (!D) return;
    const vis = visible();
    if (!vis.length) { renderAll(); return; }
    let quotes;
    try {
      quotes = await fetchQuotes([...new Set(vis.map((o) => o.p.slug))]);
    } catch (e) {
      liveFailed = true;
      renderAll();
      return;
    }
    const now = Date.now();
    for (const o of vis) {
      if (!(o.p.slug in quotes)) continue;
      const q = quotes[o.p.slug];
      o.p.checked = now;
      if (q && q.start) o.startLive = q.start;
      const px = !q ? NaN : o.p.side === 'long' ? q.ask : (Number.isFinite(q.bid) ? 1 - q.bid : NaN);
      if (okPrice(px)) {
        o.p.now = Math.round(px * 10000) / 10000;
        o.p.move = o.p.scanTop != null ? o.p.now - o.p.scanTop : null;
        o.p.price = Math.max(o.p.scan, o.p.now);   // never better than the scan
        o.p.gone = false;
      } else {
        o.p.now = null;
        o.p.move = null;
        o.p.price = o.p.scan;
        o.p.gone = true;
      }
      recompute(o);
    }
    // How much is really there, for anything still under $1
    await Promise.all(visible().filter((o) => o.per < 1 && !o.p.gone).slice(0, 8).map(refreshBook));
    liveAt = Date.now();
    liveFailed = false;
    renderAll();
  }

  // ------------------------------------------------------------ boot
  async function load() {
    try {
      const res = await fetch('data/arb.json?v=' + Math.floor(Date.now() / 60000));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      D = await res.json();
    } catch (e) {
      $('#updated').textContent = 'Couldn’t load prices. Refresh the page to try again.';
      $('#list').innerHTML = '<p class="empty">The arbitrage scan didn’t load. If this keeps happening, the update job on GitHub may have failed.</p>';
      return;
    }
    D.opps = D.opps || [];
    D.kAt = Date.parse(D.k_at || D.updated);
    D.pAt = Date.parse(D.p_at || D.updated);
    for (const o of D.opps) {
      o.p.scan = o.p.price;   // what 1 full contract cost at the scan
      // the scan's best bid or ask (can be a dust order), to compare with the live best bid or ask
      const top = o.p.side === 'long' ? o.p.ask : (o.p.bid != null ? 1 - o.p.bid : null);
      o.p.scanTop = Number.isFinite(top) ? top : null;
      o.p.move = null;
    }
    $('#kind').value = S.kind;
    $('#stake').value = S.stake;
    renderAll();
    if (!D.ok) {
      $('#summary').innerHTML = '<p class="lead">The last scan didn’t finish.</p><p class="sub">It runs again on GitHub’s schedule, usually within an hour. Check back shortly.</p>';
    }
    refreshPM();
    setInterval(() => { if (!document.hidden) refreshPM(); }, 30000);
    setInterval(() => { if (!document.hidden) renderAll(); }, 60000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshPM(); });
  }

  $('#leagues').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-lg]');
    if (!b) return;
    S.league = b.dataset.lg; S.limit = PAGE; render();
  });
  $('#kind').addEventListener('change', (e) => { S.kind = e.target.value; S.limit = PAGE; render(); save(); });
  $('#onlyArb').addEventListener('change', (e) => { S.onlyArb = e.target.checked; S.limit = PAGE; render(); });
  let t;
  $('#stake').addEventListener('input', (e) => {
    clearTimeout(t);
    t = setTimeout(() => { const v = parseFloat(e.target.value); if (v > 0 && v < 1e7) { S.stake = v; render(); save(); } }, 200);
  });
  $('#more').addEventListener('click', () => { S.limit += PAGE; render(); });

  load();
})();
