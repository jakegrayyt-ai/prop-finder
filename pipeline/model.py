"""Projection and probability model for player props.

The idea, in plain terms:
  1. Estimate tonight's average for the stat from this season (recent games
     weigh more), pulled toward last season while the sample is small.
  2. Nudge it for context: opponent defense vs the position, home/away,
     the game's betting total and rest. Every nudge is small and capped.
  3. Turn that average into a probability of reaching the Kalshi line using a
     distribution that fits the stat (counts vs yards).
  4. Compare to the Kalshi price after Kalshi's fee.
"""
import math

from scipy import stats as st

HALF_LIFE = {"nba": 10.0, "nhl": 12.0, "nfl": 4.0}      # games until a game's weight halves
PRIOR_GAMES = {"nba": 8.0, "nhl": 10.0, "nfl": 4.0}     # how many "games" last season is worth
VAR_PSEUDO = 10.0                                       # pseudo-games for the spread prior

# Typical game-to-game coefficient of variation, used to stabilise small samples.
CV_PRIOR = {
    "pts": 0.33, "reb": 0.42, "ast": 0.48, "3pm": 0.70, "pra": 0.27, "pr": 0.31, "pa": 0.32,
    "ra": 0.37, "stl": 0.85, "blk": 0.95, "tov": 0.60, "fgm": 0.35, "ftm": 0.60,
    "pass_yds": 0.28, "pass_tds": 0.75, "pass_att": 0.20, "pass_cmp": 0.22, "ints": 1.10,
    "rush_yds": 0.55, "rush_att": 0.35, "rush_tds": 1.40, "rec": 0.45, "rec_yds": 0.62,
    "rec_tds": 1.80, "tds": 1.20, "rush_rec_yds": 0.45, "pass_rush_yds": 0.28, "targets": 0.40,
    "goals": 1.60, "assists": 1.20, "points": 0.95, "sog": 0.55, "saves": 0.25, "ga": 0.55,
    "blocked": 0.90, "hits": 0.70, "ppp": 1.80, "pim": 1.5,
}
CONTINUOUS = {"pass_yds", "rush_yds", "rec_yds", "rush_rec_yds", "pass_rush_yds"}

# How strongly each context factor is allowed to move the projection.
OPP_WEIGHT = 0.5
HOME_WEIGHT = 0.25
TOTAL_WEIGHT = {"scoring": 0.5, "other": 0.25}
SCORING_STATS = {"pts", "pra", "pr", "pa", "3pm", "fgm", "pass_yds", "pass_tds", "rec_yds", "rec_tds",
                 "rush_yds", "rush_tds", "tds", "rush_rec_yds", "pass_rush_yds", "goals", "assists",
                 "points", "rec"}
B2B_FACTOR = {"nba": 0.97, "nhl": 0.98}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def weighted_mean_var(vals, half_life):
    """vals most-recent-first. Returns (mean, var, n_eff)."""
    if not vals:
        return None, None, 0.0
    w = [0.5 ** (i / half_life) for i in range(len(vals))]
    sw = sum(w)
    m = sum(wi * v for wi, v in zip(w, vals)) / sw
    var = sum(wi * (v - m) ** 2 for wi, v in zip(w, vals)) / sw
    n_eff = sw * sw / sum(wi * wi for wi in w)
    if n_eff > 1:
        var *= n_eff / (n_eff - 1)  # small-sample correction
    return m, var, n_eff


def base_projection(cur_vals, prev_vals, league, stat):
    """Return dict(mu, var, n_cur, n_prev) or None if no data."""
    hl = HALF_LIFE.get(league, 10.0)
    m_cur, v_cur, ne_cur = weighted_mean_var(cur_vals, hl)
    m_prev = sum(prev_vals) / len(prev_vals) if prev_vals else None
    v_prev = (sum((x - m_prev) ** 2 for x in prev_vals) / max(1, len(prev_vals) - 1)) if prev_vals and len(prev_vals) > 1 else None

    k = PRIOR_GAMES.get(league, 8.0)
    if m_cur is not None and m_prev is not None:
        n = len(cur_vals)
        mu = (n * m_cur + k * m_prev) / (n + k)
    elif m_cur is not None:
        mu = m_cur
    elif m_prev is not None:
        mu = m_prev
    else:
        return None

    # pooled spread, then pulled toward the typical spread for this stat
    num, den = 0.0, 0.0
    if v_cur is not None and ne_cur > 1:
        num += v_cur * ne_cur
        den += ne_cur
    if v_prev is not None:
        wprev = min(len(prev_vals), 30) * 0.5
        num += v_prev * wprev
        den += wprev
    cv = CV_PRIOR.get(stat, 0.5)
    var_prior = (cv * max(mu, 0.05)) ** 2
    var = (num + VAR_PSEUDO * var_prior) / (den + VAR_PSEUDO)
    return {"mu": mu, "var": var, "n_cur": len(cur_vals), "n_prev": len(prev_vals or [])}


def context_factors(league, stat, opp_ratio=None, home_ratio=None, total_ratio=None, back_to_back=False):
    """Each *_ratio is (situation average / overall average). Returns list of (label, factor)."""
    out = []
    if opp_ratio:
        out.append(("Matchup", clamp(1 + OPP_WEIGHT * (opp_ratio - 1), 0.88, 1.12)))
    if home_ratio:
        out.append(("Home/away", clamp(1 + HOME_WEIGHT * (home_ratio - 1), 0.96, 1.04)))
    if total_ratio:
        w = TOTAL_WEIGHT["scoring" if stat in SCORING_STATS else "other"]
        out.append(("Game total", clamp(1 + w * (total_ratio - 1), 0.93, 1.07)))
    if back_to_back and league in B2B_FACTOR:
        out.append(("Back-to-back", B2B_FACTOR[league]))
    return out


def prob_at_least(mu, var, threshold, stat):
    """P(stat >= threshold)."""
    if mu is None:
        return None
    if stat in CONTINUOUS:
        mu_pos = max(mu, 1.0)
        var = max(var, 1.0)
        shape = mu_pos * mu_pos / var
        scale = var / mu_pos
        p = st.gamma.sf(threshold - 0.5, shape, scale=scale)
    else:
        if mu <= 0:
            return 0.0 if threshold > 0 else 1.0
        k = math.ceil(threshold) - 1  # P(X >= t) = 1 - CDF(t-1)
        if var <= mu * 1.02:
            p = st.poisson.sf(k, mu)
        else:
            r = mu * mu / (var - mu)
            p = st.nbinom.sf(k, r, r / (r + mu))
    return float(clamp(p, 0.01, 0.99))


def kalshi_fee(price, multiplier=1.0):
    """Approximate taker fee per $1 contract (Kalshi: 0.07 x P x (1-P), rounded up per order)."""
    if price is None:
        return None
    return 0.07 * (multiplier or 1.0) * price * (1 - price)


def edges(p_model, yes_ask, no_ask, fee_mult=1.0):
    """Expected profit per contract (in dollars, = probability points) for each side."""
    out = {}
    if p_model is None:
        return out
    if yes_ask and 0 < yes_ask < 1:
        out["yes"] = p_model - yes_ask - kalshi_fee(yes_ask, fee_mult)
    if no_ask and 0 < no_ask < 1:
        out["no"] = (1 - p_model) - no_ask - kalshi_fee(no_ask, fee_mult)
    return out
