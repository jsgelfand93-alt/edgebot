"""The Odds API client (https://the-odds-api.com). Each odds call costs regions x markets credits."""
import requests
from . import config


def _get(path, **params):
    if not config.ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is not set (see .env.example)")
    params["apiKey"] = config.ODDS_API_KEY
    r = requests.get(f"{config.ODDS_API_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    left = r.headers.get("x-requests-remaining")
    if left is not None:
        print(f"[odds-api] credits remaining: {left}")
    return r.json()


def fetch_odds(sport_key, markets="h2h,spreads,totals"):
    """Upcoming games with every book's moneyline and spread (American odds)."""
    return _get(f"/sports/{sport_key}/odds", regions=config.ODDS_REGIONS,
                markets=markets, oddsFormat="american", dateFormat="iso")


def fetch_scores(sport_key, days_from=3):
    """Finished/live games from the last N days (for grading). Costs 2 credits."""
    return _get(f"/sports/{sport_key}/scores", daysFrom=days_from, dateFormat="iso")
