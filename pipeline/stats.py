"""Hit rates, splits and streaks from a player's normalized game log.

A normalized game looks like:
    {"eid": "401...", "date": "2026-10-28", "season": "cur"|"prev", "post": False,
     "opp": "BOS", "home": True, "min": 34.5, "s": {"pts": 25, "reb": 7, ...}}
Lists are always most-recent-first.
"""
from statistics import median

VOLUME_KEY = {
    "nba": lambda stat: "min",
    "nhl": lambda stat: "toi",
    "nfl": lambda stat: (
        "targets" if stat.startswith("rec") else
        "rush_att" if stat.startswith("rush_") and stat != "rush_rec_yds" else
        "pass_att" if stat.startswith("pass") or stat in ("ints",) else
        "touches"
    ),
}


def vals(games, stat):
    return [g["s"][stat] for g in games if g["s"].get(stat) is not None]


def hr(vs, t):
    return {"hit": sum(1 for v in vs if v >= t), "n": len(vs)}


def mean(vs):
    return round(sum(vs) / len(vs), 2) if vs else None


def streak(vs, t):
    """+N = hit the last N games in a row, -N = missed the last N in a row."""
    if not vs:
        return 0
    first = vs[0] >= t
    n = 0
    for v in vs:
        if (v >= t) != first:
            break
        n += 1
    return n if first else -n


def summarize(games, stat, t, opp=None):
    played = [g for g in games if g["s"].get(stat) is not None]
    cur = [g for g in played if g["season"] == "cur"]
    prev = [g for g in played if g["season"] == "prev"]
    allv = vals(played, stat)
    vc, vp = vals(cur, stat), vals(prev, stat)
    l10 = allv[:10]
    out = {
        "l5": hr(allv[:5], t), "l10": hr(l10, t), "l20": hr(allv[:20], t),
        "szn": hr(vc, t), "prev": hr(vp, t),
        "home": hr(vals([g for g in cur if g["home"]], stat), t),
        "away": hr(vals([g for g in cur if not g["home"]], stat), t),
        "home2": hr(vals([g for g in played if g["home"]], stat), t),
        "away2": hr(vals([g for g in played if not g["home"]], stat), t),
        "h2h": hr(vals([g for g in played if opp and g["opp"] == opp], stat), t) if opp else {"hit": 0, "n": 0},
        "streak": streak(allv, t),
        "avg": mean(vc), "avg_prev": mean(vp), "avg_l5": mean(allv[:5]), "avg_l10": mean(l10),
        "med": median(vc) if vc else None,
        "diff": round(mean(l10) - t, 2) if l10 else None,
    }
    return out


def rate(h):
    return h["hit"] / h["n"] if h and h.get("n") else None


def volume_trend(games, league, stat):
    """Recent vs season usage (minutes / ice time / targets / carries / attempts)."""
    key = VOLUME_KEY.get(league, lambda s: None)(stat)
    if not key:
        return None
    cur = [g for g in games if g["season"] == "cur" and g["s"].get(key) is not None]
    v = [g["s"][key] for g in cur]
    if len(v) < 3:
        v = [g["s"][key] for g in games if g["s"].get(key) is not None]
    if len(v) < 3:
        return None
    return {"key": key, "l3": mean(v[:3]), "szn": mean(v)}
