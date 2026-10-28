"""
Tests of queries.py, the dashboard's read API, on a small database with engine data written the way
Engine UCI.exe writes it and lichess data the way sync_lichess.py writes it, including the traps: untitled
humans, an outoftime draw, a casual game, a correspondence game, a game at 00:30 local time, aborted games and
games the sync hasn't fetched yet.
"""
import unittest
from datetime import date, datetime
from typing import Any

from helpers import (DatabaseTestCase, add_engine_game, add_engine_move, add_event, add_game, add_lichess_moves,
                     load_fixture, local_ms, queries, store_telemetry_line)

D1, D2, D3, D4 = "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"
ALL = {"gWin0001", "gLoss002", "gDraw003", "gCorr004", "gEngOnly", "gAbort06", "gTimeO07", "gEngHum8", "gEngUnk9"}
SYNCED = {"gWin0001", "gLoss002", "gDraw003", "gCorr004", "gAbort06", "gTimeO07"}
ENGINE_ONLY = ALL - SYNCED


def worker(number: int, status: str = "ok", depth: Any = 6, search_ms: Any = 100.0, **columns: Any) -> dict:
    """A worker of an engine move (worker_runs columns, plus depths / candidates)."""
    return {"worker": number, "status": status, "depth": depth, "search_ms": search_ms, **columns}


def build_dataset(con: Any) -> None:
    """Nine games: six synced (two without engine data) and three only the engine knows so far."""
    # 1. A win against an UNTITLED human (title NULL), rated, 3+2, with three engine moves and a worker timeout.
    add_game(con, "gWin0001", created_at=local_ms(2026, 10, 20, 10), result="win", status="mate", rated=1,
             speed="blitz", clock_initial_s=180, clock_increment_s=2, our_color="white", opponent_id="plain_human",
             opponent_name="Plain_Human", opponent_title=None, opponent_rating=1500, our_rating=1800,
             our_rating_diff=8, opponent_rating_diff=-8, opening_eco="C50", opening_name="Italian Game: Giuoco Piano",
             plies=6)
    add_lichess_moves(con, "gWin0001", ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"])
    add_engine_game(con, "gWin0001", local_ms(2026, 10, 20, 10) + 5000, opponent_name="Plain_Human",
                    opponent_rating=1500, opponent_is_bot=0, engine_version="build-A")
    add_engine_move(con, "gWin0001", 1, path="stockfish_opening", t_total_ms=120.0, stockfish_depth=14)
    add_engine_move(con, "gWin0001", 3, t_total_ms=900.0, best_move="g1f3", best_score=35, workers=(
        worker(1, depth=7, search_ms=700.0, total_nodes=1000, best_move="g1f3", best_score=35,
               root_moves=["g1f3", "d2d4"], unsearched_root_moves=["a2a3"],
               depths=[{"depth": 7, "ms": 600.0, "best_move": "g1f3", "score": 35},
                       {"depth": 6, "ms": 90.0, "best_move": "d2d4", "score": 20},
                       {"depth": 8, "completed": 0, "ms": 10.0}],
               candidates=[{"move": "g1f3", "score": 35, "exact": 1}, {"move": "d2d4", "score": 10, "exact": 0}]),
        worker(2, status="timeout", depth=5, search_ms=850.0, total_nodes=800, root_moves=["b1c3"],
               error="no answer within 1 s", candidates=[{"move": "b1c3", "score": 22, "exact": 1}])))
    add_engine_move(con, "gWin0001", 5, t_total_ms=400.0, workers=(worker(1, depth=8, search_ms=300.0),
                                                                     worker(2, depth=6, search_ms=350.0)))
    add_event(con, local_ms(2026, 10, 20, 10, 1), "gWin0001", 3, "worker 2 timed out", source="kernel worker 2")
    add_event(con, local_ms(2026, 10, 20, 10, 2), "gWin0001", 5, "an event of another ply")
    add_event(con, local_ms(2026, 10, 20, 9), None, None, "engine started", level="info")

    # 2. Lost ON TIME to a BOT, bullet 1+0, as Black; the engine overrode a stalemate and a worker died.
    add_game(con, "gLoss002", created_at=local_ms(2026, 10, 21, 12), result="loss", status="outoftime", rated=1,
             speed="bullet", clock_initial_s=60, clock_increment_s=0, our_color="black", opponent_name="Fast_Bot",
             opponent_title="BOT", opponent_rating=1900, our_rating=1790, our_rating_diff=-7)
    add_engine_game(con, "gLoss002", local_ms(2026, 10, 21, 12) + 3000, our_color="black", opponent_name="Fast_Bot",
                    opponent_title="BOT", opponent_rating=1900, opponent_is_bot=1, engine_version="build-B")
    add_engine_move(con, "gLoss002", 2, path="stockfish_opening", t_total_ms=100.0)
    add_engine_move(con, "gLoss002", 4, path="stalemate_override", t_total_ms=650.0, workers=(
        worker(1, depth=6, search_ms=500.0), worker(2, status="dead", depth=None, search_ms=None)))
    add_event(con, local_ms(2026, 10, 21, 12, 1), "gLoss002", 4, "worker 2 died", level="error")

    # 3. A DRAW on time (outoftime without a winner) against a GM, casual, at 00:30 LOCAL time; no engine data.
    add_game(con, "gDraw003", created_at=local_ms(2026, 10, 21, 0, 30), result="draw", status="outoftime", rated=0,
             speed="blitz", clock_initial_s=180, clock_increment_s=0, opponent_name="Grand_Master",
             opponent_title="GM", opponent_rating=2400, our_rating=1810, opening_eco="B20",
             opening_name="Sicilian Defense")

    # 4. Correspondence (no clock), casual draw, as Black, against a human whose name has no underscore.
    add_game(con, "gCorr004", created_at=local_ms(2026, 10, 22, 9), result="draw", status="draw", rated=0,
             speed="correspondence", clock_initial_s=None, clock_increment_s=None, our_color="black",
             opponent_name="PostalPal", opponent_rating=1600)

    # 5. Played against a BOT but not synced yet.
    add_engine_game(con, "gEngOnly", local_ms(2026, 10, 22, 18), opponent_name="Some_Bot", opponent_title="BOT",
                    opponent_rating=2000, opponent_is_bot=1, engine_version="build-B")
    add_engine_move(con, "gEngOnly", 1, t_total_ms=300.0, workers=(worker(1, depth=9, search_ms=250.0),))
    add_engine_move(con, "gEngOnly", 3, t_total_ms=200.0, workers=(worker(1, depth=7, search_ms=150.0),))

    # 6. Aborted: rated but no rating change.
    add_game(con, "gAbort06", created_at=local_ms(2026, 10, 22, 20), result="aborted", status="aborted", rated=1,
             opponent_name="Quick_Quit", opponent_rating=1700, our_rating=1811, plies=1)

    # 7. Won because the opponent LEFT (status timeout): not a time forfeit.
    add_game(con, "gTimeO07", created_at=local_ms(2026, 10, 23, 8), result="win", status="timeout", rated=1,
             opponent_name="Left_Early", opponent_rating=1555, our_rating=1830, our_rating_diff=5)
    add_engine_game(con, "gTimeO07", local_ms(2026, 10, 23, 8) + 2000, opponent_is_bot=0, engine_version="build-A")
    add_engine_move(con, "gTimeO07", 1, t_total_ms=250.0, workers=(worker(1, depth=5, search_ms=200.0),))

    # 8. Not synced yet, against a human (the engine knows from UCI_Opponent).
    add_engine_game(con, "gEngHum8", local_ms(2026, 10, 23, 10), our_color="black", opponent_name="Mr_X",
                    opponent_rating=1450, opponent_is_bot=0, engine_version="build-A")
    add_engine_move(con, "gEngHum8", 2, t_total_ms=500.0, workers=(worker(1, depth=6, search_ms=450.0),))

    # 9. Not synced yet, and the engine knows nothing about the opponent.
    add_engine_game(con, "gEngUnk9", local_ms(2026, 10, 23, 11), our_color=None, engine_version=None)


class QueriesTestCase(DatabaseTestCase):
    """The dataset above in a fresh database."""

    def setUp(self) -> None:
        """Build the dataset."""
        super().setUp()
        build_dataset(self.con)

    def listed(self, **filters: Any) -> set[str]:
        """The ids list_games returns for these filters (all pages)."""
        rows = queries.list_games(limit=None, con=self.con, **filters)
        self.assertEqual(len(rows), queries.count_games(con=self.con, **filters))
        return self.ids(rows)


class TestListGames(QueriesTestCase):
    """list_games() and count_games()."""

    def test_every_game_newest_first_engine_only_games_included(self) -> None:
        rows = queries.list_games(con=self.con)
        self.assertEqual([row["game_id"] for row in rows],
                         ["gEngUnk9", "gEngHum8", "gTimeO07", "gAbort06", "gEngOnly", "gCorr004", "gLoss002",
                          "gDraw003", "gWin0001"])
        engine_only = [row for row in rows if row["game_id"] == "gEngOnly"][0]
        self.assertEqual((engine_only["synced"], engine_only["result"], engine_only["opponent_kind"],
                          engine_only["engine_moves"]), (0, None, "bot", 2))

    def test_result(self) -> None:
        self.assertEqual(self.listed(result="win"), {"gWin0001", "gTimeO07"})
        self.assertEqual(self.listed(result=["draw", "loss"]), {"gLoss002", "gDraw003", "gCorr004"})
        self.assertEqual(self.listed(result="aborted"), {"gAbort06"})
        self.assertEqual(self.listed(result=[]), ALL)  # an empty choice filters nothing

    def test_speed_and_time_control(self) -> None:
        self.assertEqual(self.listed(speed="bullet"), {"gLoss002"})
        self.assertEqual(self.listed(time_control="3+2"), {"gWin0001", "gAbort06", "gTimeO07"})
        self.assertEqual(self.listed(time_control="1+0"), {"gLoss002"})
        self.assertEqual(self.listed(time_control="3+0"), {"gDraw003"})
        self.assertEqual(self.listed(time_control="corr"), {"gCorr004"})

    def test_our_color_and_rated(self) -> None:
        self.assertEqual(self.listed(our_color="black"), {"gLoss002", "gCorr004", "gEngHum8"})
        self.assertEqual(self.listed(rated=True), {"gWin0001", "gLoss002", "gAbort06", "gTimeO07"})
        self.assertEqual(self.listed(rated=False), {"gDraw003", "gCorr004"})  # unknown (not synced) is neither

    def test_opponent_kind_keeps_untitled_humans(self) -> None:
        humans = {"gWin0001", "gDraw003", "gCorr004", "gAbort06", "gTimeO07", "gEngHum8"}
        self.assertEqual(self.listed(opponent_kind="human"), humans)
        self.assertEqual(self.listed(opponent_kind="bot"), {"gLoss002", "gEngOnly"})
        naive = {row[0] for row in self.con.execute("SELECT game_id FROM v_games WHERE opponent_title <> 'BOT'")}
        self.assertEqual(naive, {"gDraw003"})  # the trap: NULL titles fall out of "<> 'BOT'"

    def test_opponent_name_part_any_case_underscore_is_literal(self) -> None:
        self.assertEqual(self.listed(opponent="BOT"), {"gLoss002", "gEngOnly"})
        self.assertEqual(self.listed(opponent="mr_x"), {"gEngHum8"})
        self.assertEqual(self.listed(opponent="_"), ALL - {"gCorr004", "gEngUnk9"})  # LIKE would match PostalPal
        self.assertEqual(self.listed(opponent=""), ALL)

    def test_opponent_rating_range(self) -> None:
        self.assertEqual(self.listed(opponent_rating_min=1600, opponent_rating_max=2000),
                         {"gLoss002", "gCorr004", "gEngOnly", "gAbort06"})
        self.assertEqual(self.listed(opponent_rating_max=1500), {"gWin0001", "gEngHum8"})

    def test_rating_change_only_matches_rated_games(self) -> None:
        self.assertEqual(self.listed(rating_diff_min=0), {"gWin0001", "gTimeO07"})
        self.assertEqual(self.listed(rating_diff_max=-1), {"gLoss002"})
        self.assertEqual(self.listed(rating_diff_min=-10, rating_diff_max=10), {"gWin0001", "gLoss002", "gTimeO07"})
        add_game(self.con, "gOddCas1", rated=0, our_rating_diff=3)  # a casual game should never count here
        self.assertEqual(self.listed(rating_diff_min=0), {"gWin0001", "gTimeO07"})

    def test_lost_on_time_is_not_every_outoftime(self) -> None:
        self.assertEqual(self.listed(status="outoftime"), {"gLoss002", "gDraw003"})
        self.assertEqual(self.listed(lost_on_time=True), {"gLoss002"})
        self.assertEqual(self.listed(lost_on_time=False), SYNCED - {"gLoss002"})
        self.assertEqual(self.listed(status=["timeout", "mate"]), {"gTimeO07", "gWin0001"})

    def test_dates_are_local_and_inclusive(self) -> None:
        self.assertEqual(self.listed(date_from=D2, date_to=D2), {"gLoss002", "gDraw003"})  # gDraw003 is at 00:30
        self.assertEqual(self.listed(date_to=D1), {"gWin0001"})
        self.assertEqual(self.listed(date_from=date(2026, 10, 23)), {"gTimeO07", "gEngHum8", "gEngUnk9"})
        self.assertEqual(self.listed(date_from=datetime(2026, 10, 23, 23, 59)), {"gTimeO07", "gEngHum8", "gEngUnk9"})
        self.assertEqual(self.listed(date_from=D3, date_to=D3), {"gCorr004", "gEngOnly", "gAbort06"})
        with self.assertRaises(ValueError):
            self.listed(date_from="2026-10-2")
        with self.assertRaises(ValueError):
            self.listed(date_to="yesterday")

    def test_engine_flags_version_and_sync_state(self) -> None:
        self.assertEqual(self.listed(had_stalemate_override=True), {"gLoss002"})
        self.assertEqual(self.listed(had_stalemate_override=False), ALL - {"gLoss002"})
        self.assertEqual(self.listed(had_timeouts=True), {"gWin0001"})
        self.assertEqual(self.listed(had_timeouts=False), ALL - {"gWin0001"})
        self.assertEqual(self.listed(engine_version="build-A"), {"gWin0001", "gTimeO07", "gEngHum8"})
        self.assertEqual(self.listed(engine_version=("build-A", "build-B")),
                         {"gWin0001", "gTimeO07", "gEngHum8", "gLoss002", "gEngOnly"})
        self.assertEqual(self.listed(synced=True), SYNCED)
        self.assertEqual(self.listed(synced=False), ENGINE_ONLY)

    def test_filters_combine(self) -> None:
        self.assertEqual(self.listed(result="win", rated=True, opponent_kind="human", date_from=D4), {"gTimeO07"})
        self.assertEqual(self.listed(result="win", speed="bullet"), set())

    def test_order_by_with_missing_values_last(self) -> None:
        ascending = queries.list_games(order_by="opponent_rating", descending=False, con=self.con)
        self.assertEqual([row["opponent_rating"] for row in ascending],
                         [1450, 1500, 1555, 1600, 1700, 1900, 2000, 2400, None])
        descending = queries.list_games(order_by="opponent_rating", con=self.con)
        self.assertEqual([row["opponent_rating"] for row in descending],
                         [2400, 2000, 1900, 1700, 1600, 1555, 1500, 1450, None])

    def test_order_by_is_whitelisted(self) -> None:
        for bad in ("started_at; DROP TABLE games", "nonexistent", "started_at DESC", ""):
            with self.subTest(order_by=bad), self.assertRaises(ValueError):
                queries.list_games(order_by=bad, con=self.con)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM games").fetchone()[0], 6)

    def test_whitelist_is_every_column_of_v_games(self) -> None:
        columns = {description[0] for description in self.con.execute("SELECT * FROM v_games LIMIT 0").description}
        self.assertEqual(queries.ORDER_BY_COLUMNS, columns)

    def test_paging(self) -> None:
        everything = [row["game_id"] for row in queries.list_games(con=self.con)]
        pages = [[row["game_id"] for row in queries.list_games(limit=4, offset=offset, con=self.con)]
                 for offset in (0, 4, 8)]
        self.assertEqual([len(page) for page in pages], [4, 4, 1])
        self.assertEqual(sum(pages, []), everything)
        self.assertEqual(queries.count_games(con=self.con), 9)
        self.assertEqual(queries.count_games(result="win", con=self.con), 2)
        with self.assertRaises(ValueError):
            queries.list_games(limit=-1, con=self.con)
        with self.assertRaises(ValueError):
            queries.list_games(offset=-5, con=self.con)

    def test_unknown_filters_are_refused(self) -> None:
        with self.assertRaises(TypeError):
            queries.list_games(reslt="win", con=self.con)
        with self.assertRaises(TypeError):
            queries.count_games(colour="white", con=self.con)

    def test_filter_choices(self) -> None:
        choices = queries.filter_choices(con=self.con)
        self.assertEqual(choices["result"], ["aborted", "draw", "loss", "win"])
        self.assertEqual(choices["speed"], ["blitz", "bullet", "correspondence"])
        self.assertEqual(choices["time_control"], ["1+0", "3+0", "3+2", "corr"])
        self.assertEqual(choices["our_color"], ["black", "white"])
        self.assertEqual(choices["opponent_kind"], ["bot", "human"])
        self.assertEqual(choices["status"], ["aborted", "draw", "mate", "outoftime", "timeout"])
        self.assertEqual(choices["opening_eco"], ["B20", "C50"])
        self.assertEqual(choices["engine_version"], ["build-A", "build-B"])
        self.assertEqual((choices["first_date"], choices["last_date"]), (D1, D4))
        for column in queries.CHOICE_FILTERS:  # every choice can be fed back into the filter
            for value in choices[column]:
                self.assertTrue(self.listed(**{column: value}), (column, value))

    def test_filter_choices_of_an_empty_database(self) -> None:
        with self.con:
            for table in ("games", "engine_games"):
                self.con.execute(f"DELETE FROM {table}")
        choices = queries.filter_choices(con=self.con)
        self.assertEqual((choices["result"], choices["first_date"], choices["last_date"]), ([], None, None))

    def test_without_a_connection_each_call_opens_its_own(self) -> None:
        self.assertEqual(len(queries.list_games()), 9)
        self.assertEqual(queries.count_games(synced=False), 3)


class TestOneGame(QueriesTestCase):
    """game_overview(), game_moves(), engine_moves() and move_detail()."""

    def test_game_overview(self) -> None:
        game = queries.game_overview("gWin0001", con=self.con)
        expected = {"our_color": "white", "result": "win", "time_control": "3+2", "opponent_kind": "human",
                    "engine_moves": 3, "kernel_moves": 2, "stockfish_moves": 1, "worker_timeouts": 1,
                    "worker_failures": 0, "max_depth": 8, "max_move_ms": 900.0, "engine_version": "build-A",
                    "synced": 1, "lost_on_time": 0, "local_date": D1}
        self.assertEqual({key: game[key] for key in expected}, expected)
        self.assertAlmostEqual(game["avg_move_ms"], (120 + 900 + 400) / 3)
        self.assertIsNone(queries.game_overview("noSuchGm", con=self.con))

    def test_game_moves_join_the_engine_side(self) -> None:
        moves = queries.game_moves("gWin0001", con=self.con)
        self.assertEqual([move["ply"] for move in moves], [1, 2, 3, 4, 5, 6])
        self.assertEqual([move["san"] for move in moves], ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"])
        self.assertEqual([move["path"] for move in moves],
                         ["stockfish_opening", None, "kernel", None, "kernel", None])
        self.assertEqual([move["by_us"] for move in moves], [1, 0, 1, 0, 1, 0])
        self.assertEqual(queries.game_moves("gEngOnly", con=self.con), [])  # before the sync

    def test_engine_moves(self) -> None:
        moves = queries.engine_moves("gWin0001", con=self.con)
        self.assertEqual([move["ply"] for move in moves], [1, 3, 5])
        stockfish, kernel = moves[0], moves[1]
        self.assertEqual((kernel["workers_ok"], kernel["workers_failed"], kernel["max_depth"],
                          kernel["total_nodes"], kernel["slowest_search_ms"], kernel["overhead_ms"]),
                         (1, 1, 7, 1800, 850.0, 50.0))
        # Stockfish's move had no Kernel worker: no overhead to measure (the view says NULL too, not 120.0,
        # the whole move with Stockfish's thinking).
        self.assertEqual((stockfish["workers_ok"], stockfish["overhead_ms"], stockfish["stockfish_depth"]),
                         (None, None, 14))
        raw = self.con.execute("SELECT overhead_ms FROM v_engine_moves WHERE game_id = 'gWin0001' AND ply = 1")
        self.assertIsNone(raw.fetchone()[0])
        self.assertIsNone(queries.move_detail("gWin0001", 1, con=self.con)["engine_move"]["overhead_ms"])
        self.assertEqual(queries.move_detail("gWin0001", 3, con=self.con)["engine_move"]["overhead_ms"], 50.0)

    def test_move_detail(self) -> None:
        detail = queries.move_detail("gWin0001", 3, con=self.con)
        self.assertEqual((detail["engine_move"]["best_move"], detail["lichess_move"]["san"]), ("g1f3", "Nf3"))
        first, second = detail["workers"]
        self.assertEqual((first["worker"], first["root_moves"], first["unsearched_root_moves"]),
                         (1, ["g1f3", "d2d4"], ["a2a3"]))
        self.assertEqual([depth["depth"] for depth in first["depths"]], [6, 7, 8])
        self.assertEqual(first["depths"][2]["completed"], 0)
        self.assertEqual([candidate["move"] for candidate in first["candidates"]], ["g1f3", "d2d4"])
        self.assertEqual((second["status"], second["error"], second["root_moves"], second["depths"]),
                         ("timeout", "no answer within 1 s", ["b1c3"], []))
        self.assertEqual([(c["move"], c["worker"], c["score"]) for c in detail["candidates"]],
                         [("g1f3", 1, 35), ("b1c3", 2, 22), ("d2d4", 1, 10)])
        self.assertEqual([event["message"] for event in detail["events"]], ["worker 2 timed out"])

    def test_move_detail_of_an_opponent_ply(self) -> None:
        detail = queries.move_detail("gWin0001", 2, con=self.con)
        self.assertIsNone(detail["engine_move"])
        self.assertEqual(detail["lichess_move"]["san"], "e5")
        self.assertEqual((detail["workers"], detail["candidates"], detail["events"]), ([], [], []))

    def test_move_detail_of_the_plan_telemetry_example(self) -> None:
        store_telemetry_line(self.con, load_fixture("plan03_telemetry_example.json")["telemetry"])
        detail = queries.move_detail("tN252leL", 23, con=self.con)
        move = detail["engine_move"]
        self.assertEqual((move["path"], move["best_move"], move["best_score"], move["workers"], move["wtime_ms"],
                          move["allowed_seconds"], move["engine_version"]),
                         ("kernel", "h2h3", -135, 1, 118000, 1, "kernel-2026-10-23"))
        self.assertEqual((move["slowest_search_ms"], move["overhead_ms"]), (226, 7))  # 233 ms total - 226 ms search
        (only,) = detail["workers"]
        self.assertEqual((only["root_moves"], only["depth"], only["nodes"]), (["f1e1", "h2h3"], 8, 2104019))
        self.assertEqual([(d["depth"], d["best_move"], d["score"]) for d in only["depths"]], [(2, "h2h3", -20)])
        self.assertEqual([(c["move"], c["score"], c["exact"], c["depth"]) for c in detail["candidates"]],
                         [("h2h3", -135, 1, 8), ("f1e1", -160, 0, 8)])

    def test_root_moves_that_are_not_json_come_back_as_text(self) -> None:
        with self.con:
            self.con.execute("UPDATE worker_runs SET root_moves = 'g1f3,d2d4' WHERE game_id = 'gWin0001' "
                             "AND ply = 3 AND worker = 1")
        detail = queries.move_detail("gWin0001", 3, con=self.con)
        self.assertEqual(detail["workers"][0]["root_moves"], "g1f3,d2d4")


class TestStatistics(QueriesTestCase):
    """results_by_day(), rating_history(), results_by_opponent_rating() and engine_health()."""

    def test_results_by_day(self) -> None:
        days = {row["local_date"]: row for row in queries.results_by_day(con=self.con)}
        self.assertEqual(list(days), [D1, D2, D3, D4])
        pick = ("games", "wins", "draws", "losses", "aborted", "not_synced", "score_pct")
        self.assertEqual(tuple(days[D1][key] for key in pick), (1, 1, 0, 0, 0, 0, 100.0))
        self.assertEqual(tuple(days[D2][key] for key in pick), (2, 0, 1, 1, 0, 0, 25.0))
        self.assertEqual(tuple(days[D3][key] for key in pick), (3, 0, 1, 0, 1, 1, 50.0))
        self.assertEqual(tuple(days[D4][key] for key in pick), (3, 1, 0, 0, 0, 2, 100.0))
        self.assertEqual([row["local_date"] for row in queries.results_by_day(D2, D3, con=self.con)], [D2, D3])

    def test_a_day_without_synced_games_counts_zero_not_null(self) -> None:
        with self.con:
            self.con.execute("DELETE FROM games WHERE game_id = 'gTimeO07'")  # now only the engine knows it
        (day,) = queries.results_by_day(D4, D4, con=self.con)
        self.assertEqual((day["games"], day["wins"], day["draws"], day["losses"], day["aborted"], day["not_synced"]),
                         (3, 0, 0, 0, 0, 3))
        self.assertIsNone(day["score_pct"])

    def test_rating_history(self) -> None:
        history = queries.rating_history(con=self.con)
        self.assertEqual([(row["game_id"], row["our_rating"], row["our_rating_diff"], row["rating_after"])
                          for row in history],
                         [("gWin0001", 1800, 8, 1808), ("gLoss002", 1790, -7, 1783), ("gTimeO07", 1830, 5, 1835)])
        self.assertEqual(history[0]["local_date"], D1)
        self.assertEqual([row["game_id"] for row in queries.rating_history("bullet", con=self.con)], ["gLoss002"])

    def test_results_by_opponent_rating(self) -> None:
        buckets = queries.results_by_opponent_rating(con=self.con)
        self.assertEqual([(b["rating_from"], b["rating_to"], b["games"], b["wins"], b["draws"], b["losses"],
                           b["score_pct"]) for b in buckets],
                         [(1500, 1599, 2, 2, 0, 0, 100.0), (1600, 1699, 1, 0, 1, 0, 50.0),
                          (1900, 1999, 1, 0, 0, 1, 0.0), (2400, 2499, 1, 0, 1, 0, 50.0)])
        wide = queries.results_by_opponent_rating(500, con=self.con)
        self.assertEqual([(b["rating_from"], b["games"], b["score_pct"]) for b in wide],
                         [(1500, 4, 62.5), (2000, 1, 50.0)])
        for bad in (0, -100, 2.5):
            with self.subTest(bucket=bad), self.assertRaises(ValueError):
                queries.results_by_opponent_rating(bad, con=self.con)

    def test_engine_health(self) -> None:
        health = queries.engine_health(con=self.con)
        self.assertEqual([row["game_id"] for row in health], ["gEngHum8", "gTimeO07", "gEngOnly", "gLoss002",
                                                              "gWin0001"])
        win = health[-1]
        self.assertEqual((win["engine_moves"], win["kernel_moves"], win["max_move_ms"], win["worker_timeouts"],
                          win["worker_failures"], win["max_depth"], win["engine_version"]),
                         (3, 2, 900.0, 1, 0, 8, "build-A"))
        self.assertAlmostEqual(win["avg_move_ms"], (120 + 900 + 400) / 3)
        # The Stockfish move (no worker, so its "overhead" is the whole move) is left out of the overhead.
        self.assertEqual((win["avg_overhead_ms"], win["max_overhead_ms"]), (50.0, 50.0))
        loss = health[-2]
        self.assertEqual((loss["avg_overhead_ms"], loss["worker_failures"], loss["kernel_moves"]), (150.0, 1, 0))
        self.assertEqual([row["game_id"] for row in queries.engine_health(2, con=self.con)], ["gEngHum8", "gTimeO07"])
        self.assertEqual(queries.engine_health(0, con=self.con), [])
        with self.assertRaises(ValueError):
            queries.engine_health(-1, con=self.con)

    def test_engine_health_agrees_with_the_games_and_their_moves(self) -> None:
        """Every figure, recomputed in Python from game_overview() and engine_moves()."""
        telemetry = load_fixture("plan03_telemetry_example.json")["telemetry"]
        add_engine_game(self.con, telemetry["gameId"], telemetry["receivedAt"], engine_version="kernel-2026-10-23")
        store_telemetry_line(self.con, telemetry)
        health = queries.engine_health(100, con=self.con)
        self.assertEqual([row["game_id"] for row in health],
                         [row["game_id"] for row in queries.list_games(limit=None, con=self.con)
                          if row["engine_moves"] is not None])
        for row in health:
            with self.subTest(game=row["game_id"]):
                game = queries.game_overview(row["game_id"], con=self.con)
                for key in ("started_at", "local_date", "engine_version", "result", "engine_moves", "kernel_moves",
                            "avg_move_ms", "max_move_ms", "worker_timeouts", "worker_failures", "max_depth"):
                    self.assertEqual(row[key], game[key], key)
                overheads = [move["overhead_ms"] for move in queries.engine_moves(row["game_id"], con=self.con)
                             if move["overhead_ms"] is not None]
                self.assertEqual(row["max_overhead_ms"], max(overheads, default=None))
                if overheads:
                    self.assertAlmostEqual(row["avg_overhead_ms"], sum(overheads) / len(overheads))
                else:
                    self.assertIsNone(row["avg_overhead_ms"])


LOCAL_GAME = "local-1793170800000"  # what Engine UCI stores for a game played without a GameId


class TestMoreFilters(QueriesTestCase):
    """The opening, crash-signal and local-game filters, and filters given as text (a web form's values)."""

    def setUp(self) -> None:
        """The dataset, plus a game played by hand in which every Kernel worker of a move timed out."""
        super().setUp()
        add_engine_game(self.con, LOCAL_GAME, local_ms(2026, 10, 23, 12), engine_version="build-A")
        add_engine_move(self.con, LOCAL_GAME, 5, path="no_kernel_answer", t_total_ms=3100.0, stockfish_depth=14,
                        workers=(worker(1, status="timeout", depth=None, search_ms=None),
                                 worker(2, status="timeout", depth=None, search_ms=None)))

    def test_opening_name_part_and_eco(self) -> None:
        self.assertEqual(self.listed(opening="italian"), {"gWin0001"})
        self.assertEqual(self.listed(opening="SICILIAN def"), {"gDraw003"})
        self.assertEqual(self.listed(opening="e"), {"gWin0001", "gDraw003"})
        self.assertEqual(self.listed(opening=""), ALL | {LOCAL_GAME})
        self.assertEqual(self.listed(opening_eco="C50"), {"gWin0001"})
        self.assertEqual(self.listed(opening_eco=["B20", "C50"]), {"gWin0001", "gDraw003"})

    def test_crash_signals(self) -> None:
        self.assertEqual(self.listed(had_no_kernel_answer=True), {LOCAL_GAME})
        self.assertEqual(self.listed(had_no_kernel_answer=False), ALL)
        self.assertEqual(self.listed(had_worker_failures=True), {"gLoss002"})  # a dead worker
        self.assertEqual(self.listed(had_worker_failures=False), ALL - {"gLoss002"} | {LOCAL_GAME})
        self.assertEqual(self.listed(had_timeouts=True), {"gWin0001", LOCAL_GAME})

    def test_local_games(self) -> None:
        self.assertEqual(self.listed(local=True), {LOCAL_GAME})
        self.assertEqual(self.listed(local=False), ALL)
        self.assertEqual(self.listed(synced=False), ENGINE_ONLY | {LOCAL_GAME})
        self.assertEqual(self.listed(synced=False, local=False), ENGINE_ONLY)  # really waiting for the sync

    def test_results_by_day_can_leave_the_local_games_out(self) -> None:
        def day(**options: Any) -> tuple:
            (row,) = queries.results_by_day(D4, D4, con=self.con, **options)
            return row["games"], row["wins"], row["not_synced"]

        self.assertEqual(day(), (4, 1, 3))
        self.assertEqual(day(local=False), (3, 1, 2))
        self.assertEqual(day(local=True), (1, 0, 1))

    def test_no_overhead_when_every_worker_timed_out(self) -> None:
        (move,) = queries.engine_moves(LOCAL_GAME, con=self.con)
        self.assertEqual((move["path"], move["workers_failed"], move["slowest_search_ms"], move["overhead_ms"]),
                         ("no_kernel_answer", 2, None, None))

    def test_numbers_given_as_text_are_converted(self) -> None:
        for name, number in (("opponent_rating_min", 1600), ("opponent_rating_max", 1500),
                             ("rating_diff_min", 0), ("rating_diff_max", -1)):
            expected = self.listed(**{name: number})
            for text in (str(number), f" {number} ", f"{number}.0"):
                with self.subTest(name=name, text=text):
                    self.assertEqual(self.listed(**{name: text}), expected)
        self.assertEqual(self.listed(opponent_rating_min="1600"), {"gLoss002", "gDraw003", "gCorr004", "gEngOnly",
                                                                    "gAbort06"})
        self.assertEqual(self.listed(opponent_rating_max=1499.5), {"gEngHum8"})  # a float stays a float

    def test_text_that_is_not_a_number_is_refused(self) -> None:
        for name in ("opponent_rating_min", "opponent_rating_max", "rating_diff_min", "rating_diff_max"):
            for bad in ("abc", "", "1500 elo", "nan", "inf", True, [1500]):
                with self.subTest(name=name, value=bad), self.assertRaises(ValueError):
                    queries.count_games(con=self.con, **{name: bad})

    def test_true_false_filters_refuse_text(self) -> None:
        flags = ("rated", "lost_on_time", "had_stalemate_override", "had_no_kernel_answer", "had_timeouts",
                 "had_worker_failures", "synced", "local")
        for name in flags:
            for bad in ("false", "False", "0", "no", "True", "", 2):
                with self.subTest(name=name, value=bad), self.assertRaises(ValueError):
                    queries.count_games(con=self.con, **{name: bad})
            with self.subTest(name=name):  # 1 and 0 still mean True and False
                self.assertEqual(self.listed(**{name: 1}), self.listed(**{name: True}))
                self.assertEqual(self.listed(**{name: 0}), self.listed(**{name: False}))


class TestEvents(QueriesTestCase):
    """game_events() and recent_events(): the events move_detail() can't show."""

    def setUp(self) -> None:
        """The dataset, plus the fatal event Engine UCI stores without a ply."""
        super().setUp()
        add_event(self.con, local_ms(2026, 10, 21, 12, 5), "gLoss002", None,
                  "go failed: Stockfish died twice  -> exiting", level="error", source="engine")

    def test_game_events_include_the_ones_without_a_ply(self) -> None:
        events = queries.game_events("gLoss002", con=self.con)
        self.assertEqual([(event["ply"], event["message"]) for event in events],
                         [(4, "worker 2 died"), (None, "go failed: Stockfish died twice  -> exiting")])
        shown = [event["message"] for ply in range(0, 50)
                 for event in queries.move_detail("gLoss002", ply, con=self.con)["events"]]
        self.assertEqual(shown, ["worker 2 died"])  # the reason game_events() exists
        self.assertEqual(queries.game_events("noSuchGm", con=self.con), [])

    def test_recent_events_newest_first(self) -> None:
        events = queries.recent_events(con=self.con)
        self.assertEqual([event["message"] for event in events],
                         ["go failed: Stockfish died twice  -> exiting", "worker 2 died", "an event of another ply",
                          "worker 2 timed out", "engine started"])
        self.assertIsNone(events[-1]["game_id"])  # an event of no game is listed too
        self.assertEqual([event["message"] for event in queries.recent_events(limit=2, con=self.con)],
                         ["go failed: Stockfish died twice  -> exiting", "worker 2 died"])
        self.assertEqual(len(queries.recent_events(limit=None, con=self.con)), 5)
        self.assertEqual(queries.recent_events(limit=0, con=self.con), [])
        with self.assertRaises(ValueError):
            queries.recent_events(limit=-1, con=self.con)

    def test_recent_events_by_level(self) -> None:
        self.assertEqual([event["message"] for event in queries.recent_events("error", con=self.con)],
                         ["go failed: Stockfish died twice  -> exiting", "worker 2 died"])
        self.assertEqual({event["level"] for event in queries.recent_events(["info", "error"], con=self.con)},
                         {"info", "error"})
        self.assertEqual(len(queries.recent_events([], con=self.con)), 5)  # an empty choice filters nothing


if __name__ == "__main__":
    unittest.main()
