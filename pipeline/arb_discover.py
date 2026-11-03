"""One-off probe (round 8): exact market shapes for the sports being added.

Writes JSON files to ./debug for reading back from the debug branch.
"""
import datetime as dt
import json
import os
import traceback

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


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as fh:
        json.dump(obj, fh, indent=1, default=str)


K_SERIES = ["KXEPLGAME", "KXEPLSPREAD", "KXEPLTOTAL", "KXEPLBTTS", "KXUCLGAME", "KXUCLSPREAD", "KXCS2GAME", "KXDOTA2GAME",
            "KXLOLGAME", "KXUFCFIGHT", "KXBOXING", "KXITFMATCH", "KXITFWMATCH", "KXATPDOUBLES", "KXNCAAWBGAME",
            "KXNCAAWBSPREAD", "KXEUROLEAGUEGAME", "KXEUROCUPSPREAD", "KXKHLGAME", "KXAHLGAME", "KXT20MATCH", "KXODIMATCH",
            "KXKBOGAME", "KXMLSGAME", "KXLIGAMXGAME", "KXWTACHALLENGERMATCH", "KXR6GAME", "KXCBAGAME", "KXNBLGAME",
            "KXNHLTEAMTOTAL", "KXNBATEAMTOTAL", "KXNBA1HSPREAD", "KXNBA1HTOTAL", "KXNFLTEAMTOTAL", "KXNCAAMB1HSPREAD"]
PM_PREFIX = ["epl", "ucl", "cs2", "dota2", "lol", "ufc", "boxing", "itfme", "itfwo", "atpdb", "wtadb", "wcbb", "eurolg",
             "eurocup", "khl", "ahl", "t20icr", "odicr", "kbo", "j1", "bra", "utr", "r6", "cba", "nbl", "bcl"]


def kalshi_samples():
    out = {}
    for s in K_SERIES:
        try:
            d = get_json(f"{KB}/markets", params={"series_ticker": s, "status": "open", "limit": 200})
            ms = d.get("markets") or []
            ev = ms[0]["event_ticker"] if ms else None
            same = [m for m in ms if m.get("event_ticker") == ev][:8]
            out[s] = [{k: m.get(k) for k in ("ticker", "title", "yes_sub_title", "no_sub_title", "floor_strike", "strike_type",
                                              "yes_bid_dollars", "yes_ask_dollars", "occurrence_datetime")}
                      | {"rules": (m.get("rules_primary") or "")[:260]} for m in same]
            log(f"K {s}: {len(ms)} open; event {ev}: " + json.dumps([(m['ticker'].rsplit('-', 1)[-1], m['title'], m['yes_sub_title'], m['floor_strike']) for m in out[s]])[:900])
        except Exception as e:  # noqa: BLE001
            log(f"K {s} failed {e!r}"[:200])
    save("k_samples.json", out)


def pm_samples(now):
    lo = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (now + dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    evs, off = [], 0
    while off < 20000:
        d = get_json(f"{PM}/v1/events", params={"closed": "false", "limit": 100, "offset": off,
                                                "startDateMin": lo, "startDateMax": hi})
        page = d.get("events") or []
        evs += [e for e in page if (e.get("slug") or "").split("-")[0] in PM_PREFIX]
        if len(page) < 100:
            break
        off += 100
    out = {}
    for pre in PM_PREFIX:
        es = [e for e in evs if e["slug"].split("-")[0] == pre]
        if not es:
            log(f"P {pre}: none")
            continue
        e = es[0]
        nested = [{"slug": m.get("slug"), "type": m.get("sportsMarketType"), "q": (m.get("question") or "")[:140],
                   "sides": [(s.get("long"), s.get("description"), (s.get("team") or {}).get("name"),
                              (s.get("team") or {}).get("abbreviation")) for s in m.get("marketSides") or []]}
                  for m in e.get("markets") or []]
        teams = [{k: t.get(k) for k in ("name", "abbreviation", "alias", "safeName", "displayAbbreviation")} for t in e.get("teams") or []]
        full = {}
        try:
            fe = get_json(f"{PM}/v1/events/slug/{e['slug']}")
            fe = fe.get("event", fe)
            for m in fe.get("markets") or []:
                t = m.get("sportsMarketType")
                full.setdefault(t, {"n": 0, "slug": m.get("slug"), "q": (m.get("question") or "")[:140],
                                    "sides": [(s.get("long"), s.get("description")) for s in m.get("marketSides") or []]})
                full[t]["n"] += 1
        except Exception as ex:  # noqa: BLE001
            full = {"error": repr(ex)[:200]}
        out[pre] = {"n_events": len(es), "event": e["slug"], "title": e.get("title"), "teams": teams, "nested": nested,
                    "full_types": full, "titles": [x.get("title") for x in es[:8]]}
        log(f"P {pre}: {len(es)} events; {e['slug']} | {e.get('title')} | teams {json.dumps(teams)[:300]}")
        log(f"     nested: {json.dumps(nested)[:700]}")
        log(f"     full: {json.dumps(full)[:900]}")
    save("pm_samples.json", out)


def main():
    now = dt.datetime.now(dt.timezone.utc)
    log(f"now {now.isoformat()}")
    kalshi_samples()
    save("_log.json", LOG)
    pm_samples(now)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
    save("_log.json", LOG)
