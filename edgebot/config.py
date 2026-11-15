"""Settings: environment variables (or a .env file) plus per-sport definitions."""
import os
from pathlib import Path


def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_env()

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
EDGE_THRESHOLD = float(os.environ.get("EDGE_THRESHOLD", "3.0"))
DB_PATH = os.environ.get("EDGEBOT_DB", "edgebot.sqlite")
OUT_PATH = os.environ.get("EDGEBOT_OUT", "edges.json")

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
KALSHI_BASES = [
    "https://api.elections.kalshi.com/trade-api/v2",
    "https://external-api.kalshi.com/trade-api/v2",
]

# Books treated as "sharp" get extra weight in the consensus.
SHARP_BOOKS = {"pinnacle", "circasports", "betonlineag", "lowvig", "bookmaker", "betcris"}
SHARP_WEIGHT = 3.0

# sport key -> settings. kalshi_series: the first part of Kalshi's game tickers.
# Verify the UFC series ticker on kalshi.com before relying on it (it isn't confirmed here).
SPORTS = {
    "NFL": {"odds_key": "americanfootball_nfl", "kalshi_series": "KXNFLGAME", "pick_style": "spread"},
    "CFB": {"odds_key": "americanfootball_ncaaf", "kalshi_series": "KXNCAAFGAME", "pick_style": "spread"},
    "UFC": {"odds_key": "mma_mixed_martial_arts", "kalshi_series": "KXUFCFIGHT", "pick_style": "moneyline"},
}

# Odds API regions: "us" covers the US books; adding "eu" brings Pinnacle but doubles the credit cost.
ODDS_REGIONS = os.environ.get("ODDS_REGIONS", "us")
