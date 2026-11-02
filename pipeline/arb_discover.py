"""One-off probe (round 5): live/started signals and tennis timing on both sites.

Writes JSON files to ./debug for reading back from the debug branch.
"""
import datetime as dt
import json
import os
import re
import traceback

import requests

from . import kalshi as K
from .net import UA, get_json

PM = "https://gateway.polymarket.us"
KB = K.BASES[0]
OUT = "debug"
os.makedirs(OUT, exist_ok=True)
LOG = []


def log(m):
    print(m, flush=True)
    LOG.append(str(m))


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as fh:
        json.dump(obj, fh, indent=1, default=str)


def raw(url, params=None):
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)
    return r.status_code, r.content, r.url


PREFIX = {"nfl", "nba", "nhl", "cfb", "cbb", "atp", "atpcq", "atpc", "wta"}
EV_KEYS = ["slug", "title", "startTime", "startDate", "endDate", "period", "live", "ended", "score", "closed",
           "active", "elapsed", "gameId", "eventState"]


def slim_event(e):
    d = {k: e.get(k) for k in EV_KEYS if k in e}
    es = d.get("eventState")
    if isinstance(es, dict):
        d["eventState"] = {k: v for k, v in es.items() if k != "marketGroupStats"}
    ms = e.get("markets") or []
    d["markets"] = [{k: m.get(k) for k in ("slug", "question", "gameStartTime", "status", "ep3Status", "closed",
                                            "marketType", "bestBidQuote", "bestAskQuote", "outcomePrices")}
                    | {"sides": [(s.get("long"), s.get("description"), (s.get("team") or {}).get("name"),
                                  (s.get("team") or {}).get("abbreviation")) for s in m.get("marketSides") or []]}
                    for m in ms[:3]]
    return d


def main():
    now = dt.datetime.now(dt.timezone.utc)
    log(f"now {now.isoformat()}")
    # 1) Polymarket US listing, now-14h .. now+3d
    lo = (now - dt.timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (now + dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    evs, off = [], 0
    while off < 6000:
        d = get_json(f"{PM}/v1/events", params={"closed": "false", "limit": 100, "offset": off,
                                                "startDateMin": lo, "startDateMax": hi})
        page = d.get("events") or []
        evs += [e for e in page if (e.get("slug") or "").split("-")[0] in PREFIX]
        if len(page) < 100:
            break
        off += 100
    log(f"pm events in window: {len(evs)}")
    from collections import Counter
    c = Counter(((e.get("slug") or "").split("-")[0], e.get("period"), e.get("live"), e.get("ended")) for e in evs)
    log("pm (league, period, live, ended): " + json.dumps(sorted(((list(k), v) for k, v in c.items()), key=str)))
    started = [slim_event(e) for e in evs if (e.get("startTime") or "") <= now.strftime("%Y-%m-%dT%H:%M:%SZ")
               or e.get("live") or (e.get("period") not in (None, "", "NS"))]
    save("pm_started.json", started[:80])
    tennis = [slim_event(e) for e in evs if (e.get("slug") or "").split("-")[0] in ("atp", "atpcq", "atpc", "wta")]
    save("pm_tennis.json", tennis)
    log(f"pm tennis events: {len(tennis)}; started-ish events: {len(started)}")
    score_vals = Counter(json.dumps(e.get("score"))[:40] for e in evs)
    log("pm score values: " + json.dumps(score_vals.most_common(12)))
    # a few full examples of live events (all keys)
    live_full = [e for e in evs if e.get("live")][:2]
    for e in live_full:
        e = dict(e)
        e["markets"] = (e.get("markets") or [])[:1]
        e.pop("teams", None)
        e.pop("tags", None)
        e.pop("primaryTag", None)
    save("pm_live_full.json", live_full)

    # 2) endpoint probes for a browser-side live check
    probes = {}
    some = [e["slug"] for e in evs[:3]]
    tslug = next((e["slug"] for e in evs if e["slug"].startswith(("atp", "wta"))), None)
    lslug = next((e["slug"] for e in evs if e.get("live")), None)
    tests = [
        ("events_slug_multi", f"{PM}/v1/events", [("slug", s) for s in some] + [("limit", 10)]),
        ("events_live_true", f"{PM}/v1/events", {"live": "true", "limit": 100, "closed": "false"}),
        ("events_slug_one_tennis", f"{PM}/v1/events/slug/{tslug}", None),
        ("events_slug_one_live", f"{PM}/v1/events/slug/{lslug}", None),
    ]
    for name, url, params in tests:
        try:
            st, body, full = raw(url, params)
            info = {"status": st, "bytes": len(body), "url": full}
            try:
                j = json.loads(body)
                if isinstance(j, dict) and "events" in j:
                    info["n"] = len(j["events"])
                    info["slugs"] = [x.get("slug") for x in j["events"]][:12]
                    info["periods"] = [(x.get("period"), x.get("live")) for x in j["events"]][:12]
                elif isinstance(j, dict):
                    ev = j.get("event", j)
                    info["keys"] = list(ev.keys())[:60] if isinstance(ev, dict) else str(type(ev))
                    if isinstance(ev, dict):
                        info["n_markets"] = len(ev.get("markets") or [])
                        info["period"] = ev.get("period")
                        info["live"] = ev.get("live")
                        info["score"] = ev.get("score")
            except ValueError:
                info["text"] = body[:300].decode("utf-8", "replace")
            probes[name] = info
        except Exception as e:  # noqa: BLE001
            probes[name] = repr(e)[:300]
    # markets endpoint for the live event's moneyline: any game-state fields?
    if lslug:
        le = next(e for e in evs if e["slug"] == lslug)
        ml = next((m for m in le.get("markets") or [] if m.get("marketType") == "moneyline"), None)
        if ml:
            st, body, _ = raw(f"{PM}/v1/markets", [("slug", ml["slug"]), ("limit", 1)])
            try:
                mm = (json.loads(body).get("markets") or [{}])[0]
                probes["market_of_live_event_keys"] = sorted(mm.keys())
                probes["market_of_live_event"] = {k: mm.get(k) for k in ("slug", "gameStartTime", "status", "ep3Status",
                                                                          "closed", "active", "bestBidQuote", "bestAskQuote")}
            except ValueError:
                pass
    save("probes.json", probes)
    log("probes: " + json.dumps(probes)[:3000])

    # 3) Kalshi timing fields for tennis + team sports
    kout = {}
    for s in ["KXWTAMATCH", "KXATPMATCH", "KXATPCHALLENGERMATCH", "KXNBAGAME", "KXNCAAMBGAME", "KXNFLGAME", "KXNHLGAME"]:
        try:
            ms = K.fetch_series(KB, s)
        except Exception as e:  # noqa: BLE001
            log(f"kalshi {s} failed {e!r}")
            continue
        rows = []
        for m in ms:
            rows.append({k: m.get(k) for k in ("ticker", "event_ticker", "title", "status", "occurrence_datetime",
                                                "expected_expiration_time", "open_time", "close_time", "updated_time",
                                                "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars",
                                                "previous_price_dollars", "volume_24h_fp")})
        kout[s] = rows
        log(f"kalshi {s}: {len(rows)} open markets")
    save("kalshi_timing.json", kout)
    # Kalshi batch-by-tickers support (for a future live re-check)
    try:
        tk = [r["ticker"] for r in (kout.get("KXNBAGAME") or [])[:3]]
        d = get_json(f"{KB}/markets", params={"tickers": ",".join(tk)})
        log(f"kalshi tickers= batch: asked {len(tk)}, got {len(d.get('markets') or [])}: {[m.get('ticker') for m in d.get('markets') or []]}")
    except Exception as e:  # noqa: BLE001
        log(f"kalshi tickers= batch failed {e!r}"[:300])

    # 4) the three tennis matches the board showed
    want = re.compile(r"(tje|hui|colwon|tsuhua|bru|vrb)", re.I)
    save("pm_named.json", [slim_event(e) for e in evs if want.search(e.get("slug") or "")])
    named_k = {s: [r for r in rows if re.search(r"(TJEHUI|WONHUA|BRUVRB)", r["event_ticker"] or "")]
               for s, rows in kout.items()}
    save("kalshi_named.json", named_k)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
    save("_log.json", LOG)
