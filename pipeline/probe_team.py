"""Probe: ESPN team schedules (format check) and every open Kalshi team market (for offline tests).

Writes JSON to ./debug, which the probe workflow publishes to the debug branch. Never crashes.
"""
import datetime as dt
import json
import os
import time
import traceback

from .net import get_json

OUT = "debug"
SITE = "https://site.api.espn.com/apis/site/v2/sports"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
PATH = {"nba": "basketball/nba", "nfl": "football/nfl", "nhl": "hockey/nhl"}
_log = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    _log.append(s)


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def probe(name, url, params=None, trim=None):
    try:
        d = get_json(url, params=params)
        save(name, trim(d) if trim else d)
        log("OK  ", name)
        return d
    except Exception as e:  # noqa: BLE001
        log("FAIL", name, repr(e)[:300])
        return None


def trim_sched(d):
    ev = d.get("events") or []
    return {"keys": list(d.keys()), "n": len(ev), "season": d.get("season"), "requestedSeason": d.get("requestedSeason"),
            "team": {k: (d.get("team") or {}).get(k) for k in ("id", "abbreviation", "displayName")},
            "types": sorted({str((e.get("seasonType") or {}).get("type")) for e in ev}),
            "first": ev[:2], "last": ev[-1:]}


def trim_sb(d):
    out = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        out.append({
            "id": e.get("id"), "date": e.get("date"), "season": e.get("season"), "week": e.get("week"),
            "status": (e.get("status") or {}).get("type"),
            "competitors": [{"id": c.get("id"), "homeAway": c.get("homeAway"), "abbr": (c.get("team") or {}).get("abbreviation"),
                             "name": (c.get("team") or {}).get("displayName"), "score": c.get("score")}
                            for c in comp.get("competitors", [])],
            "odds": comp.get("odds"), "neutral": comp.get("neutralSite"),
        })
    return {"events": out}


def espn():
    for lg, tid, seasons in (("nba", "2", (2026, 2027)), ("nfl", "2", (2025, 2026)), ("nhl", "1", (2026, 2027))):
        for s in seasons:
            probe(f"sched_{lg}_{tid}_{s}.json", f"{SITE}/{PATH[lg]}/teams/{tid}/schedule", {"season": s}, trim_sched)
            probe(f"sched_{lg}_{tid}_{s}_st2.json", f"{SITE}/{PATH[lg]}/teams/{tid}/schedule",
                  {"season": s, "seasontype": 2}, trim_sched)
        probe(f"sched_{lg}_{tid}_now.json", f"{SITE}/{PATH[lg]}/teams/{tid}/schedule", None, trim_sched)
    # everything a local test build needs: this season's scoreboards and the next week's
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).date()
    sb = {}
    for lg in ("nba", "nhl"):
        d = dt.date(2026, 10, 1)
        while d <= today + dt.timedelta(days=8):
            x = probe(f"_sb_{lg}_{d}.json", f"{SITE}/{PATH[lg]}/scoreboard", {"dates": d.strftime("%Y%m%d")}, trim_sb)
            if x is not None:
                sb[f"{lg}/{d}"] = trim_sb(x)["events"]
                os.remove(os.path.join(OUT, f"_sb_{lg}_{d}.json"))
            d += dt.timedelta(days=1)
    for wk in range(1, 11):
        x = probe(f"_sb_nfl_w{wk}.json", f"{SITE}/football/nfl/scoreboard", {"week": wk, "seasontype": 2, "dates": 2026}, trim_sb)
        if x is not None:
            sb[f"nfl/w{wk}"] = trim_sb(x)["events"]
            os.remove(os.path.join(OUT, f"_sb_nfl_w{wk}.json"))
    d = today - dt.timedelta(days=1)
    while d <= today + dt.timedelta(days=8):
        x = probe(f"_sb_nfl_{d}.json", f"{SITE}/football/nfl/scoreboard", {"dates": d.strftime("%Y%m%d")}, trim_sb)
        if x is not None:
            sb[f"nfl/{d}"] = trim_sb(x)["events"]
            os.remove(os.path.join(OUT, f"_sb_nfl_{d}.json"))
        d += dt.timedelta(days=1)
    save("scoreboards.json", sb)
    for lg in PATH:
        probe(f"injuries_{lg}.json", f"{SITE}/{PATH[lg]}/injuries", None,
              lambda d: {"injuries": [{"id": t.get("id"), "displayName": t.get("displayName"),
                                       "injuries": [{k: i.get(k) for k in ("status", "date", "shortComment", "details")} |
                                                    {"athlete": {k: (i.get("athlete") or {}).get(k) for k in ("displayName", "links", "position")}}
                                                    for i in t.get("injuries") or []]} for t in d.get("injuries") or []]})


def kalshi():
    out = {}
    for lg in ("NBA", "NFL", "NHL"):
        for kind in ("GAME", "SPREAD", "TOTAL", "TEAMTOTAL"):
            s = f"KX{lg}{kind}"
            try:
                mks, cursor = [], None
                for _ in range(6):
                    p = {"series_ticker": s, "status": "open", "limit": 1000}
                    if cursor:
                        p["cursor"] = cursor
                    d = get_json(KALSHI + "/markets", params=p)
                    mks.extend(d.get("markets") or [])
                    cursor = d.get("cursor")
                    if not cursor or len(d.get("markets") or []) < 1000:
                        break
                out[s] = mks
                log("OK  ", s, len(mks), "markets,", len({m.get("event_ticker") for m in mks}), "events")
            except Exception as e:  # noqa: BLE001
                log("FAIL", s, repr(e)[:200])
            time.sleep(0.2)
    save("kalshi_team_markets.json", out)


def main():
    t0 = time.time()
    for fn in (kalshi, espn):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log("CRASH", fn.__name__, traceback.format_exc())
    log(f"done in {time.time() - t0:.0f}s")
    save("_log.json", _log)


if __name__ == "__main__":
    main()
