(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const PM = 'https://gateway.polymarket.us';
  const LEAGUES = [['all', 'All'], ['nfl', 'NFL'], ['nba', 'NBA'], ['nhl', 'NHL'], ['cfb', 'College football'], ['cbb', 'College basketball'], ['atp', 'ATP'], ['wta', 'WTA']];
  const SHORT = { nfl: 'NFL', nba: 'NBA', nhl: 'NHL', cfb: 'College football', cbb: 'College basketball', atp: 'ATP tennis', wta: 'WTA tennis' };
  const PAGE = 40;
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
  const okPrice = (x) => x != null && x > 0.005 && x < 0.995;

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

  // ------------------------------------------------------------ formatting
  function fmtWhen(iso) {
    if (!iso) return '';
    const d = new Date(iso), now = new Date();
    const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) return 'Today ' + time;
    const tmr = new Date(now.getTime() + 864e5);
    if (d.toDateString() === tmr.toDateString()) return 'Tomorrow ' + time;
    return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ', ' + time;
  }

  function ago(ts) {
    const mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
    return mins < 1 ? 'just now' : mins < 60 ? `${mins} min ago` : `${Math.floor(mins / 60)} hr ${mins % 60} min ago`;
  }

  const sizeTxt = (n) => (n == null || n <= 0 ? 'Size unknown' : n < 1 ? 'Less than 1 contract available' : `${Math.floor(n).toLocaleString()} available`);
  const kindTxt = (o) => (o.kind === 'Moneyline' ? 'Moneyline' : `${o.kind} ${o.line}`);

  // ------------------------------------------------------------ render
  function filtered() {
    return D.opps.filter((o) => (S.league === 'all' || o.lg === S.league) && (S.kind === 'all' || o.kind === S.kind) &&
      (!S.onlyArb || o.per < 1)).sort((a, b) => a.per - b.per);
  }

  function renderSummary() {
    const c = D.counts || {};
    const games = Object.values(c).reduce((a, v) => a + (v.matched || 0), 0);
    const checked = Object.values(D.checked || {}).reduce((a, v) => a + v, 0);
    const arbs = D.opps.filter((o) => o.per < 1).length;
    const best = D.opps.length ? D.opps.reduce((m, o) => Math.min(m, o.per), 9) : null;
    let lead;
    if (arbs) lead = `<b class="pos">${arbs} arbitrage ${arbs === 1 ? 'opportunity' : 'opportunities'}</b> right now.`;
    else lead = `<b>No arbitrage right now.</b> That’s normal. The two sites usually stay within a few cents of each other, and both charge fees.`;
    const closest = best != null && best < 9 ? ` The closest pair costs ${cents(best)} per $1 payout.` : '';
    $('#summary').innerHTML = `<p class="lead">${lead}${arbs ? '' : closest}</p>
      <p class="sub">${checked ? `Checked ${checked.toLocaleString()} opposite-bet pairs across ` : 'Compared '}${games.toLocaleString()} games listed on both Kalshi and Polymarket US, starting in the next 6 days.</p>
      <ul class="arb-counts">${LEAGUES.slice(1).map(([k, n]) => c[k] ? `<li><b>${c[k].matched}</b> ${esc(n)} ${c[k].matched === 1 ? 'game' : 'games'}</li>` : '').join('')}</ul>`;
  }

  function renderLeagues() {
    const n = { all: D.opps.length };
    for (const o of D.opps) n[o.lg] = (n[o.lg] || 0) + 1;
    $('#leagues').innerHTML = LEAGUES.filter(([k]) => k === 'all' || n[k])
      .map(([k, name]) => `<button type="button" data-lg="${k}" aria-pressed="${S.league === k}">${esc(name)}<span class="ct">${n[k] || 0}</span></button>`).join('');
  }

  function renderUpdated() {
    const el = $('#updated');
    if (!D) return;
    const k = Date.parse(D.updated);
    const kMins = (Date.now() - k) / 60000;
    el.textContent = `Kalshi prices ${ago(k)}. ` + (liveAt ? `Polymarket live, ${ago(liveAt)}.` : liveFailed ? 'Polymarket from the same scan.' : 'Checking Polymarket…');
    el.classList.toggle('stale', kMins > 30);
  }

  function card(o) {
    const arb = o.per < 1;
    const pl = plan(o, S.stake);
    const sizes = [o.k.size, o.p.size].filter((x) => x != null && x > 0);
    const maxN = sizes.length ? Math.floor(Math.min(...sizes)) : null;
    const capped = maxN != null && pl.n > maxN;
    const kSide = o.k.side === 'yes' ? 'Yes' : 'No';
    const kFee100 = kFee(o.k.price, 100) / 100, pFee100 = pmFee(o.p.price, o.p.fee_coef, 100) / 100;
    const result = arb
      ? `<span class="res pos">Locks in ${cents(1 - o.per)} per contract</span>`
      : `<span class="res neg">${cents(o.per - 1)} short of break-even</span>`;
    const planTxt = pl.n > 0
      ? `With ${dollars(S.stake)}: buy ${pl.n.toLocaleString()} of each side (${dollars(pl.kSpend)} on Kalshi, ${dollars(pl.pSpend)} on Polymarket US, fees included). One side pays ${dollars(pl.n)}, for a ${pl.profit >= 0 ? 'profit' : 'loss'} of ${dollars(Math.abs(pl.profit))}.`
      : 'Raise the amount to see a full plan.';
    return `<article class="arb${arb ? ' is-arb' : ''}">
      <div class="arb-head"><span class="lgtag">${esc(SHORT[o.lg] || o.lg)}</span><span>${esc(kindTxt(o))}</span><span class="when">${esc(fmtWhen(o.start))}</span></div>
      <h2 class="arb-game">${esc(o.game)}</h2>
      <div class="legs">
        <div class="leg">
          <span class="site">Kalshi</span>
          <div class="buy"><b>Buy ${kSide}</b><span class="px">${cents(o.k.price)}</span></div>
          <p class="mk">${o.k.title ? `${kSide} on “${esc(o.k.title)}”` : ''}</p>
          <p class="means">Means: ${esc(o.k.label)}</p>
          <p class="meta2">Fee about ${cents(kFee100)}. ${esc(sizeTxt(o.k.size))}</p>
          <a class="go" href="${esc(o.k.url)}" target="_blank" rel="noopener">Open on Kalshi</a>
        </div>
        <div class="leg">
          <span class="site">Polymarket US${o.p.live ? ' <span class="livetag">live</span>' : ''}</span>
          <div class="buy"><b>Buy ${esc(o.p.label)}</b><span class="px">${cents(o.p.price)}</span></div>
          <p class="mk">${esc(o.p.market)}</p>
          <p class="meta2">Fee about ${cents(pFee100)}. ${esc(sizeTxt(o.p.size))}</p>
          <p class="go muted">Find this market in the Polymarket US app.</p>
        </div>
      </div>
      <div class="arb-math">
        <div class="tot"><span>Both sides cost</span><b>${(o.per * 100).toFixed(2)}¢</b><span>per $1 payout, fees included</span></div>
        ${result}
      </div>
      <p class="plan">${esc(planTxt)}${capped ? (maxN < 1 ? ' There’s less than 1 contract available at one of these prices right now.' : ` Only about ${maxN.toLocaleString()} contracts are available at these prices, so you can’t do the full amount.`) : ''}</p>
      ${o.note ? `<p class="note">${esc(o.note)}</p>` : ''}
    </article>`;
  }

  function render() {
    const rs = filtered();
    const shown = rs.slice(0, S.limit);
    const list = $('#list');
    if (!rs.length) {
      list.innerHTML = `<p class="empty">${S.onlyArb ? 'No real arbitrage right now. Turn off “Only show real arbitrage” to see the closest pairs.' : 'No pairs within 2¢ of break-even for this filter.'}</p>`;
    } else {
      list.innerHTML = shown.map(card).join('');
    }
    $('#more').hidden = rs.length <= S.limit;
    $('#more').textContent = `Show more (${rs.length - shown.length} left)`;
    for (const b of document.querySelectorAll('#leagues button')) b.setAttribute('aria-pressed', String(b.dataset.lg === S.league));
  }

  // ------------------------------------------------------------ live polymarket
  async function refreshPM() {
    if (!D || !D.opps.length) return;
    const slugs = [...new Set(D.opps.map((o) => o.p.slug))];
    const quotes = {};
    try {
      for (let i = 0; i < slugs.length; i += 60) {
        const chunk = slugs.slice(i, i + 60);
        const qs = chunk.map((s) => 'slug=' + encodeURIComponent(s)).join('&') + '&limit=' + chunk.length;
        const res = await fetch(`${PM}/v1/markets?${qs}`, { cache: 'no-store' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        for (const m of data.markets || []) {
          quotes[m.slug] = { bid: parseFloat((m.bestBidQuote || {}).value), ask: parseFloat((m.bestAskQuote || {}).value) };
        }
      }
    } catch (e) {
      liveFailed = true;
      renderUpdated();
      return;
    }
    for (const o of D.opps) {
      const q = quotes[o.p.slug];
      if (!q) continue;
      const px = o.p.side === 'long' ? q.ask : (Number.isFinite(q.bid) ? 1 - q.bid : NaN);
      if (okPrice(px)) {
        o.p.price = Math.round(px * 10000) / 10000;
        o.p.live = true;
        recompute(o);
      }
    }
    liveAt = Date.now();
    liveFailed = false;
    renderSummary();
    renderLeagues();
    render();
    renderUpdated();
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
    if (!D.ok) {
      $('#summary').innerHTML = '<p class="lead">The last scan didn’t finish.</p><p class="sub">It runs again about every 10 minutes. Check back shortly.</p>';
      D.opps = D.opps || [];
    }
    $('#kind').value = S.kind;
    $('#stake').value = S.stake;
    renderSummary();
    renderLeagues();
    render();
    renderUpdated();
    refreshPM();
    setInterval(() => { if (!document.hidden) refreshPM(); }, 30000);
    setInterval(renderUpdated, 30000);
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
