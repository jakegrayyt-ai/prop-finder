"""One-off discovery for the arbitrage scanner: Polymarket US + Kalshi game markets.

Writes JSON samples to ./debug. Never crashes.
"""
import json
import os
import time
import traceback

import requests

from .net import UA

OUT = "debug"
PM = "https://gateway.polymarket.us"
KA = "https://api.elections.kalshi.com/trade-api/v2"
ORIGIN = "https://jakegrayyt-ai.github.io"
KALSHI_SERIES = [
    "KXNFLGAME", "KXNBAGAME", "KXNHLGAME", "KXNCAAFGAME", "KXNCAAMBGAME",
    "KXATPMATCH", "KXWTAMATCH", "KXATPCHALLENGERMATCH",
    "KXNFLSPREAD", "KXNFLTOTAL", "KXNBASPREAD", "KXNBATOTAL", "KXNHLSPREAD", "KXNHLTOTAL",
    "KXNCAAFSPREAD", "KXNCAAFTOTAL", "KXNCAAMBSPREAD", "KXNCAAMBTOTAL",
]
_log = []
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json"})


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    _log.append(s)


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def get(url, params=None, name=None, keep=True, origin=True):
    try:
        r = S.get(url, params=params, timeout=25, headers={"Origin": ORIGIN} if origin else {})
        cors = {k: v for k, v in r.headers.items() if k.lower().startswith("access-control")}
        try:
            body = r.json()
        except ValueError:
            body = r.text[:2000]
        log(f"{r.status_code} {r.url} cors={cors}")
        if name and keep:
            save(name, {"status": r.status_code, "url": r.url, "cors": cors, "body": body})
        return r.status_code, body, cors
    except Exception as e:  # noqa: BLE001
        log(f"ERR {url} {e!r}"[:300])
        return None, None, {}


def preflight(url):
    try:
        r = S.options(url, timeout=20, headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"})
        cors = {k: v for k, v in r.headers.items() if k.lower().startswith("access-control")}
        log(f"OPTIONS {r.status_code} {url} cors={cors}")
        return cors
    except Exception as e:  # noqa: BLE001
        log(f"OPTIONS ERR {url} {e!r}"[:200])
        return {}


def polymarket():
    out = {}
    for typ in ("MONEYLINE", "SPREAD", "TOTAL"):
        allm, offset = [], 0
        for _ in range(15):
            st, body, cors = get(f"{PM}/v1/markets", {"categories": "sports", "sportsMarketTypes": typ, "active": "true",
                                                    "closed": "false", "limit": 200, "offset": offset}, keep=False)
            if st != 200 or not isinstance(body, dict):
                save(f"pm_markets_{typ}_error.json", {"status": st, "body": body})
                break
            ms = body.get("markets") or []
            allm.extend(ms)
            if len(ms) < 200:
                break
            offset += 200
            time.sleep(0.2)
        out[typ] = len(allm)
        save(f"pm_markets_{typ}.json", {"count": len(allm), "keys": sorted({k for m in allm for k in m}),
                                        "sample": allm[:25], "tail": allm[-5:]})
        if allm:
            # what leagues / categories show up
            cats = {}
            for m in allm:
                k = f"{m.get('category')}|{m.get('subcategory')}"
                cats[k] = cats.get(k, 0) + 1
            save(f"pm_cats_{typ}.json", cats)
    log("polymarket counts", out)
    # one full market + bbo + book
    try:
        sample = json.load(open(os.path.join(OUT, "pm_markets_MONEYLINE.json")))["sample"]
    except (OSError, ValueError, KeyError):
        sample = []
    for m in sample[:3]:
        slug = m.get("slug")
        if not slug:
            continue
        get(f"{PM}/v1/market/slug/{slug}", name=f"pm_market_{slug[:40]}.json")
        get(f"{PM}/v1/markets/{slug}/bbo", name=f"pm_bbo_{slug[:40]}.json")
        get(f"{PM}/v1/markets/{slug}/book", name=f"pm_book_{slug[:40]}.json")
    for path, params in [("/v1/events", {"limit": 10, "active": "true", "categories": "sports"}),
                         ("/v1/events", {"limit": 5}),
                         ("/v1/series", {"limit": 50}),
                         ("/v1/sports", None), ("/v1/leagues", None), ("/v1/sports/leagues", None),
                         ("/v1/teams", {"limit": 20}), ("/v1/sports/teams", {"limit": 20}),
                         ("/v1/games", {"limit": 10}), ("/v1/sports/games", {"limit": 10}),
                         ("/v1/search", {"query": "Lakers"}), ("/v1/search", {"q": "Lakers"})]:
        get(f"{PM}{path}", params, name="pm_probe_" + path.strip("/").replace("/", "_") + ("_" + "_".join(f"{k}{v}" for k, v in (params or {}).items()))[:60] + ".json")
    preflight(f"{PM}/v1/markets?limit=1")


def kalshi():
    counts = {}
    for s in KALSHI_SERIES:
        st, body, cors = get(f"{KA}/markets", {"series_ticker": s, "status": "open", "limit": 1000}, keep=False, origin=False)
        ms = (body or {}).get("markets") or [] if isinstance(body, dict) else []
        counts[s] = len(ms)
        save(f"k_{s}.json", {"count": len(ms), "sample": ms[:6], "cors": cors})
        if ms:
            ev = ms[0].get("event_ticker")
            get(f"{KA}/events/{ev}", {"with_nested_markets": "true"}, name=f"k_event_{s}.json", origin=False)
        time.sleep(0.1)
    log("kalshi counts", counts)
    for s in ("KXNBAGAME", "KXATPMATCH"):
        get(f"{KA}/series/{s}", name=f"k_series_{s}.json", origin=False)
    preflight(f"{KA}/markets?limit=1")


def round2():
    probes = [
        ("/v1/events", {"closed": "false", "limit": 100}),
        ("/v1/events", {"closed": "false", "active": "true", "limit": 100, "offset": 100}),
        ("/v1/events", {"closed": "false", "tagId": 5, "limit": 100}),
        ("/v1/events", {"closed": "false", "seriesSlug": "nba-2025", "limit": 100}),
        ("/v1/events", {"closed": "false", "startDateMin": "2026-11-02T00:00:00Z", "limit": 100}),
        ("/v1/events", {"closed": "false", "orderBy": "startTime", "orderDirection": "asc", "limit": 100}),
        ("/v1/markets", {"limit": 100}),
        ("/v1/markets", {"closed": "false", "limit": 100}),
        ("/v1/markets", {"closed": "false", "limit": 100, "sportsMarketTypes": "moneyline"}),
        ("/v1/markets", {"closed": "false", "limit": 100, "categories": "sports"}),
        ("/v1/markets", {"closed": "false", "limit": 100, "tagId": 5}),
        ("/v1/event/slug/nba-lal-pho-2026-11-15", None),
        ("/v1/events/slug/nba-lal-pho-2026-11-15", None),
        ("/v1/markets/aec-nba-lal-pho-2026-11-15/bbo", None),
        ("/v1/markets/aec-nba-lal-pho-2026-11-15/book", None),
        ("/v1/search", {"query": "Thunder"}),
        ("/v1/search", {"query": "Ohio State"}),
        ("/v1/search", {"query": "Sinner"}),
    ]
    for i, (path, params) in enumerate(probes):
        st, body, cors = get(f"{PM}{path}", params, name=f"r2_{i:02d}.json")
        if isinstance(body, dict):
            for k, v in body.items():
                if isinstance(v, list):
                    first = v[0] if v else None
                    log(f"   r2_{i:02d} {k}: n={len(v)} first_slug={(first or {}).get('slug') if isinstance(first, dict) else None}"
                        f" first_start={(first or {}).get('startTime') if isinstance(first, dict) else None}")
        time.sleep(0.2)


def round3():
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    lo = (now - dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (now + dt.timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tests = [
        {"closed": "false", "limit": 100, "sportsMarketTypes": "SPORTS_MARKET_TYPE_MONEYLINE"},
        {"closed": "false", "limit": 100, "sportsMarketTypes": "MONEYLINE"},
        {"closed": "false", "limit": 100, "marketType": "moneyline"},
        {"closed": "false", "limit": 100, "marketTypes": "moneyline"},
        {"closed": "false", "limit": 100, "orderBy": "gameStartTime", "orderDirection": "asc", "gameStartTimeMin": lo},
        {"closed": "false", "limit": 100, "startDateMin": lo},
        {"closed": "false", "limit": 100, "endDateMin": lo, "endDateMax": hi},
        {"closed": "false", "limit": 100, "slug": "aec-nba-lal-pho-2026-11-15"},
        {"closed": "false", "limit": 100, "slugs": "aec-nba-lal-pho-2026-11-15"},
    ]
    from collections import Counter
    for i, params in enumerate(tests):
        st, body, _ = get(f"{PM}/v1/markets", params, keep=False)
        ms = (body or {}).get("markets") if isinstance(body, dict) else None
        if ms is None:
            log(f"   r3 test {i} status={st} body={str(body)[:120]}")
            continue
        c = Counter(m.get("marketType") for m in ms)
        log(f"   r3 test {i} n={len(ms)} types={dict(c)} first={ms[0].get('slug') if ms else None} gst={ms[0].get('gameStartTime') if ms else None}")
        time.sleep(0.15)
    # count every open market (paging) and what types they are
    total, types, quoted, offset, t1 = 0, Counter(), 0, 0, time.time()
    sample_game = []
    while offset < 30000:
        st, body, _ = get(f"{PM}/v1/markets", {"closed": "false", "limit": 100, "offset": offset}, keep=False)
        ms = (body or {}).get("markets") if isinstance(body, dict) else None
        if not ms:
            break
        for m in ms:
            types[m.get("marketType")] += 1
            if m.get("bestAskQuote") or m.get("bestBidQuote"):
                quoted += 1
            if m.get("marketType") in ("moneyline", "spread", "total", "spreads", "totals") and len(sample_game) < 40:
                sample_game.append({k: m.get(k) for k in ("slug", "marketType", "sportsMarketTypeV2", "line", "gameStartTime",
                                                         "bestAskQuote", "bestBidQuote", "feeCoefficient", "outcomes",
                                                         "question", "title", "titleShort", "subtitle", "eventSubcategory")} | {
                    "sides": [(sd.get("description"), sd.get("long"), (sd.get("team") or {}).get("abbreviation"),
                               (sd.get("team") or {}).get("league"), (sd.get("team") or {}).get("name")) for sd in m.get("marketSides") or []]})
        total += len(ms)
        if len(ms) < 100:
            break
        offset += 100
    log(f"   r3 all open markets: {total} in {time.time()-t1:.1f}s types={dict(types)} quoted={quoted} pages={offset//100+1}")
    save("r3_game_markets_sample.json", sample_game)
    # events in the next 8 days
    n, off, prefixes = 0, 0, Counter()
    while off < 5000:
        st, body, _ = get(f"{PM}/v1/events", {"closed": "false", "limit": 100, "offset": off, "startDateMin": lo, "startDateMax": hi}, keep=False)
        evs = (body or {}).get("events") if isinstance(body, dict) else None
        if not evs:
            break
        for e in evs:
            prefixes[e["slug"].split("-")[0]] += 1
        n += len(evs)
        if len(evs) < 100:
            break
        off += 100
    log(f"   r3 events next 8 days: {n} prefixes={prefixes.most_common(40)}")


def main():
    t0 = time.time()
    for fn in (round3,):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log("CRASH", fn.__name__, traceback.format_exc())
    log(f"done {time.time() - t0:.1f}s")
    save("_log.json", _log)


if __name__ == "__main__":
    main()
