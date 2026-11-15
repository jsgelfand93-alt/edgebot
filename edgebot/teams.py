"""Match Odds API games/teams to Kalshi events/markets."""
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

# Odds API name -> codes Kalshi has been seen to use in NFL tickers (first = preferred).
NFL_CODES = {
    "Arizona Cardinals": ["ARI"], "Atlanta Falcons": ["ATL"], "Baltimore Ravens": ["BAL"],
    "Buffalo Bills": ["BUF"], "Carolina Panthers": ["CAR"], "Chicago Bears": ["CHI"],
    "Cincinnati Bengals": ["CIN"], "Cleveland Browns": ["CLE"], "Dallas Cowboys": ["DAL"],
    "Denver Broncos": ["DEN"], "Detroit Lions": ["DET"], "Green Bay Packers": ["GB", "GNB"],
    "Houston Texans": ["HOU"], "Indianapolis Colts": ["IND"], "Jacksonville Jaguars": ["JAC", "JAX"],
    "Kansas City Chiefs": ["KC", "KAN"], "Las Vegas Raiders": ["LV", "LVR"], "Los Angeles Chargers": ["LAC"],
    "Los Angeles Rams": ["LAR", "LA"], "Miami Dolphins": ["MIA"], "Minnesota Vikings": ["MIN"],
    "New England Patriots": ["NE", "NWE"], "New Orleans Saints": ["NO", "NOR"], "New York Giants": ["NYG"],
    "New York Jets": ["NYJ"], "Philadelphia Eagles": ["PHI"], "Pittsburgh Steelers": ["PIT"],
    "San Francisco 49ers": ["SF", "SFO"], "Seattle Seahawks": ["SEA"], "Tampa Bay Buccaneers": ["TB", "TAM"],
    "Tennessee Titans": ["TEN"], "Washington Commanders": ["WAS", "WSH"],
}
STOP = {"the", "of", "university", "fc"}


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()


def short_name(full):
    """'New York Jets' -> 'Jets', 'Ohio State Buckeyes' -> 'Ohio State' style label for picks."""
    if full in NFL_CODES:
        return full.split()[-1] if not full.endswith("49ers") else "49ers"
    return full


def et_date(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(ET).date()


def parse_event_ticker(event_ticker):
    """'KXNFLGAME-26NOV22LVDEN' -> (date(2026,11,22), 'LVDEN'). Returns (None, '') if unparseable."""
    try:
        part = event_ticker.split("-", 1)[1]
        m = re.match(r"(\d{2})([A-Z]{3})(\d{2})(.*)", part)
        y, mon, d, rest = m.groups()
        return datetime(2000 + int(y), MONTHS[mon], int(d)).date(), rest
    except Exception:
        return None, ""


def market_code(m):
    t = m.get("ticker", "")
    return t.rsplit("-", 1)[-1] if "-" in t else ""


def team_score(team, market, sport):
    """0..1 confidence that this Kalshi market is the YES side for `team`."""
    code = market_code(market)
    if sport == "NFL" and team in NFL_CODES:
        return 1.0 if code in NFL_CODES[team] else 0.0
    label = " ".join(filter(None, [market.get("yes_sub_title"), market.get("subtitle")])) or market.get("title", "")
    a = [w for w in norm(team) if w not in STOP]
    b = [w for w in norm(label) if w not in STOP]
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    # Kalshi labels are usually a short form of the full name ("Ohio State" for "Ohio State Buckeyes"),
    # so weight how much of the label is covered, with a smaller weight on how much of the team name is.
    overlap = 0.7 * len(common) / len(set(b)) + 0.3 * len(common) / len(set(a))
    fuzzy = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    return max(overlap, fuzzy)


def match_game(game, events, sport, min_score=0.6):
    """Find the Kalshi event for an Odds API game. Returns {team_name: market} or None."""
    gdate = et_date(game["commence_time"])
    teams = [game["home_team"], game["away_team"]]
    best, best_s = None, 0.0
    for ev in events:
        edate, _ = parse_event_ticker(ev.get("event_ticker", ""))
        if edate and abs((edate - gdate).days) > 1:
            continue
        mkts = ev.get("markets") or []
        if len(mkts) < 2:
            continue
        # try every (home market, away market) assignment and keep the best one
        h, a = teams
        for mh in mkts:
            for ma in mkts:
                if mh is ma:
                    continue
                sh, sa = team_score(h, mh, sport), team_score(a, ma, sport)
                if min(sh, sa) >= min_score and sh + sa > best_s:
                    best, best_s = {h: mh, a: ma}, sh + sa
    return best
