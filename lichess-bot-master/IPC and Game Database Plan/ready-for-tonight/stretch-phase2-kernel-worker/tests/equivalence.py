"""Equivalence: file mode (one fresh process per request) vs worker mode (ONE process, shuffled order).

usage: python equivalence.py <exe> <tag>
Every (position, depth) is sent to the worker TWICE, in one shuffled stream, so the test also checks
"same answer whenever a request repeats" with other requests in between.
"""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw  # noqa: E402

exe = os.path.abspath(sys.argv[1])
tag = sys.argv[2]
DEPTHS = [4, 6]
positions = json.load(open(os.path.join(kw.HERE, "data", "positions.json")))
outdir = os.path.join(kw.HERE, "runs", tag)
os.makedirs(os.path.join(outdir, "files"), exist_ok=True)

# ------------------------------------------------------------ 1. file mode
file_results = {}
t0 = time.perf_counter()
for i, pos in enumerate(positions):
    for d in DEPTHS:
        path = os.path.join(outdir, "files", f"pos{i:02d}_d{d}.json")
        r = kw.run_file_mode(exe, path, kw.file_request(pos, max_depth=d))
        assert r["returncode"] == 0, (i, d, r["returncode"], r["stderr"][:300])
        assert r["stdout"] == b"", (i, d, r["stdout"][:300])
        file_results[(i, d)] = r
file_total_s = time.perf_counter() - t0

# ------------------------------------------------------------ 2. worker mode
stream = [(i, d) for i in range(len(positions)) for d in DEPTHS] * 2
random.Random(77).shuffle(stream)
w = kw.Worker(exe, os.path.join(outdir, "worker_stderr.txt"))
hello = w.request({"type": "hello"})
mem_start = w.memory()
answers = {}
order = []
t0 = time.perf_counter()
for n, (i, d) in enumerate(stream):
    ans = w.request(kw.search_request(positions[i], n, d))
    assert ans["type"] == "result" and ans["id"] == n and ans["status"] == "ok", ans
    answers.setdefault((i, d), []).append(ans)
    order.append([n, i, d])
worker_total_s = time.perf_counter() - t0
mem_end = w.memory()
rc, rest = w.quit()
stderr_bytes = os.path.getsize(os.path.join(outdir, "worker_stderr.txt"))

# ------------------------------------------------------------ 3. compare
FIELDS = ["bestMove", "score", "nodes", "leafNodes", "pruned", "depth"]
mismatches = []
repeat_mismatches = []
for key, fr in sorted(file_results.items()):
    a1, a2 = answers[key]
    if kw.strip_timing(a1) != kw.strip_timing(a2):
        repeat_mismatches.append({"key": key, "first": a1, "second": a2})
    for f in FIELDS:
        if fr[f] != a1[f]:
            mismatches.append({"key": key, "field": f, "file": fr[f], "worker": a1[f]})

summary = {
    "exe": exe,
    "positions": len(positions),
    "depths": DEPTHS,
    "fileModeRuns": len(file_results),
    "workerRequests": len(stream),
    "fieldMismatches": len(mismatches),
    "repeatMismatches": len(repeat_mismatches),
    "workerExitCode": rc,
    "workerTrailingStdoutBytes": len(rest),
    "workerStderrBytes": stderr_bytes,
    "hello": hello,
    "memStart": mem_start,
    "memEnd": mem_end,
    "fileModeTotalS": round(file_total_s, 2),
    "workerTotalS": round(worker_total_s, 2),
    "fileModeMeanWallMsPerRequest": round(1000 * file_total_s / len(file_results), 2),
    "workerMeanWallMsPerRequest": round(1000 * worker_total_s / len(stream), 2),
    "meanSearchMs": {d: round(sum(answers[(i, d)][0]["searchMs"] for i in range(len(positions))) / len(positions), 2) for d in DEPTHS},
    "nodesRange": {d: [min(answers[(i, d)][0]["nodes"] for i in range(len(positions))),
                       max(answers[(i, d)][0]["nodes"] for i in range(len(positions)))] for d in DEPTHS},
    "bestMoveChangedBetweenDepths": sum(answers[(i, 4)][0]["bestMove"] != answers[(i, 6)][0]["bestMove"] for i in range(len(positions))),
    "inexactRootScores": sum(1 for v in answers.values() for rs in v[0]["rootScores"] if not rs["exact"]),
    "allRootScores": sum(len(v[0]["rootScores"]) for v in answers.values()),
}
json.dump({"summary": summary, "mismatches": mismatches, "repeatMismatches": repeat_mismatches[:5],
           "order": order,
           "answers": {f"{i}_{d}": v[0] for (i, d), v in answers.items()},
           "file": {f"{i}_{d}": {k: v for k, v in r.items() if k not in ("stdout", "stderr")}
                    for (i, d), r in file_results.items()}},
          open(os.path.join(outdir, "equivalence.json"), "w"), indent=1)
print(json.dumps(summary, indent=1))
if mismatches:
    print("FIRST MISMATCHES:", json.dumps(mismatches[:10], indent=1))
