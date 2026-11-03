"""Team bets: Kalshi moneylines, spreads, game totals and team totals, with each team's results as the history.

History is every finished game this season (the scoreboards the matchup table already loads) plus last season's
regular season (team schedules). Each game looks like a player's game, so hit rates, splits, streaks, the chart and
the drawer work the same way:
    {"eid", "date", "season": "cur"|"prev", "post", "opp", "home", "res", "score", "ot",
     "s": {"win", "margin", "tpts", "opp_pts", "total"}}
A game total's history is both teams' games together, a meeting between them counted once.

The model rates every team's scoring and defense from those scores, adjusted for who they played (recent games weigh
more; early in the season it leans on last season), projects both teams' points tonight, and turns that into a chance
for each Kalshi line: normal spreads for the NBA and NFL, Poisson goals for the NHL (a tie after regulation goes to
overtime or a shootout, which adds one goal for the winner, as in the final score Kalshi settles on).
"""
import datetime as dt
import math
from collections import defaultdict

from scipy import stats as st

from . import injury, kalshi, model, stats

HALF_LIFE = {"nba": 12.0, "nhl": 15.0, "nfl": 6.0}     # games until a game's weight halves
PRIOR_GAMES = {"nba": 10.0, "nhl": 12.0, "nfl": 4.0}   # how many games last season's rating is worth this season
CARRY = {"nba": 0.6, "nhl": 0.5, "nfl": 0.5}           # share of last season's rating expected to carry over
HOME_EDGE = {"nba": 2.0, "nfl": 1.6, "nhl": 0.16}      # home team's average margin edge (points or goals)
SD = {"nba": {"tpts": 11.5, "margin": 13.0, "total": 18.5},   # game-to-game spread around the projection
      "nfl": {"tpts": 9.8, "margin": 13.5, "total": 14.0}}
UNIT = {"nba": "points", "nfl": "points", "nhl": "goals"}
MIN_PRICE = 0.04          # ladder lines priced under 4c or over 96c are left off (nobody trades them)
MAX_SPREAD = 0.30         # and so are markets without a real two-sided book yet
OUT = {"Out", "Injured Reserve", "Suspension", "Doubtful"}
SEVERITY = {"Out": 0, "Suspension": 0, "Injured Reserve": 1, "Doubtful": 2, "Questionable": 3, "Day-To-Day": 4}


def r2(x, n=3):
    return None if x is None else round(x, n)


def _sig(x, d=1):
    return ("+" if x > 0.05 else "−" if x < -0.05 else "") + f"{abs(x):.{d}f}"


# ---------------------------------------------------------------- history
def history(league, finished, team_by_id, tag):
    """{team id: [games, most recent first]} from finished scoreboard-shaped games."""
    out, seen = defaultdict(list), set()
    for g in finished:
        if not g.get("completed") or g.get("home_score") is None or g.get("away_score") is None:
            continue
        if str(g.get("season_type")) not in ("2", "3") or g.get("eid") in seen or not g.get("date"):
            continue
        seen.add(g["eid"])
        detail = (g.get("detail") or "").upper()
        ot = "SO" if "SO" in detail else ("OT" if "OT" in detail else None)
        for side, other in (("home", "away"), ("away", "home")):
            tid, oid = g.get(f"{side}_id"), g.get(f"{other}_id")
            if not tid or not oid:
                continue
            pts, opp = g[f"{side}_score"], g[f"{other}_score"]
            res = "W" if pts > opp else "L" if pts < opp else "T"
            out[tid].append({
                "eid": g["eid"], "date": g["date"], "season": tag, "post": str(g.get("season_type")) == "3",
                "opp": (team_by_id.get(oid) or {}).get("abbr") or g.get(other), "opp_id": oid,
                "home": side == "home", "neutral": bool(g.get("neutral")), "res": res,
                "score": f"{pts:.0f}-{opp:.0f}", "ot": ot,
                "s": {"win": 1.0 if res == "W" else 0.0, "margin": pts - opp, "tpts": pts, "opp_pts": opp,
                      "total": pts + opp},
            })
    for gs in out.values():
        gs.sort(key=lambda x: x["date"], reverse=True)
    return out


def union(home_hist, away_hist, home_abbr, away_abbr):
    """Both teams' games for a game total. A meeting between them shows once, from the home team's side.
    "home" here means the same setup as tonight (home team at home, away team on the road); "at" is where it was."""
    out, seen = [], set()
    for abbr, gs, is_home in ((home_abbr, home_hist, True), (away_abbr, away_hist, False)):
        for g in gs:
            if g["eid"] in seen:
                continue
            seen.add(g["eid"])
            out.append({**g, "team": abbr, "at": g["home"], "home": g["home"] == is_home})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


# ---------------------------------------------------------------- ratings
def _reg_pts(league, g):
    """Points or goals the team scored, without the extra goal an NHL overtime or shootout winner gets."""
    p = g["s"]["tpts"]
    if league == "nhl" and g.get("ot") and g["res"] == "W":
        p -= 1
    return p


def fit(league, hist, avg, prior=None, k=0.0, iters=30):
    """Offense (points above average a team scores) and defense (points above average it allows) for every team,
    adjusted for the opponents it played. Recent games weigh more. Pulled toward `prior` by `k` pseudo-games."""
    hl, he = HALF_LIFE[league], HOME_EDGE[league] / 2
    pos = {(tid, g["eid"]): i for tid, gs in hist.items() for i, g in enumerate(gs)}
    rows = []
    for tid, gs in hist.items():
        for i, g in enumerate(gs):
            j = pos.get((g["opp_id"], g["eid"]), i)
            h = 0 if g.get("neutral") else (1 if g["home"] else -1)
            rows.append((tid, g["opp_id"], _reg_pts(league, g), h * he, 0.5 ** (i / hl), 0.5 ** (j / hl)))
    po, pd = prior or ({}, {})
    off, dfn = dict(po), dict(pd)
    if not rows:
        return off, dfn
    for _ in range(iters):
        num, den = defaultdict(float), defaultdict(float)
        for t, o, p, h, wt, _wo in rows:
            num[t] += wt * (p - avg - h - dfn.get(o, 0.0))
            den[t] += wt
        off = {t: (num[t] + k * po.get(t, 0.0)) / (den[t] + k) for t in den}
        num, den = defaultdict(float), defaultdict(float)
        for t, o, p, h, _wt, wo in rows:
            num[o] += wo * (p - avg - h - off.get(t, 0.0))
            den[o] += wo
        dfn = {o: (num[o] + k * pd.get(o, 0.0)) / (den[o] + k) for o in den}
        mo, md = sum(off.values()) / len(off), sum(dfn.values()) / len(dfn)
        off = {t: v - mo for t, v in off.items()}
        dfn = {t: v - md for t, v in dfn.items()}
    for t, v in po.items():
        off.setdefault(t, v)
    for t, v in pd.items():
        dfn.setdefault(t, v)
    return off, dfn


def ratings(league, cur, prev):
    """cur / prev: {tid: games} for this season and last season."""
    def avg_pts(h):
        v = [_reg_pts(league, g) for gs in h.values() for g in gs]
        return (sum(v) / len(v), len(v)) if v else (None, 0)
    a_prev, n_prev = avg_pts(prev)
    a_cur, n_cur = avg_pts(cur)
    if a_cur is None and a_prev is None:
        return None
    w = min(200, n_prev)      # last season's scoring level, worth up to 200 team-games
    avg = a_cur if a_prev is None else a_prev if a_cur is None else (n_cur * a_cur + w * a_prev) / (n_cur + w)
    p_off, p_dfn = fit(league, prev, a_prev, k=3.0) if a_prev is not None else ({}, {})
    prior = ({t: CARRY[league] * v for t, v in p_off.items()}, {t: CARRY[league] * v for t, v in p_dfn.items()})
    off, dfn = fit(league, cur, avg, prior=prior, k=PRIOR_GAMES[league])
    return {"avg": avg, "off": off, "dfn": dfn, "n_cur": n_cur}


def project(league, R, tid, oid, home, neutral=False):
    """Expected points (goals in the NHL, before any overtime) for the team and its opponent tonight."""
    h = 0.0 if neutral else HOME_EDGE[league] / 2 * (1 if home else -1)
    lo = 0.3 if league == "nhl" else 3.0
    mt = R["avg"] + R["off"].get(tid, 0.0) + R["dfn"].get(oid, 0.0) + h
    mo = R["avg"] + R["off"].get(oid, 0.0) + R["dfn"].get(tid, 0.0) - h
    return max(lo, mt), max(lo, mo)


def nhl_final(lt, lo, n=15):
    """Final-score distribution {(team goals, opponent goals): p}. Regulation goals are Poisson; a regulation tie
    goes to overtime or a shootout, which the stronger side wins a bit more often than half the time."""
    pt, pq = st.poisson.pmf(range(n), lt), st.poisson.pmf(range(n), lo)
    w = 0.5 + max(-0.06, min(0.06, 0.12 * (lt - lo)))
    out = defaultdict(float)
    for a in range(n):
        for b in range(n):
            p = pt[a] * pq[b]
            if a == b:
                out[(a + 1, b)] += p * w
                out[(a, b + 1)] += p * (1 - w)
            else:
                out[(a, b)] += p
    return out


def chance(league, kind, line, mt, mo, dist=None):
    """P(yes) for a market. mt / mo: the team's and opponent's projection (home and away for a game total)."""
    if league == "nhl":
        dist = dist or nhl_final(mt, mo)
        test = {"win": lambda a, b: a > b, "margin": lambda a, b: a - b >= line,
                "tpts": lambda a, b: a >= line, "total": lambda a, b: a + b >= line}[kind]
        p = sum(v for (a, b), v in dist.items() if test(a, b))
    else:
        sd = SD[league]
        if kind == "win":
            p = st.norm.sf(0.0, mt - mo, sd["margin"])
        elif kind == "margin":
            p = st.norm.sf(line - 0.5, mt - mo, sd["margin"])
        elif kind == "tpts":
            p = st.norm.sf(line - 0.5, mt, sd["tpts"])
        else:
            p = st.norm.sf(line - 0.5, mt + mo, sd["total"])
    return float(model.clamp(p, 0.01, 0.99))


# ---------------------------------------------------------------- injuries
def usage_line(league, u, pos):
    if not u or not u.get("gp"):
        return "hasn't played this season"
    n = u["gp"]
    if league == "nba":
        return f"{u.get('min', 0):.0f} min, {u.get('pts', 0):.1f} pts a game in {n}"
    if league == "nhl":
        if u.get("gs"):
            return f"{u['gs']} starts in goal"
        return f"{u.get('toi', 0):.0f} min, {u.get('points', 0):.2f} pts a game in {n}"
    p = (pos or "").upper()
    if p == "QB":
        return f"{u.get('pass_yds', 0):.0f} pass yds a game in {n}"
    if p in ("RB", "FB"):
        return f"{u.get('rush_att', 0):.0f} carries, {u.get('targets', 0):.1f} targets a game in {n}"
    if p in ("WR", "TE"):
        return f"{u.get('targets', 0):.1f} targets, {u.get('rec_yds', 0):.0f} yds a game in {n}"
    return f"played {n} game" + ("s" if n != 1 else "")


def is_key(league, u, pos, team_n):
    if not u or u.get("gp", 0) < (1 if league == "nfl" else 2):
        return False
    if league == "nba":
        return u.get("min", 0) >= 26 or u.get("pts", 0) >= 14
    if league == "nhl":
        if u.get("gs"):
            return team_n > 0 and u["gs"] >= 0.5 * team_n
        return u.get("toi", 0) >= 19 or u.get("points", 0) >= 0.7
    p = (pos or "").upper()
    if p == "QB":
        return u.get("pass_att", 0) >= 20
    if p in ("RB", "FB"):
        return u.get("rush_att", 0) + u.get("targets", 0) >= 12
    if p in ("WR", "TE"):
        return u.get("targets", 0) >= 5.5
    return False


def injury_report(league, tid, L, before):
    """Everyone on the team's injury report, most important first."""
    tg = (L.get("team_games") or {}).get(tid) or []
    team_n = len(tg)
    out = []
    for aid, i in (L.get("inj") or {}).items():
        if str(i.get("team_id")) != str(tid) or not i.get("status") or i["status"] == "Active":
            continue
        u = (L.get("usage") or {}).get(aid)
        key = is_key(league, u, i.get("pos"), team_n)
        missed = injury.missed_since(tg, aid, before) if u and u.get("gp") else 0
        out.append({"name": i.get("name") or "Unknown", "pos": i.get("pos"), "status": i["status"],
                    "type": i.get("type"), "use": usage_line(league, u, i.get("pos")), "key": key, "missed": missed,
                    "out": i["status"] in OUT})
    out.sort(key=lambda x: (not x["key"], SEVERITY.get(x["status"], 5), x["name"]))
    return out[:12]


# ---------------------------------------------------------------- one market
def evaluate(league, m, g, hist, R, ctx):
    """ctx: tid, oid, home (team side), abbr, opp, inj_t, inj_o, rest_t, rest_o, n_t, n_o."""
    kind, line = m["kind"], m["line"]
    stat = "margin" if kind == "win" else kind                 # a win is a margin of 1 or more
    played = [x for x in hist if (x["date"] or "") < g["date"]]
    summ = stats.summarize(played, stat, line, ctx["opp"])

    if kind == "total":
        mt, mo = project(league, R, g["home_id"], g["away_id"], True, g.get("neutral"))
    else:
        mt, mo = project(league, R, ctx["tid"], ctx["oid"], ctx["home"], g.get("neutral"))
    p_model = chance(league, kind, line, mt, mo)

    yb, ya = m["yes_bid"], m["yes_ask"]
    na = m["no_ask"] if m.get("no_ask") and 0 < m["no_ask"] < 1 else ((1 - yb) if yb and yb > 0 else None)
    two_sided = bool(yb and ya and 0 < yb < ya < 1)
    mid = (yb + ya) / 2 if two_sided else (ya if ya and 0 < ya < 1 else None)
    liquid = two_sided and (ya - yb) <= 0.06

    live = g["state"] == "in"
    flags = []
    if live:
        flags.append("Live")
    if not liquid:
        flags.append("Wide spread")
    if not m.get("volume"):
        flags.append("No trades yet")
    key_out = [x for x in (ctx["inj_t"] + ctx["inj_o"]) if x["key"] and x["out"] and x["missed"] < 3]
    if key_out:
        flags.append("Key player out")
    b2b = [ctx["abbr_t"]] if ctx["rest_t"] == 1 else []
    if ctx["rest_o"] == 1:
        b2b.append(ctx["abbr_o"])
    if b2b and league in ("nba", "nhl"):
        flags.append("Back-to-back")
    n_cur = min(ctx["n_t"], ctx["n_o"])
    small = n_cur < (2 if league == "nfl" else 4)
    if small:
        flags.append("Small sample")
    conf = 2 - (1 if small and not summ["prev"]["n"] else 0) - (1 if (not liquid or live) else 0)
    conf = ["low", "low", "med"][max(0, conf)]
    gap = (p_model - mid) if mid is not None else None
    if liquid and gap is not None and abs(gap) > 0.12:
        flags.append("Check news")

    # Team markets are the most traded on Kalshi, so its price moves even less toward the stats than for props.
    # Far from 50/50 it moves less again: a bell curve's tails are where a simple score model is least reliable,
    # and long shots on prediction markets tend to be overpriced already.
    p_blend, k = None, None
    if gap is not None and not live:
        k = (0.25 if liquid else 0.4) * {"low": 0.5, "med": 1.0}[conf]
        k *= math.exp(-max(0.0, abs(gap) - 0.08) / 0.08)
        k *= min(1.0, mid * (1 - mid) / 0.16)
        p_blend = model.clamp(mid + k * gap, 0.005, 0.995)
    e = model.edges(p_blend, ya, na)
    best = max(e, key=e.get) if e else None

    l10 = summ["avg_l10"]
    row = {
        "id": m["ticker"], "lg": league, "pid": ctx["pid"], "gid": f"{league}-{g['eid']}", "kind": ctx["entity"],
        "stat": kind, "line": line, "opp": ctx["opp"], "home": ctx["home"],
        "k": {"yb": r2(yb, 2), "ya": r2(ya, 2), "last": r2(m["last"], 2), "vol": round(m["volume"]) if m.get("volume") else 0},
        "mid": r2(mid, 3),
        "h": {w: [v["hit"], v["n"]] for w, v in summ.items() if isinstance(v, dict) and w not in ("home2", "away2")},
        "strk": summ["streak"], "avg": summ["avg"], "avg10": l10,
        "diff": None if (kind == "win" or l10 is None) else round(l10 - (line - 0.5), 2),
        "last10": [x["s"][stat] for x in played[:10]],
        "p": r2(p_model), "pb": r2(p_blend), "e": {s: r2(v, 4) for s, v in e.items()}, "best": best,
        "be": r2(e.get(best), 4) if best else None, "conf": conf, "flags": flags,
    }
    det = {"steps": steps(league, kind, line, R, ctx, g, mt, mo), "k": r2(k), "key_out": [x["name"] for x in key_out],
           "rest": ctx["rest_t"], "rest_o": ctx["rest_o"], "b2b": b2b}
    return row, det


def steps(league, kind, line, R, ctx, g, mt, mo):
    """How the projection was built, as [label, value, note] rows for the drawer."""
    u = UNIT[league]
    if kind == "total":
        t_id, o_id, t_ab, o_ab, home = g["home_id"], g["away_id"], g["home"], g["away"], True
    else:
        t_id, o_id, t_ab, o_ab, home = ctx["tid"], ctx["oid"], ctx["abbr_t"], ctx["abbr_o"], ctx["home"]
    off_t, dfn_t = R["off"].get(t_id, 0.0), R["dfn"].get(t_id, 0.0)
    off_o, dfn_o = R["off"].get(o_id, 0.0), R["dfn"].get(o_id, 0.0)
    out = [["League average", f"{R['avg']:.1f}" if league != "nhl" else f"{R['avg']:.2f}",
            f"{u.capitalize()} per team per game" + (" before overtime" if league == "nhl" else "")],
           [f"{t_ab} offense", _sig(off_t, 2 if league == "nhl" else 1), f"{u.capitalize()} scored vs average, adjusted for the defenses faced"],
           [f"{o_ab} defense", _sig(dfn_o, 2 if league == "nhl" else 1), f"{u.capitalize()} allowed vs average (minus is a better defense)"],
           [f"{o_ab} offense", _sig(off_o, 2 if league == "nhl" else 1), ""],
           [f"{t_ab} defense", _sig(dfn_t, 2 if league == "nhl" else 1), ""]]
    if not g.get("neutral"):
        he = HOME_EDGE[league]
        out.append(["Home edge", f"{he:g}", f"Average home margin, split between the two teams ({t_ab} {'home' if home else 'away'})"])
    d = 2 if league == "nhl" else 1
    out.append([f"{t_ab} projected", f"{mt:.{d}f}", ""])
    out.append([f"{o_ab} projected", f"{mo:.{d}f}", ""])
    if league == "nhl":
        spread = "Goals are random like a Poisson count. A tie after regulation goes to overtime or a shootout, which adds one goal for the winner"
    else:
        spread = f"Spread of about ±{SD[league]['margin' if kind in ('win', 'margin') else kind]:g} game to game"
    if kind in ("win", "margin"):
        out.append(["Projected margin", _sig(mt - mo, d), spread])
    elif kind == "tpts":
        out.append([f"Projected {t_ab} {u}", f"{mt:.{d}f}", spread])
    else:
        out.append(["Projected total", f"{mt + mo:.{d}f}", spread])
    return out


# ---------------------------------------------------------------- everything for one league
def build(league, tmk, L, today, log):
    """Returns {"rows", "details": {pid: {ticker: det}}, "players": {pid: info}, "files": {pid: blob}, "games": {gid: game}}."""
    team_by_id = L["teams"]
    cur = history(league, L.get("done") or [], team_by_id, "cur")
    prev = history(league, L.get("prev_games") or [], team_by_id, "prev")
    R = ratings(league, cur, prev)
    out = {"rows": [], "details": defaultdict(dict), "players": {}, "files": {}, "games": {}, "unmatched": defaultdict(int)}
    if R is None:
        log(f"{league}: no team results to rate teams from")
        return out
    hist = {t: cur.get(t, []) + prev.get(t, []) for t in set(cur) | set(prev)}
    by_date = defaultdict(list)
    for g in L["games"].values():
        by_date[g["date"]].append(g)

    def find_game(m):
        tm = lambda c, a: kalshi.team_match(league, c, a)  # noqa: E731
        t = m["teams"]
        for d in (m["date"],):
            for g in by_date.get(d, []):
                for i in range(2, len(t) - 1):
                    a, b = t[:i], t[i:]
                    if (tm(a, g["away"]) and tm(b, g["home"])) or (tm(a, g["home"]) and tm(b, g["away"])):
                        return g
        return None

    def rest(tid, before):
        last = next((x["date"] for x in hist.get(tid, []) if x["date"] < before), None)
        return (dt.date.fromisoformat(before) - dt.date.fromisoformat(last)).days if last else None

    inj_cache, n_kept = {}, 0

    def inj(tid, before):
        if (tid, before) not in inj_cache:
            inj_cache[(tid, before)] = injury_report(league, tid, L, before)
        return inj_cache[(tid, before)]

    for m in tmk:
        g = find_game(m)
        if not g:
            out["unmatched"][f"{m['event']} (no game)"] += 1
            continue
        if g["completed"]:
            continue
        yb, ya = m["yes_bid"], m["yes_ask"]
        if not (yb and ya and 0 < yb < ya < 1) or ya - yb > MAX_SPREAD:
            continue                     # nobody's really quoting it yet (new listings sit at 1c bid / 95c ask)
        mid = (yb + ya) / 2
        if m["kind"] != "win" and not (MIN_PRICE <= mid <= 1 - MIN_PRICE):
            continue
        hid, aid_ = g["home_id"], g["away_id"]
        if m["kind"] == "total":
            tid, oid, home, entity = hid, aid_, True, "game"
            pid = f"{league}-game-{g['eid']}"
            h = union(hist.get(hid, []), hist.get(aid_, []), (team_by_id.get(hid) or {}).get("abbr") or g["home"],
                      (team_by_id.get(aid_) or {}).get("abbr") or g["away"])
        else:
            if kalshi.team_match(league, m["k_team"], g["home"]):
                tid, oid, home = hid, aid_, True
            elif kalshi.team_match(league, m["k_team"], g["away"]):
                tid, oid, home = aid_, hid, False
            else:
                out["unmatched"][f"{m['ticker']} (team code)"] += 1
                continue
            entity, pid = "team", f"{league}-team-{tid}"
            h = hist.get(tid, [])
        ab = lambda x: (team_by_id.get(x) or {}).get("abbr") or (g["home"] if x == hid else g["away"])  # noqa: E731
        ctx = {"pid": pid, "entity": entity, "tid": tid, "oid": oid, "home": home,
               "abbr_t": ab(tid), "abbr_o": ab(oid), "opp": ab(oid),
               "inj_t": inj(tid, g["date"]), "inj_o": inj(oid, g["date"]),
               "rest_t": rest(tid, g["date"]), "rest_o": rest(oid, g["date"]),
               "n_t": sum(1 for x in cur.get(tid, []) if x["date"] < g["date"]),
               "n_o": sum(1 for x in cur.get(oid, []) if x["date"] < g["date"])}
        row, det = evaluate(league, m, g, h, R, ctx)
        out["rows"].append(row)
        out["details"][pid][row["id"]] = det
        n_kept += 1
        gid = row["gid"]
        out["games"].setdefault(gid, g)
        if pid not in out["files"]:
            if entity == "game":
                a_t, h_t = team_by_id.get(aid_) or {}, team_by_id.get(hid) or {}
                name = f"{a_t.get('short') or g['away']} @ {h_t.get('short') or g['home']}"
                info = {"name": name, "team": None, "pos": "", "lg": league, "inj": None, "kind": "game"}
                games = h
            else:
                t = team_by_id.get(tid) or {}
                info = {"name": t.get("name") or ab(tid), "team": ab(tid), "pos": "", "lg": league, "inj": None, "kind": "team"}
                games = hist.get(tid, [])
            out["players"][pid] = info
            keep = ("eid", "date", "opp", "home", "res", "score", "ot", "post", "season", "s", "team", "at")
            out["files"][pid] = {"pid": pid, **info, "games": [{k: x[k] for k in keep if x.get(k) is not None}
                                                               for x in games[:140]], "injuries": {}}
        out["files"][pid]["injuries"][ab(tid)] = ctx["inj_t"]
        out["files"][pid]["injuries"][ab(oid)] = ctx["inj_o"]
    log(f"{league}: {n_kept} team markets kept, ratings from {R['n_cur']} team-games this season")
    return out
