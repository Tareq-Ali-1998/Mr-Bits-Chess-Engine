# 🔥 V9 · Large chooses three; your evaluator judges the leaves

<style>
body{font-family:Segoe UI,Arial,sans-serif;line-height:1.4;color:#223047}h1,h2{color:#2354a5}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5e1;padding:.3em .45em}th{background:#edf3fc}pre{white-space:pre-wrap;font-size:.86em}@media print{body{font-size:10pt;line-height:1.25}h1{font-size:18pt}h2{font-size:14pt}table,pre{break-inside:avoid}}@page{size:A4;margin:15mm}
</style>

<div style="border-left:5px solid #ea580c;background:#fff7ed;color:#7c2d12;padding:10px 14px;">
<strong>Your aggressive experiment:</strong> ask Large to rank every eligible move, retain only its first three, and search that smaller tree. Ordinary position values come entirely from your original material/piece-square scoring. Large chooses the shortlist; it does not replace the leaf evaluator.
</div>

## 🟧 1 / 2 · Exactly what V9 does

V9 began as an exact PowerShell copy of V8. It retains the newer legal move generation, exact make/undo, mate/stalemate handling, alpha-beta, bounded quiescence, worker protocol, and clock admission. Its policy is in [V9 V10 Search.hpp](../V9%20V10%20Search.hpp); read [the V7 walkthrough](../v7/HOW_V7_WORKS.md) for that shared foundation.

```text
Regular node or worker root
    |
Validate/generate legal candidates and recognize terminals
    |
Large evaluates EVERY candidate's child position once
    |
Sort best to worst for the side making the move
    |
Keep min(3, candidate_count); discard the rest
    |
Alpha-beta search of those retained continuations
    |
Leaf / tactical-search static value: your original score
```

If there are **30 candidates**, Large evaluates all 30, then V9 retains **3** and discards **27**. For two candidates it evaluates both and keeps both. Even one candidate receives a Large evaluation; an empty list returns immediately. Ranking uses the moving side: White prefers a higher White-perspective score; Black prefers a lower one. Ties preserve incoming order.

There is **no depth threshold, cheap-ordering fallback, or protected capture/check-evasion exception**. Captures, promotions, quiet checks, and necessary-looking defensive moves compete for the same three places. At an in-check node with seven legal evasions, only Large's three highest-ranked evasions continue. This is the intentionally aggressive policy you asked to test.

### Which evaluator is used?

```text
ordinary value = engineScore - opponentScore
```

Those are your incrementally maintained material and piece-square scores, in engine-perspective centipawns. V9 does not call Small for static evaluation. Nonterminal values retain the inherited ±99,999 clamp; rule-based mate scores remain around ±1,000,000 and stalemate remains zero.

At ordinary depth zero, V9 retains the bounded six-ply tactical extension. Outside check, it first tries its static stand-pat bound, then considers captures, en passant, and promotions. If that candidate list needs searching, **Large ranks it and the same top-three limit applies**. While in check, the eligible list starts with every legal evasion before the limit. At the extension cap, the static evaluator is used after terminal recognition. Thus “always Large” describes each eligible list that reaches move expansion; a terminal, cap, deadline, or stand-pat cutoff can return before sorting.

<div style="page-break-before:always;"></div>

## 🟥 2 / 2 · Why try it, and what can go wrong?

The attraction is the narrow tree: ordinary branching is at most three, suggesting a `3^depth` shape before alpha-beta and tactical extensions. That can permit greater nominal depth. **It does not prove a better move.** A winning sacrifice or the opponent's strongest defense can be ranked fourth and disappear permanently. Alpha-beta then solves the retained tree, not the full legal tree.

Large still scores every candidate **before** the narrowing. At the 38-active-feature bound, each position uses about **34,126,336 useful arithmetic operations** under the documented MAC convention. Ranking 30 moves can therefore cost up to **1,023,790,080** such operations, before encoding, activations, and sorting overhead. Keeping three does not reduce that initial cost to three evaluations. See [operation counts](../../Neural%20Networks/OPERATION_COUNTS.md).

The search-only branching bound also omits legal-generation work and Large's per-node ranking work. With up to `b` candidates available for ranking, a coarse bound is `O(b × C_large × 3^(d+6))`, plus legality and comparison costs. Quiescence and alpha-beta usually make the actual tree different. This is a cost model, not a runtime prediction.

### A worker's three is not the whole engine's three

The controller supplies a root subset to each worker. If four workers each receive eight moves, each worker can retain its own best three: up to **12 root candidates across those four subsets**, not one global best-three shortlist. Deeper internal nodes independently apply the same policy to their own legal continuations.

| Worker field / counter | What it tells you |
|---|---|
| `rootScores` | Up to three retained root candidates from the last completed iteration |
| `unsearchedRootMoves` | Assigned root candidates omitted from that iteration's search |
| `rootCandidatesBefore/Retained/Discarded` | The root beam decision |
| `largeOrderingCalls`, `largeRankedMoves` | Started ranking batches and successfully scored candidates |
| `beamOrderingBatches`, `beamTruncations`, `beamDiscardedMoves` | Completed batches and deliberate omissions |
| `scoreScope: beam_restricted_tree` | Score/bound claims concern the retained tree |

The existing `pruned` count continues to describe alpha-beta cutoffs; it does not silently absorb beam omissions. Extra policy counters are returned in worker JSON but are not yet persisted by the SQLite writer. Root `exact` flags mean exact versus a bound **within this restricted search**, not a proof over discarded alternatives.

### Run and compare

Stop the current bot, open `Launch Server.bat`, and choose **9 / v9**. Only **Large** weights are required. The first load reads and validates the model once per worker process. Ranking batches are not interruptible; a deadline after a batch discards an unfinished iteration rather than substituting a different ranking policy.

The inherited timing and draw limits still apply: no repetition/fifty-move/insufficient-material adjudication, and a hard quiescence cap that can statically evaluate a nonterminal checked position. Compare equal-time results, tactical misses, and deadline failures against V7/V8. Greater displayed depth alone cannot establish strength, Elo, or 95% best-move retention.

**Verified offline, 31 October 2026:** 61,810 checks passed, including 136 independent legality/perft fixtures, direct Large-ranking parity and a Python-combined beam/quiescence oracle. The compiled worker also passed startup plus seven actual search requests. Repeat with `python engines/tests/run_kernel_v9_v11_tests.py --versions 9` from `lichess-bot-master`; local receipts are in the lab's `diagnostics/kernel-v9-v11-20261031/v9/`.

