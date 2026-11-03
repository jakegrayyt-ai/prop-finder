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
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import arb, cache, model, stats
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


# ---------------------------------------------------------------- which series
def league_series(log):
    """{league key: {"label", "group", "unit", "series": [(ticker, kind)]}} for every per-game sports series."""
    def fetch():
        d = get_json(BASE + "/series", params={"category": "Sports"})
        return [{"ticker": s.get("ticker"), "title": s.get("title") or "", "tags": s.get("tags") or []}
                for s in d.get("series") or [] if (s.get("category") or "Sports") == "Sports"]
    series = cache.cached("kalshi/series-sports", 6 * 3600, fetch)
    arb_label = {s: c["label"] for c in arb.LEAGUES.values() for s in c["game"]}
    out = {}
    for s in series:
        t = s["ticker"] or ""
        m = SERIES_RE.match(t)
        stem, kind = (m.group(1), SUFFIX[m.group(2)]) if m else ((t, "win") if t == "KXBOXING" else (None, None))
        if not stem or stem.startswith(CORE) or SKIP_STEM.search(stem):
            continue
        tag = (s["tags"] or [""])[0]
        group = STEM_GROUP.get(stem) or TAG_GROUP.get(tag) or "other"
        lg = out.setdefault(stem[2:].lower(), {"label": None, "group": group, "unit": UNIT[group], "series": []})
        lg["series"].append((t, kind))
        if kind == "win":
            title = re.sub(r"\s+(Games?|Match(es)?|Fights?|Winner)$", "", s["title"]).strip()
            lg["label"] = lg["label"] or title or arb_label.get(t)
    for key, lg in out.items():
        lg["label"] = lg["label"] or key.upper()
    log(f"sports: {len(out)} leagues, {sum(len(v['series']) for v in out.values())} series")
    return out


# ---------------------------------------------------------------- markets
def parse(kind, mk):
    """One Kalshi market -> what it pays on. line: the whole number that wins (over 2.5 -> 3)."""
    ev = mk.get("event_ticker") or ""
    key = ev.split("-", 1)[1] if "-" in ev else ""
    date = arb.k_event_date(ev)
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
                if p["k"] == "win":
                    e.setdefault("n", {})[p["c"]] = p["name"]
                if res == "yes":
                    e["w"] = p["c"] or "TIE"
                elif res not in ("yes", "no"):
                    e["void"] = 1          # cancelled, postponed or settled at a fair price
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
    m = arb.EVENT_RE.match(key)
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
    flags = ["Live"] if live else []
    if not liquid:
        flags.append("Wide spread")
    if not q.get("vol"):
        flags.append("No trades yet")
    if n < 5:
        flags.append("Small sample")
    conf = "low" if (n < 5 or not liquid or live) else "med"
    gap = p_model - mid
    p_blend, k = None, None
    if not live:
        # a raw hit rate doesn't know who the games were against, so it barely moves the price
        k = (0.10 if liquid else 0.15) * {"low": 0.5, "med": 1.0}[conf] * min(1.0, mid * (1 - mid) / 0.16)
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
    rate = (hw / w) if w else None
    det = {"k": r2(k), "steps": [
        ["Kalshi’s price", f"{mid * 100:.0f}%", "What traders think right now"],
        ["Hit rate, recent games counted more", "—" if rate is None else f"{rate * 100:.0f}%",
         f"{n} game{'s' if n != 1 else ''} with a known result since Kalshi’s history starts (late summer)"],
        ["Trend estimate", f"{p_model * 100:.0f}%",
         f"The hit rate pulled toward the price with {PRIOR:.0f} games’ worth of weight, since a couple of months of results says little on its own"]]}
    return row, det


# ---------------------------------------------------------------- everything
def build(today, log):
    """Returns {"rows", "games", "players", "files", "leagues"} for every sport outside the NBA, NFL and NHL."""
    t0 = time.time()
    leagues = league_series(log)
    all_series = [(lg, s, kind) for lg, c in leagues.items() for s, kind in c["series"]]
    empty = cache.get("kalshi/open-empty", EMPTY_TTL) or {}
    todo = [s for _, s, _ in all_series if not (s in empty and time.time() - empty[s] < EMPTY_TTL)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        fetched = dict(ex.map(arb.k_fetch, todo))
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

    # settled history only for leagues with games on the board
    want = [(lg, s, kind) for lg, s, kind in all_series if lg in events]
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
    starts = milestones(log)

    now = time.time()
    out = {"rows": [], "games": {}, "players": {}, "files": {}, "leagues": {}, "details": defaultdict(dict)}
    for lg in live_leagues:
        cfg = leagues[lg]
        hist, who = team_history(lg, cfg, past[lg])
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
                            for g in hist.get(tids[c], []):
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
                    h, opp = hist.get(tids[c], []), o
                    home = (c == b) if cfg["group"] in AWAY_FIRST else None
                    name, team = ev["names"][c], c
                ctx = {"pid": pid, "entity": entity, "opp": opp, "home": home}
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
    for pid, blob in out["files"].items():
        blob["props"] = out["details"].get(pid, {})
    log(f"sports: {len(out['rows'])} rows, {len(out['games'])} games, {len(out['leagues'])} leagues "
        f"in {time.time() - t0:.0f}s")
    return out
