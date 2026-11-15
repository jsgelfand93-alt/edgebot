# Edgebot — Chip's brain

Compares the sportsbooks' odds (vig removed, sharp books weighted 3×) with Kalshi game prices for NFL, college football and UFC. Where they disagree by 3+ percentage points, it makes a pick, locks it about a day before kickoff, grades it after the game, and keeps a record per sport. Everything lands in `edges.json`, which Chip's video pipeline reads.

## Setup (about 15 minutes, no computer needs to stay on)

1. **Get a free Odds API key** at https://the-odds-api.com. The free plan gives 500 credits a month, and this bot uses about 60 a week.
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

- **Vegas number**: each book's moneyline converted to a probability with the vig removed, then averaged across books, with sharp books (Pinnacle, Circa, BetOnline, LowVig, Bookmaker) weighted 3×. The free US region usually doesn't include Pinnacle; set `ODDS_REGIONS=us,eu` to add it, at double the credit cost.
- **Kalshi number**: the bid/ask midpoint when the spread is 10¢ or tighter, otherwise the last trade.
- **Gap**: Vegas minus Kalshi, for each team. If the bigger gap is 3+ points, the bot picks that team: against the spread for football (e.g. "Jets +7.5"), moneyline for UFC.
- **Locking**: picks lock once a game is within 30 hours. Later scans keep showing the numbers but never change a locked pick, so the record is honest.
- **Line movement**: every scan is saved, and `gap_move` in `edges.json` shows how much the gap has grown or shrunk since the bot first saw the game.

## Things to check in the first week

- **UFC**: the Kalshi series ticker `KXUFCFIGHT` in `edgebot/config.py` is a best guess. Open any UFC fight on kalshi.com; the URL contains the series ticker (the part before the first dash in the market ticker). If it differs, change it there.
- **Unmatched games**: the log and `edges.json` list any games the bot couldn't pair with a Kalshi market. A few small-school college games are normal. If an NFL game shows up there, Kalshi changed a team code; add it to `NFL_CODES` in `edgebot/teams.py`.
- **Not betting advice**: this is a model for content and research. Prices move, and the 3-point threshold is a starting point, not a proven edge. Run it in shadow mode for 2–3 weeks and compare its record with the current stand-in before relying on it.
