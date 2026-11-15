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
  vegas REAL, kalshi REAL, gap REAL, result TEXT DEFAULT 'pending', score TEXT DEFAULT '',
  kind TEXT, book TEXT, price REAL, ev REAL
);
"""
CHIP_SCHEMA = """
CREATE TABLE IF NOT EXISTS chip_picks (
  id TEXT PRIMARY KEY, locked_at TEXT, sport TEXT, game_id TEXT, date TEXT, commence_time TEXT,
  game TEXT, team TEXT, home TEXT, away TEXT, pick TEXT, spread REAL,
  vegas_home_spread REAL, chip_home_spread REAL, upset INTEGER, result TEXT DEFAULT 'pending', score TEXT DEFAULT ''
);
"""
NEW_COLS = {"kind": "TEXT", "book": "TEXT", "price": "REAL", "ev": "REAL", "close_fair": "REAL", "close_ev": "REAL"}


def db():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.executescript(CHIP_SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(picks)")}
    for col, typ in NEW_COLS.items():  # upgrade databases made by v0.1
        if col not in have:
            con.execute(f"ALTER TABLE picks ADD COLUMN {col} {typ}")
    # picks locked before the long-shot rule: moneylines longer than the cap move to the Long Shot record
    con.execute("UPDATE picks SET kind='longshot' WHERE kind='price' AND pick LIKE '% ML %' AND price > ?",
                (config.MAX_DOG_ODDS,))
    con.commit()
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


def lock_pick(con, row, pk=None):
    """Record a pick once; later scans never overwrite a locked pick."""
    pk = pk or row["pick_info"]
    fair = row["fair"][pk["team"]]
    kal = next((s["kalshi"]["mid"] for s in row["sides"] if s["team"] == pk["team"]), None)
    pid = f"{row['sport']}-{row['game_id']}" + ("-LS" if pk["kind"] == "longshot" else "")
    con.execute("""INSERT OR IGNORE INTO picks (id, locked_at, sport, game_id, date, commence_time, game, team,
                   home, away, pick, spread, vegas, kalshi, gap, kind, book, price, ev)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, now(), row["sport"], row["game_id"], row["date"], row["commence_time"], row["game"],
                 pk["team"], row["home"], row["away"], pk["label"], pk["line"], fair["p"], kal, row["gap"],
                 pk["kind"], pk["book"], pk["price"], pk["ev"]))
    con.commit()


def lock_chip_pick(con, row, cl):
    """Lock Chip's own-line pick (graded against the Vegas spread at lock time)."""
    con.execute("""INSERT OR IGNORE INTO chip_picks (id, locked_at, sport, game_id, date, commence_time, game, team,
                   home, away, pick, spread, vegas_home_spread, chip_home_spread, upset)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"{row['sport']}-{row['game_id']}", now(), row["sport"], row["game_id"], row["date"],
                 row["commence_time"], row["game"], cl["pick_team"], row["home"], row["away"], cl["pick"],
                 cl["pick_line"], cl["vegas_home_spread"], cl["chip_home_spread"], int(cl["upset"])))
    con.commit()


def chip_record(con, sport=None):
    q = "SELECT result, COUNT(*) n FROM chip_picks WHERE result IN ('W','L','P')"
    args = ()
    if sport:
        q += " AND sport=?"; args = (sport,)
    r = {"W": 0, "L": 0, "P": 0}
    for row in con.execute(q + " GROUP BY result", args):
        r[row["result"]] = row["n"]
    return r


def grade(pick, home_score, away_score):
    """Grade against the locked spread (or straight up for moneyline picks). Returns W, L or P."""
    team_pts = home_score if pick["team"] == pick["home"] else away_score
    opp_pts = away_score if pick["team"] == pick["home"] else home_score
    line = pick["spread"] if pick["spread"] is not None and " ML" not in pick["pick"] else 0
    margin = team_pts - opp_pts + line
    return "W" if margin > 0 else ("L" if margin < 0 else "P")


def units_for(result, price):
    """Profit in units for a 1-unit bet. Spread/Kalshi picks without a stored price assume -110."""
    if result == "L":
        return -1.0
    if result != "W":
        return 0.0
    p = float(price) if price not in (None, "") else -110.0
    return p / 100 if p > 0 else 100 / -p


def _kind_filter(longshots):
    return " AND kind='longshot'" if longshots else " AND COALESCE(kind,'') != 'longshot'"


def update_close(con, row, sport):
    """Closing-line value: re-price each locked, not-yet-started pick for this game with the latest fair line."""
    from .edges import fair_cover, american_to_decimal
    for p in con.execute("SELECT * FROM picks WHERE game_id=? AND result='pending'", (row["game_id"],)).fetchall():
        fc = fair_cover(row["cons"], sport, p["team"], p["spread"] if p["kind"] != "longshot" and " ML" not in p["pick"] else None)
        if fc is None or p["price"] is None:
            continue
        con.execute("UPDATE picks SET close_fair=?, close_ev=? WHERE id=?",
                    (fc, fc * american_to_decimal(p["price"]) - 1, p["id"]))
    con.commit()


def units(con, sport=None, longshots=False):
    q = "SELECT result, price FROM picks WHERE result IN ('W','L','P')" + _kind_filter(longshots)
    args = ()
    if sport:
        q += " AND sport=?"; args = (sport,)
    return round(sum(units_for(r["result"], r["price"]) for r in con.execute(q, args)), 2)


def record(con, sport=None, longshots=False):
    q = "SELECT result, COUNT(*) n FROM picks WHERE result IN ('W','L','P')" + _kind_filter(longshots)
    args = ()
    if sport:
        q += " AND sport=?"; args = (sport,)
    r = {"W": 0, "L": 0, "P": 0}
    for row in con.execute(q + " GROUP BY result", args):
        r[row["result"]] = row["n"]
    return r
