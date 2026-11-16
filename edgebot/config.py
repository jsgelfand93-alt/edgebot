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

# Best-price check: a single book's price must beat the fair (vig-free consensus) line by this much
# expected value per $1 before the bot calls it a pick. 0.02 = +2% EV.
BEST_PRICE_MIN_EV = float(os.environ.get("BEST_PRICE_MIN_EV", "0.02"))
# Main Money Bets can't be moneyline underdogs longer than this; longer ones become "Long Shot" picks.
MAX_DOG_ODDS = float(os.environ.get("MAX_DOG_ODDS", "250"))
# Need at least this many books for a trustworthy fair line.
MIN_BOOKS = int(os.environ.get("MIN_BOOKS", "4"))
# Only these (US-regulated) books can supply a best-price pick, so viewers can actually get the number.
# Offshore books (MyBookie, BetUS, Bovada, BetOnline, LowVig) still count toward the fair line.
BEST_PRICE_BOOKS = set(os.environ.get("BEST_PRICE_BOOKS",
    "draftkings,fanduel,betmgm,williamhill_us,espnbet,fanatics,betrivers,hardrockbet,ballybet,betparx,unibet_us").split(","))
# Approximate cover-probability value of one point of spread (used to price half-point differences).
POINT_VALUE = {"NFL": 0.03, "CFB": 0.025}

# Chip's own line: how far (points) Chip's spread must differ from Vegas before he makes a pick.
CHIP_PICK_THRESHOLD = {"NFL": float(os.environ.get("CHIP_NFL_PTS", "3.0")),
                       "CFB": float(os.environ.get("CHIP_CFB_PTS", "6.0"))}
DEFAULT_TOTAL = {"NFL": 44.0, "CFB": 52.0}
# NFL extras: how much Chip's rating trusts EPA (play-by-play) vs final scores, and the backup-QB baseline.
EPA_WEIGHT = float(os.environ.get("EPA_WEIGHT", "0.6"))
BACKUP_QB_EPA = float(os.environ.get("BACKUP_QB_EPA", "-0.12"))

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

# Picks pulled before they aired (e.g. starting QB ruled out). (game date, team name) - removed from every record.
VOID_PICKS = [
    ("2026-11-15", "Dolphins"),
]

# Home field Chip uses = what Vegas implies on the slate, kept within these bounds (points).
HFA_MIN, HFA_MAX = 0.0, 3.0
