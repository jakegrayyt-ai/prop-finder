# Prop Finder

A research board for **Kalshi player props and team bets** in the NBA, NFL and NHL. For every open market it shows the Kalshi price next to the history: hit rates over the last 5, 10 and 20 games, this season, last season, against tonight's opponent and at home or away, plus the current streak, a matchup rating and a stats-based estimate of the edge after Kalshi's fee.

**Live site:** https://jakegrayyt-ai.github.io/prop-finder/

## How it works

A GitHub Actions job (`.github/workflows/update.yml`) is scheduled every 10 minutes. GitHub runs scheduled jobs when it has room, so in practice updates land every 10 to 60 minutes:

1. **Kalshi** (public market data, no account or API key). It reads every open market in the standard player-prop series: NBA points, rebounds, assists, threes, PRA, steals, blocks, steals + blocks, double-doubles and triple-doubles. NFL passing, rushing and receiving yards, receptions, touchdowns, passing TDs, completions, attempts, interceptions and longest plays. NHL goals, points, assists and goalie saves.
   Team bets too: moneylines, spreads ("Boston wins by over 8.5"), game totals and team totals.
2. **ESPN** (public JSON, also one of Kalshi's settlement sources). It pulls rosters, schedules with betting totals, injury reports, each player's game log for this season and last season, and every finished box score this season. The box scores feed the opponent-defense numbers.
3. **The model** (`pipeline/model.py`) estimates tonight's average for the stat. It weights recent games more and pulls toward last season while the sample is small. Then it nudges for matchup, home or away, the betting total and back-to-backs, and turns that into a chance of reaching the line.
4. **The edge** compares that to Kalshi's price after the fee (0.07 × price × (1 − price) per contract). Kalshi's price is treated as a strong prior, so the model only moves it part of the way. When a liquid market and the model disagree by more than 15 points, the prop is flagged **Check news**, and the edge stays close to the market. A gap that size usually means an injury or lineup change the box scores don't show yet.
5. The results are written to `site/data/` and published to the `gh-pages` branch, which GitHub Pages serves.

## Arbitrage page

**https://jakegrayyt-ai.github.io/prop-finder/arb.html**

Every scan, `pipeline/arb.py` lists the next 6 days of games on both **Kalshi** and **Polymarket US** (the US-regulated app, not polymarket.com), for every sport both sites list:

- NFL, NBA, NHL, college football, men's and women's college basketball
- About 50 soccer leagues (Champions League, Premier League, La Liga, Serie A, Bundesliga, Ligue 1, MLS, Brasileirão and many smaller ones)
- ATP, WTA, ITF and doubles tennis, UFC and boxing
- Esports (CS2, Dota 2, League of Legends, Rainbow Six)
- Basketball, hockey, baseball and cricket leagues outside the US (EuroLeague, CBA, KHL, AHL, KBO and others)

It matches the same game on both sites by date and team or player names. US teams must match their school or city exactly, so Kentucky never pairs with Western Kentucky. Clubs abroad match on their distinctive words ("Everton" = "Everton FC"), and both teams have to match. Then it prices every pair of opposite bets:

- Moneyline: Team A on one site + Team B on the other. Soccer is win, draw or win on both sites, so each outcome is paired with its own opposite (Arsenal wins on one site, Arsenal doesn't win on the other)
- Spread and total, for the full game and the first half: Team A −X + Team B +X, Over T + Under T (the same X or T only)
- Team totals, both teams to score
- NBA, NFL and NHL player props: Kalshi's "Jaylen Brown: 25+ points" against Polymarket's "at least 25 points". If the player doesn't play, the sites may settle differently

Polymarket's best bid or ask is often a dust order (a hundredth of a contract) that can't be traded, so each candidate is priced at what 1 full contract costs on the real order book, and pairs without 1 contract are dropped.

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

## Team bets

Kalshi's moneylines, spreads, game totals and team totals sit on the same board (pick **Team bets** under *Bets* to see only them). They work like props:

- **The line.** `−8.5` is Kalshi's "wins by over 8.5", so yes needs a win by 9 or more and no is the other side +8.5. `O 112.5` is a team or game total of 113 or more. `Win` is the moneyline.
- **Hit rates** come from the team's final scores this season and last season. A game total uses both teams' games, a meeting between them counted once, and its *Venue* split is the home team at home plus the away team on the road. Margin bars hang below zero for losses.
- **The model** (`pipeline/teams.py`) rates every team's scoring and defense, adjusted for the teams it played. Recent games count more, and early in the season it leans on last season. It projects both teams' scores tonight with a home edge, then turns them into a chance for each line: a bell curve around the projected margin, team score or total in the NBA and NFL, and Poisson goals in the NHL (a tie after regulation goes to overtime or a shootout, which adds a goal for the winner, as in the final score).
- **The edge** leans on Kalshi's price even harder than for props, because team markets are Kalshi's busiest. It leans harder still on long shots, where a simple score model is least reliable.
- **Injury report.** The drawer lists both teams' injuries from ESPN with each player's minutes and production this season from the box scores, and flags **Key player out** when a regular is out. A team's past results include games he played, so its trends can look better than tonight's lineup.
- Kalshi settles team bets on the final score, overtime included.

## Injuries

- **Games he left hurt.** If a player played far less than usual (under half his normal minutes in the NBA or ice time in the NHL; under 40% of his normal pass attempts, or carries plus targets, in the NFL) and then missed his team's next game or went on the injury report within a few days, that game is marked *left early hurt*. It's drawn grey, and it's left out of hit rates and the model. Whether he missed a game comes from both the box score and his game log. Short games without that evidence (foul trouble, ejections, blowouts) are noted but still count.
- **Missed games.** Players who missed their team's last game or games are flagged, and so are players who left their last game hurt. Both lower the confidence rating.
- **Today's injury report.** ESPN's status (Questionable, Doubtful, Out) shows next to the player and lowers confidence. Out players get no edge.
- All-Star games and exhibitions against teams outside the league are left out of the game logs.
- Kalshi still settles on the stats if a player plays at all, so an early injury exit is a loss there. The hit rates just don't let one fluky game drag down a healthy player's numbers.

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
pipeline/kalshi.py     Kalshi prop and team markets -> player or team, stat, line, prices
pipeline/espn.py       ESPN rosters, schedules, team schedules, injuries, game logs, box scores
pipeline/teams.py      team bets: results history, team ratings, projected scores, injury report
pipeline/matchups.py   opponent defense vs position from this season's box scores
pipeline/stats.py      hit rates, splits, streaks
pipeline/model.py      projection, probability, Kalshi fee and edge
pipeline/arb.py        Kalshi vs Polymarket US arbitrage scanner
pipeline/build.py      ties it together and writes site/data/
site/                  the website (plain HTML, CSS and JavaScript)
```
