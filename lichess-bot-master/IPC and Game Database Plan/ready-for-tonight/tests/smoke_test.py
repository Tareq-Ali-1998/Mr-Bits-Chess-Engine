"""Smoke test: drive Engine UCI with the REAL python-chess exactly the way lichess-bot 2024.6.6.2 does.

Mirrors (file:line in lichess-bot-master):
  UCIEngine.__init__      lib/engine_wrapper.py:493  popen_uci(commands, timeout=10., debug=False, setpgrp=True, stderr=..., cwd=...)
  EngineWrapper.configure lib/engine_wrapper.py:106  configure(uci_options | game_specific_options(game))  (uci_options is {})
  get_opponent_info       lib/engine_wrapper.py:418  send_opponent_information(opponent=Opponent(...), engine_rating=me.rating)
  move_time               lib/engine_wrapper.py:639  first move of each side: Limit(time=10); later: clocks - move_overhead
  search                  lib/engine_wrapper.py:244  play(board, limit, info=INFO_ALL, ponder=..., draw_offered=..., root_moves=None)
  __exit__                lib/engine_wrapper.py:117  ping(); quit()  then SimpleEngine.close()

Usage (PowerShell, normal PATH):
  python -B harness\\smoke_test.py --engine "<root>\\engines\\Engine UCI.exe" --cwd <dir> --label A --out <dir>
"""
import argparse
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import time
import traceback

import chess
import chess.engine


class Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def snapshot(folder: pathlib.Path) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob("*")} if folder.exists() else set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--moves", type=int, default=4)
    ap.add_argument("--start-moves", default="", help="space-separated UCI moves played before the test starts")
    ap.add_argument("--clock-ms", type=int, default=9000, help="simulated remaining clock of both sides (2+3 game)")
    ap.add_argument("--inc-ms", type=int, default=3000)
    ap.add_argument("--move-overhead-ms", type=int, default=2000, help="config.yml move_overhead")
    ap.add_argument("--game-id", default="tN252leL")
    ap.add_argument("--no-game-id", action="store_true", help="configure({}) like today's extra_game_handlers.py")
    ap.add_argument("--env", action="append", default=[], help="KEY=VALUE added to the engine's environment")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    engine_path = os.path.abspath(args.engine)
    cwd = pathlib.Path(args.cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    root = pathlib.Path(engine_path).parent.parent

    wire_log = out / f"{args.label}_pychess_wire.log"
    logger = logging.getLogger("chess.engine")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(wire_log, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s %(message)s", "%H:%M:%S"))
    logger.addHandler(fh)
    warnings = Collect()
    logger.addHandler(warnings)

    summary: dict = {"label": args.label, "engine": engine_path, "cwd": str(cwd), "python_chess": chess.__version__,
                     "moves": []}
    before = snapshot(cwd)
    engine = None
    try:
        popen_args: dict = {"cwd": str(cwd)}
        if args.env:
            env = dict(os.environ)
            for item in args.env:
                key, _, value = item.partition("=")
                env[key] = value
            popen_args["env"] = env
        t = time.perf_counter()
        # silence_stderr: false  ->  lichess-bot passes stderr=subprocess.DEVNULL (engine_wrapper.py:51)
        engine = chess.engine.SimpleEngine.popen_uci([engine_path], timeout=10., debug=False, setpgrp=True,
                                                     stderr=subprocess.DEVNULL, **popen_args)
        summary["handshake_ms"] = round((time.perf_counter() - t) * 1000)
        summary["pid"] = engine.transport.get_pid()
        summary["id"] = dict(engine.id)
        summary["declared_options"] = {name: {"type": o.type, "default": o.default}
                                       for name, o in engine.options.items()}

        extra = {} if args.no_game_id else {"GameId": args.game_id}   # = proposed game_specific_options(game)
        t = time.perf_counter()
        try:
            engine.configure({} | extra)
        except Exception:
            engine.close()          # what EngineWrapper.configure does before re-raising
            raise
        summary["configure_ms"] = round((time.perf_counter() - t) * 1000)

        opponent = chess.engine.Opponent(name="Demolito_L4", title="BOT", rating=1692, is_engine=True)
        engine.send_opponent_information(opponent=opponent, engine_rating=1700)

        board = chess.Board()
        for uci in args.start_moves.split():
            board.push_uci(uci)
        replies = ["e7e5", "b8c6", "g8f6", "f8c5", "d7d6", "a7a6"]
        white_clock = black_clock = args.clock_ms / 1000
        inc = args.inc_ms / 1000
        for n in range(args.moves):
            if len(board.move_stack) < 2:                          # lichess-bot first_move_time()
                limit = chess.engine.Limit(time=10, clock_id="first move")
                ponder = False
            else:                                                  # lichess-bot game_clock_time()
                overhead = args.move_overhead_ms / 1000
                limit = chess.engine.Limit(white_clock=max(0.0, white_clock - overhead), black_clock=black_clock,
                                           white_inc=inc, black_inc=inc, clock_id="real time")
                ponder = True                                      # config.yml engine.ponder: true
            limit.depth = None                                     # add_go_commands() with no go_commands
            limit.nodes = None
            fen_before = board.fen()
            t = time.perf_counter()
            result = engine.play(board, limit, info=chess.engine.INFO_ALL, ponder=ponder, draw_offered=False,
                                 root_moves=None)
            elapsed = time.perf_counter() - t
            move = result.move
            legal = move is not None and move in board.legal_moves
            summary["moves"].append({"ply": len(board.move_stack), "limit": str(limit), "ponder_flag": ponder,
                                     "bestmove": move.uci() if move else None, "legal": legal,
                                     "play_ms": round(elapsed * 1000), "fen_before": fen_before})
            print(f"[{args.label}] ply {len(board.move_stack)}: bestmove {move} legal={legal} "
                  f"in {elapsed * 1000:.0f} ms", flush=True)
            if not legal:
                break
            board.push(move)
            if len(board.move_stack) > 2:
                white_clock = white_clock - elapsed + inc
            reply = chess.Move.from_uci(replies[n]) if n < len(replies) else None
            if reply not in board.legal_moves:
                reply = sorted(board.legal_moves, key=lambda m: m.uci())[0]
            board.push(reply)

        t = time.perf_counter()
        engine.ping()          # EngineWrapper.__exit__: ping() ...
        engine.quit()          # ... then quit()
        summary["ping_quit_ms"] = round((time.perf_counter() - t) * 1000)
        summary["ok"] = all(m["legal"] for m in summary["moves"]) and len(summary["moves"]) == args.moves
    except Exception as e:
        summary["ok"] = False
        summary["error"] = f"{type(e).__name__}: {e}"
        summary["traceback"] = traceback.format_exc()
        print(f"[{args.label}] ERROR {type(e).__name__}: {e}", flush=True)
    finally:
        if engine is not None:
            engine.close()
        time.sleep(0.3)
        logger.removeHandler(fh)
        fh.close()

    summary["warnings"] = warnings.records
    summary["cwd_new_entries"] = sorted(snapshot(cwd) - before)
    pid = summary.get("pid")
    if pid is not None:
        logs = sorted((root / "logs").glob(f"uci_*_pid{pid}.log"))
        if logs:
            copy = out / f"{args.label}_engine_command.log"
            shutil.copyfile(logs[-1], copy)
            summary["engine_log"] = str(logs[-1])
    (out / f"{args.label}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("traceback",)}, indent=1)[:4000])
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
