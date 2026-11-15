"""Command line:  python -m edgebot scan [--sports NFL,CFB,UFC] [--lock-hours 30]
                 python -m edgebot grade
                 python -m edgebot record
"""
import argparse, json
from datetime import datetime, timezone, timedelta
from . import config, odds_api, kalshi, store
from .edges import evaluate, chip_line
from . import ratings as ratings_mod
from .teams import match_game


def _chip_model(sp, fetch_results):
    if sp not in ratings_mod.LEAGUES:
        return None
    try:
        games = fetch_results(sp)
        r, hfa = ratings_mod.fit(games, sp)
        print(f"[{sp}] Chip's ratings: {len(r)} teams from {len(games)} games, home field {hfa:+.1f}")
        return r, hfa
    except Exception as e:
        print(f"[{sp}] Chip's ratings unavailable: {e}")
        return None


def scan(sports, lock_hours, fetch_odds=odds_api.fetch_odds, fetch_events=kalshi.fetch_events, out=None,
         fetch_results=ratings_mod.fetch_results):
    con = store.db()
    rows, unmatched, ok = [], [], 0
    now = datetime.now(timezone.utc)
    for sp in sports:
        cfg = config.SPORTS[sp]
        try:
            games = fetch_odds(cfg["odds_key"])
        except Exception as e:
            print(f"[{sp}] skipped: {e}")
            continue
        try:
            events = fetch_events(cfg["kalshi_series"])
        except Exception as e:  # Kalshi down: best-price check still runs
            print(f"[{sp}] Kalshi unavailable ({e}); running best-price check only")
            events = []
        ok += 1
        model = _chip_model(sp, fetch_results)
        for g in games:
            start = datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00"))
            if start <= now:
                continue  # already started
            pair = match_game(g, events, sp)
            if not pair:
                unmatched.append(f"{sp}: {g['away_team']} @ {g['home_team']}")
            row = evaluate(g, pair, sp)
            if not row:
                continue
            row["gap_move"] = 0.0
            if row["sides"]:
                store.save_snapshot(con, row)
                mv = store.movement(con, row["game_id"], row["best_team"])
                row["gap_move"] = round(row["gap"] - mv[0], 1) if mv else 0.0
            if row["pick"] and start - now <= timedelta(hours=lock_hours):
                store.lock_pick(con, row)
                row["locked"] = True
            if row["longshot"] and start - now <= timedelta(hours=lock_hours):
                store.lock_pick(con, row, row["longshot"])
                row["longshot"]["locked"] = True
            store.update_close(con, row, sp)
            row["chip"] = chip_line(row, *model, sp) if model else None
            if row["chip"] and row["chip"]["pick"] and start - now <= timedelta(hours=lock_hours):
                store.lock_chip_pick(con, row, row["chip"])
                row["chip"]["locked"] = True
            rows.append(row)
        print(f"[{sp}] {len(games)} games, {sum(1 for r in rows if r['sport'] == sp)} matched to Kalshi")
    rows.sort(key=lambda r: -_strength(r))
    if not ok:
        print("No data source worked; keeping the previous edges.json.")
        return rows
    write_output(con, rows, unmatched, out or config.OUT_PATH)
    print_table(rows)
    if unmatched:
        print(f"\nNot matched to a Kalshi market ({len(unmatched)}): " + "; ".join(unmatched[:10]))
    return rows


def _rec_str(r):
    return f"{r['W']}-{r['L']}" + (f"-{r['P']}" if r["P"] else "")


def _rec_full(con, sport=None, longshots=False):
    """'NFL 1-4 · +1.0u' style string pieces: record and units."""
    u = store.units(con, sport, longshots)
    r = _rec_str(store.record(con, sport, longshots))
    return {"record": r, "units": u, "label": f"{r} · {u:+.1f}u"}


def _strength(r):
    pk = r["pick_info"]
    return (pk["ev"] or 0) * 100 if pk and pk["kind"] == "price" else (r["gap"] or 0)


def write_output(con, rows, unmatched, path):
    """edges.json: what Chip's video pipeline reads. Percentages are whole points."""
    def pick_json(r):
        pk = r["pick_info"]; t = pk["team"]
        cl = con.execute("SELECT close_ev FROM picks WHERE id=?", (f"{r['sport']}-{r['game_id']}",)).fetchone()
        k = next((s for s in r["sides"] if s["team"] == t), None)
        return {"sport": r["sport"], "date": r["date"], "kickoff": r["commence_time"], "game": r["game"],
                "pick": r["pick"], "kind": pk["kind"], "team": t,
                "fair_pct": round(r["fair"][t]["p"] * 100), "fair_spread": r["fair"][t]["spread"],
                "line": pk["line"], "price": pk["price"], "book": pk["book"],
                "ev_pct": round(pk["ev"] * 100, 1) if pk["ev"] is not None else None,
                "kalshi_pct": round(k["kalshi"]["mid"] * 100) if k else None,
                "kalshi_gap": round(k["gap"], 1) if k else None,
                "locked": bool(r.get("locked")), "books": r["books"],
                "fair_odds": __import__("edgebot.edges", fromlist=["x"]).prob_to_american(r["fair"][t]["p"]),
                "close_ev_pct": round(cl["close_ev"] * 100, 1) if cl and cl["close_ev"] is not None else None}
    picks = sorted((r for r in rows if r["pick"]), key=lambda r: -_strength(r))
    data = {
        "generated_at": store.now(),
        "rules": {"kalshi_gap_pts": config.EDGE_THRESHOLD, "best_price_min_ev_pct": config.BEST_PRICE_MIN_EV * 100},
        "records": {sp: _rec_full(con, sp) for sp in config.SPORTS} | {"overall": _rec_full(con)},
        "picks": [pick_json(r) for r in picks],
        "slate": [
            {"sport": r["sport"], "date": r["date"], "kickoff": r["commence_time"], "game": r["game"],
             "pick": r["pick"] or "NO EDGE", "kalshi_gap": r["gap"],
             "best_ev_pct": round(r["best_price"]["ev"] * 100, 1) if r["best_price"] else None}
            for r in sorted(rows, key=lambda r: r["commence_time"])],
        "longshot_records": {sp: _rec_full(con, sp, True) for sp in config.SPORTS} | {"overall": _rec_full(con, None, True)},
        "longshots": [
            {"sport": r["sport"], "date": r["date"], "kickoff": r["commence_time"], "game": r["game"],
             "pick": r["longshot"]["label"], "team": r["longshot"]["team"], "price": r["longshot"]["price"],
             "book": r["longshot"]["book"], "ev_pct": round(r["longshot"]["ev"] * 100, 1),
             "fair_odds": __import__("edgebot.edges", fromlist=["x"]).prob_to_american(r["fair"][r["longshot"]["team"]]["p"]),
             "locked": bool(r["longshot"].get("locked"))}
            for r in rows if r.get("longshot")],
        "closing_value": [
            {"pick": p["pick"], "sport": p["sport"], "game": p["game"], "kind": p["kind"],
             "close_ev_pct": round(p["close_ev"] * 100, 1)}
            for p in con.execute("SELECT * FROM picks WHERE close_ev IS NOT NULL ORDER BY locked_at DESC LIMIT 40")],
        "chip_records": {sp: _rec_str(store.chip_record(con, sp)) for sp in ("NFL", "CFB")} | {"overall": _rec_str(store.chip_record(con))},
        "chip_lines": [
            {"sport": r["sport"], "date": r["date"], "kickoff": r["commence_time"], "game": r["game"],
             "home": r["home"], "away": r["away"],
             "vegas_home_spread": r["chip"]["vegas_home_spread"], "chip_home_spread": r["chip"]["chip_home_spread"],
             "diff": r["chip"]["diff"], "total": r["chip"]["total"],
             "chip_score": r["chip"]["chip_score"], "pick": r["chip"]["pick"] or "PASS",
             "upset": r["chip"]["upset"], "upset_team": r["chip"]["upset_team"],
             "locked": bool(r["chip"].get("locked"))}
            for r in sorted(rows, key=lambda r: r["commence_time"]) if r.get("chip")],
        "unmatched_kalshi": unmatched,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"wrote {path}")


def print_table(rows):
    print(f"\n{'SPORT':5} {'GAME':32} {'PICK':24} {'KALSHI GAP':>10} {'BEST PRICE':>28}")
    for r in rows:
        bp = r["best_price"]
        bps = f"{bp['ev']*100:+.1f}% {bp['book'][:14]}" if bp else ""
        gap = f"{r['gap']:+.1f}" if r["gap"] is not None else "n/a"
        print(f"{r['sport']:5} {r['game'][:32]:32} {(r['pick'] or 'no edge')[:24]:24} {gap:>10} {bps:>28}"
              + ("  LOCKED" if r.get("locked") else ""))


def grade_all(fetch_scores=odds_api.fetch_scores):
    con = store.db()
    cache = {}
    def cached(key):  # one scores call per sport, shared by both tables
        if key not in cache:
            cache[key] = fetch_scores(key)
        return cache[key]
    for table in ("picks", "chip_picks"):
        _grade_table(con, table, cached)
    print_record(con)


def _grade_table(con, table, fetch_scores):
    pending = con.execute(f"SELECT * FROM {table} WHERE result='pending'").fetchall()
    by_sport = {}
    for p in pending:
        by_sport.setdefault(p["sport"], []).append(p)
    for sp, picks in by_sport.items():
        try:
            scores = {g["id"]: g for g in fetch_scores(config.SPORTS[sp]["odds_key"]) if g.get("completed")}
        except Exception as e:
            print(f"[{sp}] scores unavailable: {e}")
            continue
        for p in picks:
            g = scores.get(p["game_id"])
            if not g or not g.get("scores"):
                continue
            pts = {s["name"]: float(s["score"]) for s in g["scores"]}
            res = store.grade(p, pts[p["home"]], pts[p["away"]])
            score = f"{p['away']} {pts[p['away']]:g} - {p['home']} {pts[p['home']]:g}"
            con.execute(f"UPDATE {table} SET result=?, score=? WHERE id=?", (res, score, p["id"]))
            print(f"[{table}] {p['pick']:24} {res}  ({score})")
    con.commit()


def print_record(con=None):
    con = con or store.db()
    parts = [f"{sp} {_rec_full(con, sp)['label']}" for sp in config.SPORTS]
    print("Money Bets: " + " · ".join(parts) + f" · Overall {_rec_full(con)['label']}")
    print(f"Long Shots: {_rec_full(con, None, True)['label']}")
    print("Chip's Picks: " + " · ".join(f"{sp} {_rec_str(store.chip_record(con, sp))}" for sp in ("NFL", "CFB"))
          + f" · Overall {_rec_str(store.chip_record(con))}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="edgebot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="find edges and write edges.json")
    s.add_argument("--sports", default="NFL,CFB,UFC")
    s.add_argument("--lock-hours", type=float, default=30,
                   help="lock picks for games starting within this many hours (default 30)")
    sub.add_parser("grade", help="grade finished locked picks")
    sub.add_parser("record", help="show records by sport")
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        scan([x.strip().upper() for x in a.sports.split(",") if x.strip()], a.lock_hours)
    elif a.cmd == "grade":
        grade_all()
    else:
        print_record()


if __name__ == "__main__":
    main()
