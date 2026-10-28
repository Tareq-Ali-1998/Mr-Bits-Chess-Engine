"""
Tests of sync_lichess.py: lichess game JSON -> games / moves rows, the think times, storing, the cursor, the API
passes (with a fake session: no network), the token handling and the command line.
"""
import contextlib
import io
import json
import logging
import os
import statistics
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import chess
import chess.variant

from helpers import (DUMMY_TOKEN, DatabaseTestCase, FakeResponse, FakeSession, account, add_engine_game,
                     api_examples, load_fixture, local_ms, run_main, synthetic_game, synthetic_games, write_ndjson)
from helpers import sync_lichess as sync

STORED_SYNTHETIC = [game for game in synthetic_games() if "skip" not in game["_expected"]]


def example(game_id: str) -> dict[str, Any]:
    """One of the two official lichess API examples."""
    return next(game for game in api_examples() if game["id"] == game_id)


class CollectLogs(logging.Handler):
    """Keeps every log record (to check that no output ever shows the token)."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep the formatted message."""
        self.messages.append(record.getMessage())


# ############################################################################
# lichess JSON -> rows
# ############################################################################

class TestGameRow(unittest.TestCase):
    """game_row() and game_result()."""

    def test_official_casual_example_seen_by_black(self) -> None:
        row = sync.game_row(example("WFZ8aZWA"), "lance5500", synced_at=123)
        self.assertEqual(set(row), set(sync.GAME_COLUMNS))
        expected = {
            "game_id": "WFZ8aZWA", "created_at": 1789840707868, "last_move_at": 1789841896663, "rated": 0,
            "variant": "standard", "source": "simul", "initial_fen": None, "speed": "blitz",
            "clock_initial_s": 300, "clock_increment_s": 3, "our_color": "black", "opponent_id": "furo951",
            "opponent_name": "Furo951", "opponent_title": None, "our_rating": 2552, "our_rating_diff": None,
            "opponent_rating": 1775, "opponent_rating_diff": None, "our_accuracy": 92, "opponent_accuracy": 86,
            "result": "win", "status": "resign", "opening_eco": "D31",
            "opening_name": "Queen's Gambit Declined: Charousek Variation", "plies": 82, "pgn": None,
            "synced_at": 123}
        self.assertEqual(row, expected)

    def test_official_rated_draw_seen_by_white(self) -> None:
        row = sync.game_row(example("q7ZvsdUF"), "lance5500", synced_at=0)
        self.assertEqual((row["our_color"], row["result"], row["status"], row["rated"]), ("white", "draw", "draw", 1))
        self.assertEqual((row["our_rating"], row["our_rating_diff"]), (2389, 4))
        self.assertEqual((row["opponent_id"], row["opponent_title"], row["opponent_rating"],
                          row["opponent_rating_diff"]), ("tryinghard87", None, 2498, -4))
        self.assertEqual((row["our_accuracy"], row["opponent_accuracy"], row["plies"]), (90, 90, 125))

    def test_the_same_game_seen_by_the_other_player(self) -> None:
        row = sync.game_row(example("q7ZvsdUF"), "TryingHard87", synced_at=0)  # any case
        self.assertEqual((row["our_color"], row["our_rating_diff"], row["opponent_id"], row["opponent_title"]),
                         ("black", -4, "lance5500", "LM"))

    def test_a_game_the_bot_did_not_play(self) -> None:
        with self.assertRaises(sync.NotOurGameError):
            sync.game_row(example("q7ZvsdUF"), "mr_bits", synced_at=0)

    def test_results(self) -> None:
        cases = [("mate", "white", "white", "win"), ("resign", "black", "white", "loss"),
                 ("outoftime", "white", "black", "loss"), ("outoftime", None, "white", "draw"),
                 ("timeout", "black", "black", "win"), ("draw", None, "white", "draw"),
                 ("stalemate", None, "black", "draw"), ("aborted", None, "white", "aborted"),
                 ("noStart", None, "black", "aborted"), ("noStart", "white", "black", "loss"),
                 ("insufficientMaterialClaim", None, "white", "draw")]
        for status, winner, our_color, expected in cases:
            with self.subTest(status=status, winner=winner, our_color=our_color):
                self.assertEqual(sync.game_result(status, winner, our_color), expected)

    def test_bot_stream_shapes_are_accepted(self) -> None:
        game = dict(synthetic_game("syn00002"), variant={"key": "standard"}, initialFen="startpos")
        row = sync.game_row(game, "mr_bits", synced_at=0)
        self.assertEqual((row["variant"], row["initial_fen"]), ("standard", None))

    def test_correspondence_has_no_clock(self) -> None:
        row = sync.game_row(synthetic_game("syn00014"), "mr_bits", synced_at=0)
        self.assertEqual((row["clock_initial_s"], row["clock_increment_s"], row["speed"]),
                         (None, None, "correspondence"))


class TestMoves(unittest.TestCase):
    """move_rows(), think_times() and game_ended_by_last_move()."""

    def test_official_examples_replay_from_san_to_uci(self) -> None:
        for game, color in ((example("q7ZvsdUF"), "white"), (example("WFZ8aZWA"), "black")):
            with self.subTest(game=game["id"]):
                rows = sync.move_rows(game, color)
                sans = game["moves"].split()
                self.assertEqual([row[1] for row in rows], list(range(1, len(sans) + 1)))
                self.assertEqual([row[4] for row in rows], sans)
                self.assertEqual([row[2] for row in rows], [int((ply % 2 == 1) == (color == "white"))
                                                             for ply in range(1, len(sans) + 1)])
                castles = {row[4]: row[3] for row in rows if row[4].startswith("O-O")}
                self.assertTrue(castles)
                self.assertTrue(set(castles.values()) <= {"e1g1", "e8g8", "e1c1", "e8c8"})
                board = chess.Board()
                for row in rows:  # the UCI moves replay to the same game
                    board.push_uci(row[3])
                self.assertEqual(len(board.move_stack), len(sans))
                self.assertTrue(all(row[5] is None and row[6] is None for row in rows))  # no clocks in the examples

    def test_synthetic_games_match_their_hand_computed_answers(self) -> None:
        for game in STORED_SYNTHETIC:
            expected = game["_expected"]
            with self.subTest(game=game["id"], case=game["_case"]):
                row = sync.game_row(game, "mr_bits", synced_at=0)
                rows = sync.move_rows(game, row["our_color"])
                self.assertEqual((row["result"], row["our_color"], row["plies"]),
                                 (expected["result"], expected["our_color"], expected["plies"]))
                self.assertEqual([r[1] for r in rows], list(range(1, row["plies"] + 1)))
                self.assertEqual([r[2] for r in rows], expected["by_us"])
                self.assertEqual([r[5] for r in rows], expected["clock_cs"])
                self.assertEqual([r[6] for r in rows], expected["think_ms"])
                if "first_uci" in expected:
                    self.assertEqual(rows[0][3], expected["first_uci"])

    def test_clocks_that_do_not_fit_the_moves_are_left_out_with_a_warning(self) -> None:
        with self.assertLogs(sync.logger, "WARNING") as logs:
            rows = sync.move_rows(synthetic_game("syn00012"), "white")
        self.assertIn("2 clock values for 3 plies", logs.output[0])
        self.assertEqual([(r[5], r[6]) for r in rows], [(None, None)] * 3)

    def test_n_plus_one_clocks_ignore_the_extra_one(self) -> None:
        rows = sync.move_rows(synthetic_game("syn00003"), "white")
        self.assertEqual([r[5] for r in rows], [18000, 18000, 17900, 300, 17700])

    def test_think_times_formula(self) -> None:
        clocks = [18000, 18000, 17900, 17800, 17500]
        self.assertEqual(sync.think_times(clocks, 2000, ended_by_last_move=False), [None, None, 3000, 4000, 6000])
        self.assertEqual(sync.think_times(clocks, 2000, ended_by_last_move=True), [None, None, 3000, 4000, 4000])
        self.assertEqual(sync.think_times([6000, 6000], 1000, ended_by_last_move=True), [None, None])
        self.assertEqual(sync.think_times([], 1000, ended_by_last_move=False), [])
        # One increment per ply (Black's are 0: he berserked): ply 4 is 180 s - 178 s = 2 s, without 2 s more.
        self.assertEqual(sync.think_times(clocks, [2000, 0, 2000, 0, 2000], ended_by_last_move=False),
                         [None, None, 3000, 2000, 6000])

    def test_a_player_who_berserked_gets_no_increment(self) -> None:
        """Arena: berserk halves the player's clock and cancels his increment (lichess sends "berserk": true)."""
        game = {"id": "arena001", "rated": True, "variant": "standard", "speed": "blitz", "perf": "blitz",
                "createdAt": 1793200000000, "lastMoveAt": 1793200300000, "status": "resign", "source": "arena",
                "winner": "white", "moves": "e4 e5 Nf3 Nc6 Bc4",
                "players": {"white": {"user": {"name": "Mr_Bits", "title": "BOT", "id": "mr_bits"}, "rating": 1800},
                            "black": {"user": {"name": "Rusher", "id": "rusher"}, "rating": 1700, "berserk": True}},
                "clock": {"initial": 180, "increment": 2, "totalTime": 260},  # 3+2; Black starts on 90 s
                "clocks": [18000, 9000, 17700, 8500, 17400]}
        # Ply 3 (White): 180 s - 177 s + 2 s = 5 s. Ply 4 (Black, berserk): 90 s - 85 s = 5 s, no increment.
        # Ply 5 (White): 177 s - 174 s + 2 s = 5 s.
        self.assertEqual([row[6] for row in sync.move_rows(game, "white")], [None, None, 5000, 5000, 5000])
        game["players"]["black"]["berserk"] = False
        self.assertEqual([row[6] for row in sync.move_rows(game, "white")], [None, None, 5000, 7000, 5000])
        game["players"]["black"].pop("berserk")  # (outside arenas lichess doesn't send the field at all)
        self.assertEqual([row[6] for row in sync.move_rows(game, "white")], [None, None, 5000, 7000, 5000])
        game["players"]["white"]["berserk"] = True  # the bot itself can berserk too
        game["clocks"] = [9000, 18000, 8700, 17500, 8400]
        self.assertEqual([row[6] for row in sync.move_rows(game, "white")], [None, None, 3000, 7000, 3000])

    def test_which_last_moves_end_the_game_themselves(self) -> None:
        start = chess.Board()
        kings_only = chess.Board("8/8/4k3/8/8/4K3/8/8 b - - 0 1")
        fifty_moves = chess.Board("8/8/4k3/8/8/4K3/8/4R3 b - - 100 90")
        fivefold = chess.Board()
        for _ in range(4):
            for uci in ("g1f3", "g8f6", "f3g1", "f6g8"):
                fivefold.push_uci(uci)
        for status in ("mate", "stalemate", "variantEnd"):
            self.assertTrue(sync.game_ended_by_last_move(status, start), status)
        self.assertTrue(sync.game_ended_by_last_move("draw", kings_only))
        self.assertTrue(sync.game_ended_by_last_move("draw", fifty_moves))
        self.assertTrue(sync.game_ended_by_last_move("draw", fivefold))
        self.assertFalse(sync.game_ended_by_last_move("draw", start))  # agreed or claimed: the game went on
        for status in ("resign", "outoftime", "timeout", "aborted", "insufficientMaterialClaim"):
            self.assertFalse(sync.game_ended_by_last_move(status, kings_only), status)

    def test_variants_and_unreadable_moves(self) -> None:
        fen960 = "bqnb1rkr/pp3ppp/3ppn2/2p5/5P2/P2P4/NPP1P1PP/BQ1BNRKR w HFhf - 2 9"
        self.assertTrue(sync._start_board("chess960", fen960).chess960)
        self.assertIsInstance(sync._start_board("atomic", None), chess.variant.AtomicBoard)
        self.assertEqual(sync._start_board("fromPosition", "8/8/4k3/8/8/4K3/8/8 w - - 0 1").fen(),
                         "8/8/4k3/8/8/4K3/8/8 w - - 0 1")
        with self.assertRaises(ValueError):
            sync._start_board("noSuchVariant", None)
        with self.assertRaisesRegex(ValueError, r"ply 2 \(Ke2\)"):
            sync.move_rows(dict(synthetic_game("syn00002"), moves="e4 Ke2"), "white")

    def test_think_times_of_a_real_game_match_the_wall_clock(self) -> None:
        """Game tN252leL (2+3, won by mate), rebuilt from lichess-bot's log with the bot's real clocks."""
        fixture = load_fixture("real_tN252leL.json")
        game = fixture["game"]
        row = sync.game_row(game, "mr_bits", synced_at=0)
        think = {r[1]: r[6] for r in sync.move_rows(game, row["our_color"])}
        self.assertEqual((row["our_color"], row["result"], row["status"], row["plies"]), ("white", "win", "mate", 137))
        self.assertEqual((think[1], think[2], think[3], think[4]), (None, None, 2960, 310))
        wall = {int(ply): ms for ply, ms in fixture["our_wall_ms"].items() if int(ply) >= 3}
        differences = [think[ply] - wall[ply] for ply in wall]
        self.assertEqual(len(differences), 68)
        self.assertLessEqual(abs(statistics.median(differences)), 20)
        self.assertGreaterEqual(sum(abs(d) <= 100 for d in differences), 60)
        # The mating move: 1670 ms charged, 1639 ms measured; with the increment it would be 3 s off.
        self.assertEqual(think[137], 1670)
        self.assertLess(abs(think[137] - wall[137]), 100)


# ############################################################################
# Storing
# ############################################################################

class TestStore(DatabaseTestCase):
    """import_games(), store_game() and --from-file."""

    def count(self, table: str, where: str = "1", *params: Any) -> int:
        """Rows of a table."""
        return self.con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]

    def test_game_columns_cover_the_games_table(self) -> None:
        columns = [row[1] for row in self.con.execute("PRAGMA table_info(games)")]
        self.assertEqual(list(sync.GAME_COLUMNS), columns)

    def test_file_import_end_to_end(self) -> None:
        path = write_ndjson(self.tmp / "games.ndjson", synthetic_games())
        code, out, err = run_main(sync.main, ["--from-file", str(path), "--user", "Mr_Bits"])
        self.assertEqual(code, 0, err)
        self.assertIn("lichess sync: 12 games inserted, 0 updated, 52 moves written; skipped: 1 still running, "
                      "1 not played by the bot, 0 with errors", out)
        self.assertEqual(self.count("games"), 12)
        self.assertEqual(self.count("moves"), 52)
        self.assertEqual(self.count("games", "game_id IN ('syn00010', 'syn00011')"), 0)
        self.assertEqual(self.con.execute("SELECT think_ms FROM moves WHERE game_id = 'syn00009' AND ply = 3")
                         .fetchone()[0], 1200)
        self.assertEqual(self.count("sync_state"), 0)  # a file import never moves the API cursor
        overview = self.con.execute("SELECT time_control, lost_on_time, opponent_kind FROM v_games "
                                    "WHERE game_id = 'syn00004'").fetchone()
        self.assertEqual(tuple(overview), ("1+0", 1, "bot"))

    def test_a_second_import_updates_and_replaces_the_moves(self) -> None:
        summary = sync.Summary()
        sync.import_games(self.con, synthetic_games(), "mr_bits", summary)
        shorter = dict(synthetic_game("syn00001"), moves="e4 e5 Nf3", clocks=[18000, 18000, 17850], status="draw")
        shorter.pop("winner")
        again = sync.Summary()
        sync.import_games(self.con, [shorter], "mr_bits", again)
        self.assertEqual((again.inserted, again.updated, again.moves), (0, 1, 3))
        self.assertEqual(self.count("moves", "game_id = 'syn00001'"), 3)
        self.assertEqual(tuple(self.con.execute("SELECT result, plies FROM games WHERE game_id = 'syn00001'")
                               .fetchone()), ("draw", 3))
        self.assertEqual(self.count("moves"), 52 - 3)

    def test_a_reimport_without_accuracy_opening_or_pgn_keeps_them(self) -> None:
        game = dict(example("WFZ8aZWA"), pgn="[Event \"x\"] 1. d4")
        sync.import_games(self.con, [game], "lance5500", sync.Summary())
        bare = dict(game)
        bare.pop("opening")
        bare.pop("pgn")
        bare["players"] = {color: {k: v for k, v in side.items() if k != "analysis"}
                           for color, side in game["players"].items()}
        bare["status"] = "outoftime"
        sync.import_games(self.con, [bare], "lance5500", sync.Summary())
        row = self.con.execute("SELECT our_accuracy, opponent_accuracy, opening_eco, pgn, status FROM games").fetchone()
        self.assertEqual(tuple(row), (92, 86, "D31", "[Event \"x\"] 1. d4", "outoftime"))

    def stored_moves(self, game_id: str) -> list[tuple[Any, ...]]:
        """(ply, uci, clock_cs, think_ms) of every stored ply of a game."""
        return [tuple(row) for row in self.con.execute(
            "SELECT ply, uci, clock_cs, think_ms FROM moves WHERE game_id = ? ORDER BY ply", (game_id,))]

    def test_a_reimport_without_clocks_keeps_the_stored_clocks(self) -> None:
        full = synthetic_game("syn00002")
        sync.import_games(self.con, [full], "mr_bits", sync.Summary())  # the sync asks for clocks=true
        before = self.stored_moves("syn00002")
        self.assertEqual(before[2], (3, "f1c4", 5950, 1500))
        without_clocks = {key: value for key, value in full.items() if key != "clocks"}  # lichess's default
        path = write_ndjson(self.tmp / "no-clocks.ndjson", [without_clocks])
        code, out, err = run_main(sync.main, ["--from-file", str(path), "--user", "mr_bits"])
        self.assertEqual(code, 0, err)
        self.assertIn("0 games inserted, 1 updated, 7 moves written", out)
        self.assertEqual(self.stored_moves("syn00002"), before)

    def test_a_reimport_without_moves_keeps_the_moves_and_their_number(self) -> None:
        full = synthetic_game("syn00002")
        sync.import_games(self.con, [full], "mr_bits", sync.Summary())
        before = self.stored_moves("syn00002")
        without_moves = {key: value for key, value in full.items() if key not in ("moves", "clocks")}  # moves=false
        summary = sync.Summary()
        sync.import_games(self.con, [dict(without_moves, status="outoftime")], "mr_bits", summary)
        self.assertEqual((summary.updated, summary.moves, summary.errors), (1, 0, 0))
        self.assertEqual(self.stored_moves("syn00002"), before)
        self.assertEqual(tuple(self.con.execute("SELECT plies, status FROM games").fetchone()), (7, "outoftime"))
        new_game = dict(without_moves, id="noMoves1")  # never stored before: no moves, plies unknown
        sync.import_games(self.con, [new_game], "mr_bits", sync.Summary())
        self.assertEqual(self.con.execute("SELECT plies FROM games WHERE game_id = 'noMoves1'").fetchone()[0], None)
        self.assertEqual(self.stored_moves("noMoves1"), [])

    def test_a_reimport_without_clocks_keeps_only_the_clocks_of_the_same_moves(self) -> None:
        sync.import_games(self.con, [synthetic_game("syn00002")], "mr_bits", sync.Summary())
        other = dict(synthetic_game("syn00002"), moves="e4 e5 Nf3", status="resign", winner="black")
        other.pop("clocks")
        sync.import_games(self.con, [other], "mr_bits", sync.Summary())
        self.assertEqual(self.stored_moves("syn00002"),
                         [(1, "e2e4", 6000, None), (2, "e7e5", 6000, None), (3, "g1f3", None, None)])

    def test_a_game_without_an_id_is_refused(self) -> None:
        add_engine_game(self.con, "AbCd1234", first_move_at=1)
        summary = sync.Summary()
        no_moves = synthetic_game("syn00007")  # noStart: no move row could fail, so the games row would stay
        with self.assertLogs(sync.logger, "WARNING") as logs:
            sync.import_games(self.con, [dict(no_moves, id=None), dict(no_moves, id=""), dict(no_moves, id=7)],
                              "mr_bits", summary)
        self.assertEqual((summary.inserted, summary.errors), (0, 3))
        self.assertIn("no game id", logs.output[0])
        self.assertEqual(self.count("games"), 0)
        self.assertEqual(sync.missing_engine_games(self.con), ["AbCd1234"])

    def test_lines_that_are_not_games_are_skipped_even_without_user(self) -> None:
        path = self.tmp / "mixed.ndjson"
        not_games = '[1, 2]\nnull\n5\n"x"\n{"id": "brokenP1", "createdAt": 1, "players": [1, 2]}\n'
        path.write_text("".join(json.dumps(game) + "\n" for game in api_examples()) + not_games, encoding="utf-8")
        with self.assertLogs(sync.logger, "WARNING"):
            code, out, err = run_main(sync.main, ["--from-file", str(path)])  # the bot is still found: lance5500
        self.assertEqual(code, 0, err)
        self.assertIn("2 games inserted", out)
        self.assertIn("5 with errors", out)

    def test_games_with_a_broken_structure_are_skipped(self) -> None:
        good = synthetic_game("syn00002")
        broken = [dict(good, id="brokenP1", players=[1, 2]),
                  dict(good, id="brokenP2", players={"white": "Mr_Bits", "black": good["players"]["black"]}),
                  dict(good, id="brokenC1", clock="1+1"),
                  dict(good, id="brokenO1", opening="Bishop's Opening")]
        path = write_ndjson(self.tmp / "broken.ndjson", broken + [good])
        with self.assertLogs(sync.logger, "WARNING"):
            code, out, err = run_main(sync.main, ["--from-file", str(path), "--user", "mr_bits"])
        self.assertEqual(code, 0, err)
        self.assertIn("1 games inserted", out)
        self.assertIn("4 with errors", out)
        self.assertEqual([row[0] for row in self.con.execute("SELECT game_id FROM games")], ["syn00002"])

    def test_a_game_and_its_moves_are_one_transaction(self) -> None:
        broken_moves = [("syn00002", 1, 1, "e2e4", "e4", None, None)] * 2  # the same ply twice: refused
        summary = sync.Summary()
        with mock.patch.object(sync, "move_rows", return_value=broken_moves):
            with self.assertLogs(sync.logger, "WARNING"):
                sync.import_games(self.con, [synthetic_game("syn00002")], "mr_bits", summary)
        self.assertEqual((summary.inserted, summary.errors), (0, 1))
        self.assertEqual(self.count("games"), 0)  # the games row was rolled back with the moves
        self.assertEqual(self.count("moves"), 0)

    def test_a_broken_game_does_not_stop_the_others(self) -> None:
        broken = dict(synthetic_game("syn00002"), id="broken01", moves="e4 Ke2")
        no_date = dict(synthetic_game("syn00002"), id="broken02")
        no_date.pop("createdAt")
        summary = sync.Summary()
        with self.assertLogs(sync.logger, "WARNING") as logs:
            sync.import_games(self.con, [broken, no_date, synthetic_game("syn00013")], "mr_bits", summary)
        self.assertEqual((summary.inserted, summary.errors), (1, 2))
        self.assertIn("broken01", logs.output[0])

    def test_dry_run_writes_nothing(self) -> None:
        path = write_ndjson(self.tmp / "games.ndjson", synthetic_games())
        code, out, _ = run_main(sync.main, ["--from-file", str(path), "--user", "mr_bits", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("dry run, nothing written): 12 games to insert, 0 to update, 52 moves", out)
        self.assertEqual((self.count("games"), self.count("moves"), self.count("sync_state")), (0, 0, 0))

    def test_the_bot_is_inferred_from_the_file(self) -> None:
        path = self.tmp / "examples.ndjson"
        write_ndjson(path, api_examples())
        code, out, err = run_main(sync.main, ["--from-file", str(path)])
        self.assertEqual(code, 0, err)
        rows = self.con.execute("SELECT game_id, our_color FROM games ORDER BY game_id").fetchall()
        self.assertEqual([tuple(row) for row in rows], [("WFZ8aZWA", "black"), ("q7ZvsdUF", "white")])

    def test_an_ambiguous_file_needs_user(self) -> None:
        path = write_ndjson(self.tmp / "one.ndjson", [synthetic_game("syn00002")])
        code, _, err = run_main(sync.main, ["--from-file", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("--user", err)
        self.assertEqual(self.count("games"), 0)

    def test_a_file_import_never_reads_the_token_or_uses_the_network(self) -> None:
        path = write_ndjson(self.tmp / "games.ndjson", api_examples())
        with mock.patch.object(sync, "load_token", side_effect=AssertionError("token read")), \
                mock.patch.object(sync, "make_session", side_effect=AssertionError("network used")):
            code, _, err = run_main(sync.main, ["--from-file", str(path)])
        self.assertEqual(code, 0, err)

    def test_an_empty_file_imports_nothing(self) -> None:
        path = self.tmp / "empty.ndjson"
        path.write_text("\n", encoding="utf-8")
        code, out, _ = run_main(sync.main, ["--from-file", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("0 games inserted", out)

    def test_a_broken_line_is_named(self) -> None:
        path = self.tmp / "broken.ndjson"
        path.write_text('{"id": "x"}\n\nnot json\n', encoding="utf-8")
        code, _, err = run_main(sync.main, ["--from-file", str(path), "--user", "mr_bits"])
        self.assertEqual(code, 1)
        self.assertIn("line 3", err)

    def test_a_file_with_a_byte_order_mark_is_read(self) -> None:
        path = self.tmp / "bom.ndjson"
        path.write_text("﻿" + "".join(json.dumps(game) + "\n" for game in api_examples()), encoding="utf-8")
        self.assertEqual(len(sync.read_ndjson_file(path)), 2)

    def test_options_that_do_not_go_together(self) -> None:
        for argv in (["--user", "mr_bits"], ["--from-file", "x.ndjson", "--since", "2026-10-27"],
                     ["--since", "2026-13-01"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                run_main(sync.parse_args, argv)

    def test_no_database_yet(self) -> None:
        with mock.patch.object(sync.db, "DB_PATH", self.tmp / "missing.sqlite"):
            code, _, err = run_main(sync.main, ["--from-file", "x.ndjson", "--user", "mr_bits"])
        self.assertEqual(code, 1)
        self.assertIn("db.py --init", err)


# ############################################################################
# Cursor
# ############################################################################

class TestCursor(DatabaseTestCase):
    """choose_since() and update_cursor()."""

    def test_since_order(self) -> None:
        week_ago = local_ms(*(date.today() - timedelta(days=7)).timetuple()[:3])
        self.assertEqual(sync.choose_since(self.con), week_ago)
        add_engine_game(self.con, "first001", first_move_at=local_ms(2026, 10, 25, 14))
        add_engine_game(self.con, "second01", first_move_at=local_ms(2026, 10, 26, 9))
        self.assertEqual(sync.choose_since(self.con), local_ms(2026, 10, 25, 14) - sync.DAY_MS)
        with self.con:
            self.con.execute("INSERT INTO sync_state (source, cursor, updated_at) "
                             "VALUES ('lichess', '1793000000000', 0)")
        self.assertEqual(sync.choose_since(self.con), 1793000000000)
        self.assertEqual(sync.choose_since(self.con, date(2026, 10, 27)), local_ms(2026, 10, 27))
        self.assertEqual(sync.choose_since(self.con, date(2001, 1, 1)), sync.LICHESS_MIN_SINCE_MS)

    def test_cursor_is_the_newest_game_minus_a_day(self) -> None:
        self.assertIsNone(sync.update_cursor(self.con))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sync_state").fetchone()[0], 0)
        sync.import_games(self.con, [synthetic_game("syn00001"), synthetic_game("syn00013")], "mr_bits",
                          sync.Summary())
        cursor = sync.update_cursor(self.con)
        self.assertEqual(cursor, synthetic_game("syn00013")["createdAt"] - sync.DAY_MS)
        stored = self.con.execute("SELECT cursor, updated_at FROM sync_state WHERE source = 'lichess'").fetchone()
        self.assertEqual(stored[0], str(cursor))
        self.assertGreater(stored[1], 0)


# ############################################################################
# lichess API (fake session: no network)
# ############################################################################

class TestApi(DatabaseTestCase):
    """sync_from_lichess() and main() against a fake lichess."""

    def lichess(self, user_games: list[dict[str, Any]], by_id: dict[str, dict[str, Any]] = None,
                user_answer: Any = None) -> FakeSession:
        """A fake lichess: the account, the user export and the export by ids."""
        by_id = by_id or {}

        def export_ids(call: dict[str, Any]) -> FakeResponse:
            return FakeResponse(games=tuple(by_id[i] for i in call["data"].split(",") if i in by_id))

        return FakeSession({("GET", "/api/account"): account(),
                            ("GET", "/api/games/user/Mr_Bits"): user_answer or FakeResponse(games=tuple(user_games)),
                            ("POST", "/api/games/export/_ids"): export_ids})

    def run_sync(self, session: FakeSession, dry_run: bool = False) -> sync.Summary:
        """sync_from_lichess() from a fixed date, its progress lines swallowed."""
        with contextlib.redirect_stdout(io.StringIO()):
            return sync.sync_from_lichess(self.con, session, since_ms=1792000000000, dry_run=dry_run)

    def test_both_passes(self) -> None:
        add_engine_game(self.con, "syn00002", first_move_at=1)  # in the user export too
        add_engine_game(self.con, "syn00004", first_move_at=2)  # only by id
        add_engine_game(self.con, "syn00010", first_move_at=3)  # still running
        add_engine_game(self.con, "gone0001", first_move_at=4)  # lichess has nothing
        session = self.lichess([synthetic_game(g) for g in ("syn00001", "syn00002", "syn00003")],
                               {g: synthetic_game(g) for g in ("syn00004", "syn00010")})

        summary = self.run_sync(session)

        self.assertEqual((summary.inserted, summary.updated, summary.running, summary.errors), (4, 0, 1, 0))
        account_call, export_call, ids_call = session.calls
        self.assertEqual((account_call["method"], account_call["headers"]["Accept"]), ("GET", "application/json"))
        self.assertEqual(export_call["params"], {"since": "1792000000000", "pgnInJson": "true", "clocks": "true",
                                                 "opening": "true", "accuracy": "true", "sort": "dateAsc"})
        self.assertEqual(export_call["headers"]["Accept"], "application/x-ndjson")
        self.assertTrue(export_call["stream"])
        self.assertEqual(ids_call["data"], "syn00004,syn00010,gone0001")
        self.assertEqual(ids_call["params"], sync.EXPORT_FLAGS)
        self.assertEqual(ids_call["headers"], {"Accept": "application/x-ndjson", "Content-Type": "text/plain"})
        self.assertTrue(all(call["timeout"] == sync.TIMEOUT_S for call in session.calls))
        stored = {row[0] for row in self.con.execute("SELECT game_id FROM games")}
        self.assertEqual(stored, {"syn00001", "syn00002", "syn00003", "syn00004"})
        cursor = self.con.execute("SELECT cursor FROM sync_state WHERE source = 'lichess'").fetchone()[0]
        self.assertEqual(int(cursor), synthetic_game("syn00004")["createdAt"] - sync.DAY_MS)

    def test_only_real_lichess_ids_are_asked_for(self) -> None:
        for game_id, first_move in (("AbCd1234", 1), ("local-test-1", 2), ("tooShort", 3), ("x,y12345", 4)):
            add_engine_game(self.con, game_id, first_move_at=first_move)
        self.assertEqual(sync.missing_engine_games(self.con), ["AbCd1234", "tooShort"])

    def test_a_null_game_id_in_games_does_not_hide_the_missing_games(self) -> None:
        """One NULL id in games (the primary key allows it) can't stop the by-id pass (NOT IN would never match)."""
        add_engine_game(self.con, "AbCd1234", first_move_at=1)
        with self.con:
            self.con.execute("INSERT INTO games (game_id, created_at, rated, our_color) VALUES (NULL, 1, 0, 'white')")
        self.assertEqual(sync.missing_engine_games(self.con), ["AbCd1234"])

    def test_ids_go_300_at_a_time(self) -> None:
        for number in range(650):
            add_engine_game(self.con, f"e{number:07d}", first_move_at=number)
        session = self.lichess([])
        self.run_sync(session)
        sizes = [len(call["data"].split(",")) for call in session.calls if call["method"] == "POST"]
        self.assertEqual(sizes, [300, 300, 50])

    def test_429_waits_a_minute_then_tries_once_more(self) -> None:
        session = self.lichess([synthetic_game("syn00001")])
        session.routes[("GET", "/api/account")] = [FakeResponse(429), account()]
        with mock.patch.object(sync.time, "sleep") as sleep, self.assertLogs(sync.logger, "WARNING") as logs:
            summary = self.run_sync(session)
        sleep.assert_called_once_with(60)
        self.assertIn("429", logs.output[0])
        self.assertEqual(summary.inserted, 1)

    def test_429_twice_stops_the_sync(self) -> None:
        session = self.lichess([])
        session.routes[("GET", "/api/account")] = [FakeResponse(429), FakeResponse(429)]
        with mock.patch.object(sync.time, "sleep") as sleep, self.assertLogs(sync.logger, "WARNING"):
            with self.assertRaisesRegex(sync.SyncError, "twice"):
                self.run_sync(session)
        sleep.assert_called_once_with(60)

    def test_an_http_error_stops_the_sync_and_keeps_the_cursor(self) -> None:
        with self.con:
            self.con.execute("INSERT INTO sync_state (source, cursor, updated_at) "
                             "VALUES ('lichess', '1792500000000', 1)")
        session = self.lichess([], user_answer=FakeResponse(500))
        with mock.patch.object(sync, "load_token", return_value=DUMMY_TOKEN), \
                mock.patch.object(sync, "make_session", return_value=session):
            code, _, err = run_main(sync.main, [])
        self.assertEqual(code, 1)
        self.assertIn("lichess didn't answer properly", err)
        self.assertEqual(session.calls[1]["params"]["since"], "1792500000000")
        self.assertEqual(self.con.execute("SELECT cursor FROM sync_state").fetchone()[0], "1792500000000")

    def test_dry_run_against_the_api_writes_nothing(self) -> None:
        add_engine_game(self.con, "syn00004", first_move_at=2)
        session = self.lichess([synthetic_game("syn00001")], {"syn00004": synthetic_game("syn00004")})
        summary = self.run_sync(session, dry_run=True)
        self.assertEqual((summary.inserted, summary.moves), (2, 11))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sync_state").fetchone()[0], 0)

    def test_main_uses_the_token_only_for_the_session_and_never_shows_it(self) -> None:
        session = self.lichess([synthetic_game("syn00001"), synthetic_game("syn00011")])
        logs = CollectLogs()
        logging.getLogger().addHandler(logs)
        self.addCleanup(logging.getLogger().removeHandler, logs)
        with mock.patch.object(sync, "load_token", return_value=DUMMY_TOKEN), \
                mock.patch.object(sync, "make_session", return_value=session) as make_session:
            code, out, err = run_main(sync.main, ["--since", "2026-10-20"])
        self.assertEqual(code, 0, err)
        make_session.assert_called_once_with(DUMMY_TOKEN)
        self.assertEqual(session.calls[1]["params"]["since"], str(local_ms(2026, 10, 20)))
        self.assertIn("1 games inserted", out)
        for text in [out, err, *logs.messages, repr(session.calls)]:
            self.assertNotIn(DUMMY_TOKEN, text)
        self.assertTrue(session.closed)


# ############################################################################
# Token
# ############################################################################

class TestToken(DatabaseTestCase):
    """load_token() and make_session(): with a temporary config.yml, never the real one."""

    def config(self, text: str) -> Path:
        """A temporary config.yml."""
        path = self.tmp / "config.yml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_the_token_from_the_config(self) -> None:
        path = self.config(f'token: "{DUMMY_TOKEN}"    # Lichess OAuth2 Token.\nurl: "https://lichess.org/"\n')
        self.assertEqual(sync.load_token(path), DUMMY_TOKEN)

    def test_the_environment_variables_win(self) -> None:
        path = self.config('token: "lip_fromTheConfigFile"\n')
        os.environ[sync.LICHESS_BOT_TOKEN_ENV] = "lip_lichessBotsOwnVariable"
        self.assertEqual(sync.load_token(path), "lip_lichessBotsOwnVariable")
        os.environ[sync.TOKEN_ENV] = DUMMY_TOKEN
        self.assertEqual(sync.load_token(path), DUMMY_TOKEN)

    def test_no_token_anywhere(self) -> None:
        for path in (self.tmp / "missing.yml", self.config('url: "https://lichess.org/"\n'), self.config("")):
            with self.subTest(path=path.name), self.assertRaisesRegex(sync.SyncError, sync.TOKEN_ENV):
                sync.load_token(path)

    def test_a_token_a_header_cannot_carry_is_refused_without_showing_it(self) -> None:
        for text in ('token: "lip_dummyLeakCheck\\nPart2"\n',  # YAML turns \n into a real line break
                     'token: "lip_dummyLeakCheck Part2"\n', 'token: "lip_dummyLeakCheck\\tPart2"\n',
                     'token: "lip_dummyLeakCheck\\u00e9"\n'):
            path = self.config(text)
            with self.subTest(text=text), self.assertRaises(sync.SyncError) as caught:
                sync.load_token(path)
            self.assertNotIn("lip_dummyLeakCheck", str(caught.exception))
            self.assertIn(str(path), str(caught.exception))
        os.environ[sync.TOKEN_ENV] = "lip_dummyLeakCheck\r\nPart2"
        with self.assertRaises(sync.SyncError) as caught:
            sync.load_token(self.config(f'token: "{DUMMY_TOKEN}"\n'))
        self.assertNotIn("lip_dummyLeakCheck", str(caught.exception))
        self.assertIn(sync.TOKEN_ENV, str(caught.exception))

    def test_main_never_shows_a_token_in_its_errors(self) -> None:
        self.config('token: "lip_dummyLeakCheck\\nPart2"\n')
        with mock.patch.object(sync, "CONFIG_PATH", self.tmp / "config.yml"), \
                mock.patch("requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network used")):
            code, out, err = run_main(sync.main, [])
        self.assertEqual(code, 1)
        self.assertIn("Sync stopped", err)
        for text in (out, err):
            self.assertNotIn("lip_dummyLeakCheck", text)

    def test_main_never_shows_the_header_requests_refuses(self) -> None:
        """requests' InvalidHeader message quotes the header: "Bearer <the token>". main() must not print it."""
        leaky = "lip_dummyLeakCheck\nPart2"
        with mock.patch.object(sync, "load_token", return_value=leaky), \
                mock.patch("requests.adapters.HTTPAdapter.send", side_effect=AssertionError("network used")):
            code, out, err = run_main(sync.main, [])  # (the real make_session: requests itself refuses the header)
        self.assertEqual(code, 1)
        self.assertIn("header", err)
        for text in (out, err):
            self.assertNotIn("lip_dummyLeakCheck", text)

    def test_a_broken_config_never_shows_its_lines(self) -> None:
        path = self.config(f'token: "{DUMMY_TOKEN}\nengine: [unclosed\n')
        with self.assertRaises(sync.SyncError) as caught:
            sync.load_token(path)
        self.assertNotIn(DUMMY_TOKEN, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)  # the YAML error (which quotes lines) is hidden

    def test_main_without_a_token_stops_cleanly(self) -> None:
        code, _, err = run_main(sync.main, [])
        self.assertEqual(code, 1)
        self.assertIn("no token", err)

    def test_the_session_sends_the_token_as_a_bearer_header(self) -> None:
        session = sync.make_session(DUMMY_TOKEN)
        self.addCleanup(session.close)
        self.assertEqual(session.headers["Authorization"], f"Bearer {DUMMY_TOKEN}")
        self.assertEqual(session.headers["User-Agent"], sync.USER_AGENT)


class TestPaths(unittest.TestCase):
    """Where the sync looks for lichess-bot's config.yml (the file itself is never opened here)."""

    def test_config_path(self) -> None:
        database_folder = Path(sync.__file__).resolve().parent
        self.assertEqual(sync.CONFIG_PATH, database_folder.parent / "config.yml")


if __name__ == "__main__":
    unittest.main()
