"""Dashboard behavior on isolated SQLite fixtures; never touch config or the real DB."""
from hashlib import sha256
from contextlib import closing
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Thread
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import server


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fixture.sqlite"
        with closing(sqlite3.connect(self.path)) as con:
            con.executescript((HERE.parent / "schema.sql").read_text(encoding="utf-8"))
        self.http = None

    def populate(self):
        with closing(sqlite3.connect(self.path)) as con:
            for index, (game, result, build) in enumerate([
                ("winGame1", "win", "uci=test;kernel=v1;worker=v1-test"),
                ("lossGame", "loss", "uci=test;kernel=v2;worker=v2-test"),
                ("oldGame1", "draw", "2026-10-20 12:00:00"),
                ("mixGame1", "draw", "uci=test;kernel=v1"),
                ("partial1", None, None),
            ]):
                con.execute("INSERT INTO engine_games(game_id,first_move_at,our_color,engine_version) VALUES(?,?,?,?)",
                            (game, 1793100000000 + index * 10000, "white", build))
                if result:
                    con.execute("INSERT INTO games(game_id,created_at,rated,our_color,result,speed,variant,opponent_name) "
                                "VALUES(?,?,1,'white',?,'blitz','standard',?)",
                                (game, 1793100000000 + index * 10000, result, "Fixture <opponent>"))
                con.execute("INSERT INTO engine_moves(game_id,ply,received_at,path,best_move,t_total_ms,engine_version) "
                            "VALUES(?,1,1,'kernel','e2e4',100,?)", (game, build))
            con.execute("INSERT INTO engine_moves(game_id,ply,received_at,path,engine_version) "
                        "VALUES('mixGame1',3,3,'kernel','uci=test;kernel=v2')")
            con.execute("INSERT INTO moves(game_id,ply,by_us,uci,san) VALUES('winGame1',1,1,'e2e4','e4')")
            con.execute("INSERT INTO moves(game_id,ply,by_us,uci,san) VALUES('winGame1',2,0,'e7e5','e5')")
            con.execute("INSERT INTO worker_runs(game_id,ply,worker,status,depth,total_nodes,search_ms) "
                        "VALUES('winGame1',1,1,'ok',6,1234,80)")
            con.execute("INSERT INTO worker_depths(game_id,ply,worker,depth,completed,nodes,best_move,score) "
                        "VALUES('winGame1',1,1,6,1,1234,'e2e4',22)")
            con.execute("INSERT INTO root_candidates(game_id,ply,worker,move,score,exact,depth) "
                        "VALUES('winGame1',1,1,'e2e4',22,1,6)")
            con.commit()

    def start_http(self):
        self.http = server.DashboardServer(("127.0.0.1", 0), self.path)
        thread = Thread(target=self.http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.port = self.http.server_address[1]

    def request(self, path, method="GET", headers=None):
        con = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            con.request(method, path, headers=headers or {})
            response = con.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            con.close()


class DataTests(Fixture):
    def test_missing_database_is_not_created(self):
        absent = self.path.parent / "absent.sqlite"
        with self.assertRaises(FileNotFoundError):
            with server.read_connection(absent):
                pass
        self.assertFalse(absent.exists())

    def test_empty_state_has_no_fabricated_results(self):
        with server.read_connection(self.path) as con:
            data = server.summary(con, {})
            self.assertEqual((data["games"], data["engine_moves"], data["decided"]), (0, 0, 0))
            self.assertIsNone(data["score_pct"])
            self.assertIsNone(data["avg_move_ms"])
            self.assertEqual(data["versions"], [])
            self.assertEqual(data["days"], [])
            self.assertEqual(server.list_games(con, {})["games"], [])

    def test_one_request_is_consistent_and_next_refresh_sees_new_commits(self):
        with server.read_connection(self.path) as reader:
            self.assertEqual(server.summary(reader, {})["games"], 0)
            with closing(sqlite3.connect(self.path)) as writer:
                writer.execute("INSERT INTO engine_games(game_id,first_move_at,engine_version) "
                               "VALUES('liveGame',1,'uci=fixture;kernel=v4')")
                writer.commit()
            self.assertEqual(server.summary(reader, {})["games"], 0)
        with server.read_connection(self.path) as reader:
            self.assertEqual(server.summary(reader, {})["games"], 1)

    def test_connections_are_readonly_and_queries_preserve_database(self):
        self.populate()
        original = sha256(self.path.read_bytes()).hexdigest()
        with server.read_connection(self.path) as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM games")
            data = server.summary(con, {})
            self.assertEqual(data["games"], 5)
            self.assertEqual(data["outcomes"], {"win": 1, "loss": 1, "draw": 2, "aborted": 0, "pending": 1})
            self.assertEqual(data["score_pct"], 50)
            self.assertEqual(data["engine_moves"], 6)
            self.assertEqual(data["avg_move_ms"], 100)
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), original)

    def test_version_metadata_stays_honest_and_filters_before_paging(self):
        self.populate()
        with server.read_connection(self.path) as con:
            rows = {r["game_id"]: r for r in server.list_games(con, {})["games"]}
            self.assertEqual(rows["winGame1"]["kernel_variant"], "v1")
            self.assertEqual(rows["lossGame"]["kernel_variant"], "v2")
            self.assertEqual(rows["oldGame1"]["kernel_variant"], "unknown")
            self.assertEqual(rows["partial1"]["kernel_variant"], "unknown")
            self.assertEqual(rows["mixGame1"]["kernel_variant"], "mixed")
            filtered = server.list_games(con, {"kernel": ["v1"], "limit": ["1"]})
            self.assertEqual(filtered["total"], 1)
            self.assertEqual(filtered["games"][0]["game_id"], "winGame1")
            self.assertEqual(server.list_games(con, {"opponent": ["' OR 1=1 --"]})["total"], 0)
            self.assertEqual(server.summary(con, {"result": ["pending"]})["decided"], 0)

    def test_game_move_details_and_legal_replay(self):
        self.populate()
        with server.read_connection(self.path) as con:
            detail = server.game_detail(con, "winGame1")
            self.assertEqual(len(detail["moves"]), 2)
            self.assertEqual(detail["moves"][0]["engine"]["total_nodes"], 1234)
            self.assertEqual(detail["moves"][1]["engine"], None)
            if server.chess:
                self.assertEqual(len(detail["replay"]["frames"]), 3)
                self.assertEqual(detail["replay"]["frames"][-1]["fen"].split()[1], "w")
            self.assertEqual(server.game_detail(con, "partial1")["replay"]["frames"], [])
            move = server.queries.move_detail("winGame1", 1, con=con)
            self.assertEqual(move["workers"][0]["depths"][0]["depth"], 6)
            self.assertEqual(move["candidates"][0]["move"], "e2e4")
            self.assertIsNone(server.game_detail(con, "does-not-exist"))

    def test_v4_and_future_versions_require_explicit_tokens(self):
        with closing(sqlite3.connect(self.path)) as con:
            for game, build in [("v4Game01", "uci=build;kernel=v4;worker=v4-2026"),
                                ("v40Game1", "uci=build;kernel=v40"),
                                ("nameOnly", "Kernel-v4.exe")]:
                con.execute("INSERT INTO engine_games(game_id,first_move_at,engine_version) VALUES(?,1,?)", (game, build))
            con.commit()
        with server.read_connection(self.path) as con:
            rows = server.list_games(con, {"kernel": ["v4"]})
            self.assertEqual(rows["total"], 1)
            self.assertEqual(rows["games"][0]["game_id"], "v4Game01")
            self.assertEqual(server.summary(con, {"kernel": ["v4"]})["versions"][0]["kernel_variant"], "v4")
            self.assertEqual(server.list_games(con, {"kernel": ["v40"]})["games"][0]["game_id"], "v40Game1")
            self.assertEqual(server.list_games(con, {"kernel": ["unknown"]})["total"], 1)
            self.assertIn("v40", server.summary(con, {})["kernel_variants"])
        for build in ("kernel=v0", "kernel=v04", "kernel=v4.exe", "kernel=v4;kernel=v5", "Kernel-v4.exe"):
            self.assertEqual(server.recorded_kernel(build), "unknown")

    def test_replay_missing_optional_dependency_and_invalid_history(self):
        from unittest.mock import patch
        record = {"variant": "standard", "initial_fen": None, "pgn": None}
        with patch.object(server, "chess", None):
            self.assertIn("dependency", server.replay(record, [])["message"])
        if server.chess:
            data = server.replay(record, [{"ply": 2, "uci": "e2e4"}])
            self.assertEqual(len(data["frames"]), 1)
            self.assertIn("incomplete", data["message"])


class HttpTests(Fixture):
    def test_static_routes_and_empty_api(self):
        self.start_http()
        for path, content_type in [("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css"), ("/favicon.svg", "image/svg+xml")]:
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn(content_type, headers["Content-Type"])
            self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, _, body = self.request("/api/summary")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["games"], 0)
        self.assertEqual(self.request("/../schema.sql")[0], 404)
        self.assertEqual(self.request("/config.yml")[0], 404)
        self.assertEqual(self.request("/api/summary?sql=DELETE")[0], 400)
        self.assertEqual(self.request("/api/games?limit=-1")[0], 400)
        self.assertEqual(self.request("/api/games?result=win&result=loss")[0], 400)

    def test_game_routes_mutations_and_cross_origin_are_rejected(self):
        self.populate()
        self.start_http()
        status, _, body = self.request("/api/game/winGame1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["game"]["kernel_variant"], "v1")
        status, _, body = self.request("/api/game/winGame1/move/1")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["workers"]), 1)
        self.assertEqual(self.request("/api/game/missing")[0], 404)
        self.assertEqual(self.request("/api/game/winGame1/move/zero")[0], 400)
        self.assertEqual(self.request("/api/game/%2e%2e%2fschema.sql")[0], 400)
        self.assertEqual(self.request("/api/games", method="POST")[0], 405)
        self.assertEqual(self.request("/api/summary", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("/api/summary", headers={"Origin": "https://evil.example"})[0], 403)


if __name__ == "__main__":
    unittest.main()
