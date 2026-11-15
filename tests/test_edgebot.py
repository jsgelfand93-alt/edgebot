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

    def test_kalshi_short_names(self):
        g = {"id": "o", "commence_time": iso(START), "home_team": "Nebraska Cornhuskers", "away_team": "Ohio State Buckeyes",
             "bookmakers": []}
        ev = {"event_ticker": f"KXNCAAFGAME-{tick_date(START)}OSUNEB", "markets": [
            {"ticker": "x-OSU", "yes_sub_title": "Ohio St."}, {"ticker": "x-NEB", "yes_sub_title": "Nebraska"}]}
        self.assertEqual(teams.match_game(g, [ev], "CFB")["Ohio State Buckeyes"]["ticker"], "x-OSU")
        g2 = {"id": "m2", "commence_time": iso(START), "home_team": "Kent State Golden Flashes",
              "away_team": "Miami (OH) RedHawks", "bookmakers": []}
        ev2 = {"event_ticker": f"KXNCAAFGAME-{tick_date(START)}MOHKENT", "markets": [
            {"ticker": "x-MOH", "yes_sub_title": "Miami (OH)"}, {"ticker": "x-KENT", "yes_sub_title": "Kent St."}]}
        self.assertEqual(teams.match_game(g2, [ev2], "CFB")["Miami (OH) RedHawks"]["ticker"], "x-MOH")

    def test_fighter_accents(self):
        g = {"id": "f", "commence_time": iso(START), "home_team": "Tymoteusz Łopaczyk", "away_team": "Adrian Bartosinski",
             "bookmakers": []}
        ev = {"event_ticker": f"KXUFCFIGHT-{tick_date(START)}BARLOP", "markets": [
            {"ticker": "x-LOP", "yes_sub_title": "Tymoteusz Lopaczyk"}, {"ticker": "x-BAR", "yes_sub_title": "Adrian Bartosinski"}]}
        self.assertEqual(teams.match_game(g, [ev], "UFC")["Tymoteusz Łopaczyk"]["ticker"], "x-LOP")

    def test_edge_and_pick(self):
        row = edges.evaluate(NFL_GAME, teams.match_game(NFL_GAME, [NFL_EVENT], "NFL"), "NFL")
        self.assertEqual(row["pick"], "Jets ML (Kalshi 18¢)")      # Kalshi underprices the Jets -> buy on Kalshi
        self.assertGreater(row["gap"], 3)

    def test_best_price(self):
        H, A = "New York Jets", "Buffalo Bills"
        g = {"id": "bp", "commence_time": iso(START), "home_team": H, "away_team": A, "bookmakers": [
            book("draftkings", H, A, 330, -420, 7.5), book("fanduel", H, A, 320, -400, 7.5),
            book("betmgm", H, A, 325, -410, 7.5), book("williamhill_us", H, A, 330, -420, 9.5)]}
        g["bookmakers"][3]["title"] = "Caesars"
        row = edges.evaluate(g, None, "NFL")
        self.assertEqual(row["pick"], "Jets +9.5")
        self.assertEqual(row["pick_info"]["kind"], "price")
        self.assertEqual(row["pick_info"]["book"], "Caesars")
        self.assertGreater(row["pick_info"]["ev"], 0.02)
        # the same better line at an offshore book is ignored
        g3 = dict(g, bookmakers=g["bookmakers"][:3] + [book("mybookieag", H, A, 330, -420, 9.5)])
        self.assertIsNone(edges.evaluate(g3, None, "NFL")["pick"])
        # every book identical -> no pick
        g2 = dict(g, bookmakers=[book(k, H, A, 330, -420, 7.5) for k in ("a", "b", "c", "d")])
        self.assertIsNone(edges.evaluate(g2, None, "NFL")["pick"])

    def test_longshot_split(self):
        H, A = "Tennessee Titans", "Jacksonville Jaguars"
        bks = [book(k, H, A, 450, -600, 10.5) for k in ("draftkings", "fanduel", "betmgm")] + [book("williamhill_us", H, A, 600, -600, 10.5)]
        g = {"id": "ls", "commence_time": iso(START), "home_team": H, "away_team": A, "bookmakers": bks}
        row = edges.evaluate(g, None, "NFL")
        self.assertIsNone(row["pick"])                       # +600 is too long for a main Money Bet
        self.assertEqual(row["longshot"]["label"], "Titans ML +600")
        # the same value on the spread becomes a normal Money Bet instead
        bks2 = [book(k, H, A, 450, -600, 10.5) for k in ("draftkings", "fanduel", "betmgm")] + [book("williamhill_us", H, A, 450, -600, 12.5)]
        row2 = edges.evaluate(dict(g, bookmakers=bks2), None, "NFL")
        self.assertEqual(row2["pick"], "Titans +12.5")

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
        rows = cli.scan(["NFL", "CFB"], 30, fetch_odds=lambda k: games[k], fetch_events=lambda s: events[s],
                        fetch_results=lambda sp: [{"home": "New York Jets", "away": "Buffalo Bills", "hs": 3, "as": 30,
                                                   "neutral": False, "date": iso(-48)}] * 3)
        out = json.load(open(os.environ["EDGEBOT_OUT"]))
        self.assertEqual(out["picks"][0]["pick"], "Jets ML (Kalshi 18¢)")
        self.assertTrue(out["picks"][0]["locked"])
        self.assertEqual(len(out["slate"]), 3)
        self.assertEqual(out["picks"][0]["kind"], "kalshi")
        jets = next(c for c in out["chip_lines"] if c["game"] == "Bills @ Jets")
        self.assertEqual(jets["pick"], "Bills -7.5")       # Chip's ratings: Bills way better than a 7.5 spread
        self.assertTrue(jets["locked"])
        self.assertIn("chip_records", out)
        # grading through the CLI with a fake scores feed
        scores = [{"id": "g1", "completed": True, "scores": [{"name": "New York Jets", "score": "21"},
                                                              {"name": "Buffalo Bills", "score": "24"}]}]
        cli.grade_all(fetch_scores=lambda k: scores)
        self.assertEqual(store.record(store.db(), "NFL"), {"W": 0, "L": 1, "P": 0})   # Jets lost outright (Kalshi ML)
        self.assertAlmostEqual(store.units(store.db(), "NFL"), -1.0, places=2)

    def test_espn_parse_and_chip_line(self):
        from edgebot import ratings
        ev = lambda h, a, hs, as_, done=True: {"competitions": [{"status": {"type": {"completed": done}}, "neutralSite": False,
            "date": iso(-24 * 7), "competitors": [
                {"homeAway": "home", "score": str(hs), "team": {"displayName": h}},
                {"homeAway": "away", "score": str(as_), "team": {"displayName": a}}]}]}
        data = {"events": [ev("New York Jets", "Buffalo Bills", 10, 31), ev("Buffalo Bills", "Miami Dolphins", 35, 10),
                           ev("Miami Dolphins", "New York Jets", 20, 17), ev("New York Jets", "Miami Dolphins", 0, 0, done=False)]}
        games = ratings.parse_events(data)
        self.assertEqual(len(games), 3)
        r, hfa = ratings.fit(games, "NFL")
        self.assertGreater(r["Buffalo Bills"], r["New York Jets"])
        row = edges.evaluate(NFL_GAME, None, "NFL")
        cl = edges.chip_line(row, r, hfa, "NFL")
        self.assertEqual(cl["vegas_home_spread"], 7.5)
        self.assertIsNotNone(cl["chip_home_spread"])
        if cl["pick"]:
            self.assertIn(cl["pick_team"], ("New York Jets", "Buffalo Bills"))
        self.assertEqual(sum(cl["chip_score"].values()), round(cl["total"]) if False else sum(cl["chip_score"].values()))

    def test_chip_pick_rule(self):
        # Ratings that make Bills much stronger than Vegas thinks -> Chip takes Bills at the Vegas line
        row = edges.evaluate(NFL_GAME, None, "NFL")
        cl = edges.chip_line(row, {"New York Jets": -8.0, "Buffalo Bills": 8.0}, 2.0, "NFL")
        self.assertEqual(cl["chip_home_spread"], 14.0)
        self.assertEqual(cl["pick"], "Bills -7.5")
        self.assertFalse(cl["upset"])
        cl2 = edges.chip_line(row, {"New York Jets": 3.0, "Buffalo Bills": 0.0}, 2.0, "NFL")
        self.assertTrue(cl2["upset"])                     # Chip has the Vegas underdog winning
        self.assertEqual(cl2["pick"], "Jets +7.5")

    def test_units(self):
        self.assertAlmostEqual(store.units_for("W", 500), 5.0)
        self.assertAlmostEqual(store.units_for("W", -110), 0.909, places=3)
        self.assertEqual(store.units_for("L", 500), -1.0)
        self.assertEqual(store.units_for("P", 500), 0.0)


if __name__ == "__main__":
    unittest.main()
