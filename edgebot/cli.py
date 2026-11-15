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
        except Exception as e:
            print(f"[{sp}] skipped: {e}")
            continue
        try:
            events = fetch_events(cfg["kalshi_series"])
        except Exception as e:  # Kalshi down: best-price check still runs
            print(f"[{sp}] Kalshi unavailable ({e}); running best-price check only")
            events = []
        ok += 1
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


def _rec_full(con, sport=None):
    """'NFL 1-4 · +1.0u' style string pieces: record and units."""
    u = store.units(con, sport)
    return {"record": _rec_str(store.record(con, sport)), "units": u, "label": f"{_rec_str(store.record(con, sport))} · {u:+.1f}u"}


def _strength(r):
    pk = r["pick_info"]
    return (pk["ev"] or 0) * 100 if pk and pk["kind"] == "price" else (r["gap"] or 0)


def write_output(con, rows, unmatched, path):
    """edges.json: what Chip's video pipeline reads. Percentages are whole points."""
    def pick_json(r):
        pk = r["pick_info"]; t = pk["team"]
        k = next((s for s in r["sides"] if s["team"] == t), None)
        return {"sport": r["sport"], "date": r["date"], "kickoff": r["commence_time"], "game": r["game"],
                "pick": r["pick"], "kind": pk["kind"], "team": t,
                "fair_pct": round(r["fair"][t]["p"] * 100), "fair_spread": r["fair"][t]["spread"],
                "line": pk["line"], "price": pk["price"], "book": pk["book"],
                "ev_pct": round(pk["ev"] * 100, 1) if pk["ev"] is not None else None,
                "kalshi_pct": round(k["kalshi"]["mid"] * 100) if k else None,
                "kalshi_gap": round(k["gap"], 1) if k else None,
                "locked": bool(r.get("locked")), "books": r["books"]}
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
    parts = [f"{sp} {_rec_full(con, sp)['label']}" for sp in config.SPORTS]
    print("Record: " + " · ".join(parts) + f" · Overall {_rec_full(con)['label']}")


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
