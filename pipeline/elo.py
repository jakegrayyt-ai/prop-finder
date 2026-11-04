"""Elo ratings from Kalshi's settled results, for the winner markets of every sport outside the NBA, NFL and NHL.

A league's results run in date order. A win moves a rating up by K x (1 - expected), a loss moves it down by
K x expected, and a draw counts as half a win. K starts high and shrinks as a player or team plays more
(250 / (matches + 5)^0.4, the formula FiveThirtyEight used for tennis), so a newcomer's rating finds its level
fast and an established one moves slowly.

Tennis players are rated across tours. ATP, ATP Challenger and ITF men share one pool, WTA, WTA 125 and ITF women
another, and doubles pairs get their own. A player's first rating depends on the tour they first show up in,
so an ITF regular doesn't start level with a tour pro.

Every match is predicted before its result is used, and those predictions are scored afterwards. That calibrates
how far apart two ratings have to be for a given chance and, where there's a home side, what home is worth. The
score against a coin flip ("skill") says how much the ratings actually know, and the edge leans on them only
as much as that.
"""
import math
from collections import defaultdict

NEUTRAL = {"tennis", "esports", "fights"}            # no home side
SCALES = (0.5, 0.65, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0)   # stretch of the rating gap (ratings trained on a short history
HOMES = (-60, -30, 0, 30, 60, 90)                    # are squeezed toward the middle); home edge in rating points
MIN_PRIOR = 8                                        # matches each side needs before its prediction is scored


def k_factor(n):
    return 250.0 / (n + 5) ** 0.4


def pool(lg, group):
    """Which ratings pool a league's results go into."""
    if group != "tennis":
        return lg
    dbl = lg.endswith("dbl")
    base = lg[:-3] if dbl else lg
    women = "wta" in base or base.endswith("w")
    return "tennis-" + ("w" if women else "m") + ("-dbl" if dbl else "")


POOL_LABEL = {"tennis-m": "men’s tennis (ATP, Challenger and ITF)", "tennis-w": "women’s tennis (WTA, WTA 125 and ITF)",
              "tennis-m-dbl": "men’s doubles", "tennis-w-dbl": "women’s doubles"}


def start(lg, group):
    if group != "tennis":
        return 1500.0
    if "itf" in lg:
        return 1350.0
    if "challenger" in lg or "125" in lg:
        return 1450.0
    return 1550.0


def expected(x):
    return 1.0 / (1.0 + 10 ** (-x / 400.0))


def _loss(obs, s, h):
    tot = 0.0
    for d, hs, sa in obs:
        p = min(max(expected(s * d + h * hs), 1e-6), 1 - 1e-6)
        tot -= sa * math.log(p) + (1 - sa) * math.log(1 - p)
    return tot / len(obs)


def _fit(obs, neutral):
    if len(obs) < 20:
        return 1.0, 0.0, None
    best = None
    for s in SCALES:
        for h in ((0,) if neutral else HOMES):
            ll = _loss(obs, s, h)
            if best is None or ll < best[2]:
                best = (s, float(h), ll)
    return best


def _pass(matches, group, h_raw):
    r, n, last = {}, defaultdict(int), {}
    obs = []
    for m in matches:
        a, b = m["a"], m["b"]
        ra = r.setdefault(a, start(m["lg"], group))
        rb = r.setdefault(b, start(m["lg"], group))
        hs = 0 if m["home"] is None else (1 if m["home"] == "a" else -1)
        if n[a] >= MIN_PRIOR and n[b] >= MIN_PRIOR:
            obs.append((ra - rb, hs, m["sa"]))
        e = expected(ra - rb + h_raw * hs)
        r[a] = ra + k_factor(n[a]) * (m["sa"] - e)
        r[b] = rb - k_factor(n[b]) * (m["sa"] - e)
        n[a] += 1
        n[b] += 1
        last[a] = last[b] = m["date"]
    return r, n, last, obs


def rate(matches, group):
    """matches: [{"date", "eid", "a", "b", "sa" (1 a won, 0.5 draw, 0 b won), "home" ("a"/"b"/None), "lg"}].
    Returns the ratings, match counts, calibration and skill for one pool."""
    neutral = group in NEUTRAL
    ms = sorted(matches, key=lambda x: (x["date"], x["eid"]))
    r, n, last, obs = _pass(ms, group, 0.0)
    s, h, ll = _fit(obs, neutral)
    if not neutral and h:
        r, n, last, obs = _pass(ms, group, h / s)          # rerun with the home edge in the updates
        s, h, ll = _fit(obs, neutral)
    skill = None if ll is None else max(0.0, 1 - ll / math.log(2))
    rated = sorted((x for x in r if n[x] >= 5), key=lambda x: -r[x])
    return {"r": r, "n": dict(n), "last": last, "s": s, "h": h, "skill": skill, "nobs": len(obs),
            "rank": {x: i + 1 for i, x in enumerate(rated)}, "of": len(rated),
            "first": ms[0]["date"] if ms else None, "matches": len(ms)}


def chance(R, a, b, home_sign):
    """Chance a beats b (expected score: a draw counts half) from pool ratings R, or None if either is unrated."""
    if a not in R["r"] or b not in R["r"]:
        return None
    return expected(R["s"] * (R["r"][a] - R["r"][b]) + R["h"] * home_sign)
