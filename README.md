# Prop Finder

A research board for **Kalshi player props** in the NBA, NFL and NHL. For every open prop it shows the Kalshi price next to the player's history: hit rates over the last 5, 10 and 20 games, this season, last season, against tonight's opponent and at home or away, plus the current streak, a matchup rating and a stats-based estimate of the edge after Kalshi's fee.

**Live site:** https://jakegrayyt-ai.github.io/prop-finder/

## How it works

A GitHub Actions job (`.github/workflows/update.yml`) runs about every 20 minutes:

1. **Kalshi** (public market data, no account or API key). It reads every open market in the standard player-prop series: NBA points, rebounds, assists, threes, PRA, steals, blocks, steals + blocks, double-doubles and triple-doubles. NFL passing, rushing and receiving yards, receptions, touchdowns, passing TDs, completions, attempts, interceptions and longest plays. NHL goals, points, assists and goalie saves.
2. **ESPN** (public JSON, also one of Kalshi's settlement sources). It pulls rosters, schedules with betting totals, injury reports, each player's game log for this season and last season, and every finished box score this season. The box scores feed the opponent-defense numbers.
3. **The model** (`pipeline/model.py`) estimates tonight's average for the stat. It weights recent games more and pulls toward last season while the sample is small. Then it nudges for matchup, home or away, the betting total and back-to-backs, and turns that into a chance of reaching the line.
4. **The edge** compares that to Kalshi's price after the fee (0.07 × price × (1 − price) per contract). Kalshi's price is treated as a strong prior, so the model only moves it part of the way. When a liquid market and the model disagree by more than 15 points, the prop is flagged **Check news**, and the edge stays close to the market. A gap that size usually means an injury or lineup change the box scores don't show yet.
5. The results are written to `site/data/` and published to the `gh-pages` branch, which GitHub Pages serves.

## Reading the board

| Column | Meaning |
|---|---|
| Line | Kalshi's threshold. `25+` means 25 or more. |
| Kalshi | What a Yes or No contract costs right now (pays $1 if it wins). |
| Last 10 | One bar per game. Green bars reached the line, red bars didn't. The dashed line is the threshold. |
| L5 / L10 / L20 | Hit rate over the player's most recent games. These can include last season early in the year. |
| Season, H2H, Home/Away | Hit rate this season, against tonight's opponent, and at tonight's venue. |
| Streak | `+3` means he hit his last 3 games, `−2` means he missed his last 2. |
| Model | The stats-only chance of hitting, next to what Kalshi's price implies. |
| Edge | Expected profit per $1 contract after the fee, for the better side. The bars show confidence (sample size, liquidity, injuries, role changes). |

Hit rates are colored **against the price**, not against 50%. A 60% hit rate on a line priced at 75¢ shows red, because the player clears it less often than the market expects.

## Honest limits

- The data refreshes about every 20 minutes. Always check the live price on Kalshi before trading.
- The model only knows box scores. It doesn't know about an injured teammate, a new starter or a blowout risk. Kalshi's traders often do.
- Small samples (early season, rookies, players who changed teams) are noisy. Those props are marked low confidence.
- If a player doesn't play, Kalshi settles the market at a fair price instead of Yes or No.
- Nothing here guarantees a result. It's a research tool, not advice.

## Running it

- **Run now:** Actions tab → `update` → **Run workflow**.
- **Schedule paused?** GitHub pauses scheduled jobs in public repos after 60 days without commits. Open the Actions tab and click **Enable workflow**, or push any commit.
- **Locally:** `pip install -r requirements.txt && python -m pipeline.build`, then serve the `site/` folder (`python -m http.server -d site`).

## Files

```
pipeline/kalshi.py     Kalshi prop markets -> player, stat, line, prices
pipeline/espn.py       ESPN rosters, schedules, injuries, game logs, box scores
pipeline/matchups.py   opponent defense vs position from this season's box scores
pipeline/stats.py      hit rates, splits, streaks
pipeline/model.py      projection, probability, Kalshi fee and edge
pipeline/build.py      ties it together and writes site/data/
site/                  the website (plain HTML, CSS and JavaScript)
```
