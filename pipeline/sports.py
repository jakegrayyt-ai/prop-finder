"""Every other sport on Kalshi, on the props board: college football and basketball, soccer, tennis, UFC and boxing,
esports, cricket, and basketball, hockey, football and baseball leagues outside the NBA, NFL and NHL.

Kalshi only has player props for the NBA, NFL and NHL (build.py). Everywhere else it lists game markets, and those
are what this adds: winner (and draw in soccer), spread, game total, team total and both teams to score.

The leagues aren't hard-coded. Kalshi tags every series with its sport, so each run reads the list of sports series
and keeps the per-game ones (…GAME, …MATCH, …SPREAD, …TOTAL…). A league Kalshi adds tomorrow shows up on its own.

History comes from Kalshi too: every market it settled (its API keeps about two months; we cache what we've seen, so
it grows from there). A settled market carries the real result in expiration_value: the total for totals, the
winning margin for spreads, both scores for team totals, the winner for game markets. Each team's games then look
like the ESPN team games in teams.py, so the board, hit rates and charts work the same way.

The model is a trend estimate: the hit rate on that exact line, recent games counted more, pulled hard toward
Kalshi's price because a couple of months of results says little on its own. The edge leans on the price even more.
"""
import datetime as dt
import math
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import backtest, cache, elo, kprops, model, stats
from . import kalshi as K
from .net import get_json

BASE = K.BASES[0]
CORE = ("KXNBA", "KXNFL", "KXNHL")                      # props and team bets there come from ESPN
SUFFIX = {"GAME": "win", "MATCH": "win", "FIGHT": "win", "DOUBLES": "win", "SPREAD": "margin", "GSPREAD": "margin",
          "TOTAL": "total", "GTOTAL": "total", "TOTALMAPS": "total", "TEAMTOTAL": "tpts", "BTTS": "btts"}
SERIES_RE = re.compile(r"^(KX[A-Z0-9]+?)(TEAMTOTAL|TOTALMAPS|GTOTAL|GSPREAD|DOUBLES|SPREAD|TOTAL|GAME|MATCH|FIGHT|BTTS)$")
SKIP_STEM = re.compile(r"(?:1H|2H|1Q|2Q|3Q|4Q|1P|2P|3P|EXACT|F5|RFI|PRECISE)$")   # halves, quarters, exact scores
TAG_GROUP = {"Soccer": "soccer", "Basketball": "hoops", "Football": "football", "Baseball": "baseball",
             "Esports": "esports", "Tennis": "tennis", "Hockey": "hockey", "Cricket": "cricket", "MMA": "fights",
             "Boxing": "fights", "UFC": "fights"}
STEM_GROUP = {"KXNCAAF": "cfb", "KXNCAAMB": "cbb", "KXNCAAWB": "cbb"}
GROUPS = {"cfb": "College football", "cbb": "College basketball", "soccer": "Soccer", "tennis": "Tennis",
          "fights": "UFC and boxing", "esports": "Esports", "hoops": "Basketball", "hockey": "Hockey",
          "football": "Football", "baseball": "Baseball", "cricket": "Cricket", "other": "Other sports"}
UNIT = {"soccer": "goals", "hockey": "goals", "hoops": "points", "football": "points", "cfb": "points",
        "cbb": "points", "baseball": "runs", "tennis": "games", "esports": "maps", "cricket": "runs",
        "fights": "rounds", "other": "points"}
AWAY_FIRST = {"cfb", "cbb", "football"}                  # Kalshi lists the away team first in US games
DURATION = {"soccer": 2.0, "cfb": 3.5, "football": 3.5, "cbb": 2.2, "hoops": 2.2, "hockey": 2.6, "baseball": 3.0,
            "tennis": 2.0, "esports": 2.5, "cricket": 4.0, "fights": 0.5, "other": 2.0}
MIN_PRICE, MAX_SPREAD = 0.06, 0.30
LADDER = 7                          # lines kept per ladder (team + bet type), the ones closest to a coin flip
DAYS_AHEAD = 6
HALF_LIFE, PRIOR = 10.0, 10.0       # trend estimate: games until a game's weight halves; games' worth of price prior
# (the edge then moves only 10% of the way from the price toward that estimate)
SETTLED_TTL = 90 * 60               # top up each series' settled history at most this often
SETTLED_PAGES = 160                 # per run; the first backfill spreads over a few runs instead of tripping rate limits
EMPTY_TTL = 3 * 3600                # a series with nothing open is checked again after this long
NO_EXACT_MARGIN = {"tennis"}        # Kalshi's value on tennis game spreads isn't the margin
HIST_TTL = 7 * 86400                # winners from before Kalshi's live window: refreshed weekly
HIST_PAGES = int(os.environ.get("PROP_HIST_PAGES", 60))   # per run, so the first backfill spreads over a few runs
ELO_K = (0.25, 0.35)                # how far the edge moves from the price toward the ratings (liquid, thin book)
ELO_FULL_N = 15                     # results each side needs for the full weight
ELO_FULL_SKILL = 0.08               # calibrated improvement on a coin flip that earns the full weight
ELO_DECAY = 0.10                    # past a 10-point gap with the price, the weight fades
ELO_NEWS = 0.20                     # past 20 points on a liquid market, flag it
CLOSE_KEY = "kalshi/elo-closing"    # last price and rating forecast before each rated match starts
CLOSE_DAYS = 45                     # how long those are kept for learning the weight
FIT_PRIOR = 300                     # settled matches' worth of trust in the default weight


def r2(x, n=3):
    return None if x is None else round(x, n)


def _num(x):
    try:
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _ts(s):
    try:
        return dt.datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40]


EVENT_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})(\d{4})?([A-Z0-9]+)$")   # 26NOV03 [1430] PENGAM


def event_date(ev):
    """'KXEPLGAME-26NOV08ARSCHE' -> 2026-11-08."""
    part = ev.split("-", 1)[1] if "-" in ev else ev
    m = EVENT_RE.match(part)
    if not m:
        return None
    try:
        return dt.date(2000 + int(m.group(1)), K.MONTHS[m.group(2)], int(m.group(3)))
    except (KeyError, ValueError):
        return None


def fetch_open(series, log=print):
    """One series' open markets, retried after a pause if Kalshi rate-limits us (HTTP 429)."""
    for attempt in range(3):
        try:
            return series, K.fetch_series(BASE, series)
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                log(f"sports: {series} failed {e!r}"[:200])
            time.sleep(4 * (attempt + 1))
    return series, []


# ---------------------------------------------------------------- which series
def league_series(log):
    """{league key: {"label", "group", "unit", "series": [(ticker, kind)]}} for every per-game sports series."""
    def fetch():
        d = get_json(BASE + "/series", params={"category": "Sports"})
        return [{"ticker": s.get("ticker"), "title": s.get("title") or "", "tags": s.get("tags") or []}
                for s in d.get("series") or [] if (s.get("category") or "Sports") == "Sports"]
    series = cache.cached("kalshi/series-sports", 6 * 3600, fetch)
    out = {}
    for s in series:
        t = s["ticker"] or ""
        m = SERIES_RE.match(t)
        stem, kind = (m.group(1), SUFFIX[m.group(2)]) if m else ((t, "win") if t == "KXBOXING" else (None, None))
        if not stem or stem.startswith(CORE) or SKIP_STEM.search(stem):
            continue
        tag = (s["tags"] or [""])[0]
        group = STEM_GROUP.get(stem) or TAG_GROUP.get(tag) or "other"
        key = stem[2:].lower()
        if m and m.group(2) == "DOUBLES":
            key += "dbl"                   # doubles pairs are their own league, not mixed in with singles players
        lg = out.setdefault(key, {"label": None, "group": group, "unit": UNIT[group], "series": []})
        lg["series"].append((t, kind))
        if kind == "win":
            title = re.sub(r"\s+(Games?|Match(es)?|Fights?|Winner)$", "", s["title"]).strip()
            lg["label"] = lg["label"] or title
    for key, lg in out.items():
        lg["label"] = lg["label"] or key.upper()
    log(f"sports: {len(out)} leagues, {sum(len(v['series']) for v in out.values())} series")
    return out


# ---------------------------------------------------------------- markets
def parse(kind, mk):
    """One Kalshi market -> what it pays on. line: the whole number that wins (over 2.5 -> 3)."""
    ev = mk.get("event_ticker") or ""
    key = ev.split("-", 1)[1] if "-" in ev else ""
    date = event_date(ev)
    if not key or not date:
        return None
    suf = (mk.get("ticker") or "").rsplit("-", 1)[-1]
    sub = (mk.get("yes_sub_title") or "").strip()
    base = {"key": key, "date": date.isoformat(), "ticker": mk.get("ticker")}
    if kind == "win":
        if suf == "TIE" or sub.lower() in ("tie", "draw"):
            return {**base, "k": "draw", "c": None, "line": 1}
        return {**base, "k": "win", "c": suf, "line": 1, "name": sub or suf}
    if kind == "btts":
        return {**base, "k": "btts", "c": None, "line": 1}
    x = K._f(mk.get("floor_strike"))
    if x is None or mk.get("strike_type") not in ("greater", None):
        return None
    line = int(x // 1) + 1
    if kind == "total":
        return {**base, "k": "total", "c": None, "line": line}
    code = re.sub(r"\d+$", "", suf)
    return {**base, "k": kind, "c": code, "line": line} if code else None


def add_win(e, p, res):
    """One settled winner (or draw) market into its event's summary."""
    if p["k"] == "win":
        e.setdefault("n", {})[p["c"]] = p["name"]
    if res == "yes":
        e["w"] = p["c"] or "TIE"
    elif res not in ("yes", "no"):
        e["void"] = 1          # cancelled, postponed or settled at a fair price


def settled_old(series, budget):
    """Winners Kalshi settled before its live API's window (about two months; older ones move to
    /historical/markets). Only winners, since that's all the ratings need. One full pass per series, resumed across
    runs with the saved cursor, then refreshed weekly. budget: shared list [pages left this run]."""
    key = f"kalshi/hist-win/{series}"
    data, saved = cache.entry(key)
    if data and data.get("done") and time.time() - saved < HIST_TTL:
        return data["ev"]
    if budget[0] <= 0:
        return (data or {}).get("ev", {})
    if not data or data.get("done"):
        data = {"ev": (data or {}).get("ev", {}), "cursor": None, "done": False}
    cursor = data.get("cursor")
    while budget[0] > 0:
        params = {"series_ticker": series, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        budget[0] -= 1
        try:
            d = get_json(BASE + "/historical/markets", params=params)
        except Exception:
            data["cursor"] = None          # maybe a stale cursor: start this series over next time
            cache.put(key, data)
            raise
        mks = d.get("markets") or []
        for mk in mks:
            p = parse("win", mk)
            if p:
                add_win(data["ev"].setdefault(p["key"], {"d": p["date"]}), p, mk.get("result"))
        cursor = d.get("cursor")
        if not cursor or not mks:
            data["done"], cursor = True, None
            break
        time.sleep(0.05)
    data["cursor"] = cursor
    cache.put(key, data)
    return data["ev"]


def settled(series, kind, budget):
    """Settled results for one series, by event key. Cached; each run only asks for what settled since last time.
    budget: shared list [pages left this run]."""
    key = f"kalshi/settled3/{series}"
    data, saved = cache.entry(key)
    if data and time.time() - saved < SETTLED_TTL:
        return data["ev"]
    if budget[0] <= 0:
        return (data or {}).get("ev", {})
    data = data or {"since": 0, "ev": {}}
    params = {"series_ticker": series, "status": "settled", "limit": 1000}
    if data["since"]:
        params["min_close_ts"] = int(data["since"]) - 3 * 86400
    newest, cursor = data["since"], None
    for _ in range(80):
        if cursor:
            params["cursor"] = cursor
        budget[0] -= 1
        d = get_json(BASE + "/markets", params=params)
        mks = d.get("markets") or []
        for mk in mks:
            p = parse(kind, mk)
            if not p:
                continue
            newest = max(newest, _ts(mk.get("close_time")))
            e = data["ev"].setdefault(p["key"], {"d": p["date"]})
            res, val = mk.get("result"), mk.get("expiration_value")
            r = 1 if res == "yes" else 0 if res == "no" else None
            if kind == "win":
                add_win(e, p, res)
            elif kind == "btts" and res in ("yes", "no"):
                e["b"] = 1 if res == "yes" else 0
            elif kind == "total":
                if _num(val) is not None:
                    e["t"] = _num(val)
                if r is not None:
                    e.setdefault("tk", []).append([p["line"], r])
            elif kind == "margin":
                if _num(val) is not None:
                    e["m"] = abs(_num(val))
                if r is not None:
                    e.setdefault("mk", []).append([p["c"], p["line"], r])
            elif kind == "tpts":
                sc = re.match(r"\s*Home:\s*(\d+)\s*,\s*Away:\s*(\d+)", str(val or ""))
                if sc:
                    e["s"] = [int(sc.group(1)), int(sc.group(2))]
                if r is not None:
                    e.setdefault("sk", []).append([p["c"], p["line"], r])
        cursor = d.get("cursor")
        if not cursor or len(mks) < 1000:
            break
        time.sleep(0.05)
    data["since"] = newest
    cache.put(key, data)
    return data["ev"]


def milestones(log):
    """Kalshi's start times: event ticker (and event key) -> ISO start."""
    def fetch():
        out, cursor = {}, None
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
        for _ in range(80):
            params = {"limit": 100, "category": "Sports", "minimum_start_date": since}
            if cursor:
                params["cursor"] = cursor
            d = get_json(BASE + "/milestones", params=params)
            for m in d.get("milestones") or []:
                start = m.get("start_date")
                evs = set(m.get("related_event_tickers") or []) | set(m.get("primary_event_tickers") or [])
                main = (m.get("details") or {}).get("main_game_event_ticker")
                if main:
                    evs.add(main)
                for ev in evs:
                    out[ev] = start
                    if "-" in ev:
                        out.setdefault(ev.split("-", 1)[1], start)
            cursor = d.get("cursor")
            if not cursor or not d.get("milestones"):
                break
        return out
    try:
        return cache.cached("kalshi/milestones", 20 * 60, fetch)
    except Exception as e:  # noqa: BLE001
        log(f"sports: milestones failed {e!r}"[:200])
        return {}


# ---------------------------------------------------------------- history
def bounds(checks, lo=None, hi=None):
    """[(line, won)] -> the range the real value must be in: 'over 2.5' won means 3 or more."""
    for line, r in checks:
        if r:
            lo = line if lo is None else max(lo, line)
        else:
            hi = line - 1 if hi is None else min(hi, line - 1)
    return lo, hi


def pick(value, lo, hi):
    """Kalshi's reported value if the settled lines agree with it, else the value the lines pin down, else None."""
    inside = value is not None and (lo is None or value >= lo) and (hi is None or value <= hi)
    if inside:
        return float(value)
    if lo is not None and lo == hi:
        return float(lo)
    return None


def order_codes(key, codes):
    """'26OCT31ORSTFRES' + {'FRES', 'ORST'} -> ['ORST', 'FRES'] (the order in the ticker)."""
    m = EVENT_RE.match(key)
    teams = m.group(5) if m else key
    cs = sorted(codes, key=len, reverse=True)
    for a in cs:
        if teams.startswith(a):
            rest = [b for b in cs if b != a]
            return [a] + rest
    return sorted(codes)


def team_history(lg, cfg, past):
    """past: {kind: {event key: summary}} -> {team id: [games, most recent first]}, {team id: (code, name)}."""
    games, who = defaultdict(list), {}
    for key, e in past.get("win", {}).items():
        names = e.get("n") or {}
        codes = [c for c in names if c != "TIE"]
        if len(codes) != 2 or e.get("void") or not e.get("w"):
            continue
        a, b = order_codes(key, codes)
        w = e["w"]
        te = past.get("total", {}).get(key) or {}
        me = past.get("margin", {}).get(key) or {}
        se = past.get("tpts", {}).get(key) or {}
        btts = (past.get("btts", {}).get(key) or {}).get("b")
        total = pick(te.get("t"), *bounds(te.get("tk") or []))
        # each team's margin range: its own spread lines, the other team's (inverted), and who won
        mb = {}
        for c, o in ((a, b), (b, a)):
            lo, hi = (0, 0) if w == "TIE" else ((1, None) if w == c else (None, -1))
            for code, line, r in me.get("mk") or []:
                if code == c:
                    lo, hi = bounds([(line, r)], lo, hi)
                elif code == o:      # other team won by `line`+  <=>  this team's margin <= -line
                    if r:
                        hi = -line if hi is None else min(hi, -line)
                    else:
                        lo = 1 - line if lo is None else max(lo, 1 - line)
            mb[c] = (lo, hi)
        mabs = None if cfg["group"] in NO_EXACT_MARGIN else me.get("m")
        score = {}
        if se.get("s"):   # "Home: x, Away: y": use whichever way round agrees with the team-total lines and the winner
            hs, aws = se["s"]
            for home_code in ((b, a) if cfg["group"] in AWAY_FIRST else (a, b)):
                away_code = b if home_code == a else a
                cand = {home_code: hs, away_code: aws}
                ok = all(((cand.get(code, -1) >= line) == bool(r)) for code, line, r in se.get("sk") or [] if code in cand)
                won = (w == "TIE" and hs == aws) or (w in cand and cand[w] > max(v for k2, v in cand.items() if k2 != w))
                if ok and won:
                    score = cand
                    break
            if score and total is None:
                total = float(hs + aws)
        for c, o in ((a, b), (b, a)):
            res = "D" if w == "TIE" else ("W" if w == c else "L")
            s = {"win": 1.0 if res == "W" else 0.0, "wl": {"W": 1.0, "L": -1.0, "D": 0.0}[res],
                 "draw": 1.0 if res == "D" else 0.0}
            if score:
                s["tpts"], s["opp_pts"] = float(score[c]), float(score[o])
                s["margin"] = s["tpts"] - s["opp_pts"]
            else:
                cand = None if mabs is None else (0.0 if res == "D" else (mabs if res == "W" else -mabs))
                m_ = pick(cand, *mb[c])
                if m_ is not None:
                    s["margin"] = m_
                tp = pick(None, *bounds([(line, r) for code, line, r in se.get("sk") or [] if code == c]))
                if tp is not None:
                    s["tpts"] = tp
            m_ = s.get("margin")
            if total is not None and m_ is not None and (total - abs(m_) < 0 or (total - abs(m_)) % 2):
                s.pop("margin")      # total minus margin is twice the losing score, so it can't be odd or negative
            if total is not None and abs(s.get("margin", 0)) <= total:
                s["total"] = float(total)
            if btts is not None:
                s["btts"] = float(btts)
            tid = f"{c}:{slug(names.get(c))}"
            who[tid] = (c, names.get(c) or c)
            home = (c == b) if cfg["group"] in AWAY_FIRST else None
            sc_txt = f"{score[c]}-{score[o]}" if score else None
            if not sc_txt and "tpts" in s and "margin" in s and s["tpts"] - s["margin"] >= 0:
                sc_txt = f"{s['tpts']:.0f}-{s['tpts'] - s['margin']:.0f}"     # their score and the margin give both
            games[tid].append({"eid": key, "date": e["d"], "season": "cur", "post": False, "opp": o,
                               "oppn": names.get(o) or o, "home": home, "res": res, "score": sc_txt, "s": s})
    for gs in games.values():
        gs.sort(key=lambda g: (g["date"], g["eid"]), reverse=True)
    return games, who


# ---------------------------------------------------------------- one market
def trend(vals, line):
    """Recency-weighted hit rate pulled toward nothing yet: (weighted hits, weight)."""
    w = [0.5 ** (i / HALF_LIFE) for i in range(len(vals))]
    return sum(wi for wi, v in zip(w, vals) if v >= line), sum(w)


def evaluate(lg, cfg, m, q, ev, hist, ctx):
    kind, line = m["k"], m["line"]
    stat = "wl" if kind == "win" else kind
    played = [x for x in hist if x["date"] < ev["date"] and x["s"].get(stat) is not None]
    summ = stats.summarize(played, stat, line, ctx["opp"])
    if cfg["group"] not in AWAY_FIRST or kind in ("total", "btts", "draw"):
        summ["home"] = summ["away"] = {"hit": 0, "n": 0}
    yb, ya = q["yb"], q["ya"]
    na = q["na"] if q.get("na") and 0 < q["na"] < 1 else ((1 - yb) if yb and yb > 0 else None)
    mid = (yb + ya) / 2
    liquid = (ya - yb) <= 0.06
    vals = [x["s"][stat] for x in played]
    hw, w = trend(vals, line)
    p_model = model.clamp((hw + PRIOR * mid) / (w + PRIOR), 0.01, 0.99)
    n = len(vals)
    live = ev["state"] == "in"
    tail = min(1.0, mid * (1 - mid) / 0.16)
    E = ctx.get("elo") if kind == "win" else None
    if E and E.get("p") is not None:
        p_model = model.clamp(E["p"] - 0.5 * E["draw"], 0.01, 0.99)    # a draw counts half in the ratings
        n_min = min(E["n"], E["n_opp"])
        skill = E["skill"] or 0.0
    else:
        E = None
    flags = ["Live"] if live else []
    if not liquid:
        flags.append("Wide spread")
    if not q.get("vol"):
        flags.append("No trades yet")
    small = (n_min < 6) if E else (n < 5)
    if small:
        flags.append("Small sample")
    conf = "low" if (small or not liquid or live or (E and skill < 0.02)) else "med"
    gap = p_model - mid
    if E and liquid and abs(gap) > ELO_NEWS:
        flags.append("Check news")       # a gap this big usually means news the results don't know about
    p_blend, k, kraw = None, None, None
    if not live and E:
        # the ratings know who beat whom, not injuries, form or surface, so the price still does most of the work,
        # and more of it the further apart the two are. kraw is the default weight; m is what settled matches
        # say the ratings deserve on top of it (learn_weights)
        kraw = default_weight(mid, p_model, n_min, skill, liquid)
        k = kraw * E["m"]
        p_blend = model.clamp(mid + k * gap, 0.005, 0.995)
    elif not live:
        # a raw hit rate doesn't know who the games were against, so it barely moves the price
        k = (0.10 if liquid else 0.15) * {"low": 0.5, "med": 1.0}[conf] * tail
        p_blend = model.clamp(mid + k * gap, 0.005, 0.995)
    e = model.edges(p_blend, ya, na)
    best = max(e, key=e.get) if e else None
    show = [x["s"].get("margin", x["s"]["wl"]) if kind == "win" else x["s"][stat] for x in played[:10]]
    row = {
        "id": m["ticker"], "lg": lg, "grp": cfg["group"], "src": "k", "u": cfg["unit"], "pid": ctx["pid"],
        "gid": f"{lg}-{ev['key']}", "kind": ctx["entity"], "stat": kind, "line": line, "opp": ctx["opp"],
        "home": ctx["home"],
        "k": {"yb": r2(yb, 2), "ya": r2(ya, 2), "last": r2(q.get("last"), 2), "vol": round(q["vol"]) if q.get("vol") else 0},
        "mid": r2(mid, 3),
        "h": {wn: [v["hit"], v["n"]] for wn, v in summ.items()
              if isinstance(v, dict) and wn in ("l5", "l10", "l20", "szn", "h2h", "home", "away") and (v["n"] or wn not in ("home", "away"))},
        "strk": summ["streak"], "last10": show, "p": r2(p_model), "pb": r2(p_blend),
        "e": {s: r2(v, 4) for s, v in e.items()}, "best": best, "be": r2(e.get(best), 4) if best else None,
        "conf": conf, "flags": flags,
    }
    if kind in ("margin", "tpts", "total") and summ["avg_l10"] is not None:
        row["avg10"] = summ["avg_l10"]
        row["diff"] = round(summ["avg_l10"] - (line - 0.5), 2)
    elif kind == "win" and any("margin" in x["s"] for x in played[:10]):
        known = [x["s"]["margin"] for x in played[:10] if "margin" in x["s"]]
        row["avg10"] = round(sum(known) / len(known), 2)
    if E:
        row["el"] = [round(E["r"]), round(E["r_opp"]), E["n"], E["n_opp"]]
        if kraw is not None:
            row["kraw"] = r2(kraw, 4)
        return row, elo_details(E, mid, p_model, k)
    rate = (hw / w) if w else None
    det = {"k": r2(k), "steps": [
        ["Kalshi’s price", f"{mid * 100:.0f}%", "What traders think right now"],
        ["Hit rate, recent games counted more", "—" if rate is None else f"{rate * 100:.0f}%",
         f"{n} game{'s' if n != 1 else ''} with a known result since Kalshi’s history starts (late summer)"],
        ["Trend estimate", f"{p_model * 100:.0f}%",
         f"The hit rate pulled toward the price with {PRIOR:.0f} games’ worth of weight, since a couple of months of results says little on its own"]]}
    return row, det


def default_weight(mid, p_model, n_min, skill, liquid):
    """How far the edge moves from Kalshi's price toward the ratings before the backtest's verdict (m) is applied."""
    low = n_min < 6 or not liquid or skill < 0.02
    tail = min(1.0, mid * (1 - mid) / 0.16)
    return (ELO_K[0] if liquid else ELO_K[1]) * (0.5 if low else 1.0) * tail \
        * min(1.0, n_min / ELO_FULL_N) * min(1.0, skill / ELO_FULL_SKILL) \
        * math.exp(-max(0.0, abs(p_model - mid) - ELO_DECAY) / ELO_DECAY)


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _md(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def elo_details(E, mid, p_model, k):
    R = E["R"]

    def note(x, n):
        s = f"From {n} result{'s' if n != 1 else ''} on Kalshi"
        if x in R["rank"]:
            s += f", {_ordinal(R['rank'][x])} of {R['of']} rated in {E['label']}"
        return s
    steps = [["Kalshi’s price", f"{mid * 100:.0f}%", "What traders think right now"],
             [f"{E['name']}’s rating", f"{E['r']:.0f}", note(E["me"], E["n"])],
             [f"{E['name_opp']}’s rating", f"{E['r_opp']:.0f}", note(E["opp"], E["n_opp"])]]
    if E["hs"] and R["h"]:
        side = E["name"] if E["hs"] > 0 else E["name_opp"]
        steps.append(["Home side", side, f"Home is worth about {abs(R['h']):.0f} rating points in this league"
                      + (" (here the first-listed team does better, whoever hosts)" if R["h"] < 0 else "")])
    gap = R["s"] * (E["r"] - E["r_opp"])
    if E["draw"]:
        src = "Kalshi’s draw price" if E["draw_src"] == "k" else "how often this league’s games end level"
        steps.append(["Ratings say", f"{p_model * 100:.0f}%",
                      f"{E['name']} takes {E['p'] * 100:.0f}% of the points (a draw counts half). With a "
                      f"{E['draw'] * 100:.0f}% chance of a draw ({src}), that’s a {p_model * 100:.0f}% chance to win"])
    else:
        steps.append(["Ratings say", f"{p_model * 100:.0f}%",
                      f"Chance {E['name']} wins, from the {abs(gap):.0f}-point gap"
                      + (" with home included" if E["hs"] and R["h"] else "")])
    sk = R["skill"] or 0.0
    since = f" since {_md(R['first'])}" if R.get("first") else ""
    steps.append(["How much the ratings know", f"{sk * 100:.0f}%",
                  f"The ratings predicted {R['nobs']:,} past matches{since} before each result counted, and beat a "
                  f"coin flip by {sk * 100:.0f}% (log loss). The edge leans on them less when that’s small"])
    if E.get("m_n"):
        steps.append(["Tested against Kalshi’s price", f"×{E['m']:.2f}",
                      f"On {E['m_n']:,} settled matches in this sport, moving Kalshi’s pre-match price toward the "
                      f"ratings " + ("helped, so they get more weight than the default" if E["m"] > 1.02 else
                                     "made things worse, so the edge is just Kalshi’s price" if E["m"] < 0.05 else
                                     "didn’t help much, so they get less weight than the default" if E["m"] < 0.98 else
                                     "made little difference, so the default weight stands")])
    return {"k": r2(k), "m": "elo", "steps": steps}


# ---------------------------------------------------------------- ratings
def rating_id(group, code, name):
    """Who a result belongs to in the ratings: tennis players by name across tours, everyone else per league."""
    return slug(name) if group == "tennis" else f"{code}:{slug(name)}"


def pool_matches(leagues, pool_of, live_pools, past, old):
    """Every settled winner result, in the form the ratings take, for each pool with games on the board
    -> ({pool: [match]}, {league: chance of a draw}, {pool: group})."""
    matches, draw_rate, group_of = defaultdict(list), {}, {}
    for lg, cfg in leagues.items():
        pl = pool_of[lg]
        if pl not in live_pools:
            continue
        g = group_of[pl] = cfg["group"]
        evs = {}
        for src in (old.get(lg, {}), past[lg].get("win", {})):     # the live API last: it's the freshest
            for key, e in src.items():
                cur = evs.setdefault(key, {})
                for f, v in e.items():
                    if f == "n":
                        cur.setdefault("n", {}).update(v)
                    else:
                        cur[f] = v
        full = defaultdict(set)              # the archive sometimes has only a code where the live API has a name
        for e in evs.values():
            for c, nm in (e.get("n") or {}).items():
                if nm and nm != c:
                    full[c].add(nm)
        n_all = n_draw = 0
        for key, e in evs.items():
            names = e.get("n") or {}
            codes = [c for c in names if c != "TIE"]
            w = e.get("w")
            if len(codes) != 2 or e.get("void") or not w or not e.get("d"):
                continue
            a, b = order_codes(key, codes)
            sa = 0.5 if w == "TIE" else 1.0 if w == a else 0.0 if w == b else None
            if sa is None:
                continue
            nm = {}
            for c in (a, b):
                x = names.get(c) or c
                if x == c and len(full.get(c, ())) == 1:
                    x = next(iter(full[c]))
                nm[c] = x
            n_all += 1
            n_draw += sa == 0.5
            home = None if g in elo.NEUTRAL else ("b" if g in AWAY_FIRST else "a")
            matches[pl].append({"date": e["d"], "eid": key, "a": rating_id(g, a, nm[a]), "b": rating_id(g, b, nm[b]),
                                "sa": sa, "home": home, "lg": lg})
        if n_all >= 30:
            draw_rate[lg] = n_draw / n_all if n_draw / n_all > 0.02 else 0.0
        else:
            draw_rate[lg] = 0.26 if g == "soccer" else 0.0
    return matches, draw_rate, group_of


def ratings(leagues, pool_of, live_pools, past, old, log):
    """Elo ratings for every pool with games on the board -> ({pool: ratings}, {league: chance of a draw})."""
    t0 = time.time()
    matches, draw_rate, group_of = pool_matches(leagues, pool_of, live_pools, past, old)
    R = {}
    for pl, ms in matches.items():
        R[pl] = elo.rate(ms, group_of[pl])
        R[pl]["label"] = elo.POOL_LABEL.get(pl) or (leagues.get(pl) or {}).get("label") or pl
    big = sorted(R.items(), key=lambda kv: -kv[1]["matches"])
    log(f"sports: ratings for {len(R)} pools, {sum(v['matches'] for v in R.values()):,} matches "
        f"({time.time() - t0:.1f}s): " + ", ".join(
            f"{pl} {v['matches']}/{v['nobs']} from {v['first']} s{v['s']} h{v['h']:.0f} "
            f"skill {0 if v['skill'] is None else v['skill']:.3f}"
            for pl, v in big[:45]))
    return R, draw_rate, matches, group_of


def learn_weights(log, tested=None):
    """How much each sport's edge should lean on the ratings, learned from matches that have settled.

    Every run saves each rated winner market's last price and forecast before the start. Once a match settles,
    that's one test: did moving the price toward the ratings (by the weight used then, times m) predict the result
    better than the price alone? m is fitted per sport by log loss and pulled toward 1 (the default weight) with
    FIT_PRIOR matches' worth of weight, so it takes a few hundred settled matches to move it far. m = 0 would mean
    the ratings add nothing to Kalshi's price; 2 would mean they deserve twice the default."""
    saved = cache.get(CLOSE_KEY) or {}
    memo, obs, seen = {}, defaultdict(list), set()
    for grp, xs in (tested or {}).items():          # the daily backtest's matches (backtest.py)
        for mid, pe, k, y, sk in xs:
            if k and tuple(sk) not in seen:
                seen.add(tuple(sk))
                obs[grp].append((mid, pe, k, y))
    for ticker, (mid, pe, k, date, grp) in sorted(saved.items()):
        parts = ticker.split("-")
        if len(parts) < 3 or not k:
            continue
        series, key, code = parts[0], parts[1], parts[-1]
        if (series, key) in seen:       # a match's two sides mirror each other: count it once
            continue
        seen.add((series, key))
        if series not in memo:
            memo[series] = ((cache.entry(f"kalshi/settled3/{series}")[0] or {}).get("ev") or {})
        e = memo[series].get(key)
        if not e or e.get("void") or not e.get("w"):
            continue
        obs[grp].append((mid, pe, k, 1.0 if e["w"] == code else 0.0))
    out = {}
    for grp, xs in obs.items():
        def loss(m):
            tot = 0.0
            for mid, pe, k, y in xs:
                p = min(max(mid + m * k * (pe - mid), 1e-4), 1 - 1e-4)
                tot -= y * math.log(p) + (1 - y) * math.log(1 - p)
            return tot
        best = min((m / 10 for m in range(0, 31)), key=loss)
        n = len(xs)
        m = (n * best + FIT_PRIOR * 1.0) / (n + FIT_PRIOR)
        out[grp] = {"m": round(min(2.0, max(0.0, m)), 3), "fit": best, "n": n,
                    "gain": round((loss(0.0) - loss(best)) / n, 5) if n else 0.0}
    if out:
        log("sports: rating weights learned from settled matches: " + ", ".join(
            f"{g} m{v['m']} (fit {v['fit']} on {v['n']}, log loss -{v['gain']})" for g, v in sorted(out.items())))
    return out


def save_closing(rows, games, today):
    """Keep each rated winner market's latest pre-start price and forecast, for learn_weights."""
    saved = cache.get(CLOSE_KEY) or {}
    cut = (today - dt.timedelta(days=CLOSE_DAYS)).isoformat()
    saved = {t: v for t, v in saved.items() if v[3] >= cut}
    side = {t.rsplit("-", 1)[0]: t for t in saved}          # one side per match is enough: the other mirrors it
    for r in rows:
        g = games.get(r["gid"]) or {}
        if r.get("el") and r["stat"] == "win" and g.get("state") == "pre" and r.get("kraw") and r["mid"] is not None:
            ev = r["id"].rsplit("-", 1)[0]
            if side.setdefault(ev, r["id"]) != r["id"]:
                continue
            saved[r["id"]] = [r["mid"], r["p"], r["kraw"], g.get("date") or today.isoformat(), r["grp"]]
    cache.put(CLOSE_KEY, saved)
    return len(saved)


# ---------------------------------------------------------------- everything
def build(today, log):
    """Returns {"rows", "games", "players", "files", "leagues"} for every sport outside the NBA, NFL and NHL."""
    t0 = time.time()
    leagues = league_series(log)
    all_series = [(lg, s, kind) for lg, c in leagues.items() for s, kind in c["series"]]
    empty = cache.get("kalshi/open-empty", EMPTY_TTL) or {}
    todo = [s for _, s, _ in all_series if not (s in empty and time.time() - empty[s] < EMPTY_TTL)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        fetched = dict(ex.map(lambda s_: fetch_open(s_, log), todo))
    for s_ in todo:
        if fetched.get(s_):
            empty.pop(s_, None)
        else:
            empty[s_] = time.time()
    cache.put("kalshi/open-empty", empty)
    lo, hi = (today - dt.timedelta(days=1)).isoformat(), (today + dt.timedelta(days=DAYS_AHEAD)).isoformat()
    events = defaultdict(dict)                      # lg -> event key -> {"date", "codes", "names", "markets": []}
    occur = {}
    for lg, s, kind in all_series:
        for mk in fetched.get(s, []):
            if mk.get("status") not in ("active", "open", None):
                continue
            p = parse(kind, mk)
            if not p or not (lo <= p["date"] <= hi):
                continue
            yb, ya = K.price(mk, "yes_bid"), K.price(mk, "yes_ask")
            q = {"yb": yb, "ya": ya, "na": K.price(mk, "no_ask"), "last": K.price(mk, "last_price"), "vol": K.qty(mk, "volume")}
            ev = events[lg].setdefault(p["key"], {"key": p["key"], "date": p["date"], "names": {}, "markets": []})
            if p["k"] == "win":
                ev["names"][p["c"]] = p["name"]
            ev["markets"].append((p, q, mk.get("event_ticker")))
            occur.setdefault(p["key"], mk.get("occurrence_datetime") or mk.get("expected_expiration_time"))
    live_leagues = [lg for lg in leagues if events.get(lg)]
    log(f"sports: open games in {len(live_leagues)} leagues, {sum(len(v) for v in events.values())} games, "
        f"{len(todo)} of {len(all_series)} series checked ({time.time() - t0:.0f}s)")

    # settled history for leagues with games on the board, plus the winners of any league that shares a ratings
    # pool with one (a Challenger player's ITF results count toward his rating)
    pool_of = {lg: elo.pool(lg, c["group"]) for lg, c in leagues.items()}
    live_pools = {pool_of[lg] for lg in live_leagues}
    want = [(lg, s, kind) for lg, s, kind in all_series
            if lg in events or (kind == "win" and pool_of[lg] in live_pools)]
    # never fetched (or oldest) first, and winners before ladders: they're small and give every league its W/L record
    rank = {"win": 0, "btts": 1, "total": 2, "margin": 3, "tpts": 4}
    want.sort(key=lambda x: (cache.entry(f"kalshi/settled3/{x[1]}")[1] > 0, rank.get(x[2], 5),
                             cache.entry(f"kalshi/settled3/{x[1]}")[1]))
    budget = [SETTLED_PAGES]

    def get_settled(item):
        lg, s, kind = item
        try:
            return item, settled(s, kind, budget)
        except Exception as e:  # noqa: BLE001
            log(f"sports: settled {s} failed {e!r}"[:200])
            return item, (cache.entry(f"kalshi/settled3/{s}")[0] or {}).get("ev", {})
    with ThreadPoolExecutor(max_workers=2) as ex:
        past_by = list(ex.map(get_settled, want))
    past = defaultdict(lambda: defaultdict(dict))  # lg -> kind -> event key -> summary
    for (lg, s, kind), evs in past_by:
        for key, e in evs.items():
            cur = past[lg][kind].setdefault(key, {})
            for f, v in e.items():
                if f == "n":
                    cur.setdefault("n", {}).update(v)
                else:
                    cur[f] = v
    log(f"sports: settled history for {len(want)} series, {SETTLED_PAGES - budget[0]} pages fetched "
        f"({time.time() - t0:.0f}s)")

    # older winners from Kalshi's archive, for the ratings only (the hit rates stay on this season's results)
    old_todo = [(lg, s) for lg, s, kind in want if kind == "win"]
    old_todo.sort(key=lambda x: ((cache.entry(f"kalshi/hist-win/{x[1]}")[0] or {}).get("done", False),
                                 leagues[x[0]]["group"] not in ("tennis", "esports"),
                                 cache.entry(f"kalshi/hist-win/{x[1]}")[1]))
    hbudget = [HIST_PAGES]

    def get_old(item):
        lg, s = item
        try:
            return item, settled_old(s, hbudget)
        except Exception as e:  # noqa: BLE001
            log(f"sports: archive {s} failed {e!r}"[:200])
            return item, (cache.entry(f"kalshi/hist-win/{s}")[0] or {}).get("ev", {})
    with ThreadPoolExecutor(max_workers=2) as ex:
        old_by = list(ex.map(get_old, old_todo))
    old = defaultdict(dict)                         # lg -> event key -> winner summary
    for (lg, s), evs in old_by:
        for key, e in evs.items():
            cur = old[lg].setdefault(key, {})
            for f, v in e.items():
                if f == "n":
                    cur.setdefault("n", {}).update(v)
                else:
                    cur[f] = v
    done = sum(1 for lg, s in old_todo if (cache.entry(f"kalshi/hist-win/{s}")[0] or {}).get("done"))
    log(f"sports: archive {done} of {len(old_todo)} winner series complete, {HIST_PAGES - hbudget[0]} pages fetched, "
        f"{sum(len(v) for v in old.values()):,} older games ({time.time() - t0:.0f}s)")
    R, draw_rate, matches, group_of = ratings(leagues, pool_of, live_pools, past, old, log)
    series_of = {}                                  # (league, event key) -> its winner series; + "a": first-listed code
    for (lg, s, kind), evs in past_by:
        if kind == "win":
            for key in evs:
                series_of[(lg, key)] = s
    for (lg, s), evs in old_by:
        for key in evs:
            series_of.setdefault((lg, key), s)
    for lg in leagues:
        for src in ((past.get(lg) or {}).get("win") or {}, old.get(lg) or {}):
            for key, e in src.items():
                codes = [c for c in (e.get("n") or {}) if c != "TIE"]
                if len(codes) == 2:
                    series_of[(lg, key, "a")] = order_codes(key, codes)[0]
    try:
        tested, tests = backtest.run(BASE, matches, group_of, draw_rate, series_of,
                                     {pl: v["skill"] for pl, v in R.items()}, default_weight, log)
    except Exception as e:  # noqa: BLE001
        log(f"sports: backtest failed {e!r}"[:300])
        tested, tests = {}, {}
    weights = learn_weights(log, tested)
    starts = milestones(log)

    now = time.time()
    out = {"rows": [], "games": {}, "players": {}, "files": {}, "leagues": {}, "details": defaultdict(dict)}
    merged = defaultdict(lambda: defaultdict(list))   # tennis: pool -> player -> matches on every tour, newest first
    for lg, cfg in leagues.items():
        if cfg["group"] == "tennis" and pool_of[lg] in live_pools and lg in past:
            for tid, gs in team_history(lg, cfg, past[lg])[0].items():
                merged[pool_of[lg]][tid.split(":", 1)[1]].extend(gs)
    for mp in merged.values():
        for gs in mp.values():
            gs.sort(key=lambda g: (g["date"], g["eid"]), reverse=True)
    for lg in live_leagues:
        cfg = leagues[lg]
        hist, who = team_history(lg, cfg, past[lg])
        Rp = R.get(pool_of[lg])
        tennis = cfg["group"] == "tennis"
        n_rows = 0
        by_code = defaultdict(list)       # a code can belong to two players or teams; names tell them apart
        for tid, (c, name) in who.items():
            by_code[c].append(tid)
        for key, ev in events[lg].items():
            codes = [c for c in ev["names"]]
            if len(codes) != 2:
                continue
            a, b = order_codes(key, codes)
            tids = {}
            for c in (a, b):
                tid = f"{c}:{slug(ev['names'][c])}"
                if tid not in hist and len(by_code.get(c, [])) == 1:
                    tid = by_code[c][0]            # same code, name spelled a bit differently
                tids[c] = tid
            start = None
            for _, _, evt in ev["markets"]:
                start = start or starts.get(evt)
            start = start or starts.get(key)
            est = False
            if not start and occur.get(key):
                t = _ts(occur[key]) - DURATION[cfg["group"]] * 3600
                start = dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")
                est = True
            state = "in" if (start and _ts(start) <= now) else "pre"
            ev2 = {"key": key, "date": ev["date"], "state": state}
            gid = f"{lg}-{key}"
            union = None
            hists = {c: (merged[pool_of[lg]].get(tids[c].split(":", 1)[1]) if tennis else None) or hist.get(tids[c], [])
                     for c in (a, b)}
            rid = {c: rating_id(cfg["group"], c, ev["names"][c]) if tennis else tids[c] for c in (a, b)}
            home_code = None if cfg["group"] in elo.NEUTRAL else (b if cfg["group"] in AWAY_FIRST else a)
            draw_mid = None
            for p_, q_, _ in ev["markets"]:
                if p_["k"] == "draw" and q_["yb"] and q_["ya"] and 0 < q_["yb"] < q_["ya"] < 1 \
                        and q_["ya"] - q_["yb"] <= MAX_SPREAD:
                    draw_mid = (q_["yb"] + q_["ya"]) / 2
            p_draw, draw_src = (draw_mid, "k") if draw_mid is not None else (draw_rate.get(lg) or 0.0, "league")
            ladders = defaultdict(list)
            for p, q, _ in ev["markets"]:
                yb, ya = q["yb"], q["ya"]
                if not (yb and ya and 0 < yb < ya < 1) or ya - yb > MAX_SPREAD:
                    continue
                mid = (yb + ya) / 2
                if p["k"] not in ("win", "draw") and not (MIN_PRICE <= mid <= 1 - MIN_PRICE):
                    continue
                ladders[(p["k"], p["c"])].append((abs(mid - 0.5), p, q))
            keep = [x for lad in ladders.values() for x in sorted(lad, key=lambda t: t[0])[:LADDER]]
            for _, p, q in keep:
                if p["k"] in ("total", "btts", "draw"):
                    entity, pid = "game", f"{lg}-g-{slug(key)}"
                    if union is None:
                        union, seen = [], set()
                        for c in (b, a):
                            for g in hists[c]:
                                if g["eid"] not in seen:
                                    seen.add(g["eid"])
                                    union.append({**g, "team": c, "at": g["home"]})
                        union.sort(key=lambda g: (g["date"], g["eid"]), reverse=True)
                    h, opp, home = union, a, True
                    name = f"{ev['names'][a]} {'@' if cfg['group'] in AWAY_FIRST else 'vs'} {ev['names'][b]}"
                    team = None
                else:
                    c = p["c"]
                    if c not in tids:
                        continue
                    o = b if c == a else a
                    entity, pid = "team", f"{lg}-t-{slug(tids[c])}"
                    h, opp = hists[c], o
                    home = (c == b) if cfg["group"] in AWAY_FIRST else None
                    name, team = ev["names"][c], c
                ctx = {"pid": pid, "entity": entity, "opp": opp, "home": home}
                if p["k"] == "win" and Rp:
                    hs = 0 if home_code is None else (1 if c == home_code else -1)
                    pe = elo.chance(Rp, rid[c], rid[o], hs)
                    if pe is not None:
                        ctx["elo"] = {"R": Rp, "me": rid[c], "opp": rid[o], "p": pe, "hs": hs,
                                      "r": Rp["r"][rid[c]], "r_opp": Rp["r"][rid[o]],
                                      "n": Rp["n"].get(rid[c], 0), "n_opp": Rp["n"].get(rid[o], 0),
                                      "skill": Rp["skill"], "draw": p_draw or 0.0, "draw_src": draw_src,
                                      "m": (weights.get(cfg["group"]) or {}).get("m", 1.0),
                                      "m_n": (weights.get(cfg["group"]) or {}).get("n", 0),
                                      "name": ev["names"][c], "name_opp": ev["names"][o], "label": Rp["label"]}
                row, det = evaluate(lg, cfg, p, q, ev2, h, ctx)
                out["rows"].append(row)
                out["details"][pid][row["id"]] = det
                n_rows += 1
                if gid not in out["games"]:
                    out["games"][gid] = {"start": start, "est": est, "date": ev["date"], "state": state, "detail": None,
                                         "away": a, "home": b, "away_name": ev["names"][a], "home_name": ev["names"][b],
                                         "total": None, "line": None, "lg": lg, "grp": cfg["group"],
                                         "sep": "@" if cfg["group"] in AWAY_FIRST else "vs"}
                if pid not in out["files"]:
                    info = {"name": name, "team": team, "pos": "", "lg": lg, "inj": None, "kind": entity}
                    out["players"][pid] = info
                    keep = ("eid", "date", "opp", "oppn", "home", "res", "score", "season", "s", "team", "at")
                    out["files"][pid] = {"pid": pid, **info, "src": "k",
                                         "games": [{f: x[f] for f in keep if x.get(f) is not None} for x in h[:60]]}
        if n_rows:
            out["leagues"][lg] = {"label": cfg["label"], "group": cfg["group"], "unit": cfg["unit"], "rows": n_rows}
    try:
        kprops.build(today, leagues, out, starts, sys.modules[__name__], log)
    except Exception as e:  # noqa: BLE001
        log(f"props: failed {e!r}"[:300])
    for pid, blob in out["files"].items():
        blob["props"] = out["details"].get(pid, {})
    try:
        n_saved = save_closing(out["rows"], out["games"], today)
        log(f"sports: {n_saved} rated markets saved for learning the weights")
    except Exception as e:  # noqa: BLE001
        log(f"sports: saving closing prices failed {e!r}"[:200])
    out["weights"] = weights
    out["tests"] = {g: {**v, "m": (weights.get(g) or {}).get("m", 1.0)} for g, v in tests.items()}
    log(f"sports: {len(out['rows'])} rows, {len(out['games'])} games, {len(out['leagues'])} leagues "
        f"in {time.time() - t0:.0f}s")
    return out
