"""One-off discovery: dump what Kalshi / ESPN / NHL APIs actually return.

Output goes to ./debug as JSON so the shapes can be inspected before the real
pipeline is written. Never crashes: every probe is wrapped and logged.
"""
import datetime as dt
import json
import os
import time
import traceback

from .net import get_json

OUT = "debug"
KALSHI_BASES = [
    "https://api.elections.kalshi.com/trade-api/v2",
    "https://external-api.kalshi.com/trade-api/v2",
]
ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_WEB = "https://site.web.api.espn.com/apis/common/v3/sports"
LEAGUES = {"nba": ("basketball", "nba"), "nfl": ("football", "nfl"), "nhl": ("hockey", "nhl")}
SAMPLE_ATHLETES = {
    "nba": ["1966", "3112335"],            # LeBron James, Nikola Jokic
    "nfl": ["3139477", "4262921", "3117251"],  # Mahomes, J. Jefferson, McCaffrey
    "nhl": ["3895074"],                    # Connor McDavid
}
SEASON_START = {"nba": "20261001", "nfl": "20260901", "nhl": "20261001"}

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
        data = get_json(url, params=params)
        if trim:
            data = trim(data)
        save(name, data)
        log("OK  ", name)
        return data
    except Exception as e:  # noqa: BLE001
        log("FAIL", name, url, repr(e)[:300])
        return None


# ---------------------------------------------------------------- Kalshi
def kalshi():
    base, series = None, None
    for b in KALSHI_BASES:
        try:
            d = get_json(b + "/series", params={"category": "Sports"})
            base, series = b, d.get("series") or []
            break
        except Exception as e:  # noqa: BLE001
            log("kalshi base failed", b, repr(e)[:200])
    if base is None:
        return
    log("kalshi base", base, "| sports series:", len(series))
    save("kalshi_series_all.json", series)

    keys = ["nba", "nfl", "nhl", "basketball", "football", "hockey"]
    cands = []
    for s in series:
        text = " ".join(str(s.get(k, "")) for k in ("ticker", "title", "tags")).lower()
        if any(k in text for k in keys):
            cands.append(s)
    log("league-matching series:", len(cands))

    summary, samples, events = [], {}, {}
    for s in cands:
        t = s.get("ticker")
        try:
            m = get_json(base + "/markets", params={"series_ticker": t, "status": "open", "limit": 1000})
            mk = m.get("markets") or []
            row = {k: s.get(k) for k in ("ticker", "title", "tags", "frequency", "fee_type", "fee_multiplier")}
            row["open_markets"] = len(mk)
            row["has_more"] = bool(m.get("cursor"))
            summary.append(row)
            if mk:
                samples[t] = mk[:4]
        except Exception as e:  # noqa: BLE001
            summary.append({"ticker": t, "title": s.get("title"), "error": repr(e)[:200]})
        time.sleep(0.08)
    summary.sort(key=lambda x: -(x.get("open_markets") or 0))
    save("kalshi_league_series_summary.json", summary)
    save("kalshi_market_samples.json", samples)

    for row in summary[:40]:
        t = row["ticker"]
        if not samples.get(t):
            continue
        ev = samples[t][0].get("event_ticker")
        try:
            events[t] = get_json(f"{base}/events/{ev}")
        except Exception as e:  # noqa: BLE001
            events[t] = {"error": repr(e)[:200]}
        time.sleep(0.08)
    save("kalshi_event_samples.json", events)


# ---------------------------------------------------------------- ESPN
def trim_scoreboard(d):
    out = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        out.append({
            "id": e.get("id"), "date": e.get("date"), "name": e.get("name"),
            "shortName": e.get("shortName"), "season": e.get("season"), "week": e.get("week"),
            "status": (e.get("status") or {}).get("type"),
            "competitors": [{
                "id": c.get("id"), "homeAway": c.get("homeAway"),
                "abbr": (c.get("team") or {}).get("abbreviation"),
                "name": (c.get("team") or {}).get("displayName"), "score": c.get("score"),
            } for c in comp.get("competitors", [])],
            "odds": comp.get("odds"),
        })
    return {"count": len(out), "events": out}


def trim_range(d):
    t = trim_scoreboard(d)
    by_status = {}
    for e in t["events"]:
        k = ((e.get("status") or {}).get("name"), (e.get("season") or {}).get("type"))
        by_status[str(k)] = by_status.get(str(k), 0) + 1
    return {"count": t["count"], "by_status_and_seasontype": by_status, "first": t["events"][:3], "last": t["events"][-3:]}


def trim_teams(d):
    teams = []
    for lg in d.get("sports", [{}])[0].get("leagues", []):
        for t in lg.get("teams", []):
            t = t.get("team", t)
            teams.append({k: t.get(k) for k in ("id", "abbreviation", "displayName", "shortDisplayName", "name", "location", "slug")})
    return teams


def espn():
    for lg, (sport, league) in LEAGUES.items():
        today = dt.datetime.utcnow().strftime("%Y%m%d")
        sb = probe(f"espn_{lg}_scoreboard_today.json", f"{ESPN_SITE}/{sport}/{league}/scoreboard", trim=trim_scoreboard)
        rng = probe(f"espn_{lg}_scoreboard_range.json", f"{ESPN_SITE}/{sport}/{league}/scoreboard",
                    params={"dates": f"{SEASON_START[lg]}-{today}", "limit": 1000}, trim=None)
        completed = []
        if rng:
            completed = [e for e in rng.get("events", []) if (e.get("status") or {}).get("type", {}).get("completed")]
            save(f"espn_{lg}_scoreboard_range_trim.json", trim_range(rng))
            os.remove(os.path.join(OUT, f"espn_{lg}_scoreboard_range.json"))
        teams = probe(f"espn_{lg}_teams.json", f"{ESPN_SITE}/{sport}/{league}/teams", trim=trim_teams)
        roster = None
        if teams:
            roster = probe(f"espn_{lg}_roster_{teams[0]['abbreviation']}.json",
                           f"{ESPN_SITE}/{sport}/{league}/teams/{teams[0]['id']}/roster")
        probe(f"espn_{lg}_injuries.json", f"{ESPN_SITE}/{sport}/{league}/injuries",
              trim=lambda d: {"keys": list(d.keys()), "first_teams": (d.get("injuries") or [])[:3]})
        for aid in SAMPLE_ATHLETES[lg]:
            probe(f"espn_{lg}_gamelog_{aid}.json", f"{ESPN_WEB}/{sport}/{league}/athletes/{aid}/gamelog")
        last = {"nba": "2026", "nhl": "2026", "nfl": "2025"}[lg]
        probe(f"espn_{lg}_gamelog_{SAMPLE_ATHLETES[lg][0]}_season{last}.json",
              f"{ESPN_WEB}/{sport}/{league}/athletes/{SAMPLE_ATHLETES[lg][0]}/gamelog", params={"season": last})
        if lg == "nhl" and roster:
            # find a goalie anywhere in the roster payload
            gid = None
            for grp in roster.get("athletes", []):
                items = grp.get("items", [grp]) if isinstance(grp, dict) else []
                for a in items:
                    pos = ((a.get("position") or {}).get("abbreviation") or "").upper()
                    if pos == "G":
                        gid = a.get("id")
                        break
                if gid:
                    break
            if gid:
                probe(f"espn_nhl_gamelog_goalie_{gid}.json", f"{ESPN_WEB}/{sport}/{league}/athletes/{gid}/gamelog")
        if completed:
            ev = completed[-1]["id"]
            probe(f"espn_{lg}_summary_{ev}.json", f"{ESPN_SITE}/{sport}/{league}/summary", params={"event": ev},
                  trim=lambda d: {"keys": list(d.keys()), "header": d.get("header", {}).get("competitions"),
                                  "boxscore": d.get("boxscore")})
        if sb and sb.get("events"):
            ev = sb["events"][0]["id"]
            probe(f"espn_{lg}_summary_upcoming_{ev}.json", f"{ESPN_SITE}/{sport}/{league}/summary", params={"event": ev},
                  trim=lambda d: {"keys": list(d.keys()), "pickcenter": d.get("pickcenter"), "odds": d.get("odds"),
                                  "injuries": d.get("injuries")})


# ---------------------------------------------------------------- NHL API
def nhl():
    base = "https://api-web.nhle.com/v1"
    probe("nhl_gamelog_mcdavid_now.json", f"{base}/player/8478402/game-log/now")
    probe("nhl_roster_EDM.json", f"{base}/roster/EDM/current")
    probe("nhl_schedule_now.json", f"{base}/schedule/now",
          trim=lambda d: {"keys": list(d.keys()), "gameWeek": (d.get("gameWeek") or [])[:2]})


def main():
    started = time.time()
    for fn in (kalshi, espn, nhl):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log("CRASH in", fn.__name__, traceback.format_exc())
    log(f"done in {time.time() - started:.1f}s")
    save("_log.json", _log)


if __name__ == "__main__":
    main()
