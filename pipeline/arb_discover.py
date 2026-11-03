"""One-off probe (round 6): can a browser read Kalshi directly, and how heavy is a Polymarket US live check?

Writes JSON files to ./debug for reading back from the debug branch.
"""
import datetime as dt
import json
import os
import traceback

import requests

from .net import UA, get_json

PM = "https://gateway.polymarket.us"
OUT = "debug"
os.makedirs(OUT, exist_ok=True)
LOG = []
ORIGIN = "https://jakegrayyt-ai.github.io"


def log(m):
    print(m, flush=True)
    LOG.append(str(m))


def probe(name, url, params=None, origin=ORIGIN, method="GET", extra=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if origin:
        h["Origin"] = origin
    if extra:
        h.update(extra)
    try:
        r = requests.request(method, url, params=params, headers=h, timeout=30)
        cors = {k: v for k, v in r.headers.items() if k.lower().startswith("access-control") or k.lower() in ("vary", "cache-control", "server", "cf-cache-status")}
        log(f"{name}: {r.status_code} bytes={len(r.content)} {cors} :: {r.text[:160]!r}")
        return r
    except Exception as e:  # noqa: BLE001
        log(f"{name}: error {e!r}"[:300])
        return None


def main():
    now = dt.datetime.now(dt.timezone.utc)
    log(f"now {now.isoformat()}")
    tk = "KXNBAGAME-26NOV05MIAGSW-MIA"
    ev = "KXNBAGAME-26NOV05MIAGSW"
    for base in ("https://api.elections.kalshi.com", "https://external-api.kalshi.com", "https://trading-api.kalshi.com",
                 "https://api.kalshi.com"):
        probe(f"{base} markets?tickers no-origin", f"{base}/trade-api/v2/markets", {"tickers": tk}, origin=None)
        probe(f"{base} markets?tickers origin", f"{base}/trade-api/v2/markets", {"tickers": tk})
        probe(f"{base} markets/{{t}} origin", f"{base}/trade-api/v2/markets/{tk}")
        probe(f"{base} OPTIONS markets", f"{base}/trade-api/v2/markets", {"tickers": tk}, method="OPTIONS",
              extra={"Access-Control-Request-Method": "GET"})
    probe("v1 events origin", f"https://api.elections.kalshi.com/v1/events/{ev}")
    probe("v1 series origin", "https://api.elections.kalshi.com/v1/series/KXNBAGAME")
    probe("kalshi.com origin as kalshi", "https://api.elections.kalshi.com/trade-api/v2/markets", {"tickers": tk},
          origin="https://kalshi.com")
    probe("origin null", "https://api.elections.kalshi.com/trade-api/v2/markets", {"tickers": tk}, origin="null")

    # Polymarket US: how heavy is a tennis match event, and a narrow live listing?
    probe("pm tennis event", f"{PM}/v1/events/slug/atp-colwon-tsuhua-2026-11-01")
    lo = (now - dt.timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (now + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = probe("pm live narrow", f"{PM}/v1/events", {"live": "true", "closed": "false", "limit": 100,
                                                   "startDateMin": lo, "startDateMax": hi})
    if r is not None and r.ok:
        evs = r.json().get("events") or []
        log(f"  live narrow: n={len(evs)} prefixes={sorted({(e.get('slug') or '').split('-')[0] for e in evs})}")
        sizes = sorted(((len(json.dumps(e)), e.get("slug"), len(e.get("markets") or [])) for e in evs), reverse=True)[:5]
        log(f"  biggest: {sizes}")
    for extra in ({"seriesSlug": "atp-2025"}, {"tagSlug": "tennis"}, {"category": "sports", "live": "true"},
                  {"fields": "slug,live,period"}, {"includeMarkets": "false"}):
        p = {"closed": "false", "limit": 20, "startDateMin": lo, "startDateMax": hi} | extra
        r = probe(f"pm events {extra}", f"{PM}/v1/events", p)
        if r is not None and r.ok:
            evs = r.json().get("events") or []
            log(f"   -> n={len(evs)} first={[e.get('slug') for e in evs[:4]]} mk/ev={[len(e.get('markets') or []) for e in evs[:4]]}")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
    with open(os.path.join(OUT, "_log.json"), "w") as fh:
        json.dump(LOG, fh, indent=1)
