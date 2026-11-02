"""Opponent defense vs position, built from every finished box score this season.

For each team we add up what opposing players at each position produced against
it, per game. A ratio above 1 means the team gives up more of that stat to that
position than the league average.
"""
from collections import defaultdict

from .espn import pos_group

STATS = {
    "nba": ["pts", "reb", "ast", "3pm", "stl", "blk", "pra", "stocks"],
    "nfl": ["pass_yds", "pass_tds", "pass_cmp", "pass_att", "ints", "rush_yds", "rush_att", "rush_tds",
            "rec", "rec_yds", "rec_tds", "rush_rec_yds", "tds", "targets"],
    "nhl": ["goals", "assists", "points", "sog", "saves"],
}


def build(league, boxes, roster_pos):
    """boxes: {eid: [player lines]}; roster_pos: {aid: position abbr}. Returns table dict."""
    totals = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))  # opp -> group -> stat -> sum
    games = defaultdict(set)  # opp -> set(eid)
    for eid, lines in boxes.items():
        for ln in lines:
            opp = ln.get("opp_id")
            if not opp:
                continue
            games[opp].add(eid)
            grp = pos_group(league, ln.get("pos") or roster_pos.get(ln["aid"]))
            if not grp:
                continue
            for st in STATS[league]:
                v = ln["s"].get(st)
                if v is not None:
                    totals[opp][grp][st] += v
    per_game = {}
    for opp, groups in totals.items():
        n = len(games[opp])
        if not n:
            continue
        per_game[opp] = {"n": n, "g": {grp: {st: v / n for st, v in sts.items()} for grp, sts in groups.items()}}
    # league average and rank per (group, stat)
    avg, ranks = defaultdict(dict), defaultdict(dict)
    groups = {grp for t in per_game.values() for grp in t["g"]}
    for grp in groups:
        for st in STATS[league]:
            vals = [(tid, t["g"].get(grp, {}).get(st)) for tid, t in per_game.items()]
            vals = [(tid, v) for tid, v in vals if v is not None]
            if len(vals) < 4:
                continue
            avg[grp][st] = sum(v for _, v in vals) / len(vals)
            for i, (tid, _) in enumerate(sorted(vals, key=lambda x: -x[1]), 1):
                ranks[tid][(grp, st)] = (i, len(vals))
    return {"per_game": per_game, "avg": avg, "ranks": ranks}


def lookup(table, opp_id, grp, stat):
    """-> dict(allowed, avg, ratio, rank, of, n) or None."""
    if not table or not opp_id or not grp:
        return None
    t = table["per_game"].get(opp_id)
    a = table["avg"].get(grp, {}).get(stat)
    if not t or not a:
        return None
    v = t["g"].get(grp, {}).get(stat)
    if v is None:
        return None
    rank, of = table["ranks"].get(opp_id, {}).get((grp, stat), (None, None))
    n = t["n"]
    raw_ratio = v / a if a else 1.0
    # early in the season a handful of games is mostly noise: shrink toward 1
    w = min(1.0, n / 12.0)
    return {"allowed": round(v, 2), "avg": round(a, 2), "ratio": round(1 + w * (raw_ratio - 1), 4),
            "raw_ratio": round(raw_ratio, 3), "rank": rank, "of": of, "n": n}
