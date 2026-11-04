# Prop Finder

A research board for **Kalshi player props and team bets** in the NBA, NFL and NHL, plus the game markets for every other sport Kalshi lists (college football and basketball, soccer, tennis, UFC and boxing, esports, cricket and more). For every open market it shows the Kalshi price next to the history: hit rates over the last 5, 10 and 20 games, this season, last season, against tonight's opponent and at home or away, plus the current streak, a matchup rating and a stats-based estimate of the edge after Kalshi's fee.

**Live site:** https://jakegrayyt-ai.github.io/prop-finder/

## How it works

A GitHub Actions job (`.github/workflows/update.yml`) is scheduled every 10 minutes. GitHub runs scheduled jobs when it has room, so in practice updates land every 10 to 60 minutes:

1. **Kalshi** (public market data, no account or API key). It reads every open market in the standard player-prop series: NBA points, rebounds, assists, threes, PRA, steals, blocks, steals + blocks, double-doubles and triple-doubles. NFL passing, rushing and receiving yards, receptions, touchdowns, passing TDs, completions, attempts, interceptions and longest plays. NHL goals, points, assists and goalie saves.
   Team bets too: moneylines, spreads ("Boston wins by over 8.5"), game totals and team totals.
2. **ESPN** (public JSON, also one of Kalshi's settlement sources). It pulls rosters, schedules with betting totals, injury reports, each player's game log for this season and last season, and every finished box score this season. The box scores feed the opponent-defense numbers.
3. **The model** (`pipeline/model.py`) estimates tonight's average for the stat. It weights recent games more and pulls toward last season while the sample is small. Then it nudges for matchup, home or away, the betting total and back-to-backs, and turns that into a chance of reaching the line.
4. **The edge** compares that to Kalshi's price after the fee (0.07 × price × (1 − price) per contract). Kalshi's price is treated as a strong prior, so the model only moves it part of the way. When a liquid market and the model disagree by more than 15 points, the prop is flagged **Check news**, and the edge stays close to the market. A gap that size usually means an injury or lineup change the box scores don't show yet.
5. The results are written to `site/data/` and published to the `gh-pages` branch, which GitHub Pages serves.

## Picks page

**https://jakegrayyt-ai.github.io/prop-finder/picks.html**

The 10 best bets for today's games that haven't started, ranked by edge after Kalshi's fee: NBA, NFL and NHL player props and team bets, plus the game markets for tennis, esports, soccer, college and every other sport on the board. Tabs split it by sport (All, NBA, NFL, NHL, Tennis, Esports, Soccer, College, More), each with its own top 10. The All tab takes at most 4 from one sport.

A bet only makes the list if:

- its edge after the fee is positive (at least 0.1¢ per $1)
- the side you'd buy costs 20–80¢ (no long shots)
- its confidence is medium or high, with at least 10 contracts traded and a tight bid and ask
- for props and trend-model game bets, its last 10 games and this season agree with that side
- for winner markets rated with Elo, both sides have at least 8 rated results
- it has no injury tag, missed games, role change or "check news" flag

There's one line per player or team, one winner pick per game (yes on one side is the same bet as no on the other), and at most 3 picks per game. Each pick shows why (hit rates, ratings or model vs price, projection and matchup) and links to the full breakdown on the board. The list refreshes as prices move, and games drop off once they start.

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

## Every other sport

Kalshi only has player props for the NBA, NFL and NHL. For everything else it lists game markets, and the board shows all of them: winner (and draw in soccer), spread, game total, team total and both teams to score, for college football and basketball, about 60 soccer leagues, tennis, UFC and boxing, esports, cricket, and basketball, hockey, football and baseball leagues abroad. They load a moment after the props, under their own chips.

- **No hand-made list.** `pipeline/sports.py` reads Kalshi's list of sports series each run and keeps the per-game ones, so a league Kalshi adds shows up by itself.
- **History comes from Kalshi.** Every market Kalshi settled since late summer (as far back as its API goes; the cache keeps what it has seen, so the history grows). A settled market carries the result: the total, the margin, both scores. A reported number is used only when all of that game's settled lines agree with it; otherwise the lines themselves pin the score down where they can.
- **Winner markets use Elo ratings.** `pipeline/elo.py` runs every result Kalshi has settled in date order, including older ones from its archive (`/historical/markets`, backfilled a few dozen pages per run, then refreshed weekly). Beating a strong opponent moves a rating more than beating a weak one. Tennis players are rated across tours: ATP, Challenger and ITF men in one pool, WTA, WTA 125 and ITF women in another, doubles pairs separately, with a lower starting rating on the lower tours. Each pool is calibrated on its own past predictions, which sets how far apart two ratings are for a given chance and what home is worth where there's a home side. The calibration's improvement on a coin flip says how much to trust it. In soccer, a draw counts half, and the chance of a win takes Kalshi's draw price out.
- **The edge leans on Kalshi's price.** It moves at most a quarter of the way toward the ratings, less with few results, poor calibration or a long shot, and less again once the gap passes 10 points. A liquid market more than 20 points from the ratings is flagged *check news*. Every run also saves each rated market's last price before the start. Once a few hundred have settled, each sport's weight is refitted against the results, so the ratings only get more say where they've actually beaten the price.
- **Spreads, totals and the rest use a trend estimate.** The hit rate on that line, recent games counted more, pulled toward Kalshi's price with 10 games' worth of weight. The edge leans on the price even more, and more again for long shots.
- Kalshi lists the away team first for US college games, so those get home and away splits. Elsewhere Kalshi doesn't say who's at home, so there's no venue split.
- Ladders keep the 7 lines closest to a coin flip, and lines without a real two-sided quote are left off.

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
- The Elo ratings for other sports only know who won and when, not surfaces, injuries, retirements or roster changes, and they're rough for anyone with few results on Kalshi.
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
pipeline/sports.py     every other Kalshi sport: game markets, history from Kalshi's settled markets
pipeline/elo.py        Elo ratings for those sports' winner markets, calibrated per league or tennis pool
pipeline/matchups.py   opponent defense vs position from this season's box scores
pipeline/stats.py      hit rates, splits, streaks
pipeline/model.py      projection, probability, Kalshi fee and edge
pipeline/build.py      ties it together and writes site/data/
site/                  the website (plain HTML, CSS and JavaScript); picks.js builds the Picks page from board.json and more.json
```
