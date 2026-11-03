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

def _L(label, group, game, pm, spread=(), total=(), btts=(), match="loose", three_way=False, props=False, note=None):
    return {"label": label, "group": group, "game": list(game), "spread": list(spread), "total": list(total),
            "btts": list(btts), "pm": list(pm), "match": match, "three_way": three_way, "props": props, "note": note}


TENNIS_NOTE = "If a player retires mid-match, the two sites may settle differently. Read both sites' rules first."
FIGHT_NOTE = "Fights can end in a draw or no contest, and the two sites may settle those differently. Read both sites' rules first."
CRICKET_NOTE = "A tie, no result or abandoned match may settle differently on the two sites. Read both sites' rules first."

# match: "strict" = exact school/city (US teams: Kentucky never pairs with Western Kentucky),
#        "loose"  = club names ("Manchester United" = "Manchester United FC"), "person" = players and fighters.
LEAGUES = {
    "nfl": _L("NFL", "nfl", ["KXNFLGAME"], ["nfl"], ["KXNFLSPREAD"], ["KXNFLTOTAL"], match="strict", props=True,
              note="NFL games can end in a tie. If that happens, both team-win contracts can lose, so moneyline pairs aren't risk-free."),
    "nba": _L("NBA", "nba", ["KXNBAGAME"], ["nba"], ["KXNBASPREAD"], ["KXNBATOTAL"], match="strict", props=True),
    "nhl": _L("NHL", "nhl", ["KXNHLGAME"], ["nhl"], ["KXNHLSPREAD"], ["KXNHLTOTAL"], match="strict", props=True),
    "cfb": _L("College football", "cfb", ["KXNCAAFGAME"], ["cfb"], ["KXNCAAFSPREAD"], ["KXNCAAFTOTAL"], match="strict"),
    "cbb": _L("College basketball", "cbb", ["KXNCAAMBGAME"], ["cbb"], ["KXNCAAMBSPREAD"], ["KXNCAAMBTOTAL"], match="strict"),
    "wcbb": _L("Women's college basketball", "wcbb", ["KXNCAAWBGAME"], ["wcbb"], ["KXNCAAWBSPREAD"], ["KXNCAAWBTOTAL"], match="strict"),
    "atp": _L("ATP tennis", "tennis", ["KXATPMATCH", "KXATPCHALLENGERMATCH"], ["atp", "atpcq", "atpc"], match="person", note=TENNIS_NOTE),
    "wta": _L("WTA tennis", "tennis", ["KXWTAMATCH", "KXWTACHALLENGERMATCH"], ["wta"], match="person", note=TENNIS_NOTE),
    "itf": _L("ITF tennis", "tennis", ["KXITFMATCH"], ["itfme"], match="person", note=TENNIS_NOTE),
    "itfw": _L("ITF tennis (women)", "tennis", ["KXITFWMATCH"], ["itfwo"], match="person", note=TENNIS_NOTE),
    "tdbl": _L("Tennis doubles", "tennis", ["KXATPDOUBLES", "KXATPCHALLENGERDOUBLES", "KXWTADOUBLES"], ["atpdb", "wtadb"],
               match="pairs", note=TENNIS_NOTE),
    "ufc": _L("UFC", "fights", ["KXUFCFIGHT"], ["ufc"], match="person", note=FIGHT_NOTE),
    "boxing": _L("Boxing", "fights", ["KXBOXING"], ["boxing"], match="person", note=FIGHT_NOTE),
    "cs2": _L("Counter-Strike 2", "esports", ["KXCS2GAME"], ["cs2"]),
    "dota2": _L("Dota 2", "esports", ["KXDOTA2GAME"], ["dota2"]),
    "lol": _L("League of Legends", "esports", ["KXLOLGAME"], ["lol"]),
    "r6": _L("Rainbow Six", "esports", ["KXR6GAME"], ["r6"]),
    "eurolg": _L("EuroLeague", "hoops", ["KXEUROLEAGUEGAME"], ["eurolg"]),
    "eurocup": _L("EuroCup", "hoops", ["KXEUROCUPGAME"], ["eurocup"], ["KXEUROCUPSPREAD"], ["KXEUROCUPTOTAL"]),
    "bcl": _L("Basketball Champions League", "hoops", ["KXFIBACHAMPGAME"], ["bcl"]),
    "cba": _L("China CBA", "hoops", ["KXCBAGAME"], ["cba"]),
    "nbl": _L("Australia NBL", "hoops", ["KXNBLGAME"], ["nbl"]),
    "bbl": _L("Germany BBL", "hoops", ["KXBBLGAME"], ["bbl"]),
    "vtb": _L("VTB United League", "hoops", ["KXVTBGAME"], ["vtb"]),
    "koris": _L("Finland Korisliiga", "hoops", ["KXKORISLIIGAGAME"], ["koris"]),
    "lnbp": _L("Mexico LNBP", "hoops", ["KXLNBPGAME"], ["lnbp"], ["KXLNBPSPREAD"], ["KXLNBPTOTAL"]),
    "cznbl": _L("Czech NBL", "hoops", ["KXCZENBLGAME"], ["cznbl"]),
    "kbl": _L("Korea KBL", "hoops", ["KXKBLGAME"], ["kbl"]),
    "lkl": _L("Lithuania LKL", "hoops", ["KXLKLGAME"], ["lkl"]),
    "aba": _L("Adriatic ABA League", "hoops", ["KXABAGAME"], ["aba"]),
    "denbl": _L("Denmark Basketligaen", "hoops", ["KXDBBFGAME"], ["denbl"]),
    "lnb": _L("France LNB Elite", "hoops", ["KXLNBELITEGAME"], ["lnb"]),
    "fra2": _L("France Elite 2", "hoops", ["KXLNBELITE2GAME"], ["fra2"]),
    "khl": _L("KHL", "hockey", ["KXKHLGAME"], ["khl"]),
    "ahl": _L("AHL", "hockey", ["KXAHLGAME"], ["ahl"]),
    "kbo": _L("Korea KBO", "baseball", ["KXKBOGAME"], ["kbo"], ["KXKBOSPREAD"], ["KXKBOTOTAL"]),
    "t20": _L("T20 cricket", "cricket", ["KXT20MATCH"], ["t20icr"], match="loose", note=CRICKET_NOTE),
    "odi": _L("ODI cricket", "cricket", ["KXODIMATCH"], ["odicr"], match="loose", note=CRICKET_NOTE),
}
# Soccer: Kalshi lists win / tie / win as three markets, and so does Polymarket US. Full time = 90 minutes plus stoppage.
SOCCER = [  # key, label, Kalshi series stem, Polymarket prefixes, Kalshi also has spread/total/both-teams-to-score
    ("ucl", "Champions League", "KXUCL", ["ucl"], True), ("uel", "Europa League", "KXUEL", ["uel"], True),
    ("uecl", "Conference League", "KXUECL", ["uecl"], True), ("epl", "Premier League", "KXEPL", ["epl"], True),
    ("laliga", "La Liga", "KXLALIGA", ["lal"], True), ("seriea", "Serie A", "KXSERIEA", ["sea"], True),
    ("bundesliga", "Bundesliga", "KXBUNDESLIGA", ["bun"], True), ("ligue1", "Ligue 1", "KXLIGUE1", ["lg1"], True),
    ("eflch", "EFL Championship", "KXEFLCHAMPIONSHIP", ["eflch"], True), ("efl1", "EFL League One", "KXEFLL1", ["efl1"], True),
    ("mls", "MLS", "KXMLS", ["mls"], True), ("spl", "Saudi Pro League", "KXSAUDIPL", ["spl"], True),
    ("j2", "Japan J2 League", "KXJ2LEAGUE", ["j2"], True), ("bra", "Brasileirão", "KXBRASILEIRO", ["bra"], True),
    ("brb", "Brasileirão Série B", "KXBRASILEIROB", ["brb"], True), ("lco", "Colombia Primera A", "KXDIMAYOR", ["lco"], True),
    ("par1", "Paraguay Primera", "KXAPFDDH", ["par1"], True), ("chl1", "Chile Primera", "KXCHLLDP", ["pdc"], True),
    ("pl1", "Peru Liga 1", "KXPERLIGA1", ["pl1"], True), ("alsv", "Allsvenskan", "KXALLSVENSKAN", ["alsv"], True),
    ("acle", "AFC Champions League", "KXAFCCL", ["acle"], True), ("ecu1", "Ecuador LigaPro", "KXECULP", ["ecu1"], True),
    ("uru1", "Uruguay Primera", "KXURYPD", ["uru1"], True),
    ("ligpor", "Liga Portugal", "KXLIGAPORTUGAL", ["ligpor"], False), ("ere", "Eredivisie", "KXEREDIVISIE", ["ere"], False),
    ("bun2", "2. Bundesliga", "KXBUNDESLIGA2", ["bun2"], False), ("lal2", "La Liga 2", "KXLALIGA2", ["lal2"], False),
    ("srb", "Serie B", "KXSERIEB", ["srb"], False), ("serc", "Serie C", "KXSERIEC", ["serca", "sercb", "sercc"], False),
    ("lig2", "Ligue 2", "KXLIGUE2", ["lig2"], False), ("bel1", "Belgian Pro League", "KXBELGIANPL", ["bel1"], False),
    ("swsl", "Swiss Super League", "KXSWISSLEAGUE", ["swsl"], False), ("atbl", "Austrian Bundesliga", "KXAUTBUNDES", ["atbl"], False),
    ("nb1", "Hungary NB I", "KXHUNNB1", ["nb1"], False), ("svnp", "Slovenia PrvaLiga", "KXSVNPL", ["svnp"], False),
    ("hnl", "Croatia HNL", "KXHNL", ["hnl"], False), ("ekst", "Ekstraklasa", "KXEKSTRAKLASA", ["ekst"], False),
    ("tsl", "Süper Lig", "KXSUPERLIG", ["tsl"], False), ("tff1", "TFF 1. Lig", "KXTFF1LIG", ["tff1"], False),
    ("uaepl", "UAE Pro League", "KXUAEPL", ["uaepl"], False), ("j1", "Japan J1 League", "KXJLEAGUE", ["j1"], False),
    ("lpb", "Bolivia Primera", "KXBOLPDIV", ["lpb"], False), ("sld", "Danish Superliga", "KXDENSUPERLIGA", ["sld"], False),
    ("grsl", "Greece Super League", "KXSLGREECE", ["grsl"], False), ("slr", "Romania SuperLiga", "KXROML1", ["slr"], False),
    ("flc", "Czech First League", "KXCZEFL", ["flc"], False), ("fnl", "Czech National League", "KXCZEFNL", ["fnl"], False),
    ("thai1", "Thai League 1", "KXTHAIL1", ["thai1"], False), ("idnsl", "Indonesia Super League", "KXIDNSL", ["idnsl"], False),
    ("wsl", "Women's Super League", "KXEWSL", ["wsl"], False), ("fbl", "Frauen-Bundesliga", "KXBUNDESLIGAW", ["fbl"], False),
    ("ligaf", "Liga F", "KXLIGAF", ["ligaf"], False), ("uslc", "USL Championship", "KXUSL", ["uslc"], False),
]
for _k, _label, _stem, _pm, _extras in SOCCER:
    LEAGUES[_k] = _L(_label, "soccer", [_stem + "GAME"], _pm, [_stem + "SPREAD"] if _extras else [],
                     [_stem + "TOTAL"] if _extras else [], [_stem + "BTTS"] if _extras else [], three_way=True)
PM_PREFIX = {p: lg for lg, c in LEAGUES.items() for p in c["pm"]}
RULE_NOTES = {lg: c["note"] for lg, c in LEAGUES.items() if c.get("note")}

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


# Club names differ more between the sites ("Everton" / "Everton FC", "Inter" / "Internazionale"), so leagues outside
# the US compare the distinctive words only. Both teams must still match, on the same date, in the same league.
GENERIC = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "us", "rc", "cd", "ud", "sd", "ca", "club", "de", "del", "la", "el",
           "fk", "sk", "bk", "if", "ik", "nk", "hnk", "kv", "krc", "sv", "vfb", "vfl", "tsg", "calcio", "futbol", "football",
           "futebol", "cp", "ec", "esporte", "clube", "the", "team", "esports", "gaming", "e", "bc", "kk", "basket",
           "basketball", "hc", "and", "w", "women", "wfc", "cfc", "s", "a", "of", "do", "da", "associacao", "sport"}


def core(name):
    t = [x for x in tokens(name) if x not in GENERIC and not x.isdigit()]
    return t or tokens(name)


def _tok_eq(a, b):
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def loose_score(a, b):
    """2 = same distinctive words, 1 = one name's words all appear in the other's, 0 = different."""
    x, y = core(a), core(b)
    if not x or not y:
        return 0
    if x == y or sorted(x) == sorted(y):
        return 2
    if all(any(_tok_eq(p, q) for q in y) for p in x) or all(any(_tok_eq(q, p) for p in x) for q in y):
        return 1
    return 0


def person_score(a, b):
    """Players and fighters: 2 = same full name, 1 = same last name and first initial (or one name inside the other)."""
    if "," in (b or ""):                       # "Tashiro, Yuga"
        last, _, first = b.partition(",")
        b = f"{first} {last}"
    x, y = tokens(a), tokens(b)
    if not x or not y:
        return 0
    if x == y:
        return 2
    if x[-1] == y[-1] and x[0][:1] == y[0][:1]:
        return 1
    sx, sy = set(x), set(y)
    if (sx <= sy or sy <= sx) and len(min(x, y, key=len)) >= 2:
        return 1
    return 0


def pair_names(s):
    """'Kubler J / Puttergill C' or 'Quentin Halys / Pierre-Hugues Herbert' -> set of last names."""
    out = set()
    for part in (s or "").split("/"):
        t = [x for x in tokens(part) if len(x) > 1]
        if not t:
            return set()
        # Polymarket writes "Lastname Initial", Kalshi writes "First Last"
        out.add(t[0] if len(tokens(part)) > len(t) else t[-1])
    return out


def team_score(mode, k_team, p_team):
    names = [p_team.get("name") or ""] + list(p_team.get("names") or []) + list(p_team.get("schools") or [])
    kname = k_team.get("name") or ""
    if mode == "strict":
        return 2 if same_team(k_team, p_team) else 0
    if mode == "person":
        return max((person_score(kname, n) for n in names if n), default=0)
    if mode == "pairs":
        a = pair_names(kname)
        return 2 if a and len(a) == 2 and any(a == pair_names(n) for n in names) else 0
    code = (k_team.get("code") or "").lower()
    best = max((loose_score(kname, n) for n in names if n), default=0)
    if code and len(code) >= 2 and code in {(p_team.get("abbr") or "").lower(), (p_team.get("disp") or "").lower()}:
        best = max(best, 1) + 1
    return best


# ---------------------------------------------------------------- kalshi
def k_quote(mk, series):
    return {
        "ticker": mk.get("ticker"), "event": mk.get("event_ticker"), "series": series,
        "yb": K.price(mk, "yes_bid"), "ya": K.price(mk, "yes_ask"),
        "yb_n": K.qty(mk, "yes_bid_size"), "ya_n": K.qty(mk, "yes_ask_size"),
        "title": mk.get("title"), "vol": K.qty(mk, "volume"),
    }


EVENT_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})(\d{4})?([A-Z0-9]+)$")   # 26NOV03 [1430] PENGAM


def k_event_date(ev):
    part = ev.split("-", 1)[1] if "-" in ev else ev
    m = EVENT_RE.match(part)
    if not m:
        return None
    try:
        return dt.date(2000 + int(m.group(1)), K.MONTHS[m.group(2)], int(m.group(3)))
    except (KeyError, ValueError):
        return None


def kalshi_games():
    base = K.BASES[0]
    games = {}

    def fetch(series):
        try:
            return series, K.fetch_series(base, series)
        except Exception as e:  # noqa: BLE001
            log(f"kalshi {series} failed: {e!r}"[:200])
            return series, []

    all_series = [(lg, kind, s) for lg, c in LEAGUES.items() for kind in ("game", "spread", "total", "btts") for s in c[kind]]
    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = dict(ex.map(fetch, [s for _, _, s in all_series]))
    for lg, kind, s in all_series:
        for mk in fetched.get(s, []):
            if mk.get("status") not in ("active", "open", None):
                continue
            ev = mk.get("event_ticker") or ""
            key = ev.split("-", 1)[1] if "-" in ev else ev
            date = k_event_date(ev)
            if not date:
                continue
            g = games.setdefault((lg, key), {"league": lg, "key": key, "date": date.isoformat(), "teams": {},
                                             "ml": {}, "tie": None, "btts": None, "spread": [], "total": [], "events": {}})
            g["events"][kind] = ev
            suffix = (mk.get("ticker") or "").rsplit("-", 1)[-1]
            q = k_quote(mk, s)
            if kind == "game":
                sub = (mk.get("yes_sub_title") or "").strip()
                if suffix == "TIE" or sub.lower() in ("tie", "draw"):
                    g["tie"] = q
                else:
                    g["teams"].setdefault(suffix, sub or mk.get("title") or suffix)
                    g["ml"][suffix] = q
            elif kind == "spread":
                code = re.sub(r"\d+$", "", suffix)
                x = f(mk.get("floor_strike"))
                m = re.match(r"(.+?) wins by (?:over|more than)", mk.get("title") or "")
                if m:
                    g["teams"].setdefault(code, m.group(1).strip())
                if x is not None:
                    g["spread"].append((code, x, q))
            elif kind == "total":
                t = f(mk.get("floor_strike"))
                if t is not None:
                    g["total"].append((t, q))
            elif kind == "btts":
                g["btts"] = q
    today = dt.datetime.now(ET).date()
    out = [g for g in games.values() if len(g["teams"]) == 2
           and (not LEAGUES[g["league"]]["three_way"] or g["tie"])
           and today - dt.timedelta(days=1) <= dt.date.fromisoformat(g["date"]) <= today + dt.timedelta(days=6)]
    by_lg = defaultdict(int)
    for g in out:
        by_lg[g["league"]] += 1
    log(f"kalshi: {len(out)} games from {len(all_series)} series " + json.dumps(by_lg))
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
        is_ml = lambda m: m.get("marketType") == "moneyline" or (m.get("slug") or "").startswith("aec-")  # noqa: E731
        mascots = {}
        for m in e.get("markets") or []:
            if is_ml(m) and LEAGUES[lg]["match"] == "strict":
                for sd in m.get("marketSides") or []:
                    ab = (sd.get("team") or {}).get("abbreviation")
                    if ab:
                        mascots[ab] = sd.get("description")
        g = {"league": lg, "slug": e.get("slug"), "title": e.get("title"), "start": start, "date": date,
             "teams": [pm_team(t, mascots.get(t.get("abbreviation"))) for t in (e.get("teams") or [])],
             "ml": None, "ml3": {}, "btts": None, "spread": [], "total": [], "props": None, "moved_from": None}
        for m in e.get("markets") or []:
            sched = None
            if m.get("sportsMarketType") == "soccer_team_full_time_winner":
                info = pm_info(m)
                if not info or (info["long"]["desc"] or "").lower() != "yes":
                    continue
                if (m.get("slug") or "").endswith("-draw"):
                    g["ml3"]["draw"] = info
                else:
                    ab = ((m.get("marketSides") or [{}])[0].get("team") or {}).get("abbreviation")
                    idx = next((i for i, t in enumerate(e.get("teams") or []) if ab and t.get("abbreviation") == ab), None)
                    if idx is not None:
                        g["ml3"][idx] = info
                sched = pm_sched(m.get("question"))
            elif is_ml(m):
                info = pm_info(m)
                if info:
                    g["ml"] = info
                    if not g["teams"]:
                        g["teams"] = [info["long"]["team"], info["short"]["team"]]
                    sched = pm_sched(m.get("question"))
            if sched and abs((sched - st).total_seconds()) >= 2 * 3600:
                g["moved_from"] = sched.isoformat().replace("+00:00", "Z")  # rain delay, new order of play...
        if LEAGUES[lg]["three_way"]:
            g["ml"] = None
            if len(g["ml3"]) != 3 or len(g["teams"]) != 2:
                continue
        if g["ml"] or g["ml3"]:
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
    used = defaultdict(list)
    for kg in kgames:
        codes = list(kg["teams"])
        kt = [{"code": c, "name": kg["teams"][c]} for c in codes]
        mode = LEAGUES[kg["league"]]["match"]
        tennis = LEAGUES[kg["league"]]["group"] == "tennis"
        cands = []
        for pg in by_lg.get(kg["league"], []):
            dd = abs((dt.date.fromisoformat(pg["date"]) - dt.date.fromisoformat(kg["date"])).days)
            # tennis order of play shifts by a day or two; team sports keep their date
            if dd > (2 if tennis else 1) or len(pg["teams"]) < 2:
                continue
            p0, p1 = pg["teams"][0], pg["teams"][1]
            s00, s11 = team_score(mode, kt[0], p0), team_score(mode, kt[1], p1)
            s01, s10 = team_score(mode, kt[0], p1), team_score(mode, kt[1], p0)
            fwd = s00 + s11 if s00 and s11 else 0
            rev = s01 + s10 if s01 and s10 else 0
            if not fwd and not rev:
                continue
            if fwd == rev:
                continue                    # can't tell which team is which: skip rather than guess
            assign = {codes[0]: 0, codes[1]: 1} if fwd > rev else {codes[0]: 1, codes[1]: 0}
            cands.append((max(fwd, rev), -dd, pg, assign))
        cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
        if cands and not (len(cands) > 1 and cands[1][:2] == cands[0][:2] and mode != "strict"):
            pairs.append((kg, cands[0][2], cands[0][3]))
            used[cands[0][2]["slug"]].append(kg["key"])
        else:
            near = [f"{pg['title']} [{' | '.join(','.join(t['schools']) + '/' + str(t.get('abbr')) for t in pg['teams'])}]"
                    for pg in by_lg.get(kg["league"], []) if pg["date"] == kg["date"]
                    and any(tokens(n)[:1] == tokens(t["name"])[:1] for n in kg["teams"].values() for t in pg["teams"])][:2]
            unmatched.append(f"{kg['league']} {kg['date']} {' vs '.join(f'{v}/{k}' for k, v in kg['teams'].items())}"
                             + (f"  ~ {near}" if near else ""))
    dup = {s for s, ks in used.items() if len(ks) > 1}
    if dup:
        log(f"dropped {len(dup)} Polymarket events claimed by two Kalshi games: {sorted(dup)[:8]}")
        pairs = [p for p in pairs if p[1]["slug"] not in dup]
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
        if any(name_match(info[side].get("desc") or "", n) for n in target.get("names") or []):
            return side
    return None


# ---------------------------------------------------------------- player props
# Kalshi prop series (league, stat) -> Polymarket US sportsMarketType. Both mean "at least N":
# Kalshi "Jaylen Brown: 25+" and Polymarket "astatc-...-pts-jaybro-gte25".
PROP_PM = {
    ("nba", "pts"): "basketball_player_points",
    ("nba", "reb"): "basketball_player_rebounds",
    ("nba", "ast"): "basketball_player_assists",
    ("nba", "3pm"): "basketball_player_threes",
    ("nba", "pra"): "basketball_player_points_rebounds_assists",
    ("nba", "stl"): "basketball_player_steals",
    ("nba", "blk"): "basketball_player_blocks",
    ("nfl", "pass_yds"): "football_player_passing_yards",
    ("nfl", "pass_tds"): "football_player_passing_touchdowns",
    ("nfl", "pass_cmp"): "football_player_passing_completions",
    ("nfl", "pass_att"): "football_player_passing_attempts",
    ("nfl", "ints"): "football_player_interceptions_thrown",
    ("nfl", "rush_yds"): "football_player_rushing_yards",
    ("nfl", "rush_att"): "football_player_rushing_attempts",
    ("nfl", "rec_yds"): "football_player_receiving_yards",
    ("nfl", "rec"): "football_player_receptions",
    ("nfl", "rush_rec_yds"): "football_player_scrimmage_yards",
    ("nfl", "tds"): "football_player_touchdowns",
    ("nfl", "rec_long"): "football_player_longest_reception",
    ("nfl", "rush_long"): "football_player_longest_rush",
    ("nhl", "goals"): "hockey_player_goals",
    ("nhl", "points"): "hockey_player_points",
    ("nhl", "assists"): "hockey_player_assists",
    # Kalshi's goalie saves have no Polymarket twin: its "team saves" counts every goalie who plays
}
PM_PROP_TYPES = set(PROP_PM.values())
PROP_NOTE = ("If the player doesn't play, the two sites can settle this differently, so a prop pair isn't fully risk-free. "
             "Check both sites' rules for that.")


def kalshi_props(want):
    """Kalshi player props for the matched games: (league, game key) -> [prop]."""
    base = K.BASES[0]
    series = [s for s, (lg, stat, _) in K.SERIES.items() if (lg, stat) in PROP_PM and lg in {k[0] for k in want}]

    def fetch(s):
        try:
            return s, K.fetch_series(base, s)
        except Exception as e:  # noqa: BLE001
            log(f"kalshi {s} failed: {e!r}"[:200])
            return s, []

    out = defaultdict(list)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for s, mks in ex.map(fetch, series):
            lg, stat, label = K.SERIES[s]
            for mk in mks:
                if mk.get("status") not in ("active", "open", None):
                    continue
                p = K.parse_market(s, mk)
                if not p:
                    continue
                ev = mk.get("event_ticker") or ""
                key = ev.split("-", 1)[1] if "-" in ev else ev
                if (lg, key) in want:
                    out[(lg, key)].append({"stat": stat, "label": label, "name": p["player_name"], "n": p["line"],
                                           "ptype": PROP_PM[(lg, stat)], "q": k_quote(mk, s)})
    log(f"kalshi props on matched games: {sum(len(v) for v in out.values())} in {len(out)} games")
    return out


def pm_event_markets(slug):
    try:
        d = get_json(f"{PM}/v1/events/slug/{slug}", timeout=45)
        return (d.get("event") or d).get("markets") or []
    except Exception as e:  # noqa: BLE001
        log(f"pm event {slug} failed: {e!r}"[:200])
        return []


def pm_prop(m):
    """A Polymarket US player prop ('Will X record at least N ...?') -> info with player and N, else None."""
    if m.get("sportsMarketType") not in PM_PROP_TYPES:
        return None
    info = pm_info(m)
    if not info or (info["long"]["desc"] or "").strip().lower() != "yes":
        return None
    n = f(m.get("line"))
    name = None
    mm = re.match(r"^Will (.+?) (?:record|score|have|make|throw) at least (\d+)", m.get("question") or "")
    if mm:
        name, n = mm.group(1), n if n is not None else float(mm.group(2))
    else:
        mm = re.match(r"^(.+?) (\d+)\+ ", (m.get("title") or "") + " ")
        if mm:
            name, n = mm.group(1), n if n is not None else float(mm.group(2))
    if not name or n is None or abs(n - round(n)) > 1e-6:
        return None
    info.update({"ptype": m.get("sportsMarketType"), "player": name, "n": int(round(n)), "title": m.get("title")})
    return info


def prop_index(infos):
    """(type, full name, N) -> info, plus a looser (type, last name, first initial, N) index used only when unique."""
    exact, loose = {}, defaultdict(list)
    for i in infos:
        t = tokens(i["player"])
        if not t:
            continue
        exact[(i["ptype"], " ".join(t), i["n"])] = i
        loose[(i["ptype"], t[-1], t[0][:1], i["n"])].append(i)
    return exact, loose


def prop_lookup(idx, kp):
    exact, loose = idx
    t = tokens(kp["name"])
    if not t:
        return None
    hit = exact.get((kp["ptype"], " ".join(t), kp["n"]))
    if hit:
        return hit
    cands = loose.get((kp["ptype"], t[-1], t[0][:1], kp["n"])) or []
    return cands[0] if len(cands) == 1 else None


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
        # soccer: win / draw / win are three yes-no markets on both sites. Pair each one with its own opposite:
        # Kalshi "Arsenal wins" Yes + Polymarket "Arsenal wins" No, and the reverse. (Never "No on the other team":
        # with a draw possible, that isn't the same bet.)
        if pg.get("ml3") and len(kg["ml"]) == 2 and kg.get("tie"):
            outcomes = [(kg["ml"][c], pg["ml3"].get(assign[c]), f"{names[c]} wins", f"{names[c]} doesn't win") for c in codes]
            outcomes.append((kg["tie"], pg["ml3"].get("draw"), "Draw", "No draw"))
            for kq, info, yes_lab, no_lab in outcomes:
                if not kq or not info:
                    continue
                pq = quotes.get(info["slug"]) or info["quote"]
                for kleg, klab, pside, plab in ((k_buy_yes(kq), yes_lab, "short", no_lab),
                                                (k_buy_no(kq), no_lab, "long", yes_lab)):
                    if not kleg:
                        continue
                    note("Moneyline", kleg[0], pm_buy(pq, pside), info["fee"])
                    r = combo(lg, "Moneyline", None, kg, pg, (kleg[0], kleg[1], kleg[2], kq, klab),
                              (pm_buy(pq, pside), pside, info, plab, pq), start)
                    if r:
                        r["p"]["btn"] = "Yes" if pside == "long" else "No"
                        r["p"]["means"] = plab
                        found.append(r)
        # both teams to score (soccer)
        if kg.get("btts") and pg.get("btts"):
            kq, info = kg["btts"], pg["btts"]
            pq = quotes.get(info["slug"]) or info["quote"]
            for kleg, klab, pside, plab in ((k_buy_yes(kq), "Both teams score", "short", "Not both teams score"),
                                            (k_buy_no(kq), "Not both teams score", "long", "Both teams score")):
                if not kleg:
                    continue
                note("Both teams to score", kleg[0], pm_buy(pq, pside), info["fee"])
                r = combo(lg, "Both teams to score", None, kg, pg, (kleg[0], kleg[1], kleg[2], kq, klab),
                          (pm_buy(pq, pside), pside, info, plab, pq), start)
                if r:
                    r["p"]["btn"] = "Yes" if pside == "long" else "No"
                    r["p"]["means"] = plab
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
        # player props: Kalshi "X: N+" Yes + Polymarket "X at least N" No, and the reverse
        idx = pg.get("props")
        for kp in kg.get("props") or []:
            if not idx:
                break
            info = prop_lookup(idx, kp)
            if not info:
                continue
            STATS["prop_matches"]["pairs"] += 1
            kq, n, who, what = kp["q"], kp["n"], kp["name"], kp["label"].lower()
            yes_lab, no_lab = f"{who} {n}+ {what}", f"{who} under {n} {what}"
            pq = quotes.get(info["slug"]) or info["quote"]
            for kleg, klab, pside, plab in ((k_buy_yes(kq), yes_lab, "short", no_lab),
                                            (k_buy_no(kq), no_lab, "long", yes_lab)):
                if not kleg:
                    continue
                note("Player prop", kleg[0], pm_buy(pq, pside), info["fee"])
                r = combo(lg, "Player prop", f"{kp['label']} {n}+", kg, pg, (kleg[0], kleg[1], kleg[2], kq, klab),
                          (pm_buy(pq, pside), pside, info, plab, pq), start)
                if r:
                    r["p"]["btn"] = "Yes" if pside == "long" else "No"
                    r["p"]["means"] = plab
                    r["note"] = PROP_NOTE
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

        # player props: Kalshi lists them for games in the next day or two; Polymarket US only shows them on the
        # full event, so those games are fetched whole (that also brings every spread and total line)
        prop_keys = {(kg["league"], kg["key"]) for kg, _, _ in pairs if LEAGUES[kg["league"]]["props"]}
        kprops = kalshi_props(prop_keys) if prop_keys else {}
        full_for = [(kg, pg) for kg, pg, _ in pairs if kprops.get((kg["league"], kg["key"]))]
        with ThreadPoolExecutor(max_workers=6) as ex:
            full = dict(zip([pg["slug"] for _, pg in full_for], ex.map(pm_event_markets, [pg["slug"] for _, pg in full_for])))
        log(f"polymarket: fetched {len(full)} full events for props ({sum(len(v) for v in full.values())} markets)")

        want = []
        for kg, pg, _ in pairs:
            kg["props"] = kprops.get((kg["league"], kg["key"])) or []
            base = pg["slug"]
            if pg["slug"] in full:
                continue
            if pg["ml"]:
                want.append(pg["ml"]["slug"])
            want += [i["slug"] for i in pg["ml3"].values()]
            for x in sorted({x for _, x, q in kg["spread"] if live(q)}):
                want += [f"asc-{base}-pos-{slug_num(x)}", f"asc-{base}-neg-{slug_num(x)}"]
            for t in sorted({t for t, q in kg["total"] if live(q)}):
                want.append(f"tsc-{base}-{slug_num(t)}")
            if kg.get("btts"):
                want.append(f"astatc-{base}-btts")
        markets = pm_markets_by_slug(want)
        for ms in full.values():
            for m in ms:
                markets[m.get("slug")] = m
        result["p_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        quotes = {}
        n_pm_props = 0
        for kg, pg, _ in pairs:
            base = pg["slug"]
            if base in full:
                infos = [i for i in (pm_prop(m) for m in full[base]) if i]
                pg["props"] = prop_index(infos) if infos else None
                n_pm_props += len(infos)
                for i in infos:
                    quotes[i["slug"]] = i["quote"]
            bm = markets.get(f"astatc-{base}-btts")
            if bm:
                pg["btts"] = pm_info(bm)
                if pg["btts"]:
                    quotes[bm["slug"]] = pg["btts"]["quote"]
            for info in pg["ml3"].values():
                m = markets.get(info["slug"])
                quotes[info["slug"]] = (quote_val(m.get("bestBidQuote")), quote_val(m.get("bestAskQuote"))) if m else info["quote"]
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
        top = opps[:200]
        slugs_top = list(dict.fromkeys(o["p"]["slug"] for o in top))
        with ThreadPoolExecutor(max_workers=6) as ex:
            qty = dict(zip(slugs_top, ex.map(pm_top_qty, slugs_top)))
        for o in top:
            bq, aq = qty.get(o["p"]["slug"], (None, None))
            size = aq if o["p"]["side"] == "long" else bq
            o["p"]["size"] = size if size and size > 0 else None
        counts = {}
        for lg in LEAGUES:
            c = {"kalshi": sum(1 for g in kgames if g["league"] == lg),
                 "poly": sum(1 for g in pgames if g["league"] == lg),
                 "matched": sum(1 for kg, _, _ in pairs if kg["league"] == lg)}
            if any(c.values()):
                counts[lg] = c
        leagues = {lg: {"label": c["label"], "group": c["group"]} for lg, c in LEAGUES.items()}
        log(f"props: Kalshi {sum(len(v) for v in kprops.values())} on {len(kprops)} games, Polymarket {n_pm_props}, "
            f"matched {STATS['prop_matches']['pairs']}")
        STATS.pop("prop_matches", None)
        result.update({"ok": True, "opps": top, "counts": counts, "leagues": leagues, "n_arbs": sum(1 for o in opps if o["per"] < 1),
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
