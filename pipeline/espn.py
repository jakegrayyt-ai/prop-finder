"""ESPN public JSON: teams, rosters, schedules + betting totals, injuries, game logs, box scores.

ESPN is also one of Kalshi's listed settlement sources for these props, so the
numbers here are the same ones the markets settle on.
"""
import datetime as dt
import re
import time
import unicodedata
from zoneinfo import ZoneInfo

from . import cache
from .net import get_json

SITE = "https://site.api.espn.com/apis/site/v2/sports"
WEB = "https://site.web.api.espn.com/apis/common/v3/sports"
PATH = {"nba": "basketball/nba", "nfl": "football/nfl", "nhl": "hockey/nhl"}
ET = ZoneInfo("America/New_York")
HOUR = 3600


# ------------------------------------------------------------------ helpers
def num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def first_num(x):
    """'8-15' -> 8, '23/41' -> 23."""
    if isinstance(x, str):
        for sep in ("-", "/"):
            if sep in x and not x.startswith("-"):
                return num(x.split(sep)[0])
    return num(x)


def second_num(x):
    if isinstance(x, str):
        for sep in ("/", "-"):
            if sep in x and not x.startswith("-"):
                return num(x.split(sep)[1])
    return None


def mmss(x):
    """'23:22' -> 23.37 minutes."""
    if not isinstance(x, str) or ":" not in x:
        return num(x)
    try:
        m, s = x.split(":")[:2]
        return round(int(m) + int(s) / 60, 2)
    except ValueError:
        return None


def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("’", "'")
    s = re.sub(r"[.'`]", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    parts = [p for p in s.split() if p not in ("jr", "sr", "ii", "iii", "iv", "v")]
    return " ".join(parts)


def et_date(iso):
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(ET).date().isoformat()


def season_years(league, today):
    """ESPN season parameter for the current and previous season."""
    if league == "nfl":
        cur = today.year if today.month >= 3 else today.year - 1
    else:
        cur = today.year + 1 if today.month >= 8 else today.year
    return cur, cur - 1


def pos_group(league, pos):
    p = (pos or "").upper()
    if league == "nba":
        if p.startswith("C"):
            return "C"
        if p in ("G", "PG", "SG", "G-F"):
            return "G"
        if p in ("F", "SF", "PF", "F-C", "F-G"):
            return "F"
        return None
    if league == "nfl":
        if p == "FB":
            return "RB"
        return p if p in ("QB", "RB", "WR", "TE") else None
    if league == "nhl":
        if p == "G":
            return "G"
        if p == "D":
            return "D"
        if p in ("C", "LW", "RW", "F", "W"):
            return "F"
    return None


# ------------------------------------------------------------------ teams / rosters
def teams(league):
    def fetch():
        d = get_json(f"{SITE}/{PATH[league]}/teams")
        out = []
        for lg in d.get("sports", [{}])[0].get("leagues", []):
            for t in lg.get("teams", []):
                t = t.get("team", t)
                out.append({"id": t.get("id"), "abbr": t.get("abbreviation"), "name": t.get("displayName"),
                            "short": t.get("shortDisplayName"), "location": t.get("location")})
        return out
    return cache.cached(f"espn/{league}/teams", 7 * 24 * HOUR, fetch)


def roster(league, team):
    def fetch():
        d = get_json(f"{SITE}/{PATH[league]}/teams/{team['id']}/roster")
        items = []
        for a in d.get("athletes", []):
            if isinstance(a, dict) and "items" in a:
                items.extend(a.get("items") or [])
            else:
                items.append(a)
        out = []
        for a in items:
            pos = (a.get("position") or {}).get("abbreviation")
            out.append({"id": a.get("id"), "name": a.get("displayName") or a.get("fullName"),
                        "first": a.get("firstName"), "last": a.get("lastName"), "jersey": a.get("jersey"),
                        "pos": pos, "group": pos_group(league, pos), "team_id": team["id"], "team": team["abbr"],
                        "status": (a.get("status") or {}).get("type")})
        return out
    return cache.cached(f"espn/{league}/roster/{team['id']}", 12 * HOUR, fetch)


# ------------------------------------------------------------------ schedule
def scoreboard(league, params, key, ttl):
    """Cached scoreboard. A cached day/week where every game is final never needs refetching."""
    data, ts = cache.entry(key)
    if data is not None:
        if (data and all(g.get("completed") for g in data)) or time.time() - ts < ttl:
            return data
    return cache.put(key, _fetch_scoreboard(league, params))


def _fetch_scoreboard(league, params):
    d = get_json(f"{SITE}/{PATH[league]}/scoreboard", params=params)
    out = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        side = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        h, a = side.get("home") or {}, side.get("away") or {}
        odds = (comp.get("odds") or [None])[0] or {}
        st = (e.get("status") or {}).get("type") or {}
        out.append({
            "eid": e.get("id"), "league": league, "start": e.get("date"), "date": et_date(e.get("date")),
            "state": st.get("state"), "completed": bool(st.get("completed")), "detail": st.get("shortDetail"),
            "season_type": (e.get("season") or {}).get("type"), "week": (e.get("week") or {}).get("number"),
            "home_id": (h.get("team") or {}).get("id"), "home": (h.get("team") or {}).get("abbreviation"),
            "home_name": (h.get("team") or {}).get("displayName"), "home_score": num(h.get("score")),
            "away_id": (a.get("team") or {}).get("id"), "away": (a.get("team") or {}).get("abbreviation"),
            "away_name": (a.get("team") or {}).get("displayName"), "away_score": num(a.get("score")),
            "neutral": bool(comp.get("neutralSite")),
            "total": num(odds.get("overUnder")), "line": odds.get("details"),
        })
    return out


def games_on(league, date):
    """date: datetime.date. Past days cache long, today/future refresh often."""
    today = dt.datetime.now(ET).date()
    ttl = 30 * 24 * HOUR if date < today - dt.timedelta(days=1) else 10 * 60
    return scoreboard(league, {"dates": date.strftime("%Y%m%d")}, f"espn/{league}/sb/{date.isoformat()}", ttl)


def nfl_week(season, week):
    return scoreboard("nfl", {"week": week, "seasontype": 2, "dates": season},
                      f"espn/nfl/sbw/{season}-{week}", 10 * 60)


# ------------------------------------------------------------------ injuries
def injuries(league):
    def fetch():
        d = get_json(f"{SITE}/{PATH[league]}/injuries")
        out = {}
        for t in d.get("injuries", []):
            for i in t.get("injuries", []):
                a = i.get("athlete") or {}
                aid = None
                for link in a.get("links") or []:
                    m = re.search(r"/id/(\d+)", link.get("href", ""))
                    if m:
                        aid = m.group(1)
                        break
                if not aid:
                    continue
                det = i.get("details") or {}
                out[aid] = {"status": i.get("status"), "note": i.get("shortComment"), "date": i.get("date"),
                            "type": det.get("type"), "ret": det.get("returnDate")}
        return out
    return cache.cached(f"espn/{league}/injuries", 15 * 60, fetch)


# ------------------------------------------------------------------ stat derivation
def derive(league, raw):
    """Map ESPN stat names -> our keys. Returns dict or None (did not play)."""
    s = {}
    if league == "nba":
        mins = num(raw.get("minutes"))
        if not mins:
            return None
        s["min"] = mins
        s["pts"] = num(raw.get("points"))
        s["reb"] = num(raw.get("totalRebounds", raw.get("rebounds")))
        s["ast"] = num(raw.get("assists"))
        s["stl"] = num(raw.get("steals"))
        s["blk"] = num(raw.get("blocks"))
        s["tov"] = num(raw.get("turnovers"))
        s["3pm"] = first_num(raw.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
        if None not in (s["pts"], s["reb"], s["ast"]):
            s["pra"] = s["pts"] + s["reb"] + s["ast"]
        if None not in (s["stl"], s["blk"]):
            s["stocks"] = s["stl"] + s["blk"]
        cats = [s.get(k) for k in ("pts", "reb", "ast", "stl", "blk")]
        tens = sum(1 for v in cats if v is not None and v >= 10)
        s["dd"] = 1.0 if tens >= 2 else 0.0
        s["td3"] = 1.0 if tens >= 3 else 0.0
    elif league == "nfl":
        def g(*names):
            for n in names:
                if n in raw:
                    return first_num(raw[n])
            return None
        s["pass_cmp"] = g("completions")
        if "completions/passingAttempts" in raw:
            s["pass_cmp"] = first_num(raw["completions/passingAttempts"])
            s["pass_att"] = second_num(raw["completions/passingAttempts"])
        else:
            s["pass_att"] = g("passingAttempts")
        s["pass_yds"] = g("passingYards")
        s["pass_tds"] = g("passingTouchdowns")
        s["ints"] = g("interceptions")
        s["rush_att"] = g("rushingAttempts")
        s["rush_yds"] = g("rushingYards")
        s["rush_tds"] = g("rushingTouchdowns")
        s["rush_long"] = g("longRushing")
        s["rec"] = g("receptions")
        s["targets"] = g("receivingTargets")
        s["rec_yds"] = g("receivingYards")
        s["rec_tds"] = g("receivingTouchdowns")
        s["rec_long"] = g("longReception")
        has_rush, has_rec = s["rush_yds"] is not None, s["rec_yds"] is not None
        if has_rush or has_rec:
            s["rush_rec_yds"] = (s["rush_yds"] or 0) + (s["rec_yds"] or 0)
            s["tds"] = (s["rush_tds"] or 0) + (s["rec_tds"] or 0)
            s["touches"] = (s["rush_att"] or 0) + (s["rec"] or 0)
        if has_rush and s["rush_long"] is None:
            s["rush_long"] = 0.0
        if has_rec and s["rec_long"] is None:
            s["rec_long"] = 0.0
        if all(v is None for v in s.values()):
            return None
    elif league == "nhl":
        if "saves" in raw or "shotsAgainst" in raw:  # goalie
            started = num(raw.get("gameStarted"))
            toi = mmss(raw.get("timeOnIcePerGame", raw.get("timeOnIce")))
            if started == 0 or (toi is not None and toi < 20):
                return None  # relief appearance: saves props are for starters
            s["saves"] = num(raw.get("saves"))
            s["ga"] = num(raw.get("goalsAgainst"))
            s["sa"] = num(raw.get("shotsAgainst"))
            s["toi"] = toi
        else:
            s["goals"] = num(raw.get("goals"))
            s["assists"] = num(raw.get("assists"))
            s["points"] = num(raw.get("points"))
            if s["points"] is None and s["goals"] is not None and s["assists"] is not None:
                s["points"] = s["goals"] + s["assists"]
            s["sog"] = num(raw.get("shotsTotal"))
            s["toi"] = mmss(raw.get("timeOnIcePerGame", raw.get("timeOnIce")))
            if s["goals"] is None:
                return None
    return {k: v for k, v in s.items() if v is not None}


# ------------------------------------------------------------------ game logs
def gamelog(league, aid, season, tag, ttl):
    def fetch():
        d = get_json(f"{WEB}/{PATH[league]}/athletes/{aid}/gamelog", params={"season": season})
        names = d.get("names") or []
        events = d.get("events") or {}
        out = []
        for stp in d.get("seasonTypes") or []:
            dn = (stp.get("displayName") or "").lower()
            if "preseason" in dn or "all-star" in dn:
                continue
            post = "postseason" in dn or "playoff" in dn or "play-in" in dn
            for cat in stp.get("categories") or []:
                for row in cat.get("events") or []:
                    eid = row.get("eventId")
                    ev = events.get(eid) or {}
                    s = derive(league, dict(zip(names, row.get("stats") or [])))
                    if not s:
                        continue
                    out.append({
                        "eid": eid, "date": et_date(ev.get("gameDate")), "post": post,
                        "opp": (ev.get("opponent") or {}).get("abbreviation"),
                        "opp_id": (ev.get("opponent") or {}).get("id"),
                        "team": (ev.get("team") or {}).get("abbreviation"),
                        "home": ev.get("atVs") == "vs", "res": ev.get("gameResult"), "score": ev.get("score"),
                        "s": s,
                    })
        seen, uniq = set(), []
        for g in sorted(out, key=lambda g: g["date"] or "", reverse=True):
            if g["eid"] in seen:
                continue
            seen.add(g["eid"])
            g["season"] = tag
            uniq.append(g)
        return uniq
    return cache.cached(f"espn/{league}/gl/{season}/{aid}", ttl, fetch)


# ------------------------------------------------------------------ box scores
def boxscore(league, eid):
    """Per-player lines for one finished game: list of {aid, team_id, opp_id, pos, s}."""
    def fetch():
        d = get_json(f"{SITE}/{PATH[league]}/summary", params={"event": eid})
        comps = ((d.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []
        ids = [c.get("id") or (c.get("team") or {}).get("id") for c in comps]
        players = {}
        for block in (d.get("boxscore") or {}).get("players") or []:
            tid = (block.get("team") or {}).get("id")
            opp = next((i for i in ids if i and i != tid), None)
            for grp in block.get("statistics") or []:
                keys = grp.get("keys") or grp.get("names") or []
                for a in grp.get("athletes") or []:
                    if a.get("didNotPlay"):
                        continue
                    ath = a.get("athlete") or {}
                    aid = ath.get("id")
                    if not aid:
                        continue
                    rec = players.setdefault(aid, {"aid": aid, "team_id": tid, "opp_id": opp,
                                                   "pos": (ath.get("position") or {}).get("abbreviation"), "raw": {}})
                    for k, v in zip(keys, a.get("stats") or []):
                        rec["raw"].setdefault(k, v)
        out = []
        for rec in players.values():
            raw = rec.pop("raw")
            if league == "nhl" and "timeOnIce" in raw and "saves" in raw:
                raw["timeOnIcePerGame"] = raw["timeOnIce"]
                raw["gameStarted"] = "1" if (mmss(raw["timeOnIce"]) or 0) >= 20 else "0"
            if league == "nba" and "rebounds" in raw:
                raw["totalRebounds"] = raw["rebounds"]
            s = derive(league, raw)
            if s:
                rec["s"] = s
                out.append(rec)
        return out
    return cache.cached(f"espn/{league}/box/{eid}", 365 * 24 * HOUR, fetch)
