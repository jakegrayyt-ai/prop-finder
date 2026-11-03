"""Games a player left early because he got hurt, and games he has missed since.

A game counts as "hurt" when he played far less than usual in it (minutes in the NBA, ice time in the NHL,
pass attempts for an NFL quarterback, carries plus targets for everyone else) AND there's evidence it was an
injury: he missed his team's next game(s), or he went on the injury report within a few days.

Short games without that evidence (foul trouble, an ejection, a blowout) are marked "short" and still count.
Hurt games are left out of hit rates and the model: a miss in a game he left in the first quarter says
nothing about tonight. (Kalshi still settles on the stats if he plays at all, so an early exit is a loss there.)
"""
import datetime as dt
from statistics import median

SHORT = {"nba": 0.5, "nhl": 0.5, "nfl": 0.4}           # under this share of his usual volume = a short game
FLOOR = {"nba": 16.0, "nhl": 10.0, "nfl_qb": 15.0, "nfl": 6.0}   # only for players with a real role
GAP_DAYS = {"nba": 8, "nhl": 8, "nfl": 20}             # last season (no box scores): a gap this long = missed time
UNIT = {"nba": "min", "nhl": "min", "nfl_qb": "pass attempts", "nfl": "carries + targets"}


def volume(league, g, qb=False):
    s = g.get("s") or {}
    if league == "nba":
        return s.get("min")
    if league == "nhl":
        return s.get("toi")
    if qb:
        return s.get("pass_att")
    if s.get("rush_att") is None and s.get("targets") is None:
        return None
    return (s.get("rush_att") or 0) + (s.get("targets") or 0)


def _d(x):
    try:
        return dt.date.fromisoformat((x or "")[:10])
    except ValueError:
        return None


def _n(x):
    return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"


def mark(league, games, team_games=None, aid=None, inj=None, qb=False, team_abbr=None):
    """Set g["inj"] on short games (most-recent-first list). Returns the number marked hurt.

    team_games: [(date, set of player ids who played, or None if that box score is missing)] for his current
        team's finished games this season, from the box scores. Whether he played comes from the box score,
        not his game log, so a game log ESPN hasn't updated yet can't look like a missed game.
    team_abbr: his current team, so games for a team he was traded from use the gap rule instead.
    inj: his current ESPN injury entry ({"status", "date", "type", ...}) or None."""
    key = "nfl_qb" if (league == "nfl" and qb) else league
    vols = [volume(league, g, qb) for g in games]
    logged = {g.get("date") for g in games}
    inj_date = _d((inj or {}).get("date"))
    inj_type = ((inj or {}).get("type") or "").strip().lower()
    hurt_n = 0
    for i, g in enumerate(games):
        g.pop("inj", None)
        v = vols[i]
        if v is None:
            continue
        near = sorted((j for j in range(len(games)) if j != i and vols[j] is not None and games[j].get("season") == g.get("season")),
                      key=lambda j: abs(j - i))[:10]
        if len(near) < 4:
            continue
        usual = median(vols[j] for j in near)
        if usual < FLOOR[key] or v >= SHORT[league] * usual:
            continue
        day = _d(g.get("date"))
        why = []
        same_team = not team_abbr or not g.get("team") or g.get("team") == team_abbr
        if team_games is not None and aid and g.get("season") == "cur" and same_team:
            missed = 0
            for date, who in team_games:
                if date <= g["date"]:
                    continue
                if who is None or aid in who or date in logged:   # missed only if neither source has him playing
                    break
                missed += 1
            if missed:
                why.append("missed the next game" if missed == 1 else f"missed the next {missed} games")
        elif i > 0 and not g.get("post") and not games[i - 1].get("post") and games[i - 1].get("season") == g.get("season"):
            nxt = _d(games[i - 1].get("date"))
            if nxt and day and (nxt - day).days > GAP_DAYS[league]:
                why.append(f"didn't play again for {(nxt - day).days} days")
        if inj_date and day and 0 <= (inj_date - day).days <= 5:
            why.append("went on the injury report" + (f" ({inj_type})" if inj_type else ""))
        hurt = bool(why)
        hurt_n += hurt
        unit = UNIT[key]
        g["inj"] = {"kind": "hurt" if hurt else "short", "vol": round(v, 1), "usual": round(usual, 1),
                    "why": (f"Left early hurt: {_n(v)} {unit} (usually {_n(usual)}), then " + " and ".join(why) + "."
                            if hurt else f"Short game: {_n(v)} {unit} (usually {_n(usual)}). Still counted.")}
    return hurt_n


def is_hurt(g):
    return (g.get("inj") or {}).get("kind") == "hurt"


def missed_since(team_games, aid, before, games=()):
    """His team's finished games since he last played, before tonight's date. A game counts as missed only when
    neither the box score nor his game log has him in it (NFL box scores skip players with no stats)."""
    if not team_games or not aid:
        return 0
    logged = {g.get("date") for g in games}
    seen = [date for date, who in team_games if date < before and ((who and aid in who) or date in logged)]
    if not seen:
        return 0          # hasn't played for this team this season: "first game" and "long layoff" cover that
    return sum(1 for date, who in team_games
               if seen[-1] < date < before and who is not None and aid not in who and date not in logged)
