# 🧠 V3.1 · Let Small judge the position

<div style="border-left:5px solid #7c3aed;background:#f5f3ff;color:#312e81;padding:10px 14px"><strong>STATIC SCORING: 100% Small neural network + 0% main-Kernel handcrafted scoring.</strong></div>

**Version identity:** `v3.1` was previously called `v8`. Historical verification counts, build stamps and diagnostic paths below retain that earlier identity; they are not fresh execution results for renamed binaries. [Family map](../VERSION_FAMILIES.md).

<div style="border-left:5px solid #8b5cf6;background:#f5f3ff;color:#312e81;padding:12px 16px;">
<strong>The experiment:</strong> keep V3.0's legal search, tactical extensions, move ordering, and clock policy, but change every ordinary static position score to <strong>100% Small neural evaluation</strong>. This isolates one meaningful choice: does our trained evaluator work better alone or in V3.0's 50/50 blend?
</div>

**Scoring matrix update, 5 November 2026:** this existing pure-Small profile already matches the requested v3.1, so it is reused. No duplicate v3.5 is retained. Compare it with [v3.2: 100% handcrafted](../v3.2/README.md), [v3.3: 80% Small / 20% handcrafted](../v3.3/README.md), and [v3.4: 20% Small / 80% handcrafted](../v3.4/README.md). All four retain v3.0's ordering and search policy. The zero-weight handcrafted component is compiled out of the static evaluator; shared incremental bookkeeping remains unchanged.

Read [How V3.0 works](../v3.0/HOW_V3_0_WORKS.md) first for the complete search explanation. V3.1 began as an exact PowerShell copy of V3.0; its evaluation policy now uses the shared [V3 Evaluation Search.hpp](../V3%20Evaluation%20Search.hpp), with compile-time weights. Older versions remain separate experiments.

## 🟪 1 / 2 · What the network decides

```text
Board + actual side to move + castling rights + en-passant file
                             |
                       782 input features
                             |
                  Small: 782 -> 256 -> 64 -> 1
                             |
                    White-perspective pawns
                             |
                  x 100, then engine-color sign
                             |
              round + ordinary-score safety clamp
                             |
                    alpha-beta / quiescence
```

The board is your existing `int8_t[8][8]`; no move-history neural model or GPU is needed. The branch state supplies the flags. Small's output is positive for White, regardless of whose turn it is. Search scores must instead be positive for the engine.

For example, a network output of **+1.20 pawns** becomes **+120 centipawns for a White engine**, or **−120 for a Black engine**. V3.1 returns that neural value, rounded to an integer. The handcrafted material/piece-square score contributes **zero** to it. We clamp ordinary scores to ±99,999 so they cannot outrank checkmate scores around ±1,000,000.

| Decision | V3.0 | V3.1 |
|---|---|---|
| Ordinary static value | 50% handcrafted + 50% Small | **100% Small** |
| Quiet-move neural ordering | Small | Small |
| Tactical ordering | Cheap existing heuristic | Same |
| Normal legal candidates | Retain all | Same |
| Quiescence | Up to six extra plies | Same |
| Terminal mate/stalemate | Exact rule-based score | Same |
| Large model required | No | No |

**“100% neural evaluation” describes the static value, not every part of the engine.** Rules still determine legal moves and terminal positions. Alpha-beta still searches. Your cheap heuristic still helps choose the order to inspect moves. Legacy running scores remain maintained by the inherited make/undo code, but the V3.1 evaluator does not read them. Changing those scores alone cannot change its returned static value.

A checkmated position therefore never asks the network whether it is good or bad. The legal search recognizes the terminal position first. Stalemate returns zero. This is deliberately more reliable than asking a regression model to recognize those rules numerically.

<div style="page-break-after:always;"></div>

## 🟦 2 / 2 · Which moves are searched, and when?

```text
At a regular node
  -> generate legal moves and handle mate/stalemate
  -> cheap heuristic order; captures/promotions first
  -> remaining depth >= 3 and enough time?
       yes: Small sorts the quiet tail
       no:  keep its heuristic order
  -> alpha-beta search; retain every legal candidate

At normal depth zero
  -> quiescence, up to 6 extra plies
       in check: every legal evasion
       otherwise: neural stand-pat + captures/EP/promotions
  -> terminal rules or pure Small static value
```

There is **no “keep the best five” rule**, no new late-move reduction, and no neural threshold deleting regular candidates. If a regular node has 30 legal moves, all 30 remain eligible. Alpha-beta can stop searching siblings when its bounds prove they cannot improve the result in that search window. A deadline can interrupt an iteration. Those are different from assuming a low neural rank makes a move worthless.

At the root, each worker receives a subset from the controller. V3.1 retains every legal move in its assigned subset; it cannot restore candidates that the controller did not send. Every supplied root candidate is considered in a completed iteration, while internal alpha-beta cutoffs still reduce continuation work.

Small sorting applies only to **at least two quiet moves**, at remaining depth three or more, with at least `max(5, ceil(quiet_count / 8))` milliseconds left. Captures, en passant, and promotions stay in the tactical prefix. Quiescence uses cheap ordering rather than neural sorting batches; its static evaluations still call Small. At the six-ply extension cap, a nonterminal position is evaluated even if still checked; `qCheckCapHits` makes that approximation visible.

### ⏱️ Cost, use, and the useful comparison

Small's architecture has **216,961 parameters**. Its actual first layer adds active binary-feature columns rather than multiplying every one of the 782 inputs. Later layers remain dense. A position call is independent of search depth, but many positions or move-ordering batches multiply that cost. See [exact Small/Large operation counts and m-move sorting formulas](../../Neural%20Networks/OPERATION_COUNTS.md); those arithmetic counts are not measured CPU instructions or latency.

Launch `Launch Server.bat` and choose **v3.1** after stopping an existing bot. Only `Neural Networks/Small/weights.bin` is required. The launcher performs its offline worker startup check before starting the bot. Use `Launch Dashboard.bat` for existing completed-move history. Additional `searchPolicy` counters remain in worker JSON; the SQLite writer does not yet preserve those extra fields.

Compare V3.0 and V3.1 with the same positions, Small weights, worker count, hardware, and time controls. Measure tactical accuracy, completed depth, actual time, and game results. The pure evaluator may change move ordering indirectly through search results, node counts, and cutoffs. **Neither version is an established strength winner yet.** V3.1 is the cleaner experiment for learning whether the trained value model helps by itself.

The inherited limits still matter: no repetition/fifty-move/insufficient-material adjudication here, a bounded quiescence horizon, and clock estimates that cannot interrupt a model load, legal-generation batch, or individual inference batch. There is no new transposition table in this version.

<div style="border-left:5px solid #0891b2;background:#ecfeff;color:#164e63;padding:12px 16px;">
<strong>What I like about this version:</strong> it gives your network a clear responsibility while keeping the search protections. V3.0 asks whether a blend helps; V3.1 asks whether the network can carry the ordinary position score alone. The comparison can teach us something concrete, even if V3.0 ultimately wins.
</div>

**Offline verification, 31 October 2026:** 73,688 checks passed against the independent legal-move/quiescence oracle, including sign/unit conversion and deliberately altered handcrafted scores that leave V3.1's value unchanged. The managed executable also passed the launcher startup probe and seven actual worker searches, including complete assigned root lists, Black en passant, mate, and timed/expired requests. These are correctness checks, not a strength rating. Repeat the oracle from `lichess-bot-master` with `python engines/tests/run_kernel_v8_tests.py`; local reports are under the lab's `diagnostics/kernel-v8-20261031/`.

## Focused verification

From `lichess-bot-master/engines`, run `python tests/run_kernel_v3_evaluation_tests.py` for the four scoring profiles. `--syntax-only` checks their diagnostic translation units without running a native executable. The eight affected production builds (v3.1-v3.4 and shifted v3.6-v3.9) compiled during this revision; native behavioral results must be reported separately from that compilation.

