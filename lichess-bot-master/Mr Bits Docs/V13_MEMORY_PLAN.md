# Proposed search-table experiment: the worker memory budget (formerly V13)

<div style="border-left:5px solid #38bdf8;background:#eff6ff;color:#172554;padding:12px 16px">
<strong>This is a proposed design, not an implemented or measured engine.</strong> We previously called it V13. Existing kernels are now grouped into families; this proposal's future family/revision name is unassigned. Discuss the total worker budget before deciding whether to implement it.
</div>

**For the current 28 workers, the proposed explicitly counted data totals about 289 MiB.** Adding a provisional 4 MiB allowance per worker makes the planning subtotal about **401 MiB**. These numbers are **not a hard upper bound on all worker processes' RAM**: existing dynamic inputs and process overhead still need limits and measurements. One MiB here means 1,048,576 bytes.

## 🟢 The idea: spend memory once to avoid repeated work

The proposal would start from v3.0's legal search (formerly V7) and check-aware quiescence, initially keep its 50/50 handcrafted/Small evaluation, and add PVS with full re-search when needed. A bounded search transposition table would remember search results; PV, history and killer moves would provide cheap ordering. The Small network would evaluate positions rather than repeatedly sorting every candidate through a neural network. The Large network would not be needed by this design.

```text
          ONE search-table budget: 256 MiB total
                          │
              divide by actual worker count
                          │
         ┌────────────────┼────────────────┐
      Worker 1         Worker 2         Worker 28
      ≤9.143 MiB        ≤9.143 MiB        ≤9.143 MiB
      search table     search table     search table
      + Small/cache    + Small/cache    + Small/cache
```

**Each worker is a separate process**, so its model and caches must be counted separately. Giving every worker a 256 MiB table would cost **7 GiB just for those tables**. That is not this proposal.

## 🔢 What exactly is counted?

The existing Small model has **216,961 FP32 parameters**. Its evaluation workspace contains 576 floats. The v3.8-style static evaluation cache (formerly V11) holds 4,096 entries; its recorded layout is 76 bytes per entry on the current build ABI. The additional heuristic arrays below are proposed sizes.

| Explicit data | Bytes per worker | All 28 workers |
|:--|--:|--:|
| Small parameter payload | 867,844 | 23.174 MiB |
| One Small evaluation workspace | 2,304 | 0.062 MiB |
| Static evaluation cache | 311,296 | 8.313 MiB |
| History: `2 × 64 × 64` signed 32-bit scores | 32,768 | 0.875 MiB |
| Two 16-bit killer moves per 64 plies | 256 | 0.007 MiB |
| PV: `64 × 64` encoded 16-bit moves | 8,192 | 0.219 MiB |
| Proposed Zobrist random-number arrays | 6,352 | 0.170 MiB |
| Search transposition tables, combined | divided share | **≤256 MiB** |
| **Explicit payload subtotal** | — | **≈288.818 MiB** |

For `W` workers, the exact payload formula is:

```text
256 × 1,048,576 + W × 1,229,012 bytes
W = 28 → 302,847,792 bytes ≈ 288.818 MiB

Provisional scratch allowance:
28 × 4 MiB = 112 MiB
Planning subtotal ≈ 400.818 MiB
```

For the search table, allocate at most `floor(total_budget / (W × sizeof(Entry)))` entries per worker. Larger entries mean fewer entries, while the combined payload remains within budget. We must verify structure sizes in the actual compiler; allocator bookkeeping is additional. Retaining neural move sorting would also add its separate workspace and scoring buffer, which this proposal does not count.

## 🟠 Why I cannot promise “all workers will never exceed X RAM” yet

Depth-first search keeps the **live search path**, not every node it has ever visited. The current ordinary depth limit is 30 and quiescence adds at most six levels. Searching millions of nodes therefore does not mean retaining millions of boards.

However, the current request reader accepts an uncapped line, and JSON, replay histories, legacy lookup vectors, move lists and report buffers allocate dynamically. Process stacks, runtime libraries and allocator overhead also consume memory. **The 4 MiB allowance is a planning reserve, not an enforced arena or a proved bound.**

Before claiming a full bound, we would cap request/history sizes, bound live move/scratch storage, retain explicit depth limits and measure every worker under stress. A **1 GiB aggregate worker planning target** is a reasonable starting allocation to test against, not a measured maximum or a guarantee. The UCI/controller, its reader threads, Stockfish and the operating system require additional RAM outside that target.

## 🛡️ Correct search results matter as much as the budget

A search-table hit must account for remaining depth, exact/lower/upper bounds and mate-distance normalization. Castling, legal en passant and side to move belong in position identity. Repetition and the halfmove clock also affect results: we must restrict reuse when draw history differs, rather than treating a board hash as the complete game state. The static neural cache and search-result table serve different purposes.

## 📌 Our next-step reminder

**Naming migration:** [the three-family map](../engines/Kernels/VERSION_FAMILIES.md) is now the current organization: the old V7 is v3.0 and the old V12 top-ten experiment is v3.9. The temporary old v7 folder has been retired; v3.0 is the selected baseline replacement. **This proposal stays queued:** discuss and agree on the total memory limits before any implementation. We will choose its family/revision label when its actual search design is settled; V13 is only the historical proposal name.

The code behind the current numbers: [worker count](../engines/Engine%20UCI.cpp), [Small model](../engines/Neural%20Networks/Small/Small.hpp), [v3.8 static cache](../engines/Kernels/V11%20Search.hpp), [v3.0 search](../engines/Kernels/v3.0/Kernel-v3.0.cpp) and [worker processes](../engines/Kernel%20Workers.hpp).
