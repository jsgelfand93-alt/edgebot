"""Offline tests: fixtures shaped like real Odds API / Kalshi responses. Run: python -m unittest discover tests"""
import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone

TMP = tempfile.mkdtemp()
os.environ["EDGEBOT_DB"] = os.path.join(TMP, "t.sqlite")
os.environ["EDGEBOT_OUT"] = os.path.join(TMP, "edges.json")
os.environ["EDGE_THRESHOLD"] = "3"

from edgebot import edges, teams, store, cli, config  # noqa: E402


def iso(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def book(key, home, away, ml_h, ml_a, sp_h=None):
    mk = [{"key": "h2h", "outcomes": [{"name": home, "price": ml_h}, {"name": away, "price": ml_a}]}]
    if sp_h is not None:
        mk.append({"key": "spreads", "outcomes": [{"name": home, "price": -110, "point": sp_h},
                                                  {"name": away, "price": -110, "point": -sp_h}]})
    return {"key": key, "markets": mk}


def tick_date(hours):
    d = (datetime.now(timezone.utc) + timedelta(hours=hours)).astimezone(teams.ET)
    return d.strftime("%y%b%d").upper()


START = 20  # hours from now -> inside the 30h lock window
NFL_GAME = {"id": "g1", "commence_time": iso(START), "home_team": "New York Jets", "away_team": "Buffalo Bills",
            "bookmakers": [book("draftkings", "New York Jets", "Buffalo Bills", 330, -420, 7.5),
                           book("fanduel", "New York Jets", "Buffalo Bills", 320, -400, 7.5),
                           book("pinnacle", "New York Jets", "Buffalo Bills", 340, -390, 7.5)]}
NFL_EVENT = {"event_ticker": f"KXNFLGAME-{tick_date(START)}BUFNYJ", "markets": [
    {"ticker": f"KXNFLGAME-{tick_date(START)}BUFNYJ-BUF", "yes_bid_dollars": "0.8100", "yes_ask_dollars": "0.8300"},
    {"ticker": f"KXNFLGAME-{tick_date(START)}BUFNYJ-NYJ", "yes_bid_dollars": "0.1600", "yes_ask_dollars": "0.1800"}]}
# A game with no edge: Kalshi agrees with the books.
NFL_GAME2 = {"id": "g2", "commence_time": iso(START + 3), "home_team": "Cincinnati Bengals",
             "away_team": "Pittsburgh Steelers",
             "bookmakers": [book("draftkings", "Cincinnati Bengals", "Pittsburgh Steelers", -170, 145, -3.5)]}
NFL_EVENT2 = {"event_ticker": f"KXNFLGAME-{tick_date(START + 3)}PITCIN", "markets": [
    {"ticker": f"KXNFLGAME-{tick_date(START + 3)}PITCIN-PIT", "yes_bid": 38, "yes_ask": 40},   # old cent format
    {"ticker": f"KXNFLGAME-{tick_date(START + 3)}PITCIN-CIN", "yes_bid": 61, "yes_ask": 63}]}
CFB_GAME = {"id": "c1", "commence_time": iso(START), "home_team": "Ohio State Buckeyes",
            "away_team": "Northwestern Wildcats",
            "bookmakers": [book("draftkings", "Ohio State Buckeyes", "Northwestern Wildcats", -2500, 1200, -27.5)]}
CFB_EVENT = {"event_ticker": f"KXNCAAFGAME-{tick_date(START)}NWOSU", "markets": [
    {"ticker": "x-OSU", "yes_sub_title": "Ohio State", "yes_bid_dollars": "0.9000", "yes_ask_dollars": "0.9200"},
    {"ticker": "x-NW", "yes_sub_title": "Northwestern", "yes_bid_dollars": "0.0800", "yes_ask_dollars": "0.1000"}]}


class T(unittest.TestCase):
    def test_devig(self):
        a, b = edges.devig_pair(edges.american_to_prob(-110), edges.american_to_prob(-110))
        self.assertAlmostEqual(a, 0.5)
        self.assertAlmostEqual(edges.american_to_prob(+300), 0.25)

    def test_nfl_match_by_code(self):
        pair = teams.match_game(NFL_GAME, [NFL_EVENT2, NFL_EVENT], "NFL")
        self.assertTrue(pair["New York Jets"]["ticker"].endswith("-NYJ"))

    def test_cfb_match_by_name(self):
        pair = teams.match_game(CFB_GAME, [CFB_EVENT], "CFB")
        self.assertEqual(pair["Ohio State Buckeyes"]["yes_sub_title"], "Ohio State")

    def test_same_city_rivals(self):
        g = {"id": "m", "commence_time": iso(START), "home_team": "Michigan Wolverines", "away_team": "Michigan State Spartans",
             "bookmakers": []}
        ev = {"event_ticker": f"KXNCAAFGAME-{tick_date(START)}MSUMICH", "markets": [
            {"ticker": "x-MICH", "yes_sub_title": "Michigan"}, {"ticker": "x-MSU", "yes_sub_title": "Michigan State"}]}
        pair = teams.match_game(g, [ev], "CFB")
        self.assertEqual(pair["Michigan State Spartans"]["ticker"], "x-MSU")
        self.assertEqual(pair["Michigan Wolverines"]["ticker"], "x-MICH")

    def test_edge_and_pick(self):
        row = edges.evaluate(NFL_GAME, teams.match_game(NFL_GAME, [NFL_EVENT], "NFL"), "NFL")
        self.assertEqual(row["pick"], "Jets +7.5")
        self.assertGreater(row["gap"], 3)

    def test_no_edge(self):
        row = edges.evaluate(NFL_GAME2, teams.match_game(NFL_GAME2, [NFL_EVENT2], "NFL"), "NFL")
        self.assertIsNone(row["pick"])

    def test_grade(self):
        p = {"team": "New York Jets", "home": "New York Jets", "away": "Buffalo Bills", "pick": "Jets +7.5", "spread": 7.5}
        self.assertEqual(store.grade(p, 20, 24), "W")   # lost by 4, covered +7.5
        self.assertEqual(store.grade(p, 10, 24), "L")
        p2 = dict(p, spread=4.0, pick="Jets +4")
        self.assertEqual(store.grade(p2, 20, 24), "P")

    def test_scan_end_to_end(self):
        games = {"americanfootball_nfl": [NFL_GAME, NFL_GAME2], "americanfootball_ncaaf": [CFB_GAME]}
        events = {"KXNFLGAME": [NFL_EVENT, NFL_EVENT2], "KXNCAAFGAME": [CFB_EVENT]}
        rows = cli.scan(["NFL", "CFB"], 30, fetch_odds=lambda k: games[k], fetch_events=lambda s: events[s])
        out = json.load(open(os.environ["EDGEBOT_OUT"]))
        self.assertEqual(out["picks"][0]["pick"], "Jets +7.5")
        self.assertTrue(out["picks"][0]["locked"])
        self.assertEqual(len(out["slate"]), 3)
        # grading through the CLI with a fake scores feed
        scores = [{"id": "g1", "completed": True, "scores": [{"name": "New York Jets", "score": "21"},
                                                              {"name": "Buffalo Bills", "score": "24"}]}]
        cli.grade_all(fetch_scores=lambda k: scores)
        self.assertEqual(store.record(store.db(), "NFL"), {"W": 1, "L": 0, "P": 0})


if __name__ == "__main__":
    unittest.main()
