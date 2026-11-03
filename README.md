# Prop Finder

A research board for **Kalshi player props** in the NBA, NFL and NHL. For every open prop it shows the Kalshi price next to the player's history: hit rates over the last 5, 10 and 20 games, this season, last season, against tonight's opponent and at home or away, plus the current streak, a matchup rating and a stats-based estimate of the edge after Kalshi's fee.

**Live site:** https://jakegrayyt-ai.github.io/prop-finder/

## How it works

A GitHub Actions job (`.github/workflows/update.yml`) is scheduled every 10 minutes. GitHub runs scheduled jobs when it has room, so in practice updates land every 10 to 60 minutes:

1. **Kalshi** (public market data, no account or API key). It reads every open market in the standard player-prop series: NBA points, rebounds, assists, threes, PRA, steals, blocks, steals + blocks, double-doubles and triple-doubles. NFL passing, rushing and receiving yards, receptions, touchdowns, passing TDs, completions, attempts, interceptions and longest plays. NHL goals, points, assists and goalie saves.
2. **ESPN** (public JSON, also one of Kalshi's settlement sources). It pulls rosters, schedules with betting totals, injury reports, each player's game log for this season and last season, and every finished box score this season. The box scores feed the opponent-defense numbers.
3. **The model** (`pipeline/model.py`) estimates tonight's average for the stat. It weights recent games more and pulls toward last season while the sample is small. Then it nudges for matchup, home or away, the betting total and back-to-backs, and turns that into a chance of reaching the line.
4. **The edge** compares that to Kalshi's price after the fee (0.07 × price × (1 − price) per contract). Kalshi's price is treated as a strong prior, so the model only moves it part of the way. When a liquid market and the model disagree by more than 15 points, the prop is flagged **Check news**, and the edge stays close to the market. A gap that size usually means an injury or lineup change the box scores don't show yet.
5. The results are written to `site/data/` and published to the `gh-pages` branch, which GitHub Pages serves.

## Arbitrage page

**https://jakegrayyt-ai.github.io/prop-finder/arb.html**

Every scan, `pipeline/arb.py` lists the next 6 days of NFL, NBA, NHL, college football, men's college basketball and ATP/WTA tennis games on both **Kalshi** and **Polymarket US** (the US-regulated app, not polymarket.com). It matches the same game on both sites by date and exact school or city name, so Kentucky never pairs with Western Kentucky. Then it prices every pair of opposite bets:

- Moneyline: Team A on one site + Team B on the other
- Spread: Team A −X on one site + Team B +X on the other (the same X only)
- Total: Over T on one site + Under T on the other (the same T only)

A pair is an **arbitrage** when both prices plus both taker fees come to less than $1 per contract. Kalshi's fee is 0.07 × price × (1 − price). Polymarket US lists a fee rate on each market (0.0695 right now), applied the same way. Both round up per order. Games Polymarket US marks as live (or that start within 10 minutes) are skipped, and so are 1–2¢ longshots.

The page re-checks Polymarket US prices every 30 seconds (its API allows that from a browser). Kalshi's API refuses requests from other websites, so Kalshi prices come from the last scan. Because of that, a newer Polymarket price is only allowed to make a pair look worse, never better: if Polymarket moved, Kalshi probably did too. A pair is shown as arbitrage only when Kalshi's price is under 15 minutes old, Polymarket hasn't moved 2¢ or more since the scan, and there's at least 1 contract on each side. Otherwise it's marked *re-check* with the reason. Cards disappear 2 minutes before the start (20 minutes for tennis, whose start times are estimates).

Real arbitrage is rare. The two sites usually agree within a few cents, and the combined fee is about 3¢ at even odds. Before trading, check both live prices, the available size, and both sites' rules (NFL ties, tennis retirements and postponements can settle differently).

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

- The data refreshes every 10 to 60 minutes, depending on GitHub's scheduler. The time of the last update is at the top of each page. Always check the live price on Kalshi before trading.
- The model only knows box scores. It doesn't know about an injured teammate, a new starter or a blowout risk. Kalshi's traders often do.
- Small samples (early season, rookies, players who changed teams) are noisy. Those props are marked low confidence.
- If a player doesn't play, Kalshi settles the market at a fair price instead of Yes or No.
- Nothing here guarantees a result. It's a research tool, not advice.

## Running it

- **Run now:** Actions tab → `update` → **Run workflow**.
- **Schedule paused?** GitHub pauses scheduled jobs in public repos after 60 days without commits, so the job makes one small commit a month to prevent that. If it ever does pause, open the Actions tab and click **Enable workflow**.
- **Locally:** `pip install -r requirements.txt && python -m pipeline.build`, then serve the `site/` folder (`python -m http.server -d site`).

## Files

```
pipeline/kalshi.py     Kalshi prop markets -> player, stat, line, prices
pipeline/espn.py       ESPN rosters, schedules, injuries, game logs, box scores
pipeline/matchups.py   opponent defense vs position from this season's box scores
pipeline/stats.py      hit rates, splits, streaks
pipeline/model.py      projection, probability, Kalshi fee and edge
pipeline/arb.py        Kalshi vs Polymarket US arbitrage scanner
pipeline/build.py      ties it together and writes site/data/
site/                  the website (plain HTML, CSS and JavaScript)
```
