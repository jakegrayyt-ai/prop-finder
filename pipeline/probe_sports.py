"""Probe for adding every Kalshi sport to the props board. Writes ./debug. Never crashes.

1. Settled history: how far back /markets?status=settled goes per series, what a settled market looks like,
   and whether the /historical endpoints exist.
2. Start times: /milestones and /events.
3. Open game markets for every league the arbitrage scanner knows (counts, prices, lines).
"""
import datetime as dt
import json
import os
import time
import traceback
from collections import Counter, defaultdict

from .net import get_json

OUT = "debug"
K = "https://api.elections.kalshi.com/trade-api/v2"
_log = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    _log.append(s)


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def settled(series, pages=25, **extra):
    out, cursor, n = [], None, 0
    for _ in range(pages):
        p = {"series_ticker": series, "status": "settled", "limit": 1000, **extra}
        if cursor:
            p["cursor"] = cursor
        d = get_json(K + "/markets", params=p)
        mks = d.get("markets") or []
        out.extend(mks)
        n += 1
        cursor = d.get("cursor")
        if not cursor or len(mks) < 1000:
            cursor = None
            break
        time.sleep(0.15)
    return out, n, bool(cursor)


def history():
    test = ["KXEPLGAME", "KXEPLTOTAL", "KXEPLSPREAD", "KXEPLBTTS", "KXUCLGAME", "KXNCAAFGAME", "KXNCAAFTOTAL",
            "KXNCAAFSPREAD", "KXNCAAFTEAMTOTAL", "KXNCAAMBGAME", "KXNCAAMBTOTAL", "KXATPMATCH", "KXCS2GAME",
            "KXKHLGAME", "KXUFCFIGHT", "KXT20MATCH", "KXEUROLEAGUEGAME", "KXMLSGAME", "KXITFMATCH", "KXLALIGAGAME"]
    summary, samples = {}, {}
    for s in test:
        try:
            t0 = time.time()
            mks, pages, more = settled(s)
            closes = sorted(m.get("close_time") or "" for m in mks if m.get("close_time"))
            evs = {m.get("event_ticker") for m in mks}
            summary[s] = {"markets": len(mks), "pages": pages, "more": more, "events": len(evs),
                          "first_close": closes[0] if closes else None, "last_close": closes[-1] if closes else None,
                          "results": dict(Counter(str(m.get("result")) for m in mks)),
                          "status": dict(Counter(str(m.get("status")) for m in mks)), "secs": round(time.time() - t0, 1)}
            samples[s] = mks[:3]
            log("OK  ", s, json.dumps(summary[s]))
        except Exception as e:  # noqa: BLE001
            summary[s] = {"error": repr(e)[:300]}
            log("FAIL", s, repr(e)[:300])
        time.sleep(0.3)
    save("settled_summary.json", summary)
    save("settled_samples.json", samples)
    # a recent-only page (incremental fetch)
    try:
        since = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).timestamp())
        mks, pages, more = settled("KXEPLGAME", pages=3, min_close_ts=since)
        log("OK   min_close_ts KXEPLGAME last 3 days:", len(mks), "markets", pages, "pages")
    except Exception as e:  # noqa: BLE001
        log("FAIL min_close_ts", repr(e)[:300])
    for path, params in (("/historical/cutoff", None), ("/historical/markets", {"series_ticker": "KXEPLGAME", "limit": 50})):
        try:
            d = get_json(K + path, params=params)
            save("hist_" + path.strip("/").replace("/", "_") + ".json",
                 {"keys": list(d.keys()), "n": len(d.get("markets") or []), "head": json.dumps(d)[:3000]})
            log("OK  ", path, list(d.keys()))
        except Exception as e:  # noqa: BLE001
            log("FAIL", path, repr(e)[:200])


def starts():
    now = dt.datetime.now(dt.timezone.utc)
    for name, params in (("milestones_all", {"limit": 100}),
                         ("milestones_sports", {"limit": 100, "category": "Sports",
                                                "minimum_start_date": now.isoformat(timespec="seconds").replace("+00:00", "Z")})):
        try:
            d = get_json(K + "/milestones", params=params)
            ms = d.get("milestones") or []
            save(name + ".json", {"keys": list(d.keys()), "n": len(ms), "cursor": d.get("cursor"), "first": ms[:5],
                                  "types": dict(Counter(str(m.get("type")) for m in ms))})
            log("OK  ", name, len(ms), dict(Counter(str(m.get("type")) for m in ms)))
        except Exception as e:  # noqa: BLE001
            log("FAIL", name, repr(e)[:300])
    for s in ("KXEPLGAME", "KXNCAAFGAME", "KXATPMATCH", "KXCS2GAME", "KXNCAAMBGAME", "KXUFCFIGHT"):
        try:
            d = get_json(K + "/markets", params={"series_ticker": s, "status": "open", "limit": 5})
            mk = (d.get("markets") or [{}])[0]
            ev = mk.get("event_ticker")
            e = get_json(f"{K}/events/{ev}")
            save(f"event_{s}.json", {"market": mk, "event": e.get("event"), "keys": list(e.keys())})
            log("OK   event", s, ev, (e.get("event") or {}).get("sub_title"))
        except Exception as e:  # noqa: BLE001
            log("FAIL event", s, repr(e)[:200])


def mid(q):
    yb, ya = q.get("yb"), q.get("ya")
    return (yb + ya) / 2 if yb and ya and 0 < yb < ya < 1 else None


def open_markets():
    from . import arb
    games = arb.kalshi_games()
    by = defaultdict(lambda: Counter())
    for g in games:
        c = by[g["league"]]
        c["games"] += 1
        c["ml"] += len(g["ml"]) + (1 if g.get("tie") else 0)
        c["btts"] += 1 if g.get("btts") else 0
        for k in ("spread", "total", "teamtotal", "spread1h", "total1h"):
            c[k] += len(g[k])
        for k in ("spread", "total", "teamtotal"):
            for item in g[k]:
                q = item[-1]
                m = mid(q)
                if m is not None and 0.04 <= m <= 0.96 and (q["ya"] - q["yb"]) <= 0.30:
                    c[k + "_ok"] += 1
    save("open_by_league.json", {lg: dict(c) for lg, c in sorted(by.items())})
    save("open_games_sample.json", [g for g in games if g["league"] in ("epl", "cfb", "atp", "cs2", "ufc", "cbb", "t20", "khl")][:40])
    tot = Counter()
    for c in by.values():
        tot.update(c)
    log("open totals", json.dumps(dict(tot)))


def main():
    t0 = time.time()
    for fn in (starts, history, open_markets):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log("CRASH", fn.__name__, traceback.format_exc())
    log(f"done in {time.time() - t0:.0f}s")
    save("_log.json", _log)


if __name__ == "__main__":
    main()
