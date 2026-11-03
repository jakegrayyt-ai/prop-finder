"""Build the prop board: Kalshi lines + ESPN history -> site/data/*.json

Run: python -m pipeline.build
"""
import datetime as dt
import json
import math
import os
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import cache, espn, injury, kalshi, matchups, model, stats, teams
from .espn import ET, norm_name
from .kalshi import TEAM_ALIASES, team_match

OUT = os.environ.get("PROP_OUT", "site/data")
WORKERS = 8
GAME_HOURS = {"nba": 2.6, "nhl": 2.8, "nfl": 3.6}
DEFAULT_TOTAL = {"nba": 228.0, "nfl": 44.5, "nhl": 6.1}
BINARY = {"dd", "td3"}
IGNORE_STATUS = {"Active"}
OUT_STATUS = {"Out", "Injured Reserve", "Suspension"}
INJ_KEYS = ("status", "note", "date", "type", "ret")
SHORT_LEAGUE = {"nba": "NBA", "nfl": "NFL", "nhl": "NHL"}
# season averages from box scores, for the team injury report
USAGE_KEYS = {"nba": ("min", "pts"), "nhl": ("toi", "points"),
              "nfl": ("pass_att", "pass_yds", "rush_att", "targets", "rec_yds")}

_log = []


def log(msg):
    msg = str(msg)
    print(msg, flush=True)
    _log.append(msg)


def pmap(fn, items, workers=WORKERS):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def safe(fn, *a, default=None, label=""):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        log(f"warn {label or fn.__name__}{a!r}: {e!r}"[:300])
        return default


def iso_ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def r2(x, n=3):
    return None if x is None else round(x, n)


# ---------------------------------------------------------------- per league
def load_league(league, props, today, tmk=()):
    """Everything ESPN-side for one league. tmk: Kalshi team markets (their games need schedules too)."""
    cur_season, prev_season = espn.season_years(league, today)
    team_list = espn.teams(league)       # (not `teams`: that's the team-bets module)
    team_by_id = {t["id"]: t for t in team_list}
    rosters = pmap(lambda t: safe(espn.roster, league, t, default=[], label="roster"), team_list)
    athletes = [a for r in rosters for a in r]
    by_name, by_initial = defaultdict(list), defaultdict(list)
    for a in athletes:
        n = norm_name(a["name"])
        by_name[n].append(a)
        parts = n.split()
        if len(parts) >= 2:
            by_initial[(parts[0][0], parts[-1])].append(a)
    pos_of = {a["id"]: a["pos"] for a in athletes}

    # schedule for the prop dates (+ the day before, for rest / back-to-backs)
    dates = sorted({dt.date.fromisoformat(p["date"]) for p in list(props) + list(tmk) if p.get("date")})
    sched_dates = sorted(set(dates) | {d - dt.timedelta(days=1) for d in dates} | {today, today - dt.timedelta(days=1)})
    sched = []
    for d in sched_dates:
        sched.extend(safe(espn.games_on, league, d, default=[], label="scoreboard") or [])
    games = {g["eid"]: g for g in sched}
    by_team_date = {}
    for g in games.values():
        for tid in (g["home_id"], g["away_id"]):
            by_team_date[(tid, g["date"])] = g
    last_end = {}
    for g in games.values():
        if g["completed"]:
            end = (iso_ts(g["start"]) or 0) + GAME_HOURS[league] * 3600
            for tid in (g["home_id"], g["away_id"]):
                last_end[tid] = max(last_end.get(tid, 0), end)
    totals = [g["total"] for g in games.values() if g.get("total")]
    lg_total = sum(totals) / len(totals) if len(totals) >= 4 else DEFAULT_TOTAL[league]

    # match props -> athlete + game
    matched, unmatched = [], defaultdict(int)
    for p in props:
        n = norm_name(p["player_name"])
        cands = by_name.get(n) or []
        if not cands:
            parts = n.split()
            if len(parts) >= 2:
                cands = by_initial.get((parts[0][0], parts[-1])) or []
        if len(cands) > 1:
            narrowed = [a for a in cands if team_match(league, p.get("k_team"), a["team"])] or \
                       [a for a in cands if p.get("jersey") and a.get("jersey") == p["jersey"]]
            cands = narrowed or cands
        if len(cands) != 1:
            unmatched[p["player_name"]] += 1
            continue
        a = cands[0]
        g = by_team_date.get((a["team_id"], p["date"]))
        if not g:  # roster may be stale (trade); fall back to Kalshi's team codes
            for gg in games.values():
                if gg["date"] == p["date"] and any(team_match(league, c, x) for c in (p.get("k_away"), p.get("k_home"))
                                                   for x in (gg["home"], gg["away"])):
                    if team_match(league, p.get("k_team"), gg["home"]) or team_match(league, p.get("k_team"), gg["away"]):
                        g = gg
                        break
        if not g:
            unmatched[f"{p['player_name']} (no game {p['date']})"] += 1
            continue
        team_id = a["team_id"] if a["team_id"] in (g["home_id"], g["away_id"]) else (
            g["home_id"] if team_match(league, p.get("k_team"), g["home"]) else g["away_id"])
        p["aid"], p["eid"], p["team_id"] = a["id"], g["eid"], team_id
        matched.append(p)

    # game logs for matched athletes (current season refreshes after each game)
    aids = sorted({(p["aid"], p["team_id"]) for p in matched})
    now = time.time()

    def logs_for(item):
        aid, tid = item
        key = f"espn/{league}/gl/{cur_season}/{aid}"
        _, ts = cache.entry(key)
        stale = (now - ts > 3 * 3600) or (last_end.get(tid, 0) > ts and now > last_end.get(tid, 0))
        cur = safe(espn.gamelog, league, aid, cur_season, "cur", 0 if stale else None, default=[], label="gamelog")
        prev = safe(espn.gamelog, league, aid, prev_season, "prev", 14 * 24 * 3600, default=[], label="gamelog-prev")
        return aid, (cur or []) + (prev or [])

    logs = dict(pmap(logs_for, aids))
    # All-Star games and exhibitions against teams outside the league aren't real games for a prop
    abbrs = {t.get("abbr") for t in team_list if t.get("abbr")}
    alias = TEAM_ALIASES.get(league, {})

    def in_league(opp):
        if not opp or not abbrs or opp in abbrs or alias.get(opp) in abbrs:
            return True
        return any(len(a) >= 2 and len(opp) >= 2 and (a.startswith(opp) or opp.startswith(a)) for a in abbrs)  # UTA ~ UTAH
    odd = defaultdict(int)
    for aid, gl in logs.items():
        keep = [x for x in gl if in_league(x.get("opp"))]
        for x in gl:
            if x not in keep:
                odd[x.get("opp")] += 1
        logs[aid] = keep
    if odd:
        log(f"{league}: left out games against non-league opponents {dict(odd)}")
    cur_counts = sorted(sum(1 for g in gl if g["season"] == "cur") for gl in logs.values())
    median_cur = cur_counts[len(cur_counts) // 2] if cur_counts else 0

    # opponent defense vs position from this season's finished games
    table, team_games, done, usage = safe(build_matchups, league, cur_season, today, pos_of,
                                          default=(None, {}, [], {}), label="matchups")
    done = list(done) + [g for g in games.values() if g["completed"] and g.get("season_type") in (2, 3)]
    prev_games = []
    if tmk:   # team bets also look at last season's results
        for sched_ in pmap(lambda t: safe(espn.team_schedule, league, t["id"], prev_season, default=[], label="team-sched"), team_list):
            prev_games.extend(sched_ or [])
    inj = safe(espn.injuries, league, default={}, label="injuries") or {}
    roster_by_id = {a["id"]: a for a in athletes}

    # games he left early hurt: marked, and left out of hit rates and the model
    hurt = 0
    for aid, tid in aids:
        ath = roster_by_id.get(aid) or {}
        if league == "nhl" and ath.get("pos") == "G":
            continue      # goalies sit by design (backup nights) and get pulled when shelled: neither is an injury
        hurt += injury.mark(league, logs.get(aid) or [], team_games.get(tid), aid, inj.get(aid),
                            qb=(ath.get("pos") == "QB"), team_abbr=(team_by_id.get(tid) or {}).get("abbr"))
    log(f"{league}: {hurt} games marked as left early hurt")
    return {"league": league, "matched": matched, "unmatched": dict(unmatched), "logs": logs, "games": games,
            "table": table, "inj": inj, "athletes": roster_by_id, "teams": team_by_id, "lg_total": lg_total,
            "median_cur": median_cur, "team_games": team_games, "done": done, "prev_games": prev_games,
            "usage": usage}


def build_matchups(league, season, today, pos_of):
    """Opponent defense table from this season's finished games, plus each team's game dates."""
    done = []
    if league == "nfl":
        for wk in range(1, 19):
            wk_games = [g for g in espn.nfl_week(season, wk) or [] if g["completed"] and g["season_type"] == 2]
            done.extend(wk_games)
            if not wk_games:
                break
    else:
        start = dt.date(today.year if today.month >= 8 else today.year - 1, 10, 1)
        d = start
        while d < today:
            done.extend(g for g in espn.games_on(league, d) or [] if g["completed"] and g["season_type"] in (2, 3))
            d += dt.timedelta(days=1)
    eids = sorted({g["eid"] for g in done})
    boxes = dict(zip(eids, pmap(lambda e: safe(espn.boxscore, league, e, default=[], label="box"), eids)))
    log(f"{league}: matchups from {len(eids)} finished games")
    # each team's finished games and who played in them (None when the box score didn't load)
    team_games = defaultdict(dict)
    for g in done:
        lines = boxes.get(g["eid"]) or []
        for tid in (g["home_id"], g["away_id"]):
            if tid and g.get("date"):
                who = {ln["aid"] for ln in lines if ln.get("team_id") == tid}
                team_games[tid][g["date"]] = who or None
    # everyone's season averages, for the team injury report (who's missing and how much he plays)
    sums = defaultdict(lambda: defaultdict(float))
    for lines in boxes.values():
        for ln in lines or []:
            s, u = ln.get("s") or {}, sums[ln["aid"]]
            u["gp"] += 1
            if "saves" in s:
                u["gs"] += 1
            for k in USAGE_KEYS[league]:
                if s.get(k) is not None:
                    u[k] += s[k]
    usage = {aid: {k: (v if k in ("gp", "gs") else round(v / u["gp"], 2)) for k, v in u.items()} for aid, u in sums.items()}
    for u in usage.values():
        u["gp"], u["gs"] = int(u.get("gp", 0)), int(u.get("gs", 0))
    return (matchups.build(league, boxes, pos_of), {t: sorted(v.items()) for t, v in team_games.items()}, done, usage)


# ---------------------------------------------------------------- per prop
def evaluate(p, L):
    league, stat, line = p["league"], p["stat"], p["line"]
    games = L["logs"].get(p["aid"], [])
    g = L["games"][p["eid"]]
    home = g["home_id"] == p["team_id"]
    opp_id = g["away_id"] if home else g["home_id"]
    opp = g["away"] if home else g["home"]
    played_all = [x for x in games if x["s"].get(stat) is not None and (x["date"] or "") < g["date"]]
    summ = stats.summarize(played_all, stat, line, opp)
    played = [x for x in played_all if not injury.is_hurt(x)]   # games he left hurt don't count
    cur_vals = [x["s"][stat] for x in played if x["season"] == "cur"]
    prev_vals = [x["s"][stat] for x in played if x["season"] == "prev"]
    ath = L["athletes"].get(p["aid"]) or {}
    grp = espn.pos_group(league, ath.get("pos"))
    if stat == "saves":
        grp = "G"

    # rest days
    last = next((x["date"] for x in played_all), None)
    rest = (dt.date.fromisoformat(g["date"]) - dt.date.fromisoformat(last)).days if last else None
    b2b = rest == 1 and league in ("nba", "nhl")

    # context
    mu_info = None
    p_model = None
    factors = []
    mt = matchups.lookup(L["table"], opp_id, grp, stat) if stat not in BINARY else None
    if stat in BINARY:
        k = model.PRIOR_GAMES[league]
        if cur_vals or prev_vals:
            pc = sum(cur_vals) / len(cur_vals) if cur_vals else None
            pp = sum(prev_vals) / len(prev_vals) if prev_vals else None
            if pc is not None and pp is not None:
                rate = (len(cur_vals) * pc + k * pp) / (len(cur_vals) + k)
            else:
                rate = pc if pc is not None else pp
            n = len(cur_vals) + len(prev_vals)
            p_model = model.clamp((rate * n + 0.5) / (n + 1), 0.01, 0.99)
            mu_info = {"base": r2(rate), "mu": r2(rate), "n_cur": len(cur_vals), "n_prev": len(prev_vals)}
    else:
        base = model.base_projection(cur_vals, prev_vals, league, stat)
        if base:
            allv = cur_vals + prev_vals
            overall = sum(allv) / len(allv) if allv else None
            venue = [x["s"][stat] for x in played if x["home"] == home]
            home_ratio = (sum(venue) / len(venue)) / overall if venue and overall and len(venue) >= 4 else None
            total_ratio = (g["total"] / L["lg_total"]) if g.get("total") and L["lg_total"] else None
            factors = model.context_factors(league, stat, opp_ratio=mt["ratio"] if mt else None,
                                            home_ratio=home_ratio, total_ratio=total_ratio, back_to_back=b2b)
            f = 1.0
            for _, x in factors:
                f *= x
            mu = base["mu"] * f
            var = base["var"] * (f * f if stat in model.CONTINUOUS else f)
            p_model = model.prob_at_least(mu, var, line, stat)
            mu_info = {"base": r2(base["mu"], 2), "mu": r2(mu, 2), "sd": r2(var ** 0.5, 2),
                       "n_cur": base["n_cur"], "n_prev": base["n_prev"]}

    yb, ya = p["yes_bid"], p["yes_ask"]
    na = p["no_ask"] if p.get("no_ask") and 0 < p["no_ask"] < 1 else ((1 - yb) if yb and yb > 0 else None)
    two_sided = bool(yb and ya and 0 < yb < ya < 1)
    mid = (yb + ya) / 2 if two_sided else (ya if ya and 0 < ya < 1 else None)
    spread = (ya - yb) if two_sided else None
    liquid = two_sided and spread <= 0.10

    inj = L["inj"].get(p["aid"])
    status = (inj or {}).get("status") or ""
    if status in IGNORE_STATUS:
        status = ""
    live = g["state"] == "in"
    flags = []
    if status:
        flags.append(status)
    if live:
        flags.append("Live")
    if not liquid:
        flags.append("Wide spread")
    if not p.get("volume"):
        flags.append("No trades yet")
    vol = stats.volume_trend(played, league, stat)
    if vol and vol["szn"] and abs(vol["l3"] - vol["szn"]) / max(vol["szn"], 1) > 0.25:
        flags.append("Role change")
    n_cur, n_prev = len(cur_vals), len(prev_vals)
    missed = 0 if grp == "G" else injury.missed_since((L.get("team_games") or {}).get(p["team_id"]), p["aid"], g["date"], played_all)
    if missed and not (status in OUT_STATUS):
        flags.append(f"Missed last {missed} game{'s' if missed != 1 else ''}")
    if played_all and injury.is_hurt(played_all[0]):
        flags.append("Left last game hurt")
    if n_cur == 0 and L.get("median_cur", 0) >= 3:
        flags.append("First game this season")
    elif rest is not None and rest > 25:
        flags.append("Long layoff")
    n_eff = n_cur + 0.5 * min(n_prev, 40)
    lo, hi = (5, 10) if league == "nfl" else (10, 25)
    conf = 1 if n_eff < lo else (3 if (n_cur >= (5 if league == "nfl" else 8) and n_eff >= hi) else 2)
    if n_eff < lo:
        flags.append("Small sample")
    if any(f in flags for f in ("Questionable", "Doubtful", "Day-To-Day", "Wide spread", "Role change", "Live",
                                "Left last game hurt")) or any(f.startswith("Missed last") for f in flags):
        conf -= 1
    if "First game this season" in flags or "Long layoff" in flags:
        conf = min(conf, 1)
    if status in OUT_STATUS:
        conf = 0
    gap = (p_model - mid) if (p_model is not None and mid is not None) else None
    if liquid and gap is not None and abs(gap) > 0.15:
        flags.append("Check news")
    conf = ["low", "low", "med", "high"][max(0, min(3, conf))]

    # Edge. Kalshi's price is a strong prior, so the stats model only moves it part of
    # the way, and much less when the gap is big: a big gap on a liquid market usually
    # means news the box scores don't know about yet (injury, lineup change).
    p_blend, k = None, None
    if gap is not None and not live and status not in OUT_STATUS:
        k = (0.35 if liquid else 0.5) * {"low": 0.5, "med": 1.0, "high": 1.15}[conf]
        k *= math.exp(-max(0.0, abs(gap) - 0.10) / 0.10)
        p_blend = model.clamp(mid + k * gap, 0.005, 0.995)
    e = model.edges(p_blend, ya, na)
    best = max(e, key=e.get) if e else None

    row = {
        "id": p["ticker"], "lg": league, "pid": f"{league}-{p['aid']}", "gid": f"{league}-{p['eid']}",
        "stat": stat, "line": line, "opp": opp, "home": home,
        "k": {"yb": r2(yb, 2), "ya": r2(ya, 2), "last": r2(p["last"], 2),
              "vol": round(p["volume"]) if p.get("volume") else 0},
        "mid": r2(mid, 3),
        "h": {k: [v["hit"], v["n"]] for k, v in summ.items() if isinstance(v, dict) and k not in ("home2", "away2")},
        "strk": summ["streak"], "avg": summ["avg"], "avg10": summ["avg_l10"], "diff": summ["diff"],
        "last10": [x["s"][stat] for x in played_all[:10]],
        "x10": [i for i, x in enumerate(played_all[:10]) if injury.is_hurt(x)],   # left hurt: drawn grey, not counted
        "nx": summ["hurt"],
        "p": r2(p_model), "pb": r2(p_blend), "e": {s: r2(v, 4) for s, v in e.items()}, "best": best,
        "be": r2(e.get(best), 4) if best else None, "conf": conf, "flags": flags,
    }
    detail = {
        "mu": mu_info, "factors": [[lab, r2(x, 4)] for lab, x in factors], "matchup": mt, "k": r2(k),
        "rest": rest, "b2b": b2b, "vol": vol, "total": g.get("total"), "lg_total": r2(L["lg_total"], 1),
        "summary": summ,
    }
    return row, detail


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    now = dt.datetime.now(ET)
    today = now.date()
    os.makedirs(os.path.join(OUT, "p"), exist_ok=True)

    raw, base, counts = kalshi.load_props(log)
    log(f"kalshi {base}: {len(raw)} prop markets " + json.dumps(counts))
    traw, tcounts = kalshi.load_team(base, log)
    log(f"kalshi: {len(traw)} team markets " + json.dumps(tcounts))
    counts.update(tcounts)
    lo, hi = (today - dt.timedelta(days=1)).isoformat(), (today + dt.timedelta(days=8)).isoformat()
    raw = [p for p in raw if p.get("date") and lo <= p["date"] <= hi]
    traw = [t for t in traw if lo <= t["date"] <= hi]

    rows, details, players, games_out, unmatched = [], defaultdict(dict), {}, {}, {}
    league_meta = {}
    for league in ("nba", "nfl", "nhl"):
        props = [p for p in raw if p["league"] == league]
        tmk = [t for t in traw if t["league"] == league]
        if not props and not tmk:
            league_meta[league] = {"props": 0, "games": 0}
            continue
        try:
            L = load_league(league, props, today, tmk)
        except Exception:  # noqa: BLE001
            log(f"league {league} failed:\n{traceback.format_exc()}")
            continue
        unmatched[league] = L["unmatched"]
        kept = 0
        for p in L["matched"]:
            g = L["games"][p["eid"]]
            if g["completed"]:
                continue
            try:
                row, det = evaluate(p, L)
            except Exception:  # noqa: BLE001
                log(f"evaluate failed {p['ticker']}:\n{traceback.format_exc()}"[:800])
                continue
            rows.append(row)
            details[row["pid"]][row["id"]] = det
            kept += 1
            gid = row["gid"]
            if gid not in games_out:
                games_out[gid] = {k: g.get(k) for k in ("start", "date", "state", "detail", "home", "away", "home_name",
                                                         "away_name", "total", "line", "week")}
                games_out[gid]["lg"] = league
            if row["pid"] not in players:
                a = L["athletes"].get(p["aid"]) or {}
                inj = L["inj"].get(p["aid"])
                if inj and inj.get("status") in IGNORE_STATUS:
                    inj = None
                if inj:
                    inj = {k: inj.get(k) for k in INJ_KEYS}
                team = L["teams"].get(p["team_id"], {})
                players[row["pid"]] = {"name": a.get("name") or p["player_name"], "team": team.get("abbr"),
                                       "pos": a.get("pos"), "lg": league, "inj": inj}
                gl = L["logs"].get(p["aid"], [])
                with open(os.path.join(OUT, "p", f"{row['pid']}.json"), "w") as f:
                    json.dump({"pid": row["pid"], **players[row["pid"]],
                               "games": [{k: x.get(k) for k in ("eid", "date", "opp", "home", "res", "score", "post",
                                                                "season", "s", "inj") if x.get(k) is not None or k != "inj"}
                                         for x in gl]}, f, separators=(",", ":"))
        log(f"{league}: {kept} props kept, {sum(L['unmatched'].values())} unmatched markets")

        # team bets: moneylines, spreads, game totals, team totals
        n_team = 0
        if tmk:
            try:
                T = teams.build(league, tmk, L, today, log)
            except Exception:  # noqa: BLE001
                log(f"team bets {league} failed:\n{traceback.format_exc()}"[:1500])
                T = None
            if T:
                rows.extend(T["rows"])
                n_team = len(T["rows"])
                for gid, g in T["games"].items():
                    if gid not in games_out:
                        games_out[gid] = {k: g.get(k) for k in ("start", "date", "state", "detail", "home", "away",
                                                                 "home_name", "away_name", "total", "line", "week")}
                        games_out[gid]["lg"] = league
                players.update(T["players"])
                for pid, blob in T["files"].items():
                    blob["props"] = T["details"].get(pid, {})
                    with open(os.path.join(OUT, "p", f"{pid}.json"), "w") as f:
                        json.dump(blob, f, separators=(",", ":"))
                if T["unmatched"]:
                    unmatched[league + "-team"] = dict(T["unmatched"])
                    log(f"{league}: {sum(T['unmatched'].values())} team markets unmatched")
        league_meta[league] = {"props": kept, "teams": n_team,
                               "games": len({r["gid"] for r in rows if r["lg"] == league}),
                               "unmatched": sum(L["unmatched"].values())}

    # per-player model details next to the game logs
    for pid, det in details.items():
        path = os.path.join(OUT, "p", f"{pid}.json")
        try:
            with open(path) as f:
                blob = json.load(f)
        except (OSError, ValueError):
            continue
        blob["props"] = det
        with open(path, "w") as f:
            json.dump(blob, f, separators=(",", ":"))

    rows.sort(key=lambda r: (r["be"] is None, -(r["be"] or -9)))
    board = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "leagues": league_meta, "games": games_out, "players": players, "props": rows,
        "secs": round(time.time() - t0, 1),
    }
    with open(os.path.join(OUT, "board.json"), "w") as f:
        json.dump(board, f, separators=(",", ":"))
    with open(os.path.join(OUT, "debug.json"), "w") as f:
        json.dump({"log": _log[-400:], "unmatched": unmatched, "series": counts}, f, indent=1)
    log(f"done: {len(rows)} rows (props and team bets), {len(players)} players and teams in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
