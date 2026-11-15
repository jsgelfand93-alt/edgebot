"""SQLite history: every scan snapshot (for line movement) and locked picks (for the record)."""
import sqlite3
from datetime import datetime, timezone
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  ts TEXT, sport TEXT, game_id TEXT, team TEXT,
  vegas REAL, kalshi_mid REAL, kalshi_bid REAL, kalshi_ask REAL, spread REAL, gap REAL
);
CREATE TABLE IF NOT EXISTS picks (
  id TEXT PRIMARY KEY, locked_at TEXT, sport TEXT, game_id TEXT, date TEXT, commence_time TEXT,
  game TEXT, team TEXT, home TEXT, away TEXT, pick TEXT, spread REAL,
  vegas REAL, kalshi REAL, gap REAL, result TEXT DEFAULT 'pending', score TEXT DEFAULT ''
);
"""


def db():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_snapshot(con, row):
    ts = now()
    for s in row["sides"]:
        k = s["kalshi"]
        con.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ts, row["sport"], row["game_id"], s["team"], s["vegas"], k["mid"], k["bid"], k["ask"],
                     s["spread"], s["gap"]))
    con.commit()


def movement(con, game_id, team):
    """(first_seen_gap, latest_gap, first_spread, latest_spread) for a team, or None."""
    rows = con.execute("SELECT gap, spread FROM snapshots WHERE game_id=? AND team=? ORDER BY ts",
                       (game_id, team)).fetchall()
    if not rows:
        return None
    return rows[0]["gap"], rows[-1]["gap"], rows[0]["spread"], rows[-1]["spread"]


def lock_pick(con, row):
    """Record a pick once; later scans never overwrite a locked pick."""
    side = next(s for s in row["sides"] if s["team"] == row["best_team"])
    pid = f"{row['sport']}-{row['game_id']}"
    con.execute("""INSERT OR IGNORE INTO picks (id, locked_at, sport, game_id, date, commence_time, game, team,
                   home, away, pick, spread, vegas, kalshi, gap) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, now(), row["sport"], row["game_id"], row["date"], row["commence_time"], row["game"],
                 side["team"], row["home"], row["away"], row["pick"], side["spread"], side["vegas"],
                 side["kalshi"]["mid"], row["gap"]))
    con.commit()


def grade(pick, home_score, away_score):
    """Grade against the locked spread (or straight up for moneyline picks). Returns W, L or P."""
    team_pts = home_score if pick["team"] == pick["home"] else away_score
    opp_pts = away_score if pick["team"] == pick["home"] else home_score
    margin = team_pts - opp_pts + (pick["spread"] if pick["pick"].split()[-1] != "ML" and pick["spread"] is not None else 0)
    return "W" if margin > 0 else ("L" if margin < 0 else "P")


def record(con, sport=None):
    q = "SELECT result, COUNT(*) n FROM picks WHERE result IN ('W','L','P')"
    args = ()
    if sport:
        q += " AND sport=?"; args = (sport,)
    r = {"W": 0, "L": 0, "P": 0}
    for row in con.execute(q + " GROUP BY result", args):
        r[row["result"]] = row["n"]
    return r
