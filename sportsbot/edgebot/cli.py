"""Command line:  python -m edgebot scan [--sports NFL,CFB,UFC] [--lock-hours 30]
                 python -m edgebot grade
                 python -m edgebot record
"""
import argparse, json
from datetime import datetime, timezone, timedelta
from . import config, odds_api, kalshi, store
from .edges import evaluate
from .teams import match_game


def scan(sports, lock_hours, fetch_odds=odds_api.fetch_odds, fetch_events=kalshi.fetch_events, out=None):
    con = store.db()
    rows, unmatched, ok = [], [], 0
    now = datetime.now(timezone.utc)
    for sp in sports:
        cfg = config.SPORTS[sp]
        try:
            games = fetch_odds(cfg["odds_key"])
            events = fetch_events(cfg["kalshi_series"])
        except Exception as e:
            print(f"[{sp}] skipped: {e}")
            continue
        ok += 1
        for g in games:
            start = datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00"))
            if start <= now:
                continue  # already started
            pair = match_game(g, events, sp)
            row = evaluate(g, pair, sp) if pair else None
            if not row:
                unmatched.append(f"{sp}: {g['away_team']} @ {g['home_team']}")
                continue
            store.save_snapshot(con, row)
            mv = store.movement(con, row["game_id"], row["best_team"])
            row["gap_move"] = round(row["gap"] - mv[0], 1) if mv else 0.0
            if row["pick"] and start - now <= timedelta(hours=lock_hours):
                store.lock_pick(con, row)
                row["locked"] = True
            rows.append(row)
        print(f"[{sp}] {len(games)} games, {sum(1 for r in rows if r['sport'] == sp)} matched to Kalshi")
    rows.sort(key=lambda r: -r["gap"])
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


def write_output(con, rows, unmatched, path):
    """edges.json: what Chip's video pipeline reads. Percentages are rounded to whole points."""
    def side(r):
        return next(s for s in r["sides"] if s["team"] == r["best_team"])
    data = {
        "generated_at": store.now(),
        "threshold": config.EDGE_THRESHOLD,
        "records": {sp: _rec_str(store.record(con, sp)) for sp in config.SPORTS} | {"overall": _rec_str(store.record(con))},
        "picks": [
            {"sport": r["sport"], "date": r["date"], "kickoff": r["commence_time"], "game": r["game"],
             "pick": r["pick"], "vegas": round(side(r)["vegas"] * 100), "market": round(side(r)["kalshi"]["mid"] * 100),
             "market_name": "Kalshi", "gap": r["gap"], "gap_move": r.get("gap_move", 0.0),
             "locked": bool(r.get("locked")), "books": r["books"]}
            for r in rows if r["pick"]],
        "slate": [
            {"sport": r["sport"], "date": r["date"], "game": r["game"], "pick": r["pick"] or "NO EDGE",
             "gap": r["gap"], "team": r["best_team"]}
            for r in sorted(rows, key=lambda r: r["commence_time"])],
        "unmatched": unmatched,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"wrote {path}")


def print_table(rows):
    print(f"\n{'SPORT':5} {'GAME':34} {'PICK':22} {'VEGAS':>6} {'KALSHI':>7} {'GAP':>6} {'MOVE':>6}")
    for r in rows:
        s = next(x for x in r["sides"] if x["team"] == r["best_team"])
        print(f"{r['sport']:5} {r['game'][:34]:34} {(r['pick'] or 'no edge')[:22]:22} "
              f"{s['vegas']*100:5.1f}% {s['kalshi']['mid']*100:6.1f}% {r['gap']:+6.1f} {r.get('gap_move', 0):+6.1f}"
              + ("  LOCKED" if r.get("locked") else ""))


def grade_all(fetch_scores=odds_api.fetch_scores):
    con = store.db()
    pending = con.execute("SELECT * FROM picks WHERE result='pending'").fetchall()
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
            con.execute("UPDATE picks SET result=?, score=? WHERE id=?", (res, score, p["id"]))
            print(f"{p['pick']:24} {res}  ({score})")
    con.commit()
    print_record(con)


def print_record(con=None):
    con = con or store.db()
    parts = [f"{sp} {_rec_str(store.record(con, sp))}" for sp in config.SPORTS]
    print("Record: " + " · ".join(parts) + f" · Overall {_rec_str(store.record(con))}")


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
