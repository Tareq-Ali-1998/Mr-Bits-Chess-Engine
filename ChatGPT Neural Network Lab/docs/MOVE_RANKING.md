# Legal-move ranking, independent teacher labels, and export

The network predicts one White-perspective pawn score. It evaluates all legal
successors in one batch. White ranks larger scores first; Black ranks smaller
scores first. Exact immediate terminal results override the network. Every legal
move remains in the output: this utility does not implement top-five pruning.

Run commands from the new lab directory. Replace example paths with your actual
prepared data and checkpoints; no pretrained strength is implied.

```powershell
python -m chesslab.rank --checkpoint runs/small/best.pt --fen "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" --top 7
python -m chesslab.rank --checkpoint runs/small/best.pt --fen "YOUR FEN" --json
```

The text output prints all candidates and marks the first requested `--top`
moves. JSON includes both `ranked` and `top`. Equal neural scores have a stable
UCI-move ordering. A root position already terminal returns its exact result and
an empty ranking.

`board782_v1` omits clocks and repetition history. Incoming positions are
normalized to the supported state: counters 0/1, recorded en-passant file and
retained castling rights preserved. This is a visible-state experiment. A real
engine must handle history-dependent draw rules using its complete state.

## Build a small independent benchmark

The source evaluated-position cache does not give a complete, uniformly searched
score for every legal child. A strict move-retention metric requires that missing
information. This command searches **each nonterminal child independently**:

```powershell
python -m chesslab.teacher --engine "..\lichess-bot-master\stockfish-windows-x86-64-avx2.exe" --data data/prepared --split test --positions 100 --nodes 50000 --threads 4 --hash-mb 256 --output benchmarks/test.jsonl
```

This can be expensive: 100 parents with 30 children each request approximately
150 million search nodes, before node-budget overshoot and other overhead.
The CLI prints the actual selected child count and requested workload before
labeling. This is a work estimate; wall time must be measured. Start with
`--positions 2 --nodes 1000` for a wiring check, not a chess-quality claim.

External FEN JSONL is also supported. Each line is a JSON string or an object
containing `fen`. Supply `--fen-jsonl positions.jsonl` instead of selecting
prepared parents. `--data` remains required for leakage checking.

Selection is repeatable for a fixed source, prepared manifest, seed, and candidate
limit. `--max-candidates` bounds the pool (default: at least 100 or 20 times the
requested parent count). Prepared rows use seeded random selection; external
JSONL uses a bounded prefix. The CLI may accept fewer parents than requested
because of duplicates, terminals, or overlap and reports the actual count.

Before searching, it computes every candidate parent's and every legal child's
compact position key. A bounded-memory scan of prepared `train.npy` and
`validation.npy` excludes a final-test candidate if **any** of those keys is present.
Test parents are normally selected from the test split. A separately declared
`--split validation` benchmark excludes training overlap, allows validation
positions, and records `purpose: validation` in its header and report. It is for
choosing settings, not final test evidence. External FENs inherit this explicit
`--split` purpose. The final-test exclusion policy is deliberately strict and can
remove many common openings. Increase the candidate pool rather than relaxing
the audit silently.

The benchmark header records feature version, prepared-data fingerprint,
selection, engine-reported ID, executable SHA-256, options, per-child requested
node budget, and the exclusion policy. Each child stores actual total reported
search nodes, elapsed seconds, and the depth/nodes of the last completed score
update without an upper/lower bound. A node cap can interrupt a later aspiration
search; such a bound never replaces the preceding scalar target. Every child
has the same requested cap, while completed score depth/work can differ. Scores
remain typed and White-perspective:

- `cp`: a finite centipawn score.
- `mate`: explicit winning color and nonnegative mate distance.
- `terminal`: exact immediate win/draw result and termination reason.

Stockfish's hash is cleared before every nonterminal child so earlier siblings'
transposition entries cannot silently reuse their budget. MultiPV is managed by
python-chess and each search requests one PV. Scores remain budget-dependent
teacher estimates, not chess proofs. Threads can affect reproducibility; a fixed
node limit and cleared hash do not promise bit-for-bit identical multithreaded
searches.

The JSONL writer flushes and synchronizes after each complete parent. Resume with
the same command plus `--resume`; changed data, selection, engine, or options are
rejected. A malformed/truncated final line is rejected for explicit repair rather
than silently discarded. Ranking rejects an unfinished benchmark, duplicate
parents or children, incorrect keys, false terminals, and partial legal-child
sets. These structural checks do not authenticate manually edited labels.

## Measure strict retention and near-best retention separately

```powershell
python -m chesslab.rank --checkpoint runs/small/best.pt --benchmark benchmarks/test.jsonl --output reports/small-ranking.json
```

The checkpoint's prepared-data fingerprint must match the benchmark's leakage
audit. One parent is one observation. Reports include overall and separate White/
Black results, sample counts, and Wilson 95% intervals:

- **Strict best recall @1, @5, @7:** does that prefix contain any exactly tied
  teacher-best move? All tied best moves count; no arbitrary first-PV tie breaker.
- **Near-best recall:** independently asks whether a prefix retains a finite
  teacher score within 25 cp of the best (override with `--near-cp`). Its denominator
  excludes parents whose best target is mate rather than a finite score.
- **Top-one cp regret:** loss relative to the teacher-best score, only when both
  teacher-best and chosen-move teacher scores are finite. Mean, median, p95,
  maximum, and the actual comparable-parent count are explicit.
- **Mate-category disagreements:** counted separately; forced mates are not
  converted to invented centipawn penalties. Mate distances are ordered with faster
  wins and slower losses preferred. Immediate draw results compare as zero cp.

A parent with fewer than five legal moves still contributes one parent to @5;
all its moves are retained. High @5 on such positions is easy and must be read
with material/legal-move coverage. Wilson intervals summarize these position
counts; correlated positions or small samples limit interpretation. They are not
Elo confidence intervals. A low average cp error, high retention rate, or this
small teacher test alone does not establish that pruning improves engine play.

Keep the final benchmark frozen while choosing settings on a separate validation
benchmark. Inspect tactical failures and then run equal-time engine games before
making strength claims.

The report also records legal-move count coverage and measured end-to-end ranking
latency per parent after one explicit warm-up pass. This includes legal move
generation, terminal checks, feature encoding, synchronized batch inference, and
sorting; checkpoint/benchmark loading and teacher search are excluded. It is
different from a dense-network-only microbenchmark. `--cpu-threads` controls the
PyTorch CPU thread count (default one) and is recorded alongside the timings.

## Export a dense evaluator artifact

```powershell
python -m chesslab.export --checkpoint runs/small/best.pt --output exports/small.torchscript.pt
```

The TorchScript input is **float32 `[batch,782]`**, in the frozen feature order;
the output is **float32 `[batch,1]`**, signed White-perspective pawn scores.
The compact `[batch,78]` preprocessing is not embedded. A consumer must reproduce
the feature contract and handle exact terminal/history rules itself. This is a
model artifact, not an API server or an integration into the existing C++ engine.

Export compares eager and traced outputs for seeded binary features, zero/all-one
features, batch one, and a larger batch, then reloads and checks the serialized
artifact before committing it. Those shape/numerical checks are not legal-chess
coverage or evidence of strength. The `.pt.json` sidecar records the exact input/
output contract, model and target metadata, parity tolerance, and artifact hash.
Existing artifacts are not overwritten. `--reuse-existing` accepts only an intact
artifact whose checksum and source-checkpoint checksum match. The evaluation
wrapper uses checkpoint-specific names under the run's `exports/` directory, so
it can be rerun safely after more training. The original checkpoint remains separate.

Local Python 3.14/PyTorch checks passed, but that PyTorch runtime warns that
TorchScript APIs are deprecated/unsupported on Python 3.14 and may break in a
future version. Pin a tested compatible Python/PyTorch environment for this
artifact format. This export is not a promise of support across runtime versions.
