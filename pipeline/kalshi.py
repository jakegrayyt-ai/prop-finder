"""Read open player-prop markets from Kalshi's public API (no account needed)."""
import datetime as dt
import re
import time

from .net import get_json

BASES = [
    "https://api.elections.kalshi.com/trade-api/v2",
    "https://external-api.kalshi.com/trade-api/v2",
]

# series ticker -> (league, stat key, label). Only standard "X+" binary markets:
# the Protected / Ladder / Escalator products pay out differently and are skipped.
SERIES = {
    "KXNBAPTS": ("nba", "pts", "Points"),
    "KXNBAREB": ("nba", "reb", "Rebounds"),
    "KXNBAAST": ("nba", "ast", "Assists"),
    "KXNBA3PT": ("nba", "3pm", "Threes"),
    "KXNBAPRA": ("nba", "pra", "Pts + Reb + Ast"),
    "KXNBASTL": ("nba", "stl", "Steals"),
    "KXNBABLK": ("nba", "blk", "Blocks"),
    "KXNBASTOCK": ("nba", "stocks", "Steals + Blocks"),
    "KXNBA2D": ("nba", "dd", "Double-double"),
    "KXNBA3D": ("nba", "td3", "Triple-double"),
    "KXNFLPASSYDS": ("nfl", "pass_yds", "Passing yards"),
    "KXNFLPASSTDS": ("nfl", "pass_tds", "Passing TDs"),
    "KXNFLPASSCOMP": ("nfl", "pass_cmp", "Completions"),
    "KXNFLPASSATT": ("nfl", "pass_att", "Pass attempts"),
    "KXNFLPASSINT": ("nfl", "ints", "Interceptions"),
    "KXNFLRSHYDS": ("nfl", "rush_yds", "Rushing yards"),
    "KXNFLRSHATT": ("nfl", "rush_att", "Rush attempts"),
    "KXNFLRECYDS": ("nfl", "rec_yds", "Receiving yards"),
    "KXNFLREC": ("nfl", "rec", "Receptions"),
    "KXNFLRRYDS": ("nfl", "rush_rec_yds", "Rush + rec yards"),
    "KXNFLTD": ("nfl", "tds", "Touchdowns"),
    "KXNFLLONGREC": ("nfl", "rec_long", "Longest reception"),
    "KXNFLLONGRSH": ("nfl", "rush_long", "Longest rush"),
    "KXNHLGOAL": ("nhl", "goals", "Goals"),
    "KXNHLPTS": ("nhl", "points", "Points"),
    "KXNHLAST": ("nhl", "assists", "Assists"),
    "KXNHLSAVE": ("nhl", "saves", "Saves"),
}

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
EVENT_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def price(mk, key):
    """Kalshi now sends prices as dollar strings ("0.5400"); older fields were cents."""
    v = _f(mk.get(key + "_dollars"))
    if v is None:
        c = _f(mk.get(key))
        v = c / 100 if c is not None else None
    return v


def qty(mk, key):
    v = _f(mk.get(key + "_fp"))
    return v if v is not None else _f(mk.get(key))


def parse_event(event_ticker):
    """'KXNBAPTS-26NOV02ATLIND' -> (date(2026,11,2), 'ATLIND')."""
    part = event_ticker.split("-", 1)[1] if "-" in event_ticker else event_ticker
    m = EVENT_RE.match(part)
    if not m:
        return None, None
    yy, mon, dd, teams = m.groups()
    try:
        d = dt.date(2000 + int(yy), MONTHS[mon], int(dd))
    except (KeyError, ValueError):
        d = None
    return d, teams


def split_teams(teams, player_code):
    """Split 'CGYSJ' using the player code 'SJSDICKINSON6' -> ('CGY', 'SJ', 'SJ')."""
    best = None
    for i in range(2, len(teams) - 1):
        a, b = teams[:i], teams[i:]
        if not (2 <= len(a) <= 4 and 2 <= len(b) <= 4):
            continue
        for team in (a, b):
            if player_code.startswith(team):
                # most team codes are 3 letters; prefer the split closest to 3+3
                score = (-abs(len(a) - 3) - abs(len(b) - 3), len(team))
                if best is None or score > best[0]:
                    best = (score, a, b, team)
    if best:
        return best[1], best[2], best[3]
    return None, None, None


def fetch_series(base, series):
    out, cursor = [], None
    for _ in range(10):
        params = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        d = get_json(base + "/markets", params=params)
        page = d.get("markets") or []
        out.extend(page)
        cursor = d.get("cursor")
        if not cursor or len(page) < 1000:
            break
        time.sleep(0.05)
    return out


def parse_market(series, mk):
    league, stat, label = SERIES[series]
    sub = (mk.get("yes_sub_title") or mk.get("title") or "").strip()
    name = sub.rsplit(":", 1)[0].strip() if ":" in sub else sub
    fs = _f(mk.get("floor_strike"))
    if mk.get("strike_type") not in ("greater", None) or fs is None or not name:
        return None
    line = int(fs // 1) + 1  # "greater than 24.5" -> 25+
    event = mk.get("event_ticker", "")
    date, teams = parse_event(event)
    parts = (mk.get("ticker") or "").split("-")
    pcode = parts[2] if len(parts) >= 3 else ""
    away = home = team = None
    if teams:
        away, home, team = split_teams(teams, pcode)
    jersey = None
    m = re.search(r"(\d+)$", pcode)
    if m:
        jersey = m.group(1)
    yes_bid, yes_ask = price(mk, "yes_bid"), price(mk, "yes_ask")
    no_bid, no_ask = price(mk, "no_bid"), price(mk, "no_ask")
    return {
        "series": series, "league": league, "stat": stat, "stat_label": label,
        "ticker": mk.get("ticker"), "event": event, "player_name": name, "line": line,
        "date": date.isoformat() if date else None, "k_away": away, "k_home": home, "k_team": team,
        "jersey": jersey, "title": mk.get("title"),
        "yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask,
        "last": price(mk, "last_price"), "volume": qty(mk, "volume"), "vol24": qty(mk, "volume_24h"),
        "oi": qty(mk, "open_interest"), "close_time": mk.get("close_time"),
        "occurs": mk.get("occurrence_datetime") or mk.get("expected_expiration_time"),
    }


SLUGS = {'KXNBAPTS': 'nba-player-points',
    'KXNBAREB': 'nba-player-rebounds',
    'KXNBAAST': 'nba-player-assists',
    'KXNBA3PT': 'nba-player-threes',
    'KXNBAPRA': 'nba-player-points-rebounds-assists',
    'KXNBASTL': 'nba-player-steals',
    'KXNBABLK': 'nba-player-blocks',
    'KXNBASTOCK': 'nba-player-steals-blocks',
    'KXNBA2D': 'nba-player-double-double',
    'KXNBA3D': 'nba-player-triple-double',
    'KXNFLPASSYDS': 'pro-football-passing-yards',
    'KXNFLPASSTDS': 'pro-football-player-passing-touchdowns',
    'KXNFLPASSCOMP': 'pro-football-passing-completions',
    'KXNFLPASSATT': 'pro-football-passing-attempts',
    'KXNFLPASSINT': 'pro-football-passing-interceptions',
    'KXNFLRSHYDS': 'pro-football-rushing-yards',
    'KXNFLRSHATT': 'pro-football-rushing-attempts',
    'KXNFLRECYDS': 'pro-football-receiving-yards',
    'KXNFLREC': 'pro-football-player-receptions',
    'KXNFLRRYDS': 'pro-football-rush-and-receiving-yards',
    'KXNFLTD': 'pro-football-touchdowns',
    'KXNFLLONGREC': 'longest-reception',
    'KXNFLLONGRSH': 'longest-rush',
    'KXNHLGOAL': 'nhl-goalscorer',
    'KXNHLPTS': 'pro-hockey-points',
    'KXNHLAST': 'pro-hockey-assists',
    'KXNHLSAVE': 'goaltender-saves'}


def market_url(series, event):
    slug = SLUGS.get(series, "event")
    return f"https://kalshi.com/markets/{series.lower()}/{slug}/{event.lower()}"


def load_props(log):
    """Return (props, base_used, series_counts)."""
    base = None
    for b in BASES:
        try:
            get_json(b + "/exchange/status")
            base = b
            break
        except Exception as e:  # noqa: BLE001
            log(f"kalshi base unavailable {b}: {e!r}"[:200])
    if base is None:
        base = BASES[0]
    props, counts = [], {}
    for series in SERIES:
        try:
            mks = fetch_series(base, series)
        except Exception as e:  # noqa: BLE001
            log(f"kalshi {series} failed: {e!r}"[:200])
            continue
        n = 0
        for mk in mks:
            if mk.get("status") not in ("active", "open", None):
                continue
            p = parse_market(series, mk)
            if p:
                props.append(p)
                n += 1
        counts[series] = n
    return props, base, counts
