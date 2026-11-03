"""Cross-site arbitrage scanner: Kalshi vs Polymarket US game markets.

For every game listed on both sites (moneyline, spread, total), it prices both
"opposite" pairs, e.g. Team A on Kalshi + Team B on Polymarket US. If the two
costs plus both taker fees are under $1 per contract, one side pays $1 whatever
happens: an arbitrage. Everything is read-only.

Run: python -m pipeline.arb   ->  site/data/arb.json
"""
import datetime as dt
import json
import math
import os
import re
import time
import traceback
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from . import kalshi as K
from .net import get_json

ET = ZoneInfo("America/New_York")
PM = "https://gateway.polymarket.us"
OUT = os.environ.get("PROP_OUT", "site/data")
KALSHI_TAKER = 0.07
WATCH_MAX = 1.02          # list pairs costing up to $1.02 per $1 payout as "close"
CONTRACTS = 100           # fee math for a 100-contract order (fees round up per order)

LEAGUES = {
    "nfl": {"label": "NFL", "game": ["KXNFLGAME"], "spread": ["KXNFLSPREAD"], "total": ["KXNFLTOTAL"], "pm": ["nfl"]},
    "nba": {"label": "NBA", "game": ["KXNBAGAME"], "spread": ["KXNBASPREAD"], "total": ["KXNBATOTAL"], "pm": ["nba"]},
    "nhl": {"label": "NHL", "game": ["KXNHLGAME"], "spread": ["KXNHLSPREAD"], "total": ["KXNHLTOTAL"], "pm": ["nhl"]},
    "cfb": {"label": "College football", "game": ["KXNCAAFGAME"], "spread": ["KXNCAAFSPREAD"], "total": ["KXNCAAFTOTAL"], "pm": ["cfb"]},
    "cbb": {"label": "College basketball", "game": ["KXNCAAMBGAME"], "spread": ["KXNCAAMBSPREAD"], "total": ["KXNCAAMBTOTAL"], "pm": ["cbb"]},
    "atp": {"label": "ATP tennis", "game": ["KXATPMATCH", "KXATPCHALLENGERMATCH"], "spread": [], "total": [], "pm": ["atp", "atpcq", "atpc"]},
    "wta": {"label": "WTA tennis", "game": ["KXWTAMATCH"], "spread": [], "total": [], "pm": ["wta"]},
}
PM_PREFIX = {p: lg for lg, c in LEAGUES.items() for p in c["pm"]}
RULE_NOTES = {
    "nfl": "NFL games can end in a tie. If that happens, both team-win contracts can lose, so moneyline pairs aren't risk-free.",
    "atp": "If a player retires mid-match, the two sites may settle differently. Read both sites' rules first.",
    "wta": "If a player retires mid-match, the two sites may settle differently. Read both sites' rules first.",
}

_log = []


def log(msg):
    msg = str(msg)
    print(msg, flush=True)
    _log.append(msg)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def quote_val(q):
    if isinstance(q, dict):
        return f(q.get("value"))
    return f(q)


# ---------------------------------------------------------------- names
SUFFIX = {"jr", "sr", "ii", "iii", "iv"}


def tokens(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\([^)]*\)", " ", s)          # "Miami (FL)" -> "miami"
    s = s.replace("&", " and ").replace("st.", "state ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return [t for t in s.split() if t not in SUFFIX]


def paren_tag(s):
    m = re.search(r"\(([^)]*)\)", s or "")
    return tokens(m.group(1).replace("(", "").replace(")", "")) if m else []


def name_match(kname, school, mascot=""):
    """Kalshi names a school/city ('Western Kentucky', 'Los Angeles C', 'Miami (FL)').
    It must equal Polymarket's school/city exactly - 'Kentucky' never matches 'Western Kentucky'.
    A trailing single letter is Kalshi's way of telling two teams from one city apart
    ('Los Angeles C' = Clippers), so it must match the first letter of the mascot."""
    kt, st = tokens(kname), tokens(school)
    if not kt or not st:
        return False
    ktag, stag = paren_tag(kname), paren_tag(school)
    if ktag and stag and ktag != stag:
        return False                       # Miami (FL) vs Miami (OH)
    if kt == st:
        return True
    if len(kt) == len(st) + 1 and kt[:-1] == st and len(kt[-1]) == 1:
        mt = tokens(mascot)
        return bool(mt) and mt[0].startswith(kt[-1])
    return False


def same_team(k_team, p_team):
    code = (k_team.get("code") or "").lower()
    if code and len(code) >= 3 and code in {(p_team.get("abbr") or "").lower(), (p_team.get("disp") or "").lower()}:
        return True
    return any(name_match(k_team.get("name") or "", school, p_team.get("mascot") or "")
               for school in p_team.get("schools") or [])


# ---------------------------------------------------------------- kalshi
def k_quote(mk, series):
    return {
        "ticker": mk.get("ticker"), "event": mk.get("event_ticker"), "series": series,
        "yb": K.price(mk, "yes_bid"), "ya": K.price(mk, "yes_ask"),
        "yb_n": K.qty(mk, "yes_bid_size"), "ya_n": K.qty(mk, "yes_ask_size"),
        "title": mk.get("title"), "vol": K.qty(mk, "volume"),
    }


def kalshi_games():
    base = K.BASES[0]
    games = {}

    def fetch(series):
        try:
            return series, K.fetch_series(base, series)
        except Exception as e:  # noqa: BLE001
            log(f"kalshi {series} failed: {e!r}"[:200])
            return series, []

    all_series = [(lg, kind, s) for lg, c in LEAGUES.items() for kind in ("game", "spread", "total") for s in c[kind]]
    with ThreadPoolExecutor(max_workers=4) as ex:
        fetched = dict(ex.map(fetch, [s for _, _, s in all_series]))
    for lg, kind, s in all_series:
        for mk in fetched.get(s, []):
            if mk.get("status") not in ("active", "open", None):
                continue
            ev = mk.get("event_ticker") or ""
            key = ev.split("-", 1)[1] if "-" in ev else ev
            date, _ = K.parse_event(ev)
            if not date:
                continue
            g = games.setdefault((lg, key), {"league": lg, "key": key, "date": date.isoformat(), "teams": {},
                                             "ml": {}, "spread": [], "total": [], "events": {}})
            g["events"][kind] = ev
            suffix = (mk.get("ticker") or "").rsplit("-", 1)[-1]
            q = k_quote(mk, s)
            if kind == "game":
                g["teams"].setdefault(suffix, mk.get("yes_sub_title") or mk.get("title") or suffix)
                g["ml"][suffix] = q
            elif kind == "spread":
                code = re.sub(r"\d+$", "", suffix)
                x = f(mk.get("floor_strike"))
                m = re.match(r"(.+?) wins by over", mk.get("title") or "")
                if m:
                    g["teams"].setdefault(code, m.group(1).strip())
                if x is not None:
                    g["spread"].append((code, x, q))
            elif kind == "total":
                t = f(mk.get("floor_strike"))
                if t is not None:
                    g["total"].append((t, q))
    today = dt.datetime.now(ET).date()
    out = [g for g in games.values() if len(g["teams"]) == 2
           and today - dt.timedelta(days=1) <= dt.date.fromisoformat(g["date"]) <= today + dt.timedelta(days=6)]
    log(f"kalshi: {len(out)} games " + json.dumps({lg: sum(1 for g in out if g['league'] == lg) for lg in LEAGUES}))
    return out


# ---------------------------------------------------------------- polymarket us
def pm_team(t, mascot_hint=None):
    """Polymarket team -> its school/city part ('Western Kentucky Hilltoppers' -> 'Western Kentucky')."""
    t = t or {}
    name = t.get("name") or t.get("alias") or t.get("safeName") or ""
    nt = tokens(name)
    mascot, schools = "", []
    for cand in (mascot_hint, t.get("alias"), t.get("safeName")):
        ct = tokens(cand)
        variants = [ct]
        # "SJ Sharks" / "PHI Eagles" carry a leading abbreviation: the mascot is what follows it
        first = (cand or "").split()[0] if (cand or "").split() else ""
        if len(ct) > 1 and first.isupper() and 2 <= len(first) <= 4:
            variants.append(ct[1:])
        for mt in variants:
            if mt and len(mt) < len(nt) and nt[-len(mt):] == mt:
                mascot = " ".join(mt)
                tag = paren_tag(name)  # keep "(OH)" so Miami (FL) can't match Miami (OH)
                schools.append(" ".join(nt[: -len(mt)]) + (f" ({' '.join(tag)})" if tag else ""))
                break
        if schools:
            break
    if not schools:
        schools.append(name)  # tennis players, or no mascot found
    return {"abbr": t.get("abbreviation"), "disp": t.get("displayAbbreviation"), "name": name,
            "mascot": mascot, "schools": schools, "names": [x for x in (name, t.get("alias"), t.get("safeName")) if x]}


def pm_line(m):
    v = f(m.get("line"))
    if v is not None:
        return v
    mm = re.search(r"-(neg|pos)?-?(\d+)pt(\d+)$", m.get("slug") or "")
    if mm:
        v = float(f"{mm.group(2)}.{mm.group(3)}")
        return -v if mm.group(1) == "neg" else v
    return None


def pm_info(m):
    """Normalize one Polymarket US market (moneyline / full-game spread / full-game total)."""
    if m.get("closed") or m.get("status") not in (None, "MARKET_STATUS_OPEN"):
        return None
    sides = m.get("marketSides") or []
    if len(sides) != 2:
        return None
    long_side = next((x for x in sides if x.get("long")), sides[0])
    short_side = next((x for x in sides if x is not long_side), sides[1])
    info = {"slug": m.get("slug"), "fee": f(m.get("feeCoefficient")) or KALSHI_TAKER, "q": m.get("question") or "",
            "type": m.get("marketType"),
            "long": {"desc": long_side.get("description"),
                     "team": pm_team(long_side.get("team"), long_side.get("description"))},
            "short": {"desc": short_side.get("description"),
                      "team": pm_team(short_side.get("team"), short_side.get("description"))},
            "quote": (quote_val(m.get("bestBidQuote")), quote_val(m.get("bestAskQuote")))}
    if info["type"] == "spreads":
        h = f(long_side.get("description"))
        info["h_long"] = h if h is not None else pm_line(m)
        if info["h_long"] is None:
            return None
    elif info["type"] == "totals":
        t = pm_line(m)
        if t is None or "over" not in (long_side.get("description") or "").lower():
            return None
        info["line"] = abs(t)
    return info


def slug_num(x):
    """28.5 -> '28pt5' (Polymarket slug style)."""
    whole = int(abs(x))
    frac = int(round((abs(x) - whole) * 10))
    return f"{whole}pt{frac}"


def pm_markets_by_slug(slugs, chunk=80):
    """Fetch markets (with live quotes) by exact slug, many per request. Missing slugs just don't come back."""
    slugs = list(dict.fromkeys(slugs))
    chunks = [slugs[i:i + chunk] for i in range(0, len(slugs), chunk)]

    def fetch(ch):
        want = set(ch)
        try:
            d = get_json(f"{PM}/v1/markets", params=[("slug", x) for x in ch] + [("limit", len(ch))])
            return [m for m in d.get("markets") or [] if m.get("slug") in want]
        except Exception as e:  # noqa: BLE001
            log(f"pm slug batch failed: {e!r}"[:200])
            return []

    out = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for ms in ex.map(fetch, chunks):
            for m in ms:
                out[m["slug"]] = m
    log(f"polymarket: asked for {len(slugs)} markets in {len(chunks)} requests, {len(out)} exist")
    return out


def ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


START_BUFFER = dt.timedelta(minutes=10)
SCHED_RE = re.compile(r"scheduled for ([A-Z][a-z]+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2} [AP]M) UTC")


def pm_skip_reason(e, now):
    """Why a Polymarket US event is no longer a pre-game market (None if it still is).

    Polymarket US marks games in progress with live=true and a period ("H1", "Q3", "S2"...);
    "NS" means not started. Its start times for tennis are estimates, so the live flag matters most there."""
    if e.get("ended"):
        return "over"
    if e.get("live"):
        return "live"
    period = (e.get("period") or "").strip()
    if period and period != "NS":
        return "live"
    if re.search(r"[1-9]", e.get("score") or ""):     # "0-0" before the start; "6-3, 2-1:15-0" once it's on
        return "live"
    start = ts(e.get("startTime") or e.get("startDate"))
    if start is None:
        return "no start time"
    if start <= now + START_BUFFER:
        return "starting"   # live prices move faster than this scan runs
    return None


def pm_sched(question):
    """The original schedule in Polymarket's question text ('... scheduled for November 2, 2026 at 9:30 AM UTC?')."""
    m = SCHED_RE.search(question or "")
    if not m:
        return None
    try:
        return dt.datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %d, %Y %I:%M %p").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


SKIPPED = defaultdict(int)


def pm_games(now):
    lo = (now - dt.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (now + dt.timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    events, off = [], 0
    while off < 8000:
        d = get_json(f"{PM}/v1/events", params={"closed": "false", "limit": 100, "offset": off,
                                                "startDateMin": lo, "startDateMax": hi})
        evs = d.get("events") or []
        for e in evs:
            lg = PM_PREFIX.get((e.get("slug") or "").split("-")[0])
            if lg:
                events.append((lg, e))
        if len(evs) < 100:
            break
        off += 100
    games = []
    for lg, e in events:
        start = e.get("startTime") or e.get("startDate")
        st = ts(start)
        if st is None:
            continue
        date = st.astimezone(ET).date().isoformat()
        why = pm_skip_reason(e, now)
        if why:
            SKIPPED[why] += 1
            continue
        mascots = {}
        for m in e.get("markets") or []:
            if m.get("marketType") == "moneyline":
                for sd in m.get("marketSides") or []:
                    ab = (sd.get("team") or {}).get("abbreviation")
                    if ab:
                        mascots[ab] = sd.get("description")
        g = {"league": lg, "slug": e.get("slug"), "title": e.get("title"), "start": start, "date": date,
             "teams": [pm_team(t, mascots.get(t.get("abbreviation"))) for t in (e.get("teams") or [])],
             "ml": None, "spread": [], "total": [], "moved_from": None}
        for m in e.get("markets") or []:
            if m.get("marketType") == "moneyline":
                info = pm_info(m)
                if info:
                    g["ml"] = info
                    if not g["teams"]:
                        g["teams"] = [info["long"]["team"], info["short"]["team"]]
                    sched = pm_sched(m.get("question"))
                    if sched and abs((sched - st).total_seconds()) >= 2 * 3600:
                        g["moved_from"] = sched.isoformat().replace("+00:00", "Z")  # rain delay, new order of play...
        if g["ml"] or g["spread"] or g["total"]:
            games.append(g)
    log(f"polymarket: {len(games)} pre-game games " + json.dumps({lg: sum(1 for g in games if g['league'] == lg) for lg in LEAGUES})
        + f"; skipped {json.dumps(SKIPPED)}")
    return games


def pm_quotes(slugs):
    """slug -> (bid, ask) for the long side. Tries the batch endpoint, falls back to /bbo."""
    out, slugs = {}, list(dict.fromkeys(slugs))
    batch_ok = None
    for i in range(0, len(slugs), 50):
        chunk = slugs[i:i + 50]
        if batch_ok is False:
            break
        try:
            d = get_json(f"{PM}/v1/markets", params=[("slug", s) for s in chunk] + [("limit", 100)])
            ms = d.get("markets") or []
            got = {m.get("slug"): m for m in ms if m.get("slug") in chunk}
            if batch_ok is None:
                batch_ok = len(got) >= max(2, int(0.6 * len(chunk))) if len(chunk) > 1 else bool(got)
                if not batch_ok:
                    break
            for s, m in got.items():
                out[s] = (quote_val(m.get("bestBidQuote")), quote_val(m.get("bestAskQuote")))
        except Exception as e:  # noqa: BLE001
            log(f"pm batch quotes failed: {e!r}"[:200])
            batch_ok = False
    missing = [s for s in slugs if s not in out]
    if missing:
        def bbo(s):
            try:
                d = get_json(f"{PM}/v1/markets/{s}/bbo").get("marketData") or {}
                return s, (quote_val(d.get("bestBid")), quote_val(d.get("bestAsk")))
            except Exception:  # noqa: BLE001
                return s, (None, None)
        with ThreadPoolExecutor(max_workers=8) as ex:
            out.update(dict(ex.map(bbo, missing)))
    log(f"polymarket quotes: {len(out)} markets (batch={'yes' if batch_ok else 'no'})")
    return out


def pm_top_qty(slug):
    """(qty at best bid, qty at best ask) for the long side."""
    try:
        d = get_json(f"{PM}/v1/markets/{slug}/book").get("marketData") or {}
        bids, offers = d.get("bids") or [], d.get("offers") or []
        return (f(bids[0].get("qty")) if bids else None, f(offers[0].get("qty")) if offers else None)
    except Exception:  # noqa: BLE001
        return (None, None)


# ---------------------------------------------------------------- pricing
def k_fee(p, n=CONTRACTS):
    return math.ceil(KALSHI_TAKER * n * p * (1 - p) * 100 - 1e-9) / 100


def pm_fee(p, coef, n=CONTRACTS):
    return math.ceil(coef * n * p * (1 - p) * 100 - 1e-9) / 100


def ok(p):
    return p is not None and 0.005 < p < 0.995


def k_buy_yes(q):
    return (q["ya"], q["ya_n"], "yes") if ok(q.get("ya")) else None


def k_buy_no(q):
    yb = q.get("yb")
    return ((1 - yb), q["yb_n"], "no") if yb and ok(1 - yb) else None


def pm_buy(quote, side):
    bid, ask = quote or (None, None)
    if side == "long":
        return ask if ok(ask) else None
    return (1 - bid) if bid and ok(1 - bid) else None


# ---------------------------------------------------------------- matching
def match(kgames, pgames):
    by_lg = defaultdict(list)
    for g in pgames:
        by_lg[g["league"]].append(g)
    pairs, unmatched = [], []
    for kg in kgames:
        codes = list(kg["teams"])
        kt = [{"code": c, "name": kg["teams"][c]} for c in codes]
        best = None
        for pg in by_lg.get(kg["league"], []):
            dd = abs((dt.date.fromisoformat(pg["date"]) - dt.date.fromisoformat(kg["date"])).days)
            # tennis order of play shifts by a day or two; team sports keep their date
            if dd > (2 if kg["league"] in ("atp", "wta") else 1) or len(pg["teams"]) < 2:
                continue
            p0, p1 = pg["teams"][0], pg["teams"][1]
            if same_team(kt[0], p0) and same_team(kt[1], p1):
                assign = {codes[0]: 0, codes[1]: 1}
            elif same_team(kt[0], p1) and same_team(kt[1], p0):
                assign = {codes[0]: 1, codes[1]: 0}
            else:
                continue
            if best is None or dd < best[0]:
                best = (dd, pg, assign)
        if best:
            pairs.append((kg, best[1], best[2]))
        else:
            near = [f"{pg['title']} [{' | '.join(','.join(t['schools']) + '/' + str(t.get('abbr')) for t in pg['teams'])}]"
                    for pg in by_lg.get(kg["league"], []) if pg["date"] == kg["date"]
                    and any(tokens(n)[:1] == tokens(t["name"])[:1] for n in kg["teams"].values() for t in pg["teams"])][:2]
            unmatched.append(f"{kg['league']} {kg['date']} {' vs '.join(f'{v}/{k}' for k, v in kg['teams'].items())}"
                             + (f"  ~ {near}" if near else ""))
    return pairs, unmatched


def pm_side_for_team(info, pg, team_idx):
    """Which side ('long'/'short') of a Polymarket market belongs to the event's team #team_idx."""
    target = pg["teams"][team_idx]
    for side in ("long", "short"):
        t = info[side]["team"]
        if t.get("abbr") and t.get("abbr") == target.get("abbr"):
            return side
        if t.get("name") and t.get("name") == target.get("name"):
            return side
    for side in ("long", "short"):  # fall back to names in the side description
        if name_match(info[side].get("desc") or "", target.get("names") or []):
            return side
    return None


# ---------------------------------------------------------------- evaluate
def combo(league, kind, line_txt, kg, pg, k_leg, p_leg, start):
    kp, kn, kside, kq, klabel = k_leg
    pp, pside, pinfo, plabel, pq = p_leg
    if not ok(kp) or not ok(pp) or not (0.03 <= kp <= 0.97) or not (0.03 <= pp <= 0.97):
        return None  # 1-2 cent longshots can't pay after fees and tick rounding
    kf, pf = k_fee(kp), pm_fee(pp, pinfo["fee"])
    cost = CONTRACTS * (kp + pp) + kf + pf
    per = cost / CONTRACTS
    if per > WATCH_MAX:
        return None
    return {
        "lg": league, "kind": kind, "line": line_txt, "date": kg["date"], "start": start,
        "moved_from": pg.get("moved_from"), "event": pg.get("slug"),
        "game": pg.get("title") or " vs ".join(kg["teams"].values()),
        "k": {"label": klabel, "side": kside, "price": round(kp, 4), "fee100": kf, "size": kn,
              "ticker": kq["ticker"], "title": kq.get("title"), "url": K.market_url(kq["series"], kq["event"])},
        "p": {"label": plabel, "side": pside, "price": round(pp, 4), "fee100": pf, "fee_coef": pinfo["fee"],
              "slug": pinfo["slug"], "market": pinfo["q"], "bid": pq[0], "ask": pq[1]},
        "cost100": round(cost, 2), "profit100": round(CONTRACTS - cost, 2), "per": round(per, 4),
        "roi": round((CONTRACTS - cost) / cost, 4), "note": RULE_NOTES.get(league) if kind == "Moneyline" else None,
    }


STATS = defaultdict(lambda: {"pairs": 0, "best": 9.0})


def note(kind, kp, pp, coef):
    if ok(kp) and ok(pp):
        st = STATS[kind]
        st["pairs"] += 1
        per = (CONTRACTS * (kp + pp) + k_fee(kp) + pm_fee(pp, coef)) / CONTRACTS
        st["best"] = min(st["best"], round(per, 4))


def evaluate(pairs, quotes):
    found = []
    for kg, pg, assign in pairs:
        lg, start = kg["league"], pg.get("start")
        codes = list(kg["teams"])
        names = {c: kg["teams"][c] for c in codes}
        # moneyline
        if pg["ml"] and len(kg["ml"]) == 2:
            info = pg["ml"]
            pq = quotes.get(info["slug"], (None, None))
            for c in codes:
                other = codes[1] if c == codes[0] else codes[0]
                opts = [x for x in (k_buy_yes(kg["ml"][c]), k_buy_no(kg["ml"][other])) if x]
                if not opts:
                    continue
                kp, kn, kside = min(opts, key=lambda x: x[0])
                kq = kg["ml"][c] if kside == "yes" else kg["ml"][other]
                klabel = f"{names[c]} to win"
                pside = pm_side_for_team(info, pg, assign[other])
                if not pside:
                    continue
                pp = pm_buy(pq, pside)
                note("Moneyline", kp, pp, info["fee"])
                r = combo(lg, "Moneyline", None, kg, pg, (kp, kn, kside, kq, klabel),
                          (pp, pside, info, f"{info[pside]['desc'] or names[other]} to win", pq), start)
                if r:
                    found.append(r)
        # spreads: Kalshi "A wins by over X" = A -X ; No = B +X
        for code, x, kq in kg["spread"]:
            if code not in assign:
                continue
            other = codes[1] if code == codes[0] else codes[0]
            for info in pg["spread"]:
                h = info["h_long"]
                if abs(abs(h) - x) > 1e-6:
                    continue
                pq = quotes.get(info["slug"], (None, None))
                long_side_team = pm_side_for_team(info, pg, assign[code])  # side that is `code`
                if not long_side_team:
                    continue
                code_h = h if long_side_team == "long" else -h            # handicap Polymarket gives `code`
                other_side = "short" if long_side_team == "long" else "long"
                if abs(code_h + x) < 1e-6:     # Polymarket has code -X and other +X
                    pairs_ = [(k_buy_yes(kq), f"{names[code]} -{x:g}", other_side, f"{names[other]} +{x:g}"),
                              (k_buy_no(kq), f"{names[other]} +{x:g}", long_side_team, f"{names[code]} -{x:g}")]
                else:
                    continue
                for kleg, klab, pside, plab in pairs_:
                    if not kleg:
                        continue
                    note("Spread", kleg[0], pm_buy(pq, pside), info["fee"])
                    r = combo(lg, "Spread", f"{x:g}", kg, pg, (kleg[0], kleg[1], kleg[2], kq, klab),
                              (pm_buy(pq, pside), pside, info, plab, pq), start)
                    if r:
                        found.append(r)
        # totals
        for t, kq in kg["total"]:
            for info in pg["total"]:
                if abs(info["line"] - t) > 1e-6:
                    continue
                pq = quotes.get(info["slug"], (None, None))
                for kleg, klab, pside, plab in ((k_buy_yes(kq), f"Over {t:g}", "short", f"Under {t:g}"),
                                                (k_buy_no(kq), f"Under {t:g}", "long", f"Over {t:g}")):
                    if not kleg:
                        continue
                    note("Total", kleg[0], pm_buy(pq, pside), info["fee"])
                    r = combo(lg, "Total", f"{t:g}", kg, pg, (kleg[0], kleg[1], kleg[2], kq, klab),
                              (pm_buy(pq, pside), pside, info, plab, pq), start)
                    if r:
                        found.append(r)
    found.sort(key=lambda r: r["per"])
    return found


def main():
    t0 = time.time()
    now = dt.datetime.now(dt.timezone.utc)
    os.makedirs(OUT, exist_ok=True)
    result = {"updated": now.isoformat(timespec="seconds"), "ok": False, "opps": [], "counts": {}}
    try:
        kgames = kalshi_games()
        k_at = dt.datetime.now(dt.timezone.utc)
        pgames = pm_games(now)
        pairs, unmatched = match(kgames, pgames)

        def live(q):  # a Kalshi line worth pricing: some real quote between 3c and 97c
            return any(x is not None and 0.03 <= x <= 0.97 for x in (q.get("ya"), q.get("yb")))

        want = []
        for kg, pg, _ in pairs:
            if pg["ml"]:
                want.append(pg["ml"]["slug"])
            base = pg["slug"]
            for x in sorted({x for _, x, q in kg["spread"] if live(q)}):
                want += [f"asc-{base}-pos-{slug_num(x)}", f"asc-{base}-neg-{slug_num(x)}"]
            for t in sorted({t for t, q in kg["total"] if live(q)}):
                want.append(f"tsc-{base}-{slug_num(t)}")
        markets = pm_markets_by_slug(want)
        result["p_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        quotes = {}
        for kg, pg, _ in pairs:
            base = pg["slug"]
            pg["spread"], pg["total"] = [], []
            for slug_, m in ((x, markets.get(x)) for x in [f"asc-{base}-pos-{slug_num(v)}" for _, v, _ in kg["spread"]]
                             + [f"asc-{base}-neg-{slug_num(v)}" for _, v, _ in kg["spread"]]):
                if m and slug_ not in {i["slug"] for i in pg["spread"]}:
                    info = pm_info(m)
                    if info and info["type"] == "spreads":
                        pg["spread"].append(info)
            for t, _ in kg["total"]:
                m = markets.get(f"tsc-{base}-{slug_num(t)}")
                if m and m["slug"] not in {i["slug"] for i in pg["total"]}:
                    info = pm_info(m)
                    if info and info["type"] == "totals":
                        pg["total"].append(info)
            for info in ([pg["ml"]] if pg["ml"] else []) + pg["spread"] + pg["total"]:
                m = markets.get(info["slug"])
                quotes[info["slug"]] = (quote_val(m.get("bestBidQuote")), quote_val(m.get("bestAskQuote"))) if m else info["quote"]
        opps = evaluate(pairs, quotes)
        # sizes on the Polymarket side for anything worth showing
        top = opps[:120]
        slugs_top = list(dict.fromkeys(o["p"]["slug"] for o in top))
        with ThreadPoolExecutor(max_workers=6) as ex:
            qty = dict(zip(slugs_top, ex.map(pm_top_qty, slugs_top)))
        for o in top:
            bq, aq = qty.get(o["p"]["slug"], (None, None))
            size = aq if o["p"]["side"] == "long" else bq
            o["p"]["size"] = size if size and size > 0 else None
        counts = {}
        for lg in LEAGUES:
            counts[lg] = {"kalshi": sum(1 for g in kgames if g["league"] == lg),
                          "poly": sum(1 for g in pgames if g["league"] == lg),
                          "matched": sum(1 for kg, _, _ in pairs if kg["league"] == lg)}
        result.update({"ok": True, "opps": top, "counts": counts, "n_arbs": sum(1 for o in opps if o["per"] < 1),
                       "n_close": len(opps), "checked": {k: v["pairs"] for k, v in STATS.items()},
                       "best": {k: v["best"] for k, v in STATS.items()}, "secs": round(time.time() - t0, 1),
                       "k_at": k_at.isoformat(timespec="seconds"), "skipped": dict(SKIPPED)})
        log(f"arb: {len(pairs)} matched games, {result['n_arbs']} arbs, {len(opps)} within ${WATCH_MAX:.2f}")
        pm_sp = sum(len(pg["spread"]) for _, pg, _ in pairs)
        pm_to = sum(len(pg["total"]) for _, pg, _ in pairs)
        k_sp = sum(len(kg["spread"]) for kg, _, _ in pairs)
        k_to = sum(len(kg["total"]) for kg, _, _ in pairs)
        log(f"pairs priced: {json.dumps(STATS)}; matched games carry PM spreads={pm_sp} totals={pm_to}, "
            f"Kalshi spreads={k_sp} totals={k_to}")
        ex_sp = [(kg["key"], [(c, x) for c, x, _ in kg["spread"]][:6], [(i["h_long"], i["long"]["desc"], i["long"]["team"]["abbr"]) for i in pg["spread"]][:4])
                 for kg, pg, _ in pairs if pg["spread"] and kg["spread"]][:6]
        ex_to = [(kg["key"], sorted(t for t, _ in kg["total"])[:8], [i["line"] for i in pg["total"]][:4])
                 for kg, pg, _ in pairs if pg["total"] and kg["total"]][:6]
        log(f"spread examples: {ex_sp}")
        log(f"total examples: {ex_to}")
        debug = {"unmatched_kalshi": unmatched[:300], "log": _log[-200:]}
    except Exception:  # noqa: BLE001
        log("arb failed:\n" + traceback.format_exc())
        debug = {"log": _log[-200:]}
    with open(os.path.join(OUT, "arb.json"), "w") as fh:
        json.dump(result, fh, separators=(",", ":"))
    with open(os.path.join(OUT, "arb-debug.json"), "w") as fh:
        json.dump(debug, fh, indent=1)


if __name__ == "__main__":
    main()
