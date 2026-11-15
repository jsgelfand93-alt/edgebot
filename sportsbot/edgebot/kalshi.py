"""Kalshi public market data (no login needed for reading prices)."""
import requests
from . import config


def _get(path, **params):
    last = None
    for base in config.KALSHI_BASES:
        try:
            r = requests.get(f"{base}{path}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:  # try the next host
            last = e
    raise RuntimeError(f"Kalshi request failed: {last}")


def fetch_events(series_ticker):
    """All open events in a series, with their markets (prices live on nested markets)."""
    events, cursor = [], None
    while True:
        params = dict(series_ticker=series_ticker, status="open", with_nested_markets="true", limit=200)
        if cursor:
            params["cursor"] = cursor
        data = _get("/events", **params)
        events.extend(data.get("events", []))
        cursor = data.get("cursor")
        if not cursor:
            return events


def _price(m, key):
    """Price in dollars (0-1). Handles the newer *_dollars strings and older cent integers."""
    v = m.get(f"{key}_dollars")
    if v not in (None, ""):
        try:
            return float(v)
        except ValueError:
            pass
    v = m.get(key)
    if isinstance(v, (int, float)):
        return v / 100.0 if v > 1 else float(v)
    return None


def market_prob(m):
    """Best estimate of the YES probability: bid/ask mid when the book is tight, else last trade."""
    bid, ask, last = _price(m, "yes_bid"), _price(m, "yes_ask"), _price(m, "last_price")
    if bid and ask and 0 < ask - bid <= 0.10:
        mid = (bid + ask) / 2
    elif last:
        mid = last
    elif bid and ask:
        mid = (bid + ask) / 2
    else:
        mid = None
    return {"mid": mid, "bid": bid, "ask": ask, "last": last}
