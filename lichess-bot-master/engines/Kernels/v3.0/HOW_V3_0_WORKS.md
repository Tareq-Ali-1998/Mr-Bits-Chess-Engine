# ♟️ How V3.0 thinks

**Naming note:** v3.0 is the legal/quiescence design previously called v7. The temporary old v7 folder has been retired; select v3.0 and use this canonical guide. Historical check counts and diagnostic paths retain their original identities. [Family map](../VERSION_FAMILIES.md).

<style>
body{font-family:Segoe UI,Arial,sans-serif;line-height:1.4;color:#223047}h1,h2{color:#2354a5}h3{color:#17795e}table{border-collapse:collapse;width:100%}th,td{border:1px solid #cbd5e1;padding:.32em .48em}th{background:#edf3fc}pre{white-space:pre-wrap;font-size:.86em}@media print{body{font-size:10pt;line-height:1.25}h1{font-size:18pt}h2{font-size:14pt}h3{font-size:11pt}table,pre{break-inside:avoid}}@page{size:A4;margin:15mm}
</style>

**A friendly tour of the search — from one position to one chosen move.**

<div style="border-left:5px solid #16a34a;background:#f0fdf4;color:#14532d;padding:10px 14px;margin:12px 0;">
<strong>🟢 The idea:</strong> keep every legal candidate available, search useful moves early, and look beyond the ordinary leaf when an exchange is still happening. Small helps both ordering and evaluation. V3.0 combines it with your original scoring.
</div>

## 🟩 1 / 5 · The whole journey

V3.0 started as a copy of your Kernel. It keeps the board, 16-bit moves, occupancy masks, incremental scores, worker protocol, and general engine organization. Its main additions live in [V7 Position.hpp](../V7%20Position.hpp) and [V7 Search.hpp](../V7%20Search.hpp).

```text
Worker receives position history + assigned root moves
                         |
                Replay and validate
                         |
             Try depth 2, then 4, then 6...
                         |
        Generate legal moves --> order --> alpha-beta
                         |
              Ordinary depth reaches zero
                         |
       Short tactical search: exchanges / check evasions
                         |
              50% your score + 50% Small
                         |
          Return the last completed iteration's best
```

**A depth is measured in plies:** one move by one side. Depth six means six plies of ordinary search, followed where needed by up to six additional quiescence plies. It does not mean twelve plies for every branch.

### Legal first, clever second

The position helper generates candidate moves, temporarily commits each one, and rejects any move leaving its own king attacked. It covers pins, king adjacency, all four promotion choices, castling, and en passant. Enemy kings are never capturable pieces in this tree.

Two details matter: an en-passant capture can uncover an attack on the king; queenside castling needs an empty b-file square, but an attack on that square alone does not forbid castling. V3.0 checks the king's actual path instead.

Replay history is checked move by move. An invalid history is rejected and its changes rolled back. Supplied root moves must be legal and unique.

### One worker is one part of the root

The controller can assign different root moves to different workers. If the position has **30 legal root moves** and this worker receives **6**, V3.0 retains those 6. The other 24 were not deleted by its neural sorter; they are outside this worker's assignment.

An empty assigned list does not prove stalemate. V3.0 separately checks the complete legal move pool before reporting checkmate or stalemate. This distinction keeps parallel search results meaningful.

<div style="page-break-before:always;"></div>

## 🟦 2 / 5 · Exactly when does it sort?

At the root and ordinary internal nodes, V3.0 calls `OrderMoves(depth, moves)`. Here, `depth` means **remaining ordinary depth at that node**, not distance from the starting position.

| Situation | What happens? |
|---|---|
| Zero or one candidate | Return immediately; no sorting batch |
| Two or more candidates | Your simple heuristic orders the complete list |
| After heuristic ordering | Captures, en passant, and every promotion form a tactical prefix |
| Remaining depth below 3 | Keep the heuristic order within both groups |
| Depth at least 3, enough quiet moves/time | Small reorders only the quiet tail |
| Quiescence search | Cheap heuristic ordering only; no neural sorting batch |

The tactical partition preserves the heuristic order inside each group. Castling belongs to the quiet group for this policy. A checking move that neither captures nor promotes also belongs there; “quiet” here describes move type, not whether it gives check.

### A concrete 30-move example

Suppose a node has **30 legal moves: 6 tactical + 24 quiet**.

```text
Before: 30 legal candidates
   |
Your heuristic scores and orders all 30
   |
Tactical prefix [ 6 ] | quiet tail [ 24 ]
   |                         |
Keep cheap order       Small scores 24 child positions
   |                         |
   +---------- Final ordered list: 30 moves ----------+
```

At remaining depth 4, Small can order those 24 quiet moves. At remaining depth 2, it orders **zero**; the existing heuristic order remains. Neither case deletes a legal candidate.

The time gate also requires at least two quiet moves. In timed mode, the remaining budget must be at least:

**`max(5, ceil(quiet_count / 8))` milliseconds.**

For 24 quiet moves, that threshold is **5 ms**. It is an admission heuristic, not a measured prediction that inference will finish in 5 ms. Fixed-depth tests disable the normal clock budget.

### What does one neural sort actually do?

For each candidate, the sorter commits the move, builds the child's turn/castling/en-passant flags, asks Small for one score, caches it, and restores the parent. It then sorts the cached scores. **The comparator never runs the network.** White moves rank higher White-perspective scores first; Black moves rank lower scores first. Equal scores preserve their incoming order.

<div style="border-left:5px solid #2563eb;background:#eff6ff;color:#1e3a8a;padding:10px 14px;margin:12px 0;">
<strong>🔵 How many are discarded?</strong> No fixed “top 5” or “top 7” filter exists in V3.0's ordinary search. All legal candidates remain eligible. Alpha-beta can stop examining later siblings once the current search bounds prove they cannot change the choice.
</div>

<div style="page-break-before:always;"></div>

## 🟪 3 / 5 · Search deeper where the position is unstable

### Alpha-beta: use what the tree already proved

The engine maximizes its own score; the opponent minimizes it. Suppose one root move already guarantees **+80 cp**. In another root move's continuation, the opponent finds a response limiting the engine to **+20 cp**. That continuation cannot beat +80, so the remaining sibling responses may be skipped.

This is a search-bound cutoff. It is different from deleting a move because the network ranked it badly. Good ordering helps the useful bound appear sooner, which can save considerable work; it does not guarantee the smallest possible tree.

V3.0 uses ordinary alpha-beta. It has **no late-move reduction, fixed top-k filter, transposition table, or neural confidence threshold**. Every retained ordinary continuation begins at its nominal requested depth; alpha-beta may still cut its subtree.

### Why a normal leaf can mislead us

Imagine the last searched move captures a rook, but the capturing piece can immediately be recaptured. Evaluating only that intermediate board can exaggerate the gain. V3.0's quiescence search continues selected tactical lines after ordinary depth reaches zero.

```text
At a quiescence node:
  1. Generate legal moves and detect mate/stalemate.
  2. Extension allowance exhausted? Return static score.
  3. In check? Search every legal evasion.
  4. Otherwise, use static score as a stand-pat baseline.
     Continue captures, en passant, and all promotions.
  5. Recurse with one fewer extension ply; use alpha-beta.
```

“Stand pat” means using the current evaluation as a search baseline while considering tactical continuations. It is not an actual pass move. V3.0 does not use that normal baseline cutoff while in check: a quiet king escape or blocking move may be compulsory.

Outside check, quiet non-promotion moves are omitted from **quiescence only**. A stand-pat bound may also end that node before tactical children are searched. This is selective search, with limitations; it is not a full search of every possible continuation beyond the nominal leaf.

### Mate is a rule result

No legal moves **and** king attacked → checkmate. No legal moves **and** king safe → stalemate, score zero. These checks happen before neural inference, including at the extension cap.

Mate scores start at **±1,000,000**, adjusted by distance: the engine prefers faster wins and delays forced losses. Ordinary evaluations are clamped to **±99,999**, so an ordinary estimate cannot impersonate mate.

<div style="border-left:5px solid #d97706;background:#fffbeb;color:#78350f;padding:10px 14px;margin:12px 0;">
<strong>🟠 A deliberate limit:</strong> quiescence has at most six extra plies. At the cap, a nonterminal position is evaluated statically even if still in check. <code>qCheckCapHits</code> counts that approximation. Repetition, fifty-move, and insufficient-material draw adjudication are not implemented in V3.0.
</div>

<div style="page-break-before:always;"></div>

## 🟧 4 / 5 · How does a position become a score?

Small receives the current board and a few state flags. It does not receive the whole move sequence. History is replayed to construct the board and retain the necessary state.

```text
8 x 8 board + side to move + retained castling rights + EP file
                             |
                    782 logical input features
                             |
                    256 ReLU --> 64 ReLU --> 1
                             |
                  White-perspective pawn estimate
```

The 782 features are 768 piece-square indicators, one side-to-move flag, four castling flags, and nine en-passant possibilities including “none.” The C++ evaluator uses active features for the first layer rather than multiplying every zero input. See the separate [operation-count guide](../../Neural%20Networks/OPERATION_COUNTS.md) for arithmetic details.

Positive neural output favors White, regardless of the engine's color. V3.0 converts pawn units to centipawns and then to the engine's perspective:

**`neural_engine_cp = white_pawns × 100 × (White engine ? +1 : -1)`**

The handcrafted score already has the engine's perspective:

**`legacy_engine_cp = engineScore - opponentScore`**

The static result is their rounded, clamped average:

**`V3.0 static = 0.50 × legacy_engine_cp + 0.50 × neural_engine_cp`**

For a White engine, legacy +80 cp and Small +1.20 pawns produce **+100 cp**. For a Black engine viewing the same board, equivalent inputs produce **−100 cp**. The actual side to move still enters the network separately.

These are estimated positional advantages, not probabilities of winning. Training made Small approximate searched teacher evaluations; the network alone does not calculate a proof of the position's value. V3.0's search explores continuations around that estimate. The 50/50 weights are starting choices, not a measured optimum.

### The part that respects your original engineering

Ordinary recursion uses a scoped `UndoMove` guard. It saves **2 touched squares** for normal moves/promotions, **3** for en passant, or **4** for castling, plus masks and running scores. Returning from the child restores exactly those values, including when an exception leaves the scope.

That keeps the make/search/unmake loop incremental. Legal filtering uses the same mechanism. The occupancy masks still locate pieces without a fresh board-wide piece-discovery loop.

The shared neural sorter has a different rollback implementation: it saves one complete parent snapshot and restores its board/counters after each scored candidate. That is fixed-size work on an 8×8 board, but it is still real copying; the recursive touched-square optimization should not be confused with the sorting helper.

Independent full-score recomputation also found an inherited Black en-passant update using the wrong color's piece-square tables. V3.0 fixes that in its own copy. The original and earlier versions remain separate.

<div style="page-break-before:always;"></div>

## 🟫 5 / 5 · Time, evidence, and what deserves credit

### Finish something useful before the clock expires

V3.0 searches depths **2, 4, 6, …**. After a completed timed iteration, it estimates the next one's cost using measured iteration growth, adds a **25% safety factor**, and reserves **5 ms**. It stops admitting another iteration once elapsed time reaches **80%** of the allowed budget.

Growth is clamped between 2× and 64×; after the first iteration it initially assumes 16×. These are conservative starting rules, not predictions that every position will follow.

The hard deadline is checked throughout search. If a deeper iteration is interrupted, its incomplete result is discarded and the last completed iteration remains available. If none finishes, the worker reports `no_completed_depth`; the controller's existing fallback remains relevant. Model loading, an inference batch, and a legal-generation batch cannot be interrupted halfway through, so timing is not a hard real-time guarantee.

### The strongest parts of this design

| 🟢 Decision | Why it matters |
|---|---|
| Keep every legal ordinary candidate | Neural ranking mistakes do not permanently remove a hidden tactical resource |
| Spend Small ordering on deeper quiet branches | Avoid paying a neural batch at every near-leaf node |
| Check legality and terminal rules explicitly | Search scores refer to valid continuations, with mate distinct from an estimate |
| Extend exchanges and check evasions | Reduce the risk of stopping halfway through an immediate tactical sequence |
| Restore exact touched state | Preserve your compact representation and incremental recursion |
| Report counters and incomplete iterations | Make behavior observable rather than judging it from one impressive move |

The achievement is their integration into your engine. Alpha-beta, quiescence, and legal make/unmake filtering are established chess-engine techniques; the implementation, policy choices, and compatibility work here are specific to this project.

### What has actually been checked?

The recorded V3.0 verification passed **73,448 checks**, including 136 independently generated positions, legal-move/perft comparisons, state restoration, score/sign checks, quiescence comparisons, mate searches, and actual worker requests. Starting-position perft depth 4 counted **197,281** legal move sequences. Perft checks the move tree; it does not measure playing strength.

Read the [verification summary](../../../Mr%20Bits%20Docs/ChatGPT%20Neural%20Network%20Lab/diagnostics/kernel-v7-20261029/final-summary.json) when that local diagnostics folder is present. These checks support the tested behavior. Equal-time tactical tests and games must establish any strength gain; no Elo increase or 95% best-move retention has been demonstrated.

Choose **7 / v3.0** in `Launch Server.bat` after stopping the current bot. Small weights are required. The worker JSON exposes regular/quiescence nodes, evaluation counts, ordering batches, cap hits, mates, stalemates, and deadline observations. `nodes` covers the last completed iteration; `totalNodes` includes every iteration attempted. The extra `searchPolicy` counters are not yet stored by the SQLite writer.

**My recommendation:** use V3.0 as the mixed-evaluation reference when comparing V3.1's neural-only evaluation. Keep time controls and root assignments comparable, then measure tactical correctness, time, and game results before choosing a default.
