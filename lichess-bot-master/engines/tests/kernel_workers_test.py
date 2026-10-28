"""The Kernel worker pool under trouble: dead workers, a hung worker, all workers dead, and a hard kill.

  cd lichess-bot-master\\engines
  python -B tests\\kernel_workers_test.py

One game as White, played like lichess-bot plays it (about a minute). Between two moves (or during one) the
test breaks the engine's own Kernel workers, and checks that the move is still played, that every legal move
was still searched when it could be, that the database says what happened, and that the pool is complete
again for the next move:

  ply 5   a normal Kernel move (28 workers)
  ply 7   one worker was killed while it waited  -> it gets no moves, the others search them all; restarted
  ply 9   one worker was frozen before the move  -> 1 'timeout' at exactly allowed time + 2 s; killed, restarted
  ply 11  one worker is killed during the search -> 1 'dead' (only its moves are lost, for this move); restarted
  ply 13  every worker was killed before it      -> Stockfish plays it ('no_kernel_answer'), all 28 restarted
  ply 15  a normal Kernel move again
  then    Engine UCI is killed hard (like taskkill /F): no Kernel.exe and no Stockfish may be left running

It only ever kills processes it started itself (the engine and the engine's own children). The real games
are never touched (MRBITS_DATABASE_FILE points at a new database in the output folder).
"""
import argparse
import json
import pathlib
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_tools as tools  # noqa: E402

NUMBER_OF_KERNEL_WORKERS = 28
STOCKFISH_EXE_NAME = "stockfish-windows-x86-64-avx2.exe"


def kernel_workers_of(game):
    return tools.children_of(game.pid, tools.KERNEL_EXE_NAME)


def events_at(database_file, game_id, ply):
    return tools.rows(database_file, "SELECT level, source, message FROM events WHERE game_id = ? AND ply = ? "
                      "ORDER BY event_id", (game_id, ply))


def wait_for_event(database_file, game_id, ply, message, timeout_s=5):
    """The restart event comes after the restart itself, so wait for it. All 28 at once took 0.4-0.9 s in 19 of 21
    runs, and 3.7 s and 5.2 s on a busy laptop, so that case gets more time (it's correctness here, not speed)."""
    return tools.wait_until(lambda: any(event["message"] == message
                                        for event in events_at(database_file, game_id, ply)), timeout_s)


def workers_at(database_file, game_id, ply):
    return tools.rows(database_file, "SELECT * FROM worker_runs WHERE game_id = ? AND ply = ? ORDER BY worker",
                      (game_id, ply))


def move_at(database_file, game_id, ply):
    return tools.rows(database_file, "SELECT * FROM engine_moves WHERE game_id = ? AND ply = ?", (game_id, ply))[0]


def searched_moves(workers):
    """The root moves of the workers that answered 'ok' (the moves the engine really compared)."""
    return sorted(move for worker in workers if worker["status"] == "ok" for move in json.loads(worker["root_moves"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=None, help="the output folder (default: a new temporary one)")
    arguments = parser.parse_args()
    out = pathlib.Path(arguments.out or tempfile.mkdtemp(prefix="mrbits-workers-test-"))
    out.mkdir(parents=True, exist_ok=True)
    cwd = out / "empty-cwd"
    cwd.mkdir(exist_ok=True)
    database_file = out / "test.sqlite"
    game_id = "pOoLtEsT"
    checker = tools.Checker("kernel_workers_test")
    print(f"Engine : {tools.ENGINE_UCI_EXE}\nOutput : {out}", flush=True)
    stored_plies = []

    game = tools.Game(database_file, cwd, engine_is_white=True, game_id=game_id)
    try:
        def play(label):
            record = game.play_engine_move()
            print(f"   ply {record['ply']}: {record['bestmove']} in {record['ms']:.0f} ms   ({label})", flush=True)
            tools.wait_for_engine_moves(database_file, game_id, len(game.moves))
            stored_plies.append(record["ply"])
            return record

        def pool_is_complete_again(label, timeout_s=5):
            checker.check(tools.wait_until(lambda: len(kernel_workers_of(game)) == NUMBER_OF_KERNEL_WORKERS,
                                           timeout_s),
                          f"{label}: 28 workers again after the move", str(len(kernel_workers_of(game))))

        play("Stockfish")
        play("Stockfish")
        record = play("normal")
        workers = kernel_workers_of(game)
        checker.check(len(workers) == NUMBER_OF_KERNEL_WORKERS, "28 Kernel workers after the first Kernel move",
                      str(len(workers)))
        stored_workers = workers_at(database_file, game_id, record["ply"])
        checker.check(stored_workers and all(worker["status"] == "ok" for worker in stored_workers),
                      "ply 5: every worker answered", str(sorted({worker["status"] for worker in stored_workers})))

        # 1. A worker that died while it was waiting: it gets no moves, so no legal move is lost.
        killed = workers[0]
        tools.kill_process(killed)
        tools.wait_until(lambda: not tools.is_running(killed), 2)
        record = play("one worker killed while it waited")
        stored_workers = workers_at(database_file, game_id, record["ply"])
        expected_workers = min(NUMBER_OF_KERNEL_WORKERS - 1, len(record["legal_moves"]))
        checker.check(len(stored_workers) == expected_workers and
                      all(worker["status"] == "ok" for worker in stored_workers),
                      "ply 7: the dead worker got no moves, every other worker answered 'ok'",
                      f"{len(stored_workers)} workers, {expected_workers} expected")
        checker.check(searched_moves(stored_workers) == record["legal_moves"],
                      "ply 7: every legal move was still searched", f"{len(searched_moves(stored_workers))} of "
                      f"{len(record['legal_moves'])}")
        checker.check(move_at(database_file, game_id, record["ply"])["path"] == "kernel",
                      "ply 7: the Kernel decided the move")
        checker.check(wait_for_event(database_file, game_id, record["ply"], "restarted 1 worker(s)"),
                      "ply 7: the restart is in the events",
                      "; ".join(event["message"] for event in events_at(database_file, game_id, record["ply"])))
        pool_is_complete_again("ply 7")
        checker.check(killed not in kernel_workers_of(game), "ply 7: the dead worker was replaced by a new one")

        # 2. A hung worker: alive, but it never answers.
        frozen = kernel_workers_of(game)[3]
        tools.suspend_process(frozen)
        record = play("one worker frozen before it")
        stored_workers = workers_at(database_file, game_id, record["ply"])
        statuses = [worker["status"] for worker in stored_workers]
        move = move_at(database_file, game_id, record["ply"])
        checker.check(statuses.count("timeout") == 1 and statuses.count("ok") == len(statuses) - 1,
                      "ply 9: exactly one 'timeout' worker, all the others 'ok'", str(sorted(set(statuses))))
        deadline_ms = move["allowed_seconds"] * 1000 + 2000
        checker.check(deadline_ms - 50 <= move["t_kernel_ms"] <= deadline_ms + 500,
                      "ply 9: the move waited for the deadline (allowed time + 2 s), not longer",
                      f"{move['t_kernel_ms']:.0f} ms, deadline {deadline_ms} ms")
        checker.check(move["path"] == "kernel", "ply 9: the Kernel still decided the move", move["path"])
        checker.check(tools.wait_until(lambda: not tools.is_running(frozen), 3), "ply 9: the frozen worker was killed")
        checker.check(wait_for_event(database_file, game_id, record["ply"], "restarted 1 worker(s)"),
                      "ply 9: the restart is in the events",
                      "; ".join(event["message"] for event in events_at(database_file, game_id, record["ply"])))
        pool_is_complete_again("ply 9")

        # 3. A worker killed in the middle of the search. With 28 legal moves or more, every worker gets moves.
        # It's frozen first, so it gets its request but can't answer before it dies (a search can be as short as
        # the 5% rule: 150 ms with a 3 s budget), then killed half a second into the move.
        if len(list(game.board.legal_moves)) >= NUMBER_OF_KERNEL_WORKERS:
            victim = kernel_workers_of(game)[5]
            tools.suspend_process(victim)
            timer = threading.Timer(0.5, lambda: tools.kill_process(victim))
            timer.start()
            record = play("one worker killed during the search")
            timer.join()
            stored_workers = workers_at(database_file, game_id, record["ply"])
            statuses = [worker["status"] for worker in stored_workers]
            move = move_at(database_file, game_id, record["ply"])
            checker.check(statuses.count("dead") == 1 and statuses.count("ok") == len(statuses) - 1,
                          "ply 11: exactly one 'dead' worker, all the others 'ok'", str(sorted(set(statuses))))
            checker.check(move["t_kernel_ms"] < move["allowed_seconds"] * 1000 + 2000 - 500,
                          "ply 11: the dead worker was noticed at once, not at the deadline",
                          f"{move['t_kernel_ms']:.0f} ms")
            checker.check(move["path"] == "kernel", "ply 11: the Kernel still decided the move")
            checker.check(wait_for_event(database_file, game_id, record["ply"], "restarted 1 worker(s)"),
                          "ply 11: the restart is in the events",
                          "; ".join(event["message"] for event in events_at(database_file, game_id, record["ply"])))
            pool_is_complete_again("ply 11")
        else:
            print("   (skipped the kill during the search: fewer than 28 legal moves, so not every worker has "
                  "moves)", flush=True)
            play("normal")

        # 4. Every worker dead before the move: Stockfish plays it, and the whole pool comes back.
        for worker in kernel_workers_of(game):
            tools.kill_process(worker)
        tools.wait_until(lambda: not kernel_workers_of(game), 3)
        record = play("every worker killed before it")
        move = move_at(database_file, game_id, record["ply"])
        checker.check(move["path"] == "no_kernel_answer" and move["stockfish_depth"] == 14,
                      "ply 13: Stockfish (depth 14) played the move", f"{move['path']}, depth {move['stockfish_depth']}")
        checker.check(not workers_at(database_file, game_id, record["ply"]) and move["workers"] == 0,
                      "ply 13: no worker was asked", f"{move['workers']} workers")
        has_restart_event = wait_for_event(database_file, game_id, record["ply"], "restarted 28 worker(s)", 15)
        events = events_at(database_file, game_id, record["ply"])
        checker.check(any(event["level"] == "error" and "no usable answer" in event["message"] for event in events)
                      and has_restart_event, "ply 13: the events say Stockfish played it and all 28 restarted",
                      "; ".join(event["message"] for event in events))
        pool_is_complete_again("ply 13", 15)

        record = play("normal again")
        stored_workers = workers_at(database_file, game_id, record["ply"])
        checker.check(stored_workers and all(worker["status"] == "ok" for worker in stored_workers) and
                      searched_moves(stored_workers) == record["legal_moves"],
                      "ply 15: every worker 'ok' again, every legal move searched",
                      str(sorted({worker["status"] for worker in stored_workers})))

        # A hard kill of Engine UCI: the Job Objects must take every child down with it.
        workers = kernel_workers_of(game)
        stockfish = tools.children_of(game.pid, STOCKFISH_EXE_NAME)
        checker.check(len(workers) == NUMBER_OF_KERNEL_WORKERS and len(stockfish) == 1,
                      "before the hard kill: 28 workers and 1 Stockfish", f"{len(workers)} and {len(stockfish)}")
        tools.kill_process(game.pid)
        children = workers + stockfish
        checker.check(tools.wait_until(lambda: not any(tools.is_running(pid) for pid in children), 2),
                      "after the hard kill: no Kernel.exe and no Stockfish left running",
                      f"{sum(tools.is_running(pid) for pid in children)} still running")
    finally:
        game.close_quietly()

    stored = [row["ply"] for row in tools.rows(database_file, "SELECT ply FROM engine_moves WHERE game_id = ? "
                                               "ORDER BY ply", (game_id,))]
    checker.check(stored == stored_plies, "every move before the hard kill is in the database", str(stored))
    tools.write_json(out / "kernel_workers_test.json", {"summary": checker.summary(), "moves": game.moves})
    print(f"\n{checker.summary()['passed']} passed, {checker.summary()['failed']} failed   (details: {out})")
    print("RESULT: PASS" if checker.ok else "RESULT: FAIL")
    return 0 if checker.ok else 1


if __name__ == "__main__":
    sys.exit(main())
