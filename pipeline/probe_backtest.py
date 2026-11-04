"""Backtest (wip only): would the ratings have beaten Kalshi's pre-match prices on the last month's matches?

For every settled winner market from the last ~30 days with a known start time: the ratings' forecast before the
match (replaying results in order, exactly as the site does), and Kalshi's bid and ask in the hour before the
start (batch candlesticks). Then, per sport: log loss of the price alone, the ratings alone and blends of the two,
the weight that predicts best, and what buying every positive edge after fees would have returned.
"""
import datetime as dt
import json
import math
import os
import time
from collections import defaultdict

from . import cache, elo, model, sports
from .net import get_json
from .sports import BASE

OUT = os.environ.get("PROP_OUT", "debug")
DAYS = int(os.environ.get("BT_DAYS", 30))
LINES = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LINES.append(s)


def num(v, cents_field):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 100 if cents_field else x


def close_of(c, key):
    side = c.get(key) or {}
    if side.get("close_dollars") is not None:
        return num(side["close_dollars"], False)
    if side.get("close") is not None:
        return num(side["close"], True)
    return None


def starts_since(days):
    out, cursor, pages = {}, None, 0
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")
    for _ in range(900):
        params = {"limit": 100, "category": "Sports", "minimum_start_date": since}
        if cursor:
            params["cursor"] = cursor
        d = get_json(BASE + "/milestones", params=params)
        pages += 1
        for m in d.get("milestones") or []:
            start = m.get("start_date")
            evs = set(m.get("related_event_tickers") or []) | set(m.get("primary_event_tickers") or [])
            main = (m.get("details") or {}).get("main_game_event_ticker")
            if main:
                evs.add(main)
            for ev in evs:
                out[ev] = start
        cursor = d.get("cursor")
        if not cursor or not d.get("milestones"):
            break
    log(f"milestones: {len(out):,} event tickers with a start, {pages} pages")
    return out


def preds(ms, group, R):
    """Each match's forecast before it was played, replaying the results in order like elo.rate."""
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


def ll(p, y):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def kraw(x, m=1.0):
    mid, pe, na, nb, skill, liquid = x["mid"], x["pe"], x["na"], x["nb"], x["skill"], x["liquid"]
    n_min = min(na, nb)
    low = n_min < 6 or not liquid or skill < 0.02
    tail = min(1.0, mid * (1 - mid) / 0.16)
    gap = pe - mid
    return m * (sports.ELO_K[0] if liquid else sports.ELO_K[1]) * (0.5 if low else 1.0) * tail \
        * min(1.0, n_min / sports.ELO_FULL_N) * min(1.0, skill / sports.ELO_FULL_SKILL) \
        * math.exp(-max(0.0, abs(gap) - sports.ELO_DECAY) / sports.ELO_DECAY)


def bets(xs, blend, picks_rules=True):
    """Buy the better side whenever it shows a positive edge after the fee; return count, profit, sd."""
    pnl = []
    for x in xs:
        pb = blend(x)
        e = model.edges(pb, x["ask"], 1 - x["bid"])
        if not e:
            continue
        side = max(e, key=e.get)
        if e[side] < 0.001:
            continue
        price = x["ask"] if side == "yes" else 1 - x["bid"]
        if picks_rules and (not (0.2 <= price <= 0.8) or min(x["na"], x["nb"]) < 8 or (x["ask"] - x["bid"]) > 0.06):
            continue
        fee = model.kalshi_fee(price)
        won = x["y"] if side == "yes" else 1 - x["y"]
        pnl.append(won - price - fee)
    if not pnl:
        return {"n": 0}
    mu = sum(pnl) / len(pnl)
    sd = (sum((v - mu) ** 2 for v in pnl) / max(1, len(pnl) - 1)) ** 0.5
    return {"n": len(pnl), "profit": round(sum(pnl), 2), "per_bet": round(mu, 4), "se": round(sd / len(pnl) ** 0.5, 4)}


def summarize(name, xs):
    if len(xs) < 30:
        return {"n": len(xs)}
    n = len(xs)
    L_mkt = sum(ll(x["mid"], x["y"]) for x in xs) / n
    L_elo = sum(ll(x["pe"], x["y"]) for x in xs) / n
    ws = [i / 50 for i in range(0, 51)]
    L_w = {w: sum(ll(x["mid"] + w * (x["pe"] - x["mid"]), x["y"]) for x in xs) / n for w in ws}
    w_best = min(L_w, key=L_w.get)
    ms = [i / 10 for i in range(0, 41)]
    L_m = {m: sum(ll(x["mid"] + kraw(x, m) * (x["pe"] - x["mid"]), x["y"]) for x in xs) / n for m in ms}
    m_best = min(L_m, key=L_m.get)
    gaps = sorted(abs(x["pe"] - x["mid"]) for x in xs)
    out = {"n": n, "ll_market": round(L_mkt, 4), "ll_ratings": round(L_elo, 4),
           "best_w": w_best, "ll_best_w": round(L_w[w_best], 4), "gain_best_w": round(L_mkt - L_w[w_best], 5),
           "ll_w": {str(w): round(L_w[w], 4) for w in ws if round(w * 50) in (2, 5, 10, 15, 25)},
           "best_m": m_best, "ll_default": round(L_m[1.0], 4), "gain_default": round(L_mkt - L_m[1.0], 5),
           "gain_best_m": round(L_mkt - L_m[m_best], 5), "median_gap": round(gaps[n // 2], 3),
           "bets_default": bets(xs, lambda x: x["mid"] + kraw(x) * (x["pe"] - x["mid"])),
           "bets_best_m": bets(xs, lambda x: x["mid"] + kraw(x, m_best) * (x["pe"] - x["mid"])),
           "bets_w0.3": bets(xs, lambda x: x["mid"] + 0.3 * (x["pe"] - x["mid"])),
           "bets_ratings_only": bets(xs, lambda x: x["pe"])}
    log(f"{name}: {json.dumps(out)}")
    return out


def main():
    t0 = time.time()
    leagues = sports.league_series(log)
    pool_of = {lg: elo.pool(lg, c["group"]) for lg, c in leagues.items()}
    past = defaultdict(lambda: defaultdict(dict))
    old = defaultdict(dict)
    series_of = {}
    for lg, c in leagues.items():
        for s, kind in c["series"]:
            if kind != "win":
                continue
            for key_, store in ((f"kalshi/settled3/{s}", past[lg]["win"]), (f"kalshi/hist-win/{s}", old[lg])):
                d = cache.entry(key_)[0] or {}
                for key, e in (d.get("ev") or {}).items():
                    cur = store.setdefault(key, {})
                    for f, v in e.items():
                        if f == "n":
                            cur.setdefault("n", {}).update(v)
                        else:
                            cur[f] = v
                    series_of[(lg, key)] = s
    live_pools = set(pool_of.values())
    matches, draw_rate, group_of = sports.pool_matches(leagues, pool_of, live_pools, past, old)
    log(f"{sum(len(v) for v in matches.values()):,} matches in {len(matches)} pools ({time.time() - t0:.0f}s)")
    P, skills = {}, {}
    for pl, ms in matches.items():
        R = elo.rate(ms, group_of[pl])
        skills[pl] = R["skill"] or 0.0
        for k, v in preds(ms, group_of[pl], R).items():
            P[k] = (pl, v)
    starts = starts_since(DAYS + 1)
    now = time.time()
    cut0 = now - DAYS * 86400
    want = []                                   # (ticker, start ts, lg, key)
    for (lg, key), (pl, (pe, na, nb, sa)) in P.items():
        s = series_of.get((lg, key))
        st = starts.get(f"{s}-{key}") if s else None
        if not st:
            continue
        ts = dt.datetime.fromisoformat(st.replace("Z", "+00:00")).timestamp()
        if not (cut0 <= ts <= now - 3 * 3600):
            continue
        e = past[lg]["win"].get(key) or old[lg].get(key) or {}
        codes = [c for c in (e.get("n") or {}) if c != "TIE"]
        if len(codes) != 2:
            continue
        a, b = sports.order_codes(key, codes)
        want.append((f"{s}-{key}-{a}", ts, lg, key))
    log(f"{len(want):,} settled matches from the last {DAYS} days with a start time ({time.time() - t0:.0f}s)")
    by_day = defaultdict(list)
    for w in want:
        by_day[int(w[1] // 86400)].append(w)
    price = {}
    shown = False
    calls = 0
    for day, ws in sorted(by_day.items()):
        for i in range(0, len(ws), 100):
            chunk = ws[i:i + 100]
            params = {"market_tickers": ",".join(t for t, *_ in chunk), "start_ts": day * 86400 - 8 * 3600,
                      "end_ts": day * 86400 + 86400, "period_interval": 60, "include_latest_before_start": "true"}
            try:
                d = get_json(BASE + "/markets/candlesticks", params=params)
                calls += 1
            except Exception as e:  # noqa: BLE001
                log(f"candlesticks failed {e!r}"[:300])
                continue
            if not shown:
                log("candlesticks sample: " + json.dumps(d)[:1500])
                shown = True
            mk = d.get("markets") or d.get("market_candlesticks") or []
            if isinstance(mk, dict):
                mk = [{"market_ticker": k, "candlesticks": v} for k, v in mk.items()]
            info = {t: ts for t, ts, *_ in chunk}
            for m in mk:
                t = m.get("market_ticker") or m.get("ticker")
                if t not in info:
                    continue
                cs = sorted(m.get("candlesticks") or [], key=lambda c: c.get("end_period_ts") or 0)
                before = [c for c in cs if (c.get("end_period_ts") or 0) <= info[t]]
                if not before:
                    continue
                c = before[-1]
                bid, ask = close_of(c, "yes_bid"), close_of(c, "yes_ask")
                if bid and ask and 0 < bid < ask < 1 and ask - bid <= 0.30:
                    price[t] = (bid, ask)
            time.sleep(0.05)
    log(f"pre-match prices for {len(price):,} markets from {calls} calls ({time.time() - t0:.0f}s)")
    rows = defaultdict(list)
    for t, ts, lg, key in want:
        if t not in price:
            continue
        pl, (pe_a, na, nb, sa) = P[(lg, key)]
        bid, ask = price[t]
        dr = draw_rate.get(lg) or 0.0
        pe = min(max(pe_a - 0.5 * dr, 0.01), 0.99)
        x = {"mid": (bid + ask) / 2, "bid": bid, "ask": ask, "pe": pe, "na": na, "nb": nb, "y": 1.0 if sa == 1.0 else 0.0,
             "skill": skills[pl], "liquid": ask - bid <= 0.06}
        g = group_of[pl]
        rows[g].append(x)
        rows["pool:" + pl].append(x)
    res = {}
    for name, xs in sorted(rows.items(), key=lambda kv: -len(kv[1])):
        if name.startswith("pool:") and len(xs) < 150:
            continue
        res[name] = summarize(name, xs)
        est = [x for x in xs if min(x["na"], x["nb"]) >= 8]
        if len(est) >= 100:
            res[name + " (both 8+ results)"] = summarize(name + " (both 8+ results)", est)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "backtest.json"), "w") as f:
        json.dump({"results": res, "log": LINES}, f, indent=1)
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
