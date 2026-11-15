"""Chip's own power ratings: every team's strength from this season's real scores.

Model (classic margin ratings, like a simplified Sagarin/Massey):
    home_margin = rating[home] - rating[away] + home_field   (home_field = 0 at neutral sites)
fitted by weighted ridge least squares, with
  - recency weights (a game from `half_life` weeks ago counts half as much),
  - blowout caps (margins capped so a 45-point rout doesn't count more than a 28-point one),
  - ridge shrinkage toward 0 so teams with few games stay near average.
Chip's spread for a game = rating[home] - rating[away] + home_field, written like Vegas (negative = favored).
"""
from datetime import datetime, timezone
import requests
import numpy as np

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard"
LEAGUES = {
    "NFL": {"league": "nfl", "weeks": range(1, 19), "params": {"seasontype": 2},
            "cap": 21, "ridge": 2.0, "half_life": 6.0},
    "CFB": {"league": "college-football", "weeks": range(1, 17), "params": {"seasontype": 2, "groups": 80, "limit": 400},
            "cap": 28, "ridge": 1.0, "half_life": 5.0},
}


def season_year(now=None):
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def parse_events(data):
    """ESPN scoreboard JSON -> list of finished games {home, away, hs, as, neutral, date}."""
    out = []
    for ev in data.get("events", []):
        for comp in ev.get("competitions", []):
            if not comp.get("status", ev.get("status", {})).get("type", {}).get("completed"):
                continue
            teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            if "home" not in teams or "away" not in teams:
                continue
            try:
                out.append({
                    "home": teams["home"]["team"]["displayName"], "away": teams["away"]["team"]["displayName"],
                    "hs": float(teams["home"]["score"]), "as": float(teams["away"]["score"]),
                    "neutral": bool(comp.get("neutralSite")), "date": comp.get("date") or ev.get("date"),
                })
            except (KeyError, TypeError, ValueError):
                continue
    return out


def fetch_results(sport, year=None, get=requests.get):
    cfg = LEAGUES[sport]
    year = year or season_year()
    games, empty_streak = [], 0
    for wk in cfg["weeks"]:
        r = get(ESPN.format(league=cfg["league"]), params={"dates": year, "week": wk, **cfg["params"]}, timeout=30)
        r.raise_for_status()
        g = parse_events(r.json())
        games.extend(g)
        empty_streak = 0 if g else empty_streak + 1
        if empty_streak >= 2 and games:  # past the last played week
            break
    return games


def fit(games, sport, now=None):
    """Return (ratings dict, home_field). Ratings are points above an average team."""
    cfg = LEAGUES[sport]
    now = now or datetime.now(timezone.utc)
    teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
    if len(teams) < 2:
        return {}, 0.0
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    rows, y, w = [], [], []
    for g in games:
        x = np.zeros(n + 1)
        x[idx[g["home"]]] = 1.0
        x[idx[g["away"]]] = -1.0
        x[n] = 0.0 if g["neutral"] else 1.0
        m = max(-cfg["cap"], min(cfg["cap"], g["hs"] - g["as"]))
        try:
            gd = datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
            weeks_ago = max(0.0, (now - gd).days / 7)
        except Exception:
            weeks_ago = 0.0
        rows.append(x); y.append(m); w.append(0.5 ** (weeks_ago / cfg["half_life"]))
    X, Y, Wt = np.array(rows), np.array(y), np.sqrt(np.array(w))
    Xw, Yw = X * Wt[:, None], Y * Wt
    # ridge on team ratings only (not on home field), plus a sum-to-zero row so ratings are centered
    reg = np.sqrt(cfg["ridge"]) * np.eye(n + 1)[:n]
    center = np.zeros((1, n + 1)); center[0, :n] = 1.0
    A = np.vstack([Xw, reg, center * 10])
    b = np.concatenate([Yw, np.zeros(n), [0.0]])
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    return {t: float(sol[idx[t]]) for t in teams}, float(sol[n])


def chip_spread(ratings, hfa, home, away, neutral=False):
    """Home team's spread in Vegas notation (negative = home favored), rounded to the half point. None if unknown."""
    if home not in ratings or away not in ratings:
        return None
    margin = ratings[home] - ratings[away] + (0.0 if neutral else hfa)
    return -round(margin * 2) / 2


def match_name(name, ratings):
    """Odds API team name -> ratings key (exact, then token overlap)."""
    if name in ratings:
        return name
    from .teams import norm
    a = set(norm(name))
    best, score = None, 0.0
    for t in ratings:
        b = set(norm(t))
        s = len(a & b) / max(len(a | b), 1)
        if s > score:
            best, score = t, s
    return best if score >= 0.5 else None
