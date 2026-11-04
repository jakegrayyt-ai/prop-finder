"""Tests the ratings against Kalshi's own prices, once a day.

For every settled winner market of the last 30 days with a known start time, two forecasts made before the match:
Kalshi's price in the hour before the start (from its candlesticks) and the ratings' chance (replaying the results
in order, exactly as the site rates them). Then, per sport:

- how well each one predicted the winners (log loss: lower is better), and the blend of the two that did best
- what buying every edge the ratings showed after Kalshi's fee would have returned

The observations also go to learn_weights in sports.py, so each sport's edge leans on the ratings exactly as much
as this test says they've earned: in sports where Kalshi's price already knows everything the ratings do, the edge
is just the price, and nothing gets picked.

Start times and pre-match prices are cached (a played match's price doesn't change), so after the first run each day
only fetches the new matches.
"""
import datetime as dt
import math
import time
from collections import defaultdict

from . import cache, elo, model
from .net import get_json

DAYS = 30
TTL = 20 * 3600
KEY_STARTS, KEY_PRICES, KEY_RESULT = "kalshi/bt-starts", "kalshi/bt-prices", "kalshi/backtest2"


def _ts(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _close(c, key):
    side = c.get(key) or {}
    try:
        if side.get("close_dollars") is not None:
            return float(side["close_dollars"])
        if side.get("close") is not None:
            return float(side["close"]) / 100
    except (TypeError, ValueError):
        return None
    return None


def starts(base, log):
    """Event ticker -> start time for the last DAYS days, topped up from Kalshi's milestones."""
    data = cache.get(KEY_STARTS) or {"st": {}, "through": None}
    now = time.time()
    since = now - (DAYS + 1) * 86400
    if data.get("through"):
        since = max(since, data["through"] - 2 * 86400)
    cursor, pages = None, 0
    iso = dt.datetime.fromtimestamp(since, dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for _ in range(600):
        params = {"limit": 100, "category": "Sports", "minimum_start_date": iso}
        if cursor:
            params["cursor"] = cursor
        d = get_json(base + "/milestones", params=params)
        pages += 1
        for m in d.get("milestones") or []:
            st = m.get("start_date")
            if not st:
                continue
            evs = set(m.get("related_event_tickers") or []) | set(m.get("primary_event_tickers") or [])
            main = (m.get("details") or {}).get("main_game_event_ticker")
            if main:
                evs.add(main)
            for ev in evs:
                data["st"][ev] = st
        cursor = d.get("cursor")
        if not cursor or not d.get("milestones"):
            break
    cut = now - (DAYS + 2) * 86400
    data["st"] = {k: v for k, v in data["st"].items() if _ts(v) >= cut}
    data["through"] = now
    cache.put(KEY_STARTS, data)
    return data["st"], pages


def prices(base, want, log):
    """[(ticker, start ts)] -> {ticker: (bid, ask)} in the hour before the start. Only new tickers are fetched."""
    data = cache.get(KEY_PRICES) or {}
    todo = [(t, ts) for t, ts in want if t not in data]
    by_day = defaultdict(list)
    for t, ts in todo:
        by_day[int(ts // 86400)].append((t, ts))
    calls = 0
    for day, ws in sorted(by_day.items()):
        for i in range(0, len(ws), 100):
            chunk = dict(ws[i:i + 100])
            params = {"market_tickers": ",".join(chunk), "start_ts": day * 86400 - 8 * 3600, "end_ts": day * 86400 + 86400,
                      "period_interval": 60, "include_latest_before_start": "true"}
            try:
                d = get_json(base + "/markets/candlesticks", params=params)
                calls += 1
            except Exception as e:  # noqa: BLE001
                log(f"backtest: candlesticks failed {e!r}"[:200])
                continue
            mk = d.get("markets") or []
            if isinstance(mk, dict):
                mk = [{"market_ticker": k, "candlesticks": v} for k, v in mk.items()]
            for m in mk:
                t = m.get("market_ticker") or m.get("ticker")
                if t not in chunk:
                    continue
                cs = sorted(m.get("candlesticks") or [], key=lambda c: c.get("end_period_ts") or 0)
                before = [c for c in cs if (c.get("end_period_ts") or 0) <= chunk[t]]
                bid, ask = (_close(before[-1], "yes_bid"), _close(before[-1], "yes_ask")) if before else (None, None)
                ok = bid and ask and 0 < bid < ask < 1 and ask - bid <= 0.30
                data[t] = [bid if ok else None, ask if ok else None, chunk[t]]
            for t in chunk:
                data.setdefault(t, [None, None, chunk[t]])     # nothing usable: don't ask again
            time.sleep(0.05)
    cut = time.time() - (DAYS + 2) * 86400
    data = {t: v for t, v in data.items() if v[2] >= cut}
    cache.put(KEY_PRICES, data)
    return {t: (v[0], v[1]) for t, v in data.items() if v[0] is not None}, calls


def forecasts(ms, group, R):
    """Each match's chance for its first-listed side before it was played, replaying results like elo.rate."""
    r, n, out = {}, defaultdict(int), {}
    hr = R["h"] / R["s"] if (group not in elo.NEUTRAL and R["h"]) else 0.0
    for m in sorted(ms, key=lambda x: (x["date"], x["eid"])):
        a, b = m["a"], m["b"]
        ra = r.setdefault(a, elo.start(m["lg"], group))
        rb = r.setdefault(b, elo.start(m["lg"], group))
        hs = 0 if m["home"] is None else (1 if m["home"] == "a" else -1)
        out[(m["lg"], m["eid"])] = (elo.expected(R["s"] * (ra - rb) + R["h"] * hs), n[a], n[b], m["sa"])
        e = elo.expected(ra - rb + hr * hs)
        r[a] = ra + elo.k_factor(n[a]) * (m["sa"] - e)
        r[b] = rb - elo.k_factor(n[b]) * (m["sa"] - e)
        n[a] += 1
        n[b] += 1
    return out


def _ll(p, y):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _bets(xs, blend):
    """Buy the better side whenever it shows an edge after the fee, under the Picks page's price and sample rules."""
    pnl = []
    for x in xs:
        e = model.edges(blend(x), x["ask"], 1 - x["bid"])
        if not e:
            continue
        side = max(e, key=e.get)
        price = x["ask"] if side == "yes" else 1 - x["bid"]
        if e[side] < 0.001 or not (0.2 <= price <= 0.8) or min(x["na"], x["nb"]) < 8 or x["ask"] - x["bid"] > 0.06:
            continue
        won = x["y"] if side == "yes" else 1 - x["y"]
        pnl.append(won - price - model.kalshi_fee(price))
    if not pnl:
        return {"n": 0}
    mu = sum(pnl) / len(pnl)
    sd = (sum((v - mu) ** 2 for v in pnl) / max(1, len(pnl) - 1)) ** 0.5
    return {"n": len(pnl), "per_bet": round(mu, 4), "se": round(sd / len(pnl) ** 0.5, 4)}


def summary(xs):
    n = len(xs)
    mkt = sum(_ll(x["mid"], x["y"]) for x in xs) / n
    rat = sum(_ll(x["pe"], x["y"]) for x in xs) / n
    best_w, best = 0.0, mkt
    for i in range(1, 51):
        w = i / 50
        v = sum(_ll(x["mid"] + w * (x["pe"] - x["mid"]), x["y"]) for x in xs) / n
        if v < best:
            best_w, best = w, v
    return {"n": n, "days": DAYS, "mkt": round(mkt, 4), "rat": round(rat, 4), "w": best_w,
            "gain": round(mkt - best, 5), "bets": _bets(xs, lambda x: x["pe"]),
            "bets_w": _bets(xs, lambda x: x["mid"] + 0.3 * (x["pe"] - x["mid"]))}


def run(base, matches, group_of, draw_rate, series_of, skill_of, weight, log):
    """-> ({group: [(mid, forecast, default weight, result, (series, key))]}, {group: summary}).
    weight(mid, forecast, n_min, skill, liquid) is the edge's default weight on the ratings (sports.default_weight)."""
    res = cache.get(KEY_RESULT)
    if res and time.time() - res.get("at", 0) < TTL:
        return {g: [tuple(o[:4]) + (tuple(o[4]),) for o in v] for g, v in res["obs"].items()}, res["summary"]
    t0 = time.time()
    F = {}
    for pl, ms in matches.items():
        R = elo.rate(ms, group_of[pl])
        for k, v in forecasts(ms, group_of[pl], R).items():
            F[k] = (pl, v)
    st, pages = starts(base, log)
    now = time.time()
    want, meta = [], {}
    for (lg, key), (pl, (pa, na, nb, sa)) in F.items():
        s = series_of.get((lg, key))
        iso = st.get(f"{s}-{key}") if s else None
        if not iso:
            continue
        ts = _ts(iso)
        if not (now - DAYS * 86400 <= ts <= now - 3 * 3600):
            continue
        t = f"{s}-{key}-{series_of[(lg, key, 'a')]}"
        want.append((t, ts))
        meta[t] = (lg, key, pl)
    px, calls = prices(base, want, log)
    obs, rows = defaultdict(list), defaultdict(list)
    for t, (lg, key, pl) in meta.items():
        if t not in px:
            continue
        bid, ask = px[t]
        pa, na, nb, sa = F[(lg, key)][1]
        pe = min(max(pa - 0.5 * (draw_rate.get(lg) or 0.0), 0.01), 0.99)
        mid = (bid + ask) / 2
        x = {"mid": mid, "bid": bid, "ask": ask, "pe": pe, "na": na, "nb": nb, "y": 1.0 if sa == 1.0 else 0.0}
        g = group_of[pl]
        rows[g].append(x)
        k = weight(mid, pe, min(na, nb), skill_of.get(pl) or 0.0, ask - bid <= 0.06)
        obs[g].append((round(mid, 4), round(pe, 4), round(k, 4), x["y"], (t.split("-")[0], key)))
    summ = {g: summary(xs) for g, xs in rows.items() if len(xs) >= 50}
    cache.put(KEY_RESULT, {"at": time.time(), "obs": obs, "summary": summ})
    log(f"backtest: {sum(len(v) for v in rows.values()):,} matches with a pre-match price ({pages} milestone pages, "
        f"{calls} price calls, {time.time() - t0:.0f}s): " + ", ".join(
            f"{g} {v['n']} price {v['mkt']} ratings {v['rat']} w{v['w']} bets {v['bets'].get('n', 0)} "
            f"{v['bets'].get('per_bet', 0) * 100:+.1f}c" for g, v in sorted(summ.items(), key=lambda kv: -kv[1]['n'])))
    return dict(obs), summ
