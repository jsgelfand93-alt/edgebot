"""Vig removal, sportsbook consensus, and the two pick rules:

1. Kalshi gap   - the vig-free sportsbook win chance and Kalshi's price disagree by EDGE_THRESHOLD+ points.
2. Best price   - one sportsbook offers a price/line better than the fair (vig-free consensus) line,
                  worth BEST_PRICE_MIN_EV+ expected value per $1.
"""
from statistics import median
from . import config
from .teams import short_name, et_date


def american_to_prob(odds):
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def american_to_decimal(odds):
    odds = float(odds)
    return 1 + (odds / 100 if odds > 0 else 100 / -odds)


def devig_pair(p_a, p_b):
    """Proportional vig removal for a two-way market."""
    s = p_a + p_b
    return p_a / s, p_b / s


def _outcomes(mk, home, away):
    outs = {o["name"]: o for o in mk.get("outcomes", [])}
    return outs if home in outs and away in outs else None


def consensus(game):
    """Fair win probability and fair spread per team.

    Returns {team: {"p", "p_median", "spread", "cover_p"}, "_books": n} where cover_p is the vig-free chance of
    covering the consensus spread (from books hanging exactly that number), or None.
    """
    home, away = game["home_team"], game["away_team"]
    probs = {home: [], away: []}
    spreads = {home: [], away: []}
    spread_quotes = []  # (home_point, p_home_cover, p_away_cover)
    totals = []
    for bk in game.get("bookmakers", []):
        w = config.SHARP_WEIGHT if bk.get("key") in config.SHARP_BOOKS else 1.0
        for mk in bk.get("markets", []):
            if mk["key"] == "totals":
                over = next((o for o in mk.get("outcomes", []) if o.get("name") == "Over" and "point" in o), None)
                if over:
                    totals.append(float(over["point"]))
                continue
            outs = _outcomes(mk, home, away)
            if not outs:
                continue
            if mk["key"] == "h2h":
                ph, pa = devig_pair(american_to_prob(outs[home]["price"]), american_to_prob(outs[away]["price"]))
                probs[home].append((ph, w)); probs[away].append((pa, w))
            elif mk["key"] == "spreads" and "point" in outs[home]:
                hp = float(outs[home]["point"])
                spreads[home].append(hp); spreads[away].append(float(outs[away]["point"]))
                ch, ca = devig_pair(american_to_prob(outs[home]["price"]), american_to_prob(outs[away]["price"]))
                spread_quotes.append((hp, ch, ca))
    if not probs[home]:
        return None
    out = {"_books": len(probs[home]), "_total": median(totals) if totals else None}
    for t in (home, away):
        tw = sum(w for _, w in probs[t])
        sp = median(spreads[t]) if spreads[t] else None
        if sp is not None:
            sp = round(sp * 2) / 2
        out[t] = {"p": sum(p * w for p, w in probs[t]) / tw, "p_median": median(p for p, _ in probs[t]),
                  "spread": sp, "cover_p": None}
    hs = out[home]["spread"]
    if hs is not None:
        at = [(ch, ca) for hp, ch, ca in spread_quotes if hp == hs]
        out[home]["cover_p"] = median(c for c, _ in at) if at else 0.5
        out[away]["cover_p"] = median(c for _, c in at) if at else 0.5
    return out


def best_price(game, cons, sport):
    """Best single-book bet vs the fair line. Returns the highest-EV candidate or None."""
    home, away = game["home_team"], game["away_team"]
    ppv = config.POINT_VALUE.get(sport)
    best = None
    for bk in game.get("bookmakers", []):
        if bk.get("key") not in config.BEST_PRICE_BOOKS:
            continue
        for mk in bk.get("markets", []):
            outs = _outcomes(mk, home, away)
            if not outs:
                continue
            for t in (home, away):
                o = outs[t]
                if mk["key"] == "h2h":
                    p, line, kind = cons[t]["p"], None, "ml"
                elif mk["key"] == "spreads" and ppv and cons[t]["spread"] is not None and "point" in o:
                    line, kind = float(o["point"]), "spread"
                    p = cons[t]["cover_p"] + (line - cons[t]["spread"]) * ppv
                    p = min(max(p, 0.01), 0.99)
                else:
                    continue
                ev = p * american_to_decimal(o["price"]) - 1
                if best is None or ev > best["ev"]:
                    best = {"team": t, "kind": kind, "line": line, "price": o["price"], "ev": ev,
                            "book": bk.get("title") or bk.get("key"), "fair_p": p}
    return best


def fmt_spread(x):
    if x is None:
        return ""
    x = round(x * 2) / 2
    return "PK" if x == 0 else (f"+{x:g}" if x > 0 else f"{x:g}")


def fmt_price(a):
    a = int(round(float(a)))
    return f"+{a}" if a > 0 else str(a)


def evaluate(game, kalshi_pair, sport, threshold=None):
    """Score one game. Kalshi pair may be None (best-price check still runs). Returns a row dict."""
    from .kalshi import market_prob
    threshold = config.EDGE_THRESHOLD if threshold is None else threshold
    cons = consensus(game)
    if not cons:
        return None
    home, away = game["home_team"], game["away_team"]
    style = config.SPORTS[sport]["pick_style"]
    sides = []
    if kalshi_pair:
        for t in (home, away):
            k = market_prob(kalshi_pair[t])
            if k["mid"] is None:
                sides = []
                break
            sides.append({"team": t, "vegas": cons[t]["p"], "kalshi": k, "gap": (cons[t]["p"] - k["mid"]) * 100,
                          "spread": cons[t]["spread"], "ticker": kalshi_pair[t].get("ticker")})
    kbest = max(sides, key=lambda s: s["gap"]) if sides else None

    pick = None
    trusted = cons["_books"] >= config.MIN_BOOKS
    # Rule 1: Kalshi gap
    if kbest and kbest["gap"] >= threshold:
        t = kbest["team"]
        line = cons[t]["spread"] if style == "spread" else None
        pick = {"kind": "kalshi", "team": t, "line": line, "book": None, "price": None,
                "label": f"{short_name(t)} {fmt_spread(line)}" if line is not None else f"{short_name(t)} ML",
                "ev": None}
    # Rule 2: best single-book price vs the fair line
    bp = best_price(game, cons, sport) if trusted else None
    if not pick and bp and bp["ev"] >= config.BEST_PRICE_MIN_EV:
        lbl = (f"{short_name(bp['team'])} {fmt_spread(bp['line'])}" if bp["kind"] == "spread"
               else f"{short_name(bp['team'])} ML {fmt_price(bp['price'])}")
        pick = {"kind": "price", "team": bp["team"], "line": bp["line"], "book": bp["book"],
                "price": bp["price"], "label": lbl, "ev": bp["ev"]}

    fair = {t: {"p": cons[t]["p"], "spread": cons[t]["spread"]} for t in (home, away)}
    fair["_total"] = cons["_total"]
    return {
        "sport": sport, "game_id": game["id"], "date": str(et_date(game["commence_time"])),
        "commence_time": game["commence_time"], "game": f"{short_name(away)} @ {short_name(home)}",
        "away": away, "home": home, "books": cons["_books"], "fair": fair,
        "sides": sides, "best_team": kbest["team"] if kbest else None,
        "gap": round(kbest["gap"], 1) if kbest else None,
        "best_price": bp, "pick": pick["label"] if pick else None, "pick_info": pick,
    }


def chip_line(row, ratings, hfa, sport):
    """Chip's own spread vs Vegas for one game. Returns a dict (pick None when they roughly agree)."""
    from .ratings import chip_spread, match_name
    home, away = row["home"], row["away"]
    vh = row["fair"][home]["spread"]
    rh, ra = match_name(home, ratings), match_name(away, ratings)
    if vh is None or not rh or not ra:
        return None
    ch = chip_spread(ratings, hfa, rh, ra)
    if ch is None:
        return None
    total = row["fair"].get("_total") or config.DEFAULT_TOTAL.get(sport, 45.0)
    margin = -ch  # Chip's expected home margin
    hs, as_ = round((total + margin) / 2), round((total - margin) / 2)
    diff = vh - ch  # > 0: Chip likes the home team more than Vegas does
    pick = side = None
    if abs(diff) >= config.CHIP_PICK_THRESHOLD.get(sport, 99):
        side = home if diff > 0 else away
        line = vh if side == home else -vh
        pick = f"{short_name(side)} {fmt_spread(line)}"
    vegas_fav = home if vh < 0 else away
    chip_fav = home if margin > 0 else away
    upset = bool(vh != 0 and margin != 0 and chip_fav != vegas_fav)
    return {"vegas_home_spread": vh, "chip_home_spread": ch, "diff": round(diff, 1), "total": total,
            "chip_score": {home: hs, away: as_}, "pick": pick, "pick_team": side,
            "pick_line": (vh if side == home else -vh) if side else None,
            "upset": upset, "upset_team": chip_fav if upset else None}
