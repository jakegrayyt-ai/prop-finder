"""Props for every sport outside the NBA, NFL and NHL that Kalshi lists them for.

- Player props in Kalshi's standard format ("Bukayo Saka: 1+"): soccer goals and assists (EPL, La Liga, Serie A,
  Bundesliga, Ligue 1, MLS, Liga MX, the Champions League...), MLB hits, home runs, RBIs, strikeouts and total
  bases, WNBA points, rebounds, assists and threes, and any new series Kalshi adds in the same format. Kalshi opens
  soccer props on match days; MLB and WNBA ones in season.
- Team props ("Notre Dame: 325+"): college football passing and rushing yards and touchdowns, total touchdowns,
  field goals, sacks, interceptions and the rest.
- Game props ("8+ touchdowns"): college football total touchdowns and field goals.

Kalshi lists no individual player props for college football or college basketball, so those sports get team props.

History comes from the same series' settled markets: each settled line says whether the player (or team) got there,
and Kalshi's settlement value often gives the exact number. The model is the same trend estimate the other sports'
spreads and totals use: the recent hit rate on that line, pulled hard toward Kalshi's price.
"""
import datetime as dt
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import cache, kalshi as K, model, stats

PLAYER = {"GOAL": ("goals", "Goals"), "AST": ("assists", "Assists"), "HIT": ("hits", "Hits"),
          "HRR": ("hrr", "Hits + runs + RBIs"), "HR": ("hr", "Home runs"), "RBI": ("rbi", "RBIs"),
          "KS": ("ks", "Strikeouts"), "TB": ("tb", "Total bases"), "HA": ("ha", "Hits allowed"),
          "SB": ("sb", "Stolen bases"), "PTS": ("pts", "Points"), "REB": ("reb", "Rebounds"), "3PT": ("3pm", "Threes")}
TEAM = {"TEAMRECYDS": ("passyds", "Passing yards"), "TEAMRECTD": ("passtd", "Passing TDs"),
        "TEAMRSHYDS": ("rushyds", "Rushing yards"), "TEAMRSHTD": ("rushtd", "Rushing TDs"),
        "TEAMRSHATT": ("rushatt", "Rush attempts"), "TEAMTD": ("tds", "Touchdowns"), "TEAMYDS": ("yds", "Total yards"),
        "TEAMFG": ("fg", "Field goals"), "TEAMSACK": ("sacks", "Sacks"), "TEAMINT": ("ints", "Interceptions"),
        "TEAMREC": ("rec", "Receptions"), "TEAMTO": ("takeaways", "Takeaways")}
GAME = {"TOTALTD": ("gtds", "Total touchdowns"), "TOTALFG": ("gfg", "Total field goals")}
KIND = {**{k: ("player",) + v for k, v in PLAYER.items()}, **{k: ("team",) + v for k, v in TEAM.items()},
        **{k: ("game",) + v for k, v in GAME.items()}}
SERIES_RE = re.compile(r"^(KX[A-Z0-9]+?)(" + "|".join(sorted(KIND, key=len, reverse=True)) + r")$")
CORE = ("KXNBA", "KXNFL", "KXNHL")
EMPTY_TTL = 40 * 60          # soccer props open on match days, so an empty series is checked again soon
SETTLED_TTL = 90 * 60
SETTLED_PAGES = 80           # per run; a new series' history fills in over a few runs
MIN_PRICE, MAX_SPREAD, LADDER = 0.06, 0.30, 7
PRIOR, HALF_LIFE = 10.0, 10.0
VAL_RE = re.compile(r"(\d+(?:\.\d+)?)")
HOMEAWAY_RE = re.compile(r"Home:\s*(at least\s*)?(\d+(?:\.\d+)?)\s*,\s*Away:\s*(at least\s*)?(\d+(?:\.\d+)?)", re.I)


def series_list(leagues):
    """Every prop series outside the core leagues: [(ticker, league key, kind, stat, label, tag)]. Only leagues the
    site already has game markets for, which also drops look-alikes ("first to make a three", season home runs)."""
    raw = cache.get("kalshi/series-sports") or []
    out = []
    for s in raw:
        t = s.get("ticker") or ""
        m = SERIES_RE.match(t)
        if not m or t.startswith(CORE) or m.group(1)[2:].lower() not in leagues:
            continue
        kind, stat, label = KIND[m.group(2)]
        out.append((t, m.group(1)[2:].lower(), kind, stat, label, (s.get("tags") or [""])[0]))
    return out


def split_codes(blob, token):
    """'SEVALA' + player token 'ALAAMANAS20' -> ('SEV', 'ALA', 'ALA'): the two team codes and the player's."""
    best = None
    for i in range(2, len(blob) - 1):
        a, b = blob[:i], blob[i:]
        for mine in (a, b):
            if token.startswith(mine):
                score = (-abs(len(a) - len(b)), len(mine))
                if best is None or score > best[0]:
                    best = (score, (a, b, mine))
    return best[1] if best else None


def parse(kind, mk, SP, games, lg):
    """One market -> {"key", "date", "subj", "name", "team", "codes", "line"} or None."""
    ev, t = mk.get("event_ticker") or "", mk.get("ticker") or ""
    if not ev or "-" not in ev or not t.startswith(ev + "-"):
        return None
    key = ev.split("-", 1)[1]
    m = SP.EVENT_RE.match(key)
    date = SP.event_date(ev)
    if not m or not date:
        return None
    blob, rest = m.group(5), t[len(ev) + 1:]
    sub = (mk.get("yes_sub_title") or "").strip()
    fs = mk.get("floor_strike")
    G = games.get(f"{lg}-{key}")
    codes = (G["away"], G["home"]) if G and G.get("away") and G.get("home") else None
    if kind == "player":
        if "-" not in rest or ":" not in sub:
            return None
        token, ln = rest.rsplit("-", 1)
        if not ln.isdigit():
            return None
        if codes:
            team = next((c for c in sorted(codes, key=len, reverse=True) if token.startswith(c)), None)
        else:
            sc = split_codes(blob, token)
            codes, team = (sc[:2], sc[2]) if sc else (None, None)
        if not team:
            return None
        subj, name, line = token, sub.split(":")[0].strip(), int(ln)
    elif kind == "team":
        if ":" not in sub:
            return None
        cands = []                                   # "ND325": the team code, then the line
        for a, b in ([codes] if codes else [(blob[:i], blob[i:]) for i in range(2, len(blob) - 1)]):
            for c in (a, b):
                if rest.startswith(c) and rest[len(c):].isdigit():
                    cands.append(((-abs(len(a) - len(b)), len(c)), (a, b), c))
        if not cands:
            return None
        _, codes, team = max(cands)
        subj, name, line = team, sub.split(":")[0].strip(), int(rest[len(team):])
    else:
        if not rest.isdigit():
            return None
        line, subj, name, team = int(rest), "G", None, None
        if not codes:
            return None
    if fs is not None:
        try:
            line = int(round(float(fs) + 0.5))
        except (TypeError, ValueError):
            pass
    return {"key": key, "date": date.isoformat(), "subj": subj, "name": name, "team": team, "codes": tuple(codes),
            "line": line}


def settled(series, kind, SP, lg, budget):
    """{event key: {"d": date, "codes": [a, b], "x": {subject: {"lo", "hi", "n", "team"}}}} from settled markets.
    lo is the most the subject is known to have reached, hi (exclusive) the line it's known to have missed."""
    key_ = f"kalshi/props-settled/{series}"
    data, saved = cache.entry(key_)
    if data and time.time() - saved < SETTLED_TTL:
        return data["ev"]
    data = data or {"since": 0, "ev": {}}
    newest, cursor = data["since"], None
    while budget[0] > 0:
        params = {"series_ticker": series, "status": "settled", "limit": 1000}
        if data["since"]:
            params["min_close_ts"] = int(data["since"]) - 3600
        if cursor:
            params["cursor"] = cursor
        budget[0] -= 1
        d = SP.get_json(SP.BASE + "/markets", params=params)
        mks = d.get("markets") or []
        for mk in mks:
            p = parse(kind, mk, SP, {}, lg)
            res = mk.get("result")
            if not p or res not in ("yes", "no"):
                continue
            newest = max(newest, SP._ts(mk.get("close_time")))
            e = data["ev"].setdefault(p["key"], {"d": p["date"], "codes": list(p["codes"]), "x": {}})
            x = e["x"].setdefault(p["subj"], {"lo": None, "hi": None, "n": p["name"], "team": p["team"]})
            L = p["line"]
            if res == "yes":
                x["lo"] = max(x["lo"] or 0, L)
            else:
                x["hi"] = L if x["hi"] is None else min(x["hi"], L)
                x["lo"] = x["lo"] or 0
            val = str(mk.get("expiration_value") or "")
            exact = None
            if kind == "team":
                ha = HOMEAWAY_RE.search(val)
                if ha:
                    a, b = p["codes"]
                    home = b if lg_away_first(lg) else None       # US college tickers list the away team first
                    if home:
                        sel = (ha.group(1), ha.group(2)) if p["team"] == home else (ha.group(3), ha.group(4))
                        if sel[0]:
                            x["lo"] = max(x["lo"] or 0, int(float(sel[1])))
                        else:
                            exact = int(float(sel[1]))
            elif re.fullmatch(r"\s*(at least\s*)?\d+(\.\d+)?\s*", val, re.I) or (kind == "player" and ":" in val):
                mv = VAL_RE.search(val.split(":")[-1])
                if mv:
                    if "at least" in val.lower():
                        x["lo"] = max(x["lo"] or 0, int(float(mv.group(1))))
                    else:
                        exact = int(float(mv.group(1)))
            if exact is not None and (x["hi"] is None or exact < x["hi"]) and exact >= (x["lo"] or 0):
                x["lo"], x["hi"] = exact, exact + 1
        cursor = d.get("cursor")
        if not cursor or len(mks) < 1000:
            break
        time.sleep(0.05)
    data["since"] = newest
    cache.put(key_, data)
    return data["ev"]


def lg_away_first(lg):
    return lg.startswith(("ncaaf", "ncaamb", "ncaawb"))


def history(evs, subj, kind, stat):
    """Newest first: [{"eid", "date", "opp", "home", "season", "s": {stat: value}}] for one player or team."""
    out = []
    for key, e in evs.items():
        x = e["x"].get(subj)
        if not x or x["lo"] is None or (x["hi"] is not None and x["hi"] <= x["lo"]):
            continue
        a, b = e["codes"]
        team = x.get("team")
        opp = (b if team == a else a) if team else None
        out.append({"eid": key, "date": e["d"], "opp": opp, "oppn": opp, "home": None, "season": "cur", "team": team,
                    "s": {stat: x["lo"]}})
    out.sort(key=lambda g: (g["date"], g["eid"]), reverse=True)
    return out


def evaluate(row_base, q, played, line, live, stat):
    yb, ya = q["yb"], q["ya"]
    na = q["na"] if q.get("na") and 0 < q["na"] < 1 else ((1 - yb) if yb and yb > 0 else None)
    mid = (yb + ya) / 2
    liquid = (ya - yb) <= 0.06
    vals = [g["s"][stat] for g in played]
    w = [0.5 ** (i / HALF_LIFE) for i in range(len(vals))]
    hw, ww = sum(wi for wi, v in zip(w, vals) if v >= line), sum(w)
    p_model = model.clamp((hw + PRIOR * mid) / (ww + PRIOR), 0.01, 0.99)
    n = len(vals)
    flags = ["Live"] if live else []
    if not liquid:
        flags.append("Wide spread")
    if not q.get("vol"):
        flags.append("No trades yet")
    if n < 5:
        flags.append("Small sample")
    conf = "low" if (n < 5 or not liquid or live) else "med"
    tail = min(1.0, mid * (1 - mid) / 0.16)
    k = p_blend = None
    if not live:
        k = (0.10 if liquid else 0.15) * {"low": 0.5, "med": 1.0}[conf] * tail
        p_blend = model.clamp(mid + k * (p_model - mid), 0.005, 0.995)
    e = model.edges(p_blend, ya, na)
    best = max(e, key=e.get) if e else None
    summ = stats.summarize(played, stat, line, row_base["opp"])
    r3 = lambda x, d=3: None if x is None else round(x, d)  # noqa: E731
    row = {**row_base, "line": line,
           "k": {"yb": r3(yb, 2), "ya": r3(ya, 2), "last": r3(q.get("last"), 2), "vol": round(q["vol"]) if q.get("vol") else 0},
           "mid": r3(mid), "h": {wn: [v["hit"], v["n"]] for wn, v in summ.items()
                                 if isinstance(v, dict) and wn in ("l5", "l10", "l20", "szn", "h2h")},
           "strk": summ["streak"], "last10": vals[:10], "p": r3(p_model), "pb": r3(p_blend),
           "e": {s: r3(v, 4) for s, v in e.items()}, "best": best, "be": r3(e.get(best), 4) if best else None,
           "conf": conf, "flags": flags}
    if summ.get("avg_l10") is not None:
        row["avg10"] = summ["avg_l10"]
        row["diff"] = round(summ["avg_l10"] - (line - 0.5), 2)
    rate = (hw / ww) if ww else None
    det = {"k": r3(k), "steps": [
        ["Kalshi’s price", f"{mid * 100:.0f}%", "What traders think right now"],
        ["Hit rate, recent games counted more", "—" if rate is None else f"{rate * 100:.0f}%",
         f"{n} game{'s' if n != 1 else ''} on this line or a known number, from Kalshi’s settled markets (they start in late summer)"],
        ["Trend estimate", f"{p_model * 100:.0f}%",
         f"The hit rate pulled toward the price with {PRIOR:.0f} games’ worth of weight, since a couple of months of results says little on its own"]]}
    return row, det


def build(today, leagues, out, starts, SP, log):
    """Adds the prop rows, games, players and files to sports.build's output."""
    t0 = time.time()
    plist = series_list(leagues)
    empty = cache.get("kalshi/props-open-empty") or {}
    todo = [s for s, *_ in plist if not (s in empty and time.time() - empty[s] < EMPTY_TTL)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        fetched = dict(ex.map(lambda s_: SP.fetch_open(s_, log), todo))
    for s_ in todo:
        if fetched.get(s_):
            empty.pop(s_, None)
        else:
            empty[s_] = time.time()
    cache.put("kalshi/props-open-empty", empty)
    lo, hi = (today - dt.timedelta(days=1)).isoformat(), (today + dt.timedelta(days=SP.DAYS_AHEAD)).isoformat()
    opened = defaultdict(list)                       # series -> [(parsed, quote, event ticker, market)]
    for s, lg, kind, stat, label, tag in plist:
        for mk in fetched.get(s, []):
            if mk.get("status") not in ("active", "open", None):
                continue
            p = parse(kind, mk, SP, out["games"], lg)
            if not p or not (lo <= p["date"] <= hi):
                continue
            q = {"yb": K.price(mk, "yes_bid"), "ya": K.price(mk, "yes_ask"), "na": K.price(mk, "no_ask"),
                 "last": K.price(mk, "last_price"), "vol": K.qty(mk, "volume")}
            opened[s].append((p, q, mk.get("event_ticker"), mk))
    live = [x for x in plist if opened.get(x[0])]
    budget = [SETTLED_PAGES]

    def get_hist(x):
        s, lg, kind = x[0], x[1], x[2]
        try:
            return s, settled(s, kind, SP, lg, budget)
        except Exception as e:  # noqa: BLE001
            log(f"props: {s} history failed {e!r}"[:200])
            return s, (cache.entry(f"kalshi/props-settled/{s}")[0] or {}).get("ev", {})
    with ThreadPoolExecutor(max_workers=2) as ex:
        past = dict(ex.map(get_hist, live))
    now = time.time()
    n_rows = defaultdict(int)
    for s, lg, kind, stat, label, tag in live:
        cfg = leagues.get(lg) or {}
        grp = cfg.get("group") or SP.STEM_GROUP.get("KX" + lg.upper()) or SP.TAG_GROUP.get(tag) or "other"
        lab = cfg.get("label") or lg.upper()
        evs = past.get(s) or {}
        ladders = defaultdict(list)
        for p, q, evt, mk in opened[s]:
            yb, ya = q["yb"], q["ya"]
            if not (yb and ya and 0 < yb < ya < 1) or ya - yb > MAX_SPREAD:
                continue
            mid = (yb + ya) / 2
            if not (MIN_PRICE <= mid <= 1 - MIN_PRICE):
                continue
            ladders[(p["key"], p["subj"])].append((abs(mid - 0.5), p, q, evt, mk))
        for (key, subj), lad in ladders.items():
            hist = history(evs, subj, kind, stat)
            for _, p, q, evt, mk in sorted(lad, key=lambda t: t[0])[:LADDER]:
                gid = f"{lg}-{key}"
                a, b = p["codes"]
                G = out["games"].get(gid)
                if not G:
                    start = starts.get(evt) or starts.get(key)
                    est = False
                    occ = mk.get("occurrence_datetime") or mk.get("expected_expiration_time")
                    if not start and occ:
                        start = dt.datetime.fromtimestamp(SP._ts(occ) - SP.DURATION.get(grp, 2.5) * 3600, dt.timezone.utc) \
                            .isoformat(timespec="minutes").replace("+00:00", "Z")
                        est = True
                    state = "in" if (start and SP._ts(start) <= now) else "pre"
                    G = out["games"][gid] = {"start": start, "est": est, "date": p["date"], "state": state, "detail": None,
                                             "away": a, "home": b, "away_name": a, "home_name": b, "total": None,
                                             "line": None, "lg": lg, "grp": grp,
                                             "sep": "@" if grp in SP.AWAY_FIRST else "vs"}
                names = {G["away"]: G.get("away_name") or G["away"], G["home"]: G.get("home_name") or G["home"]}
                played = [g for g in hist if g["date"] < p["date"]]
                if kind == "player":
                    pid = f"{lg}-p-{SP.slug(subj)}"
                    opp = b if p["team"] == a else a
                    name, team_name = p["name"], names.get(p["team"], p["team"])
                elif kind == "team":
                    pid = f"{lg}-tp-{SP.slug(subj)}"
                    opp = b if p["team"] == a else a
                    name, team_name = p["name"], None
                else:
                    pid = f"{lg}-gp-{SP.slug(key)}"
                    opp = b
                    name, team_name = f"{names[a]} {G.get('sep', 'vs')} {names[b]}", None
                home = None
                if grp in SP.AWAY_FIRST and kind != "game":
                    home = (p["team"] == b)
                base = {"id": mk["ticker"], "lg": lg, "grp": grp, "src": "k", "u": label.lower(), "sl": label,
                        "pid": pid, "gid": gid, "kind": kind, "stat": stat, "opp": opp, "home": home}
                row, det = evaluate(base, q, played, p["line"], G.get("state") == "in", stat)
                out["rows"].append(row)
                out["details"][pid][row["id"]] = det
                n_rows[lg] += 1
                if pid not in out["files"]:
                    info = {"name": name, "team": team_name, "pos": "", "lg": lg, "inj": None, "kind": kind}
                    out["players"][pid] = info
                    keep = ("eid", "date", "opp", "oppn", "home", "res", "season", "s", "team")
                    out["files"][pid] = {"pid": pid, **info, "src": "k",
                                         "games": [{f: g[f] for f in keep if g.get(f) not in (None, "")} for g in hist[:60]]}
        out["leagues"].setdefault(lg, {"label": lab, "group": grp, "unit": SP.UNIT.get(grp, "points"), "rows": 0})
    for lg, n in n_rows.items():
        out["leagues"][lg]["rows"] = out["leagues"][lg].get("rows", 0) + n
    for lg in [lg for lg, v in out["leagues"].items() if not v.get("rows")]:
        del out["leagues"][lg]
    log(f"props: {sum(n_rows.values())} rows from {len(live)} of {len(plist)} prop series with open markets "
        f"({', '.join(f'{lg} {n}' for lg, n in sorted(n_rows.items(), key=lambda kv: -kv[1]))}), "
        f"{SETTLED_PAGES - budget[0]} history pages ({time.time() - t0:.0f}s)")
