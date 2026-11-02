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


def get(url, params=None, name=None, keep=True):
    try:
        r = S.get(url, params=params, timeout=25, headers={"Origin": ORIGIN})
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
        st, body, cors = get(f"{KA}/markets", {"series_ticker": s, "status": "open", "limit": 1000}, keep=False)
        ms = (body or {}).get("markets") or [] if isinstance(body, dict) else []
        counts[s] = len(ms)
        save(f"k_{s}.json", {"count": len(ms), "sample": ms[:6], "cors": cors})
        if ms:
            ev = ms[0].get("event_ticker")
            get(f"{KA}/events/{ev}", {"with_nested_markets": "true"}, name=f"k_event_{s}.json")
        time.sleep(0.1)
    log("kalshi counts", counts)
    for s in ("KXNBAGAME", "KXATPMATCH"):
        get(f"{KA}/series/{s}", name=f"k_series_{s}.json")
    preflight(f"{KA}/markets?limit=1")


def main():
    t0 = time.time()
    for fn in (polymarket, kalshi):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log("CRASH", fn.__name__, traceback.format_exc())
    log(f"done {time.time() - t0:.1f}s")
    save("_log.json", _log)


if __name__ == "__main__":
    main()
