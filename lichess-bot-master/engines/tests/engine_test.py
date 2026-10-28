"""The engine test: Engine UCI.exe played exactly the way lichess-bot plays it, then every row it stored.

  cd lichess-bot-master\\engines
  python -B tests\\engine_test.py

Run it from PowerShell or cmd (not Git Bash), after every build. It takes about a minute. The real games are
never touched: the engine gets MRBITS_DATABASE_FILE = a new database in the output folder, and it plays from
an empty temporary folder, so it also proves that every path comes from the engine's own folder.

  1. lichess-bot's engine check at startup (uci, isready, quit): fast, and no Kernel worker starts
  2. a game as White, 6 moves: 2 from Stockfish (the opening), then the Kernel workers
  3. a game as Black, 4 moves
  4. a game without a GameId (a test by hand): it's stored as "local-<time>"
"""
import argparse
import json
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_tools as tools  # noqa: E402

NUMBER_OF_KERNEL_WORKERS = 28

# Engine UCI's time ladder (getBestMoveFromEngine): (clock at least, seconds, increment divisor).
WHITE_TIME_LADDER = [(300000, 90, 2000), (240000, 80, 3000), (180000, 70, 3000), (120000, 65, 3000),
                     (60000, 50, 3000), (45000, 40, None), (15000, 10, None), (10000, 5, None), (6000, 3, None),
                     (4000, 2, None)]
BLACK_TIME_LADDER = [(300000, 90, 2000), (240000, 80, 3000), (180000, 70, 3000), (120000, 60, 3000),
                     (60000, 50, 3000), (45000, 40, None), (15000, 10, None), (10000, 5, None), (6000, 3, None),
                     (4000, 2, None)]


def allowed_seconds(engine_is_white, clock_ms, increment_ms):
    for threshold, seconds, divisor in (WHITE_TIME_LADDER if engine_is_white else BLACK_TIME_LADDER):
        if clock_ms >= threshold:
            return seconds + (increment_ms // divisor if divisor else 0)
    return 1


def check_the_log(checker, label, pid, must_contain):
    logs = sorted((tools.ENGINES_DIRECTORY / "logs").glob(f"uci_*_pid{pid}.log"))
    if not checker.check(len(logs) == 1, f"{label}: the engine log exists", f"{len(logs)} file(s) for pid {pid}"):
        return ""
    text = logs[0].read_text(encoding="utf-8", errors="replace")
    for expected in must_contain:
        checker.check(expected in text, f"{label}: the log has '{expected}'")
    problems = [line for line in text.splitlines() if " !! " in line]
    checker.check(not problems, f"{label}: no problem ('!!') in the log", "; ".join(problems[:3]))
    return text


def check_the_game(checker, database_file, label, game_id, game, engine_is_white, expect_opponent=True):
    """Every row of one game against what python-chess saw."""
    games = tools.rows(database_file, "SELECT * FROM engine_games WHERE game_id = ?", (game_id,))
    if not checker.check(len(games) == 1, f"{label}: one engine_games row for '{game_id}'", f"{len(games)} rows"):
        return
    stored_game = games[0]
    checker.check(stored_game["our_color"] == ("white" if engine_is_white else "black"), f"{label}: our_color",
                  stored_game["our_color"])
    if expect_opponent:
        opponent = (stored_game["opponent_title"], stored_game["opponent_rating"], stored_game["opponent_is_bot"],
                    stored_game["opponent_name"])
        checker.check(opponent == ("BOT", 1692, 1, "Demolito_L4"), f"{label}: the opponent (UCI_Opponent)",
                      str(opponent))
    checker.check(stored_game["first_move_at"] <= stored_game["last_move_at"], f"{label}: first/last move times")

    moves = tools.rows(database_file, "SELECT * FROM engine_moves WHERE game_id = ? ORDER BY ply", (game_id,))
    checker.check([move["ply"] for move in moves] == [move["ply"] for move in game.moves], f"{label}: the plies",
                  str([move["ply"] for move in moves]))
    checker.check([move["best_move"] for move in moves] == [move["bestmove"] for move in game.moves],
                  f"{label}: the stored moves are the moves python-chess received")

    for stored, played in zip(moves, game.moves):
        ply = stored["ply"]
        where = f"{label} ply {ply}"
        path = stored["path"]
        legal_moves = played["legal_moves"]
        checker.check(stored["legal_moves"] == len(legal_moves), f"{where}: legal_moves",
                      f"{stored['legal_moves']} vs {len(legal_moves)}")

        # The "go" parameters, exactly as sent, and the time ladder's answer.
        is_first_move_of_this_side = ply <= 2
        if is_first_move_of_this_side:
            checker.check(stored["movetime_ms"] == 10000 and stored["wtime_ms"] is None,
                          f"{where}: 'go movetime 10000'", f"movetime {stored['movetime_ms']}")
            clock, increment = 10000, 0
        else:
            checker.check(stored["movetime_ms"] is None and stored["wtime_ms"] is not None and
                          stored["winc_ms"] == 3000, f"{where}: 'go wtime ... winc 3000'",
                          f"wtime {stored['wtime_ms']} btime {stored['btime_ms']}")
            clock = stored["wtime_ms"] if engine_is_white else stored["btime_ms"]
            increment = stored["winc_ms"] if engine_is_white else stored["binc_ms"]
        expected_seconds = allowed_seconds(engine_is_white, clock, increment)
        checker.check(stored["allowed_seconds"] == expected_seconds, f"{where}: allowed_seconds (time ladder)",
                      f"{stored['allowed_seconds']} vs {expected_seconds}")

        checker.check(stored["t_total_ms"] is not None and 0 < stored["t_total_ms"] <= played["ms"] + 5,
                      f"{where}: t_total_ms within python-chess's time",
                      f"{stored['t_total_ms']:.1f} vs {played['ms']:.1f} ms")

        workers = tools.rows(database_file, "SELECT * FROM worker_runs WHERE game_id = ? AND ply = ? ORDER BY worker",
                             (game_id, ply))
        if ply <= 4:
            checker.check(path in ("stockfish_opening", "only_move"), f"{where}: path (opening)", path)
        else:
            checker.check(path in ("kernel", "stalemate_override", "only_move"), f"{where}: path", path)

        if path in ("stockfish_opening", "stockfish_endgame"):
            checker.check(stored["stockfish_depth"] in (14, 16, 18, 20, 22, 24, 26), f"{where}: stockfish_depth",
                          str(stored["stockfish_depth"]))
            checker.check(stored["workers"] == 0 and not workers, f"{where}: no Kernel worker was asked")
            checker.check(stored["best_score"] is None, f"{where}: no Kernel score")
            continue
        if path != "kernel":
            continue

        # A Kernel move: every worker, its depths and its candidates.
        expected_workers = min(NUMBER_OF_KERNEL_WORKERS, len(legal_moves))
        checker.check(stored["workers"] == expected_workers == len(workers), f"{where}: workers",
                      f"{stored['workers']} stored, {len(workers)} rows, {expected_workers} expected")
        checker.check(all(worker["status"] == "ok" for worker in workers), f"{where}: every worker answered ok",
                      str(sorted({worker["status"] for worker in workers})))
        checker.check(stored["stockfish_depth"] is None, f"{where}: no Stockfish depth")
        root_moves = [json.loads(worker["root_moves"]) for worker in workers]
        all_root_moves = [move for moves_of_one_worker in root_moves for move in moves_of_one_worker]
        checker.check(sorted(all_root_moves) == legal_moves, f"{where}: the workers' root moves = the legal moves",
                      f"{len(all_root_moves)} root moves, {len(set(all_root_moves))} different")

        inconsistent_workers = []
        for worker, moves_of_this_worker in zip(workers, root_moves):
            depths = tools.rows(database_file, "SELECT * FROM worker_depths WHERE game_id = ? AND ply = ? AND "
                                "worker = ? ORDER BY depth", (game_id, ply, worker["worker"]))
            completed = [depth["depth"] for depth in depths if depth["completed"]]
            candidates = tools.rows(database_file, "SELECT * FROM root_candidates WHERE game_id = ? AND ply = ? "
                                    "AND worker = ?", (game_id, ply, worker["worker"]))
            candidate_moves = {candidate["move"] for candidate in candidates}
            unsearched = set(json.loads(worker["unsearched_root_moves"] or "[]"))
            # The worker's score is the best of its root candidates (the engine maximizes at the root).
            is_consistent = (worker["best_move"] in moves_of_this_worker and bool(completed) and
                             completed[-1] == worker["depth"] and
                             all(depth % 2 == 0 for depth in completed) and
                             bool(candidates) and candidate_moves <= set(moves_of_this_worker) and
                             candidate_moves | unsearched == set(moves_of_this_worker) and
                             max(candidate["score"] for candidate in candidates) == worker["best_score"])
            if not is_consistent:
                inconsistent_workers.append(f"worker {worker['worker']}: depth {worker['depth']}, completed "
                                            f"{completed}, {len(candidates)} candidates")
        checker.check(not inconsistent_workers, f"{where}: every worker's depths and candidates are consistent",
                      "; ".join(inconsistent_workers[:3]))

        best = max((worker["best_score"], worker["best_move"]) for worker in workers if worker["status"] == "ok")
        checker.check((stored["best_score"], stored["best_move"]) == best,
                      f"{where}: the move is the best worker answer", f"{stored['best_move']} {stored['best_score']}")
        checker.check(stored["t_kernel_ms"] <= stored["allowed_seconds"] * 1000 + 2000,
                      f"{where}: the Kernel round trip stayed in its time", f"{stored['t_kernel_ms']:.0f} ms")

    # A normal game has nothing to report: no dead worker, no restart, no fallback.
    events = tools.rows(database_file, "SELECT * FROM events WHERE game_id = ?", (game_id,))
    checker.check(not events, f"{label}: no event at all", "; ".join(event["message"] for event in events[:3]))


def snapshot(folder):
    return {str(path.relative_to(folder)) for path in folder.rglob("*")} if folder.exists() else set()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=None, help="the output folder (default: a new temporary one)")
    arguments = parser.parse_args()
    out = pathlib.Path(arguments.out or tempfile.mkdtemp(prefix="mrbits-engine-test-"))
    out.mkdir(parents=True, exist_ok=True)
    cwd = out / "empty-cwd"
    cwd.mkdir(exist_ok=True)
    database_file = out / "test.sqlite"
    checker = tools.Checker("engine_test")
    print(f"Engine : {tools.ENGINE_UCI_EXE}\nOutput : {out}\nDB     : {database_file}", flush=True)
    old_folders = {name: snapshot(tools.ROOT_DIRECTORY / name) for name in ("input", "history")}
    workers_log = tools.ENGINES_DIRECTORY / "logs" / "kernel_workers_stderr.log"
    workers_log_size = workers_log.stat().st_size if workers_log.exists() else 0
    report = {"out": str(out), "database": str(database_file)}

    # 1. lichess-bot's engine check at startup: create_engine(CONFIG) with no game -> uci, isready, quit.
    print("\n1. the engine check at startup", flush=True)
    start = time.perf_counter()
    engine = tools.open_engine(database_file, cwd)
    pid = engine.transport.get_pid()
    engine.configure({})
    engine.ping()
    kernels_during_the_check = tools.children_of(pid, tools.KERNEL_EXE_NAME)
    engine.quit()
    engine.close()
    check_ms = (time.perf_counter() - start) * 1000
    report["startup_check_ms"] = round(check_ms)
    checker.check(check_ms < 3000, "startup check: done in under 3 s", f"{check_ms:.0f} ms")
    checker.check(not kernels_during_the_check, "startup check: no Kernel worker started",
                  f"{len(kernels_during_the_check)} running")
    checker.check(tools.wait_until(lambda: not tools.is_running(pid), 3), "startup check: the engine exited")
    tables = {row["name"] for row in tools.rows(database_file, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    checker.check({"engine_games", "engine_moves", "worker_runs", "worker_depths", "root_candidates",
                   "events"} <= tables, "startup check: the database was created with the schema")
    check_the_log(checker, "startup check", pid, ["== Engine UCI (build", ">> uci", "<< uciok", "<< readyok",
                                                    "   database  : ", "== exit"])

    # 2. a game as White: plies 1 and 3 come from Stockfish, then the Kernel workers.
    print("\n2. a game as White", flush=True)
    game = tools.Game(database_file, cwd, engine_is_white=True, game_id="tN252leL")
    kernels_in_the_game = []
    for move_number in range(6):
        record = game.play_engine_move()
        print(f"   ply {record['ply']}: {record['bestmove']} in {record['ms']:.0f} ms", flush=True)
        if move_number == 2:
            kernels_in_the_game = tools.children_of(game.pid, tools.KERNEL_EXE_NAME)
    white_pid = game.pid
    report["white_quit_ms"] = round(game.finish())
    report["white_moves"] = game.moves
    checker.check(len(kernels_in_the_game) == NUMBER_OF_KERNEL_WORKERS, "White: 28 Kernel workers were running",
                  f"{len(kernels_in_the_game)}")
    checker.check(tools.wait_until(lambda: not any(tools.is_running(worker) for worker in kernels_in_the_game), 3),
                  "White: every Kernel worker exited after quit")
    checker.check(tools.wait_until(lambda: not tools.is_running(white_pid), 3), "White: the engine exited")
    tools.wait_for_engine_moves(database_file, "tN252leL", len(game.moves))
    check_the_game(checker, database_file, "White", "tN252leL", game, engine_is_white=True)
    check_the_log(checker, "White", white_pid, [">> setoption name GameId value tN252leL", ">> ucinewgame",
                                                ">> setoption name UCI_Opponent value BOT 1692 computer Demolito_L4",
                                                "<< bestmove", "== quit", "== exit"])

    # 3. a game as Black.
    print("\n3. a game as Black", flush=True)
    game = tools.Game(database_file, cwd, engine_is_white=False, game_id="bLaCk123")
    for move_number in range(4):
        record = game.play_engine_move()
        print(f"   ply {record['ply']}: {record['bestmove']} in {record['ms']:.0f} ms", flush=True)
    black_pid = game.pid
    report["black_moves"] = game.moves
    game.finish()
    tools.wait_until(lambda: not tools.is_running(black_pid), 3)
    tools.wait_for_engine_moves(database_file, "bLaCk123", len(game.moves))
    check_the_game(checker, database_file, "Black", "bLaCk123", game, engine_is_white=False)

    # 4. no GameId (configure({}) like an old extra_game_handlers.py, or a test by hand).
    print("\n4. a game without a GameId", flush=True)
    game = tools.Game(database_file, cwd, engine_is_white=True, game_id=None)
    for move_number in range(3):
        record = game.play_engine_move()
        print(f"   ply {record['ply']}: {record['bestmove']} in {record['ms']:.0f} ms", flush=True)
    local_pid = game.pid
    game.finish()
    tools.wait_until(lambda: not tools.is_running(local_pid), 3)
    local_games = tools.rows(database_file, "SELECT game_id FROM engine_games WHERE game_id LIKE 'local-%'")
    if checker.check(len(local_games) == 1, "no GameId: stored as one 'local-<time>' game",
                     str([row["game_id"] for row in local_games])):
        tools.wait_for_engine_moves(database_file, local_games[0]["game_id"], len(game.moves))
        check_the_game(checker, database_file, "no GameId", local_games[0]["game_id"], game, engine_is_white=True)

    # Nothing outside the engine's own folders: no input/history files, nothing in the launch folder.
    checker.check(not snapshot(cwd), "the launch folder stayed empty", str(sorted(snapshot(cwd))[:5]))
    for name, before in old_folders.items():
        checker.check(snapshot(tools.ROOT_DIRECTORY / name) == before, f"nothing was written into '{name}'")
    new_size = workers_log.stat().st_size if workers_log.exists() else 0
    checker.check(new_size == workers_log_size, "the Kernel workers wrote nothing to stderr",
                  f"{new_size - workers_log_size} new bytes")
    views = {"v_games": 3, "v_engine_moves": 13}
    for view, expected in views.items():
        count = tools.rows(database_file, f"SELECT COUNT(*) AS n FROM {view}")[0]["n"]
        checker.check(count == expected, f"the view {view} works", f"{count} rows, {expected} expected")

    report["summary"] = checker.summary()
    tools.write_json(out / "engine_test.json", report)
    print(f"\n{checker.summary()['passed']} passed, {checker.summary()['failed']} failed   (details: {out})")
    print("RESULT: PASS" if checker.ok else "RESULT: FAIL")
    return 0 if checker.ok else 1


if __name__ == "__main__":
    sys.exit(main())
