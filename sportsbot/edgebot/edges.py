"""Vig removal, sportsbook consensus, and the edge rule."""
from statistics import median
from . import config
from .teams import short_name, et_date


def american_to_prob(odds):
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def devig_pair(p_a, p_b):
    """Proportional vig removal for a two-way market."""
    s = p_a + p_b
    return p_a / s, p_b / s


def consensus(game):
    """Vig-free win probability per team (weighted toward sharp books) and the median spread.

    Returns {team: {"p": prob, "p_median": prob, "spread": point or None}, "_books": n}
    """
    home, away = game["home_team"], game["away_team"]
    probs = {home: [], away: []}
    spreads = {home: [], away: []}
    for bk in game.get("bookmakers", []):
        w = config.SHARP_WEIGHT if bk.get("key") in config.SHARP_BOOKS else 1.0
        for mk in bk.get("markets", []):
            outs = {o["name"]: o for o in mk.get("outcomes", [])}
            if home not in outs or away not in outs:
                continue
            if mk["key"] == "h2h":
                ph, pa = devig_pair(american_to_prob(outs[home]["price"]), american_to_prob(outs[away]["price"]))
                probs[home].append((ph, w)); probs[away].append((pa, w))
            elif mk["key"] == "spreads" and "point" in outs[home]:
                spreads[home].append(float(outs[home]["point"])); spreads[away].append(float(outs[away]["point"]))
    if not probs[home]:
        return None
    out = {"_books": len(probs[home])}
    for t in (home, away):
        tw = sum(w for _, w in probs[t])
        out[t] = {
            "p": sum(p * w for p, w in probs[t]) / tw,
            "p_median": median(p for p, _ in probs[t]),
            "spread": median(spreads[t]) if spreads[t] else None,
        }
    return out


def fmt_spread(x):
    if x is None:
        return ""
    x = round(x * 2) / 2
    return "PK" if x == 0 else (f"+{x:g}" if x > 0 else f"{x:g}")


def evaluate(game, kalshi_pair, sport, threshold=None):
    """Compare consensus with Kalshi for one game. Returns a row dict (pick=None if no edge)."""
    from .kalshi import market_prob
    threshold = config.EDGE_THRESHOLD if threshold is None else threshold
    cons = consensus(game)
    if not cons or not kalshi_pair:
        return None
    home, away = game["home_team"], game["away_team"]
    sides = []
    for t in (home, away):
        k = market_prob(kalshi_pair[t])
        if k["mid"] is None:
            return None
        gap = (cons[t]["p"] - k["mid"]) * 100  # + means books rate the team higher than Kalshi
        sides.append({"team": t, "vegas": cons[t]["p"], "kalshi": k, "gap": gap, "spread": cons[t]["spread"],
                      "ticker": kalshi_pair[t].get("ticker")})
    best = max(sides, key=lambda s: s["gap"])
    style = config.SPORTS[sport]["pick_style"]
    pick = None
    if best["gap"] >= threshold:
        label = short_name(best["team"])
        if style == "spread" and best["spread"] is not None:
            pick = f"{label} {fmt_spread(best['spread'])}"
        else:
            pick = f"{label} ML"
    return {
        "sport": sport,
        "game_id": game["id"],
        "date": str(et_date(game["commence_time"])),
        "commence_time": game["commence_time"],
        "game": f"{short_name(away)} @ {short_name(home)}",
        "away": away, "home": home,
        "books": cons["_books"],
        "sides": sides,
        "best_team": best["team"],
        "gap": round(best["gap"], 1),
        "pick": pick,
    }
