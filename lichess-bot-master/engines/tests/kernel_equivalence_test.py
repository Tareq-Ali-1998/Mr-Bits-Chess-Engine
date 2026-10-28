"""Does the Kernel worker think EXACTLY like the old Kernel.exe? 72 positions, the same depth, the same tree.

  cd lichess-bot-master\\engines
  python -B tests\\kernel_equivalence_test.py --reference <an old Kernel.exe> [--reference-mode file|worker]

The reference is a Kernel.exe from before (the one that read a JSON file: --reference-mode file, the default),
or another worker build (--reference-mode worker), for example after a change in the search. The worker under
test is engines\\Kernel.exe (or --worker <exe>).

  * file mode: the old Kernel.exe runs once per position, time-based (--seconds, 1 by default), and its report
    says the last depth it completed. A completed depth never saw the clock run out, so it's exactly the tree
    of an untimed search at that depth.
  * the worker then answers every position at that same depth (maxDepth), and bestMove, score, nodes, leaf
    nodes, pruned and depth must all be identical.
  * every request goes to ONE worker process, twice, in a shuffled order and with both colours: a game state
    that isn't reset between two requests (the board, ENGINE_COLOR, the scores) can't hide that way.

The positions are in tests\\data\\positions.json (60 random games plus castling, en passant and promotions).
"""
import argparse
import json
import pathlib
import random
import re
import subprocess
import sys
import tempfile
import time

TESTS_DIRECTORY = pathlib.Path(__file__).resolve().parent
COMPARED_FIELDS = ("bestMove", "score", "nodes", "leafNodes", "pruned", "depth")

# The numbers of the old Kernel's text report (ProcessHandler::getReport).
REPORT_FIELDS = {
    "depth": r"The current depth: (-?\d+)",
    "leafNodes": r"The number of all the final states \(Leaf Nodes\): (-?\d+)",
    "nodes": r"The number of all the inner and final states: (-?\d+)",
    "pruned": r"The number of all pruned branches: (-?\d+)",
}


def chess_state_request(position, seconds):
    """Exactly what ChessState::serializeObject() writes (the old JSON file, and now the request line)."""
    return {"engineColor": position["engineColor"], "allowedEngineTimeInSeconds": seconds,
            "previousMoves": position["moves"], "bestMove": "", "bestMoveScore": 0,
            "movesForThisThread": position["rootMoves"], "report": ""}


def run_the_old_file_mode(exe, json_file, request):
    json_file.write_text(json.dumps(request, indent=4), encoding="utf-8")
    finished = subprocess.run([str(exe), str(json_file)], capture_output=True, timeout=600)
    answer = json.loads(json_file.read_text(encoding="utf-8"))
    result = {"returncode": finished.returncode, "bestMove": answer.get("bestMove"), "score": answer.get("bestMoveScore")}
    for field, pattern in REPORT_FIELDS.items():
        match = re.search(pattern, answer.get("report", ""))
        result[field] = int(match.group(1)) if match else None
    return result


class Worker:
    """One Kernel.exe worker: one request line in, one answer line out."""

    def __init__(self, exe, stderr_file):
        self.stderr = open(stderr_file, "wb")
        self.process = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, bufsize=0)

    def ask(self, request):
        self.process.stdin.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise EOFError(f"the worker closed its stdout (exit code {self.process.poll()})")
        if line.endswith(b"\r\n"):
            raise ValueError("the answer line ends in \\r\\n (only a bare \\n is allowed)")
        return json.loads(line)

    def quit(self):
        self.process.stdin.write(b'{"type":"quit"}\n')
        self.process.stdin.close()
        try:
            exit_code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()         # only ever this test's own child
            exit_code = self.process.wait()
        self.stderr.close()
        return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", required=True, help="the Kernel.exe to compare with")
    parser.add_argument("--reference-mode", choices=("file", "worker"), default="file")
    parser.add_argument("--worker", default=str(TESTS_DIRECTORY.parent / "Kernel.exe"), help="the worker under test")
    parser.add_argument("--seconds", type=int, default=1, help="the time of the old time-based search")
    parser.add_argument("--depth", type=int, default=6, help="the fixed depth, when the reference is a worker")
    parser.add_argument("--out", default=None, help="the output folder (default: a new temporary one)")
    arguments = parser.parse_args()
    out = pathlib.Path(arguments.out or tempfile.mkdtemp(prefix="mrbits-kernel-equivalence-"))
    (out / "files").mkdir(parents=True, exist_ok=True)
    positions = json.loads((TESTS_DIRECTORY / "data" / "positions.json").read_text(encoding="utf-8"))
    print(f"Reference : {arguments.reference} ({arguments.reference_mode} mode)\nWorker    : {arguments.worker}\n"
          f"Positions : {len(positions)}\nOutput    : {out}", flush=True)

    # 1. The reference answers, and the depth each position is compared at.
    start = time.perf_counter()
    reference_answers = []
    if arguments.reference_mode == "file":
        for index, position in enumerate(positions):
            answer = run_the_old_file_mode(arguments.reference, out / "files" / f"position_{index:02d}.json",
                                           chess_state_request(position, arguments.seconds))
            if answer["returncode"] != 0 or answer["depth"] is None:
                print(f"FAIL  the reference failed on position {index}: {answer}")
                return 1
            reference_answers.append(answer)
    else:
        reference = Worker(arguments.reference, out / "reference_stderr.txt")
        for index, position in enumerate(positions):
            request = chess_state_request(position, arguments.seconds)
            request.update({"type": "search", "id": index, "maxDepth": arguments.depth})
            reference_answers.append(reference.ask(request))
        reference.quit()
    print(f"reference done in {time.perf_counter() - start:.1f} s, depths reached: "
          f"{sorted({answer['depth'] for answer in reference_answers})}", flush=True)

    # 2. Every position twice, shuffled, through ONE worker, at the reference's depth.
    jobs = [index for index in range(len(positions)) for _ in range(2)]
    random.Random(20261027).shuffle(jobs)
    worker = Worker(arguments.worker, out / "worker_stderr.txt")
    hello = worker.ask({"type": "hello"})
    mismatches, answers_by_position = [], {}
    start = time.perf_counter()
    for request_id, index in enumerate(jobs, start=1):
        request = chess_state_request(positions[index], arguments.seconds)
        request.update({"type": "search", "id": request_id, "maxDepth": reference_answers[index]["depth"]})
        answer = worker.ask(request)
        if answer.get("id") != request_id or answer.get("status") != "ok":
            mismatches.append({"position": index, "field": "status/id", "worker": answer})
            continue
        for field in COMPARED_FIELDS:
            if answer[field] != reference_answers[index][field]:
                mismatches.append({"position": index, "depth": reference_answers[index]["depth"], "field": field,
                                   "reference": reference_answers[index][field], "worker": answer[field]})
        answers_by_position.setdefault(index, []).append({field: answer[field] for field in COMPARED_FIELDS})
    exit_code = worker.quit()
    repeats_differ = sum(1 for answers in answers_by_position.values() if answers[0] != answers[-1])
    worker_seconds = time.perf_counter() - start

    summary = {"positions": len(positions), "requests": len(jobs), "mismatches": len(mismatches),
               "repeats_that_differ": repeats_differ, "worker_exit_code": exit_code, "worker_hello": hello,
               "worker_seconds": round(worker_seconds, 1),
               "stderr_bytes": (out / "worker_stderr.txt").stat().st_size}
    (out / "kernel_equivalence.json").write_text(json.dumps({"summary": summary, "mismatches": mismatches,
                                                            "reference": reference_answers}, indent=1),
                                                 encoding="utf-8")
    print(json.dumps(summary, indent=1))
    if mismatches:
        print(json.dumps(mismatches[:10], indent=1))
    is_ok = not mismatches and repeats_differ == 0 and exit_code == 0 and summary["stderr_bytes"] == 0
    print("RESULT: PASS" if is_ok else "RESULT: FAIL")
    return 0 if is_ok else 1


if __name__ == "__main__":
    sys.exit(main())
