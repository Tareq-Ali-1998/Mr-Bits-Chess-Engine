# Kernel families and scoring profiles

<div style="border-left:5px solid #16a34a;background:#f0fdf4;color:#14532d;padding:12px 16px"><strong>V7's replacement is v3.0.</strong> The temporary legacy v7 folder and launcher entry have been retired, and <strong>v3.0</strong> is the selected replacement. Its legal/quiescence search and 50/50 static evaluation are unchanged. Stop an existing application before starting another run or selecting a different strategy.</div>

## The current scoring controls

The first five v3 revisions share **v3.0's legal generation, exact undo, move ordering, candidate retention, quiescence and clock policy**. Their static scoring percentages provide a controlled comparison. The first percentage below always means Small; the second means the main Kernel's handcrafted component.

| Version | Small neural scoring | Handcrafted scoring | What changes from v3.0? |
|---|---:|---:|---|
| **v3.0** | **50%** | **50%** | Existing baseline |
| **v3.1** | **100%** | **0%** | Static value only; existing pure-Small profile reused |
| **v3.2** | **0%** | **100%** | Static value only; no Small inference for static evaluation |
| **v3.3** | **80%** | **20%** | Static value only |
| **v3.4** | **20%** | **80%** | Static value only |

```text
same legal search and move ordering
                  |
        same bounded quiescence
                  |
          static score required?
                  |
      active scoring components only
                  |
       Small% + handcrafted% -> round/clamp
```

A component with zero weight is skipped by a compile-time branch. This includes skipping Small's state construction, model load and inference in **v3.2's static evaluator**. It does not remove v3.0's separate Small-based quiet-move ordering. Normal v3.2 runs therefore still require Small weights. The make/undo code also keeps maintaining the incremental scores used by the common search and heuristics; a zero handcrafted weight skips that component in static scoring, rather than deleting shared bookkeeping.

The percentages apply to all static-evaluator calls, including quiescence stand pat and its hard cap. Mate/stalemate recognition retains the same rule-based results. All five profiles keep ordinary legal candidates eligible; none adds a fixed top-K cutoff.

**There is deliberately no v3.5 duplicate.** The previous v3.1 already implemented the requested 100% Small / 0% handcrafted experiment, so it remains v3.1. Moving another copy to v3.5 would add no distinct experiment.

## Three design families

The major number identifies a search foundation; the minor number identifies an experiment within it. These are design labels, not Elo rankings.

| Family | Foundation | Current revisions |
|---|---|---|
| `original` | Existing baseline at `engines/Kernel.cpp` | Still named `original` |
| **v1.x** | Legacy search and handcrafted ordinary leaves | v1.0 Large/top-four; v1.1 ordering only; v1.2 guarded root cutoff |
| **v2.x** | Legacy search with neural ordinary leaves | v2.0 pure Small; v2.1 50/50 blend; v2.2 guarded late reductions |
| **v3.x** | Legal moves, exact undo, mate/stalemate and Q6 | Scoring controls v3.0-v3.4, plus the experiments below |

| Retained experiment | Static scoring | Search distinction |
|---|---|---|
| **v3.6** | 0% Small / 100% handcrafted | Large sorts expanded lists; keep three, including ordinary/Q check evasions |
| **v3.7** | 50% Small / 50% handcrafted | Same aggressive Large/top-three policy |
| **v3.8** | 100% Small / 0% handcrafted | All ordinary candidates eligible; PVS re-search and exact static-value cache |
| **v3.9** | 50% Small / 50% handcrafted | Small/top-ten at remaining ordinary depth 3+; no sorting at depth 2/1 or in Q |

Only the **first four derivatives after v3.0** isolate static evaluation percentages. The later experiments intentionally change search behavior and should not be treated as scoring-only comparisons. Root cutoffs apply per worker's assigned subset, not as one global shortlist.

## Revision change on 5 November 2026

The first family-naming release used v3.1-v3.5 for the earlier experiments. The scoring controls now take the first four derivative positions:

| Before this scoring reorganization | Current name | Action |
|---|---|---|
| v3.0 | **v3.0** | Baseline unchanged |
| v3.1, 100% Small | **v3.1** | Reused; no duplicate v3.5 |
| - | **v3.2** | New 0% Small / 100% handcrafted control |
| - | **v3.3** | New 80% Small / 20% handcrafted control |
| - | **v3.4** | New 20% Small / 80% handcrafted control |
| v3.2, Large/top-three | **v3.6** | Existing experiment shifted |
| v3.3, Large/top-three blend | **v3.7** | Existing experiment shifted |
| v3.4, PVS/static cache | **v3.8** | Existing experiment shifted |
| v3.5, Small/top-ten | **v3.9** | Existing experiment shifted |

The old whole-number names map to the current set as follows:

| Historical whole-number name | Current name |
|---|---|
| original | **original** |
| v1 / v2 / v3 | **v1.0 / v1.1 / v1.2** |
| v4 / v5 / v6 | **v2.0 / v2.1 / v2.2** |
| v7 / v8 | **v3.0 / v3.1** |
| v9 / v10 / v11 / v12 | **v3.6 / v3.7 / v3.8 / v3.9** |

The temporary plain **v7** folder and launcher entry were retired on 5 November 2026 at your request. Use **v3.0** for the same baseline. Historical records named v7 still keep that recorded identity; v7 is not an additional current strategy.

## Choose the full version string

After stopping an existing application, open **Launch Server.bat** and enter a full name:

```text
v3.0   50% Small / 50% handcrafted baseline
v3.1   100% Small / 0% handcrafted
v3.2   0% Small / 100% handcrafted
v3.3   80% Small / 20% handcrafted
v3.4   20% Small / 80% handcrafted
v3.9   the separate Small/top-ten search experiment
```

A displayed menu number is just an ordinal. Use the full version when writing commands or recording an experiment. Names are strings, not floating-point numbers: **v3.10 follows v3.9**. Leading zeros are rejected.

```powershell
# From lichess-bot-master: list only, without changing selection
& '.\Launch Server.bat' --list

# Build only, without selection or games
& 'engines/Kernels/Build Version.bat' v3.3

# After stopping the current application: prepare the next selection only
& '.\Launch Server.bat' --version v3.3 --prepare-only
```

Normal launch checks weights, builds the chosen kernel/controller when needed, probes Kernel startup, then saves selection and starts the bot. `--prepare-only` skips execution but still changes next-run selection. Building a strategy alone does not select or start it. The retired V7 setup has been replaced by the selected v3.0 baseline.

## Historical records remain historical

**Existing database rows and diagnostic results keep their recorded identities.** An older `kernel=v3.2` row can mean the previous Large/top-three policy; a newly built v3.2 means 100% handcrafted static scoring. Use the recorded worker/controller build IDs and date together with the revision table above. The dashboard does not silently turn an old v3.2 game into v3.6 or rewrite its history.

The same caution applies when parameters changed under an older whole-number label. A label mapping is a reading aid, not proof that two builds are byte-identical. Historical verification counts are not fresh native tests of the new profiles.

Shared implementation headers such as `V7 Position.hpp`, `V7 Search.hpp`, `V11 Search.hpp` and `V12 Search.hpp` keep their existing filenames/namespaces for traceability and reuse by the current family implementations. The scoring-only derivatives use [V3 Evaluation Search.hpp](V3%20Evaluation%20Search.hpp). Historical test-script names also remain stable; their current source paths and active version arguments follow the current map.

## Focused verification

From `lichess-bot-master/engines`, run `python tests/run_kernel_v3_evaluation_tests.py` for the four scoring profiles. `--syntax-only` checks their diagnostic translation units without running a native executable. The eight affected production builds (v3.1-v3.4 and shifted v3.6-v3.9) compiled during this revision; native behavioral results must be reported separately from that compilation.

<div style="border-left:5px solid #8b5cf6;background:#f5f3ff;color:#312e81;padding:12px 16px"><strong>The proposed search-table engine remains queued.</strong> We previously called it V13. Its family/revision name is unassigned until its design is agreed. Discuss the <a href="../../Mr%20Bits%20Docs/V13_MEMORY_PLAN.html">combined worker memory budget</a> before implementation; these scoring profiles do not implement that proposal.</div>

Read the [kernel index](README.md), [application/dashboard guide](../../Mr%20Bits%20Docs/START_HERE_KERNELS_AND_DASHBOARD.md), or [v3.0 walkthrough](v3.0/HOW_V3_0_WORKS.md) next.
