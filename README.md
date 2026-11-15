# Edgebot — Chip's brain

Compares the sportsbooks' odds (vig removed, sharp books weighted 3×) with Kalshi game prices for NFL, college football and UFC. Where they disagree by 3+ percentage points, it makes a pick, locks it about a day before kickoff, grades it after the game, and keeps a record per sport. Everything lands in `edges.json`, which Chip's video pipeline reads.

## Setup (about 15 minutes, no computer needs to stay on)

1. **Get a free Odds API key** at https://the-odds-api.com. The free plan gives 500 credits a month, and this bot uses about 80 a week.
2. **Make a GitHub account** at https://github.com if you don't have one.
3. **Create a new repository** called `edgebot`, set to **Public**. Public lets Chip's automated runs read `edges.json`; your API key stays secret either way.
4. **Upload these files**: on the repo page, choose *Add file → Upload files* and drag in everything from this folder, including the hidden `.github` folder. If your file picker hides it, create the file by hand: *Add file → Create new file*, name it `.github/workflows/edgebot.yml`, and paste in its contents.
5. **Add your key as a secret**: *Settings → Secrets and variables → Actions → New repository secret*. Name it `ODDS_API_KEY` and paste the key.
6. **Allow it to save results**: *Settings → Actions → General → Workflow permissions →* select **Read and write permissions** → Save.
7. **Test it**: *Actions* tab → **edgebot** → **Run workflow**. After about a minute, open the run's log: you'll see a table of games, gaps and picks, and a new `edges.json` in the repo.

It then runs on its own (times in Pacific):

| When | What |
|---|---|
| Thu 7 AM | Thursday game + early weekend look |
| Fri 1 PM | College football + UFC, locks Saturday picks |
| Sat 6 AM | Refresh before college kickoffs |
| Sat 3 PM | NFL Sunday, locks Sunday picks |
| Sun 5 AM | Final NFL refresh, grades Saturday |
| Mon 7 AM | Grades Sunday, Monday night game |
| Tue 7 AM | Grades Monday night |

## Running it on a server or your own machine instead

```
pip install -r requirements.txt
cp .env.example .env        # put your key in .env
python -m edgebot scan      # find edges, write edges.json
python -m edgebot grade     # grade finished picks
python -m edgebot record    # NFL x-x · CFB x-x · UFC x-x · Overall x-x
python -m unittest discover tests   # offline self-test, no key needed
```

For cron, copy the schedule above, e.g. `0 15 * * 6 cd ~/edgebot && python -m edgebot scan`.

## How it decides

Two rules. Each game gets at most one pick, from rule 1 if it fires, otherwise rule 2.

1. **Kalshi gap.** The fair win chance (each book's moneyline with the vig removed, averaged across books, sharp books weighted 3×) compared with Kalshi's price (bid/ask midpoint, or the last trade if the spread is wide). A gap of 3+ points (`EDGE_THRESHOLD`) is a pick at the consensus spread. Expect this to be rare: Kalshi tracks the books closely.
2. **Best price.** The fair line is the consensus spread and its vig-free cover chance. The bot checks every book's price and line against it. Each half-point of spread is valued at about 1.5% cover probability for NFL and 1.25% for college; UFC is moneyline only. If one book's bet is worth +2% expected value or more (`BEST_PRICE_MIN_EV`) and at least 4 books are quoting the game (`MIN_BOOKS`), that's a pick at that book's line, e.g. "Jets +9.5" when the consensus is +7.5.

- **Locking:** picks lock once a game is within 30 hours. Later scans never change a locked pick, so the record stays honest. Grading uses the locked line.
- **Line movement:** every scan is saved, and `gap_move` in `edges.json` shows how much the Kalshi gap has moved since the bot first saw the game.
- **Free tier note:** the "us" region doesn't include Pinnacle (the sharpest book). Set `ODDS_REGIONS=us,eu` to add it, at double the credit cost.

## Chip's own line (power ratings)

Before each NFL and college scan, the bot downloads this season's final scores from ESPN's public scoreboard (no key needed) and fits a power rating for every team. Each team gets points above or below average, plus a home-field edge, with recent games weighted more and blowouts capped (21 points NFL, 28 college). That gives **Chip's spread** for every game.

- **Chip's Picks:** when Chip's spread and the Vegas spread differ by 3+ points (NFL) or 6+ (college), Chip takes the side Vegas is undervaluing, at the Vegas line. These are graded against the spread and kept in their own record, separate from the Money Bets (units).
- **Upset alert:** Chip's ratings have the Vegas underdog winning outright.
- **Chip's score:** the Vegas over/under split by Chip's margin, e.g. "Chiefs 27, Bills 23."
- Everything lands in `chip_lines` and `chip_records` in `edges.json`.

Be realistic: a simple rating model is less accurate than the betting market, so expect roughly coin-flip results against the spread over time. Its job is to give Chip an honest opinion of his own; the Money Bets are where the real edge is.

## Things to check in the first week

- **UFC**: the Kalshi series ticker `KXUFCFIGHT` in `edgebot/config.py` is a best guess. Open any UFC fight on kalshi.com; the URL contains the series ticker (the part before the first dash in the market ticker). If it differs, change it there.
- **Unmatched games**: the log and `edges.json` list any games the bot couldn't pair with a Kalshi market. A few small-school college games are normal. If an NFL game shows up there, Kalshi changed a team code; add it to `NFL_CODES` in `edgebot/teams.py`.
- **Not betting advice**: this is a model for content and research. Prices move, and the 3-point threshold is a starting point, not a proven edge. Run it in shadow mode for 2–3 weeks and compare its record with the current stand-in before relying on it.
