"""One-off probe (round 7): every sport both Kalshi and Polymarket US list, and their market types.

Writes JSON files to ./debug for reading back from the debug branch.
"""
import datetime as dt
import json
import os
import re
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import kalshi as K
from .net import get_json

PM = "https://gateway.polymarket.us"
KB = K.BASES[0]
OUT = "debug"
os.makedirs(OUT, exist_ok=True)
LOG = []


def log(m):
    print(m, flush=True)
    LOG.append(str(m))


def flush():
    save("_log.json", LOG)


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as fh:
        json.dump(obj, fh, indent=1, default=str)


def kalshi_sports():
    """One pass over all open Kalshi events (cursor pages), keeping sports ones, grouped by series."""
    by, cursor, pages, total = defaultdict(list), None, 0, 0
    t0 = time.time()
    while pages < 150 and time.time() - t0 < 150:
        p = {"status": "open", "limit": 200}
        if cursor:
            p["cursor"] = cursor
        d = get_json(f"{KB}/events", params=p)
        evs = d.get("events") or []
        pages += 1
        total += len(evs)
        for e in evs:
            if (e.get("category") or "").lower() == "sports":
                by[e.get("series_ticker")].append(e)
        cursor = d.get("cursor")
        if not cursor or not evs:
            break
    log(f"kalshi open events scanned: {total} in {pages} pages, sports series: {len(by)}")
    rows = sorted(((s, len(es), [(e.get("event_ticker"), e.get("title"), e.get("sub_title")) for e in es[:3]],
                    (es[0].get("product_metadata") or {}).get("competition")) for s, es in by.items()), key=lambda r: -r[1])
    save("kalshi_sports_series.json", rows)
    for r in rows[:400]:
        log(f"  K {r[0]!s:<30} n={r[1]:<4} {r[3]!s:<28.28} | {r[2][0] if r[2] else ''}")
    flush()
    return rows


def pm_sports(now):
    lo = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (now + dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    evs, off = [], 0
    while off < 20000:
        d = get_json(f"{PM}/v1/events", params={"closed": "false", "limit": 100, "offset": off,
                                                "startDateMin": lo, "startDateMax": hi})
        page = d.get("events") or []
        evs += [e for e in page if e.get("category") == "sports"]
        if len(page) < 100:
            break
        off += 100
    by = defaultdict(list)
    for e in evs:
        by[(e.get("slug") or "").split("-")[0]].append(e)
    summary = []
    for pre, es in sorted(by.items(), key=lambda kv: -len(kv[1])):
        e = es[0]
        mt = Counter(m.get("sportsMarketType") or m.get("marketType") for x in es for m in x.get("markets") or [])
        sides = [[(s.get("long"), s.get("description")) for s in m.get("marketSides") or []] for m in (e.get("markets") or [])[:3]]
        summary.append({"prefix": pre, "n": len(es), "tag": (e.get("primaryTag") or {}).get("label"),
                        "series": e.get("seriesSlug"), "titles": [x.get("title") for x in es[:4]],
                        "slugs": [x.get("slug") for x in es[:3]], "nested_types": dict(mt), "sides": sides,
                        "mcount": [((x.get("marketCounts") or {}).get("numMarkets")) for x in es[:5]]})
    save("pm_sports_prefixes.json", summary)
    log(f"pm sports events next 7 days: {len(evs)} in {len(by)} prefixes")
    flush()
    for s in summary:
        log(f"  P {s['prefix']:<12} n={s['n']:<4} tag={s['tag']!s:<22} {s['titles'][:2]} types={s['nested_types']} mcount={s['mcount'][:3]}")
    return by


def pm_full_types(by):
    """One full event per interesting prefix: which market types exist, with a sample of each."""
    out = {}
    want = [p for p in by if p not in ("nba", "nfl", "cbb", "cfb")][:40] + ["nhl", "nba"]
    for pre in dict.fromkeys(want):
        es = by.get(pre) or []
        if not es:
            continue
        e = max(es[:15], key=lambda x: (x.get("marketCounts") or {}).get("numMarkets") or 0)
        try:
            d = get_json(f"{PM}/v1/events/slug/{e['slug']}")
            ev = d.get("event", d)
            ms = ev.get("markets") or []
            types = Counter(m.get("sportsMarketType") for m in ms)
            samples = {}
            for m in ms:
                t = m.get("sportsMarketType")
                if t not in samples:
                    samples[t] = {"slug": m.get("slug"), "q": m.get("question"), "title": m.get("title"), "line": m.get("line"),
                                  "sides": [(s.get("long"), s.get("description"), (s.get("team") or {}).get("name")) for s in m.get("marketSides") or []],
                                  "desc": (m.get("description") or "")[:500]}
            out[pre] = {"event": e["slug"], "title": ev.get("title"), "n": len(ms), "types": dict(types), "samples": samples}
            log(f"  FULL {pre}: {e['slug']} {len(ms)} markets: {dict(types)}")
        except Exception as ex:  # noqa: BLE001
            log(f"  FULL {pre} failed {ex!r}"[:200])
    save("pm_full_types.json", out)


def pm_market_filters(by):
    e = (by.get("nba") or by.get("nhl") or [None])[0]
    if not e:
        return
    for params in ({"eventSlug": e["slug"], "limit": 500}, {"event_slug": e["slug"], "limit": 500},
                   {"eventId": e.get("id"), "limit": 500}, {"eventSlug": e["slug"], "marketType": "props", "limit": 500}):
        try:
            d = get_json(f"{PM}/v1/markets", params=params)
            ms = d.get("markets") or []
            log(f"  markets filter {params}: n={len(ms)} first={[m.get('slug') for m in ms[:3]]}")
        except Exception as ex:  # noqa: BLE001
            log(f"  markets filter {params}: {ex!r}"[:200])


def rules():
    for s in ("KXNBAPTS", "KXNHLGOAL", "KXNFLREC"):
        try:
            d = get_json(f"{KB}/markets", params={"series_ticker": s, "status": "open", "limit": 1})
            m = (d.get("markets") or [{}])[0]
            log(f"  K RULES {s}: {m.get('rules_primary')!s:.400} || {m.get('rules_secondary')!s:.700}")
        except Exception as ex:  # noqa: BLE001
            log(f"  K RULES {s} failed {ex!r}")


def main():
    now = dt.datetime.now(dt.timezone.utc)
    log(f"now {now.isoformat()}")
    kalshi_sports()
    by = pm_sports(now)
    pm_market_filters(by)
    pm_full_types(by)
    rules()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
    save("_log.json", LOG)
