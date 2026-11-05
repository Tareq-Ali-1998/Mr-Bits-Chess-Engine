# V3.3 - Mostly neural, with a handcrafted anchor

<div style="border-left:5px solid #7c3aed;background:#f5f3ff;color:#312e81;padding:10px 14px"><strong>STATIC SCORING: 80% Small neural network + 20% main-Kernel handcrafted scoring.</strong></div>

Give Small most of the static value while retaining a smaller contribution from your original score. This version is a copy of **v3.0's search**, with only the static evaluator's weights changed. It adds no top-K deletion, reductions, PVS or cache experiment. Read [How v3.0 works](../v3.0/HOW_V3_0_WORKS.md) for the common legal/search foundation.

## What remains the same?

| Part | Behavior shared with v3.0 |
|---|---|
| Legal moves and undo | Same generator, replay validation and exact restoration |
| Ordinary move ordering | Cheap heuristic and tactical prefix; Small sorts the quiet tail at depth 3+ when time permits |
| Candidate retention | Every legal ordinary candidate remains eligible; alpha-beta can still cut off |
| Quiescence | Same check-aware extension, maximum six extra plies, cheap move ordering |
| Mate and stalemate | Same terminal recognition and rule-based scores |
| Iterations and clock | Same even-depth sequence, time admission and incomplete-iteration handling |

The shared [V3 Evaluation Search.hpp](../V3%20Evaluation%20Search.hpp) is based on the v3.0/V7 search policy. The profile is fixed by the source's compile-time Small percentage.

## Where the percentages apply

```text
ordinary depth reaches zero
        |
        v
same v3.0 quiescence search
        |
        +-- exact mate/stalemate result, when terminal
        |
        +-- static value for stand pat / hard extension cap
              80% Small score + 20% handcrafted score
```

The handcrafted component is the main Kernel's maintained material/piece-square difference, **`engineScore - opponentScore`**, already in engine-perspective centipawns. Small returns White-perspective pawns; its active contribution is multiplied by 100 and signed for the engine's color. The weighted sum is rounded and clamped to the ordinary-score range of **-99,999 to +99,999**. Exact mate scores around one million retain priority.

These percentages cover every call to the static evaluator, including quiescence stand pat and its cap. They do not replace the shared terminal rules or alter which search nodes ask for a static score.

**Zero means skip the inactive scoring component.** The evaluator uses compile-time branches instead of calculating a component and multiplying it by zero. Both components are active for this profile. Their weights are compile-time constants; no runtime profile selection is needed inside the search.

<div style="border-left:5px solid #0284c7;background:#eff6ff;color:#0c4a6e;padding:10px 14px"><strong>Scoring and ordering are separate.</strong> Even the 0% Small-scoring profile keeps v3.0's Small-based quiet-move ordering. It therefore still requires the Small weights for a normal application run. The inherited make/undo code also keeps maintaining the incremental handcrafted scores needed by the existing search/heuristic machinery; a 0% handcrafted scoring profile skips reading that component in the static evaluator, not that shared bookkeeping.</div>

## Run and compare

After stopping an existing bot, open **Launch Server.bat** and enter **`v3.3`**. Only the Small model weights are required; the Large model is not used. Use `v3.0` for the unchanged 50/50 baseline comparison; the temporary legacy `v7` folder has been retired.

Compare **v3.0 (50/50), v3.1 (100/0), v3.2 (0/100), v3.3 (80/20), and v3.4 (20/80)** with the same positions, Small weights, worker allocation, clock and hardware. In that list the first percentage is always Small, the second handcrafted. Record tactical accuracy and equal-time results alongside depth and nodes. The weights are experimental choices; no Elo or best-move-retention guarantee follows from them.

The existing v3.1 already supplied the pure-Small experiment, so it is reused. There is deliberately **no v3.5 duplicate**. The previous beam/PVS experiments now live at v3.6-v3.9; see the [complete current and historical mapping](../VERSION_FAMILIES.md).

This profile does not add repetition/fifty-move adjudication or change the inherited bounded-quiescence approximation. Compilation and execution are separate verification steps; historical v7/v8 results are not fresh native results for these new weighted builds.

## Focused verification

From `lichess-bot-master/engines`, run `python tests/run_kernel_v3_evaluation_tests.py` for the four scoring profiles. `--syntax-only` checks their diagnostic translation units without running a native executable. The eight affected production builds (v3.1-v3.4 and shifted v3.6-v3.9) compiled during this revision; native behavioral results must be reported separately from that compilation.

