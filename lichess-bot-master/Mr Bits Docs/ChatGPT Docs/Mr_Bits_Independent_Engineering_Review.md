<style>
:root { color-scheme: light dark; --bits-blue:#2563eb; --bits-green:#15803d; --bits-gold:#a16207; --bits-red:#b91c1c; }
body { max-width:1080px; margin:3rem auto; padding:0 1.4rem; font-family:Inter,Segoe UI,Arial,sans-serif; line-height:1.75; }
h1,h2,h3 { line-height:1.25; letter-spacing:-.02em; }
h1 { color:var(--bits-blue); font-size:2.7rem; }
h2 { border-bottom:2px solid #64748b55; padding-bottom:.5rem; margin-top:3rem; }
h3 { margin-top:2rem; }
table { border-collapse:collapse; width:100%; margin:1.3rem 0; font-size:.94em; }
th,td { border:1px solid #64748b55; padding:.65rem .8rem; text-align:left; vertical-align:top; }
th { background:#64748b18; }
blockquote { border-left:5px solid var(--bits-blue); background:#2563eb0d; padding:.8rem 1.2rem; margin:1.5rem 0; }
pre { overflow:auto; border:1px solid #64748b44; border-radius:9px; padding:1rem; background:#64748b0d; line-height:1.45; }
code { font-family:Cascadia Code,Consolas,monospace; font-size:.91em; }
a { color:var(--bits-blue); }
.bits-good { color:var(--bits-green); font-weight:700; }
.bits-watch { color:var(--bits-gold); font-weight:700; }
.bits-critical { color:var(--bits-red); font-weight:700; }
.bits-note { color:var(--bits-blue); font-weight:700; }
@media (prefers-color-scheme:dark) { :root { --bits-blue:#93c5fd; --bits-green:#86efac; --bits-gold:#fde68a; --bits-red:#fca5a5; } }
@media print { body { max-width:none; margin:0; font-size:10.5pt; } h2,h3 { break-after:avoid; } pre,blockquote { break-inside:avoid; } }
</style>

# ♟️ Mr. Bits — Inside the Engine

**An independent engineering review for Tareq Ali**  
**Reviewed:** 21 October 2026 · **Reviewer:** ChatGPT / Codex · **Scope:** your custom engine work

<p><span class="bits-good">🟢 Strong custom core</span> · <span class="bits-watch">🟡 Experimental search</span> · <span class="bits-critical">🔴 Rules need repair</span> · <span class="bits-note">🔵 Original source preserved</span></p>

> **Bro, my honest assessment:** this is a substantial personal engineering project. The evidence is in the representations, state transitions, search, and experiments—not in the size of the surrounding repository. You built a custom search core with deliberate decisions about work per node and memory per state. That deserves to be shown.
>
> The same review also finds serious gaps: the internal search does not enforce full chess legality, several special-move rules are faulty, and the process/protocol boundary can return invalid results. Those gaps currently prevent me from calling it a trustworthy standalone chess engine. They do **not** erase what the implementation demonstrates about your thinking.

**The strongest next version would preserve your ideas and make their correctness and benefit measurable.**

**How to read this:** the verdict and strengths explain what deserves attention in your portfolio. The findings explain what needs repair. The roadmap gives the order I would follow. There is no need to read the whole document in one sitting.

The colors are optional styling for HTML conversion. The emoji and text labels remain meaningful if your converter strips CSS. Diagrams use plain text so they render without a Mermaid plugin.

---

## 🧭 Reading map

1. [What I reviewed and how I tested it](#review-method)
2. [The honest verdict](#verdict)
3. [What the engine actually does](#architecture)
4. [The strongest engineering ideas](#strengths)
5. [Confirmed problems and important limitations](#findings)
6. [Complexity, memory, and performance](#complexity)
7. [Multithreading and communication](#parallelism)
8. [Search and evaluation improvements](#search-roadmap)
9. [Neural networks: a useful path](#neural)
10. [Validation and measurement](#validation)
11. [A practical improvement sequence](#priorities)
12. [Portfolio value and future documentation](#portfolio)
13. [Source map, evidence, and references](#appendix)

<a id="review-method"></a>

## 1. 🔬 What I reviewed and how I tested it

I read the three main custom components in full:

| File | Physical lines in this snapshot | What I examined |
|---|---:|---|
| [Engine UCI.cpp](../../engines/Engine%20UCI.cpp) | 751 | Command parsing, configuration, Stockfish routing, worker distribution, process launch, aggregation, history logging |
| [Kernel.cpp](../../engines/Kernel.cpp) | 3,414 | Representation, precomputation, special moves, incremental scoring, undo, both recursive searches, ordering, iterative deepening, timing, serialization, inactive trie |
| [Stockfish Handler.hpp](../../engines/Stockfish%20Handler.hpp) | 248 | Process interaction, temporary files, legal-move enumeration, evaluation parsing, best-move retrieval, terminal-state helpers |

That is **4,413 physical lines**, including comments, blank lines, and duplicated code—not a claim of 4,413 unique implementation lines.

I also inspected `Stockfish Handler Testing.cpp`, the small scratch C++ file, your Stockfish-handler TODO note, `.gitignore`, and all **30 JSON snapshots** in `input`. I checked the contents of the requested history directories: **`history` and `old_history` contain no files in this checkout**.

**`Claude Docs` was not opened or searched for content.** This report does not use Claude's assessment. I did not review the upstream Lichess implementation or attribute Stockfish's implementation to you. I did not open the account-information file or read authentication configuration.

### Evidence labels

| Label | Meaning |
|---|---|
| 🧪 **Reproduced** | Observed in a focused execution against freshly compiled source or a harness calling your unchanged functions |
| 📌 **Source-confirmed** | Directly visible in the code and its active call path |
| 🟡 **Risk / inference** | A consequence that depends on conditions such as concurrent games, a failed child process, or different timing |
| 💡 **Proposal** | My suggested future work; it is not something the current engine already implements |

### What I ran

I used **MinGW-w64 GCC 14.2.0**, C++17, on Windows. Both main C++ programs passed syntax checking with `-Wall -Wextra -Wconversion`, with warnings, and both compiled successfully with `-O2`. Test builds went into the operating system's temporary directory; I did not replace your checked-in executables.

A temporary C++ harness included your unchanged `Kernel.cpp`, renamed its entry point, and called its functions directly. An independent `python-chess` oracle, installed here as version **1.10.0**, supplied legal moves. The harness used its own FEN setup solely to construct focused test positions. **That setup is a test facility, not evidence that your engine supports FEN correctly.**

The tests covered:

- **13 focused positions:** initial position, a pinned piece, two castling failures, white and black en passant, false en passant, mate, stalemate, promotions for both colors, and ordinary castling for both colors.
- **324 sampled positions** from 12 seeded random legal playouts, each up to 80 plies, using seed `20261021` and sampling every third ply starting with the first.
- **10,935 generated move trials** in those sampled positions, checking board/count restoration, occupancy masks, and incremental scores against full recomputation.
- A depth-four traversal using your move generator, compared with independent legal perft.
- The rebuilt UCI handshake, a terminal FEN request, the actual Stockfish adapter, three copied saved-worker requests, and a zero-budget kernel request.

These are focused review checks, **not** a complete chess conformance suite, an Elo measurement, a stable performance benchmark, or a concurrency stress test. No games were played on your online account.

**Source preservation:** I changed no existing project source, configuration, input snapshot, history, executable, or Git history. The only repository addition for this review is this document. Temporary probe code is review scaffolding, outside the repository; it is not part of your engine implementation. The four reviewed C++ files' SHA-256 fingerprints are recorded in the appendix.

<a id="verdict"></a>

## 2. 🎯 The honest verdict

### What this project proves

It demonstrates that you can take a difficult, stateful problem and work below the level of ordinary application glue:

- Design compact representations rather than defaulting to strings and object graphs everywhere.
- Move repeated work into precomputation.
- Maintain derived state incrementally.
- Implement an adversarial tree search with alpha–beta bounds.
- Coordinate independent search workers.
- Instrument behavior and change an algorithm based on experiments.
- Persist requests and results so a complex computation can be inspected.

Those are meaningful skills for systems work, C/C++, embedded software, performance-sensitive backend components, and algorithm-heavy engineering. Your earlier interview experience is consistent with the project's explanatory value; I cannot turn that into a prediction about a future hiring decision.

### Where it stands today

| Dimension | My assessment | Why |
|---|---|---|
| 🟢 Algorithmic substance | **Strong personal-project evidence** | A custom move/search/evaluation core exists beyond the surrounding bot infrastructure |
| 🟢 Representation and local efficiency | **One of its strongest areas** | Packed moves, compact pieces, occupancy masks, incremental state, precomputed rays |
| 🟢 Ownership and curiosity | **Visible in the implementation** | Multiple working mechanisms and explicit experiments, including approaches you stopped using |
| 🟡 Search quality | **Ambitious, incompletely validated** | Alpha–beta and iterative deepening coexist with selective truncation and rules gaps |
| 🔴 Chess correctness | **Incomplete** | Pseudo-legal internal search, broken special-move cases, inadequate terminal/draw handling |
| 🟡 Parallel execution | **Useful prototype with real isolation** | Separate processes prevent global-state races, but coordination and load balancing need work |
| 🔴 General UCI reliability | **Partial implementation** | FEN is discarded downstream; search blocks the command loop; several search limits are unsupported |
| 🟡 Performance evidence | **Promising mechanisms, insufficient comparison** | Counters exist, but measurement has defects and no controlled ablation suite is present in the reviewed custom files |
| 🟡 Portfolio readiness | **Worth showcasing after focused preparation** | Needs an accurate ownership map, reproducible build, known limitations, and demonstrable tests |

I would describe it today as **an experimental custom C++ chess search engine integrated into a Stockfish-assisted Lichess bot**. That description gives your work its due and makes its boundaries clear.

I would not claim that it is stronger than Stockfish, assign it an Elo, call its current depth comparable to another engine's depth, or say that its optimization choices have all been proved faster. The reviewed evidence does not establish those things.

### My response to “performance over clean code”

I agree with prioritizing speed and memory where the program spends its time. A chess search should not acquire layers of indirection to satisfy a design-pattern checklist.

But a position object, a consistent undo record, explicit score meanings, and reliable move legality can all coexist with compact storage and inlining. They can also expose optimization opportunities. Your black-en-passant scoring bug is a concrete example: duplicated color-specific arithmetic made the fast path easier to get wrong.

**The tradeoff to measure is useful chess work per second.** More nodes that search impossible continuations, or fewer nodes that discard the only saving move, do not automatically mean a better engine.

<a id="architecture"></a>

## 3. 🗺️ What the engine actually does

### The active path

```text
        Lichess bot / another UCI client
                       │
                 UCI text commands
                       ▼
              Engine UCI.cpp
         parse position and clock values
                       │
                       ├── Stockfish Handler.hpp
                       │      launch Stockfish → enumerate legal root moves
                       │      optionally select a move in configured phases
                       │
                       ▼
          shuffle and divide root moves
                       │
           C++ coordinator threads
            ┌──────────┼──────────┐
            ▼          ▼          ▼
         JSON 1     JSON 2      JSON N
            │          │          │
         Kernel     Kernel      Kernel       separate processes
            │          │          │
         replay history from initial position
         precompute movement paths and tables
         iterative deepening + custom search
            │          │          │
         overwrite each request with its result
            └──────────┼──────────┘
                       ▼
          join, compare returned scores
                       │
          Stockfish terminal/draw helper
                       │
              history log + bestmove
```

The normal kernel entry point does **not** ask Stockfish to evaluate every node. Its evaluation uses your material values and piece-square tables. The large `ChessState` class duplicated inside the kernel contains Stockfish-related methods, but that launcher is not the active search path reached from `Kernel.cpp`'s `main`.

### Stockfish's roles, precisely

| Role | Current behavior | What it means for evaluating your work |
|---|---|---|
| Root legal-move provider | `getEngineMoveWithThreading()` calls `getAllPossibleMoves()` | Every normal decision relies on Stockfish to supply legal root choices |
| Opening move selector | Active UCI setup sets two engine opening moves, using the `< 4 plies` condition | A configurable assistance policy, not the definition of your entire engine |
| Late-game selector | Active UCI route delegates when `previousMoves.size() > 80` | This is after 80 half-moves, roughly 40 full moves; it is not a material-based endgame detector |
| Post-search helper | Checks the position after the proposed move and may ask Stockfish for another move | An attempted guard around a known terminal-state weakness |
| Optional NNUE helper | Adapter can ask for static evaluation and sort candidate moves | This facility exists, but it is not your active kernel leaf evaluator |

The first two opening engine moves and the late-game delegation are **snapshot settings**. I treat them as experiments, as you requested. Independently of those settings, the root legal-move dependency is architectural and should be documented.

### A move's journey through your custom kernel

1. The worker reads JSON containing move history, engine color, budget, and its assigned root moves.
2. It constructs the initial board, occupancy masks, mapping tables, move paths, and evaluation tables.
3. It replays the history, converting coordinate moves into packed integers.
4. It converts its assigned legal root moves into the same encoding.
5. It searches depths `2, 4, 6, …, 30`, subject to time controls and its stopping policy.
6. At each child it changes the board and scores, searches recursively, restores saved masks/scores, and undoes board changes.
7. It retains the last completed iteration and writes its selected move, score, and report back to the JSON file.

That is a complete, recognizable search pipeline. The issues below concern the meaning and reliability of parts of that pipeline, not whether you implemented one.

<a id="strengths"></a>

## 4. 💎 The strongest engineering ideas

### 4.1 Packed moves: compact data with operational value

**Location:** `Kernel.cpp:575–648`, with encoding also used throughout move precomputation.

Your move fits into **15 meaningful bits**:

| Bits | Field | Width |
|---|---|---:|
| `0–2` | Source row | 3 |
| `3–5` | Source column | 3 |
| `6–8` | Destination row | 3 |
| `9–11` | Destination column | 3 |
| `12–14` | Move type | 3 |

```text
  15 14       12 11        9 8         6 5         3 2         0
 ┌──┬──────────┬───────────┬───────────┬───────────┬───────────┐
 │0 │move type │to column  │to row     │from column│from row   │
 └──┴──────────┴───────────┴───────────┴───────────┴───────────┘
                     stored in int16_t
```

All eight type codes are used: ordinary move, four promotion choices, en passant, and two castling directions. This is a useful detail: you did not implement only queen promotion and leave underpromotion out of the representation.

**Why I rate it highly:** the encoding improves storage density, copying, move-list traffic, and extraction of fields. The bit operations serve the data model. They are more than decorative low-level syntax.

The current valid encodings remain nonnegative because bit 15 is unused. A future `uint16_t` move type and named masks would make the contract clearer without increasing storage. That would be a representation improvement, not a request to replace this design with heavy objects.

### 4.2 Compact pieces and a sensible hybrid board

**Location:** `Kernel.cpp:20–37`, `1046–1097`.

Your square stores type in the low three bits and color in bit 3. `piece & 7` extracts type; `piece & 8` extracts color. Type code 2 is deliberately unused in the active piece model.

The engine combines:

- A 64-byte square array for direct piece lookup.
- Two 64-bit occupancy masks to enumerate pieces by color.
- Mapping arrays connecting bit indices to coordinates.

This is a **hybrid mailbox/bitboard representation**, rather than a full set of per-piece attack bitboards. That is a reasonable intermediate design. It preserves easy square lookup while avoiding a scan through all empty squares whenever you enumerate one side's pieces.

You also guard the `__builtin_clzll` bit scan with a nonzero-mask loop. That matters because the zero-input case is not valid for that builtin. I am not going to criticize a bug that your loop already avoids.

**Next improvement:** use `uint64_t` and unsigned bit constants consistently. This better expresses bit-pattern arithmetic; the present signed types are not a reason to claim that every observed bit operation is broken.

### 4.3 Precomputed rays preserve the reason pieces stop

**Location:** `Kernel.cpp:1107–1395`, `1742–1942`.

The good idea is not simply “cache some moves.” You preserve the *structure* of slider movement by storing separate directional sequences. At runtime, a bishop, rook, or queen walks each sequence only until its first occupied square.

```text
 Precomputation                 Runtime on the current board

 bishop from d4                ray: e5 → f6 → g7 → h8
   NE: e5 f6 g7 h8                    empty  enemy
   NW: c5 b6 a7                        add    add, then STOP
   SE: e3 f2 g1
   SW: c3 b2 a1                later squares need no visit
```

Combining bishop and rook movement to construct queen movement is also a sound reuse of geometric structure.

**What is strong:** you separated geometry that never changes from occupancy that changes every node. That is exactly the kind of distinction a performance-minded engineer should seek.

**Qualification:** on a fixed 8×8 board, this mostly reduces repeated work and constant factors. It does not change the exponential complexity of the search. The nested vectors and duplicated color-independent tables also leave room for better locality.

### 4.4 Incremental evaluation: probably your best performance instinct

**Location:** `Kernel.cpp:1010–1044`, `2042–2581`.

You do not rescan all 64 squares to evaluate every leaf. You maintain each side's score as moves change material and square placement:

```text
 move a piece:     score += PST[destination] - PST[source]
 capture a piece:  enemy_score -= material[victim] + PST[victim_square]
 promotion:        replace pawn material/PST with promoted piece material/PST
```

This exploits the fact that a move changes only a few facts. Ordinary moves, captures, promotions, and castling can all update evaluation with a bounded amount of work.

**Why it deserves emphasis in your portfolio:** it demonstrates maintenance of a derived invariant. That idea transfers well beyond chess—to indexes, caches, rolling statistics, rendering, simulations, and embedded state machines.

The black-en-passant defect is real, but the measured picture is useful: the random sample found **two incremental-score mismatches, both on black en passant**, while the tested occupancy and undo invariants passed. The response should be to protect and repair this optimization, not discard incremental evaluation.

### 4.5 Make/unmake avoids copying a position at every child

**Location:** the `MakeChanges` / `ReturnChanges` pair and call sites around `Kernel.cpp:2843`, `3096`, and `3184`.

Before searching a move you save the two occupancy masks, two score totals, and captured-square information. After recursion you restore the masks/scores and undo the board/count changes.

That is efficient depth-first state management. The reviewed hot path does not clone a whole board object per child.

The testing gives this point substance: **10,935 sampled trials restored the board and piece-move counters without a mismatch**, using the same combined restoration responsibilities as the search. Generated occupancy masks also matched recomputation in those trials. Focused promotion and ordinary castling cases passed their corresponding state checks.

**A subtle contract to document:** `ReturnChanges` alone does not restore everything. The caller restores scores and occupancy separately. A future explicit undo record can preserve the same small, bounded work while making that contract harder to violate.

### 4.6 Real alpha–beta search, with useful score conventions

**Location:** `MagicForIterativeDeepening`, `Magic`, and `GetBestMoveWithItsScore`.

You propagate alpha/beta bounds, maximize on the engine's turn, minimize on the opponent's turn, and stop when the window closes. Scores stay relative to the engine's color.

That last point makes the UCI coordinator's final maximum across workers sensible for **both White and Black**. It would be incorrect to criticize the coordinator merely for sorting scores descending when the engine is Black.

The bound machinery is a valuable foundation. Its guarantees concern the tree actually searched; they do not make that tree legal or restore branches removed by your separate four-move truncation.

### 4.7 You understood that move order changes the amount of work

**Location:** `Kernel.cpp:1947–2039`, `2878–2933`, `2989–3021`.

Your inexpensive heuristic uses capture material differences, piece-square deltas, and special-move bonuses. More expensive ordering uses shallower searches before the main search.

The underlying insight is good: an early strong candidate or refutation can produce earlier cutoffs. You are reasoning about the *work induced by an ordering*, rather than treating sorting as a cosmetic preference.

Two distinctions matter:

- A heuristic used only for ordering does not, by itself, force the engine to prefer trades in a complete fixed-depth search.
- Once low-ranked moves are discarded, that same heuristic becomes a decision about what the engine is allowed to discover.

The first mechanism is solid groundwork. The second needs a different level of validation.

### 4.8 Iterative deepening and retaining completed work

**Location:** `Kernel.cpp:3376–3403`.

You retain the last completed iteration if a deeper iteration exceeds its allowance. This is an important practical behavior: a search with uncertain cost should have useful completed work to return.

The present implementation needs a legal initial fallback and clearer abort propagation, discussed below. Still, the architecture already contains the right idea of separating “latest attempt” from “last completed result.”

### 4.9 Parallel isolation and observability

**Location:** `Engine UCI.cpp:250–336`, `Kernel.cpp:395–792`.

Splitting root moves among separate processes is a workable prototype strategy. Each kernel owns its globals in a separate address space. The coordinator writes results into distinct, preallocated per-worker vector elements and joins the threads before aggregation. I found no basis to call those separate element writes an ordinary shared-element data race.

You also expose leaf counts, inner counts, cutoff counts, elapsed time, depth, move, and score. Saving requests/results provides something concrete to inspect when a move is surprising.

There are measurement defects and concurrency risks at the file level, but the instinct to make the computation observable is strong. Keeping that visibility while removing the transport overhead would be an excellent next step.

### 4.10 The trie experiment tells a useful engineering story

**Location:** `Kernel.cpp:794–984`.

You tried to recognize repeated boards using a trie, considered board traversal order, and commented on the measured cost of an approach you stopped using. That is more interesting than pretending every experiment succeeded.

The current trie is **inactive in the search**. Its correctness and memory problems should not be misreported as a leak occurring on every move in the active engine. Its limitations are still worth learning from; the dedicated discussion below explains how a position-key approach can retain draw correctness with far less machinery.

> 💎 **What I would call the standout combination:** compact data, precomputed structure, incremental evaluation, and reversible state mutation. These are established techniques, so I would not claim you invented them. Implementing them together in a working personal system is nonetheless strong evidence of engineering ability.

<a id="findings"></a>

## 5. 🛠️ Confirmed problems and important limitations

**Priority guide:** 🔴 **P0** affects the validity of chess decisions or the move returned to a client. 🟠 **P1** affects reliability, timing, or a major engine capability. 🟡 **P2** affects efficiency, measurement, or future maintenance. These are repair priorities for this project, not claims about a security vulnerability classification.

| ID | Finding | Priority | Evidence |
|---|---|---|---|
| F01 | Internal search does not enforce full move legality | P0 | Reproduced + active source |
| F02 | Castling safety both rejects a legal castle and accepts an illegal one | P0 | Two reproductions |
| F03 | En passant can follow a one-square pawn move on the wrong rank | P0 | Reproduced from legal history |
| F04 | Black en passant updates scores using the wrong color tables | P0 | Reproduced + recomputation |
| F05 | UCI FEN is discarded by the actual position/search path | P0 | Rebuilt engine reproduction |
| F06 | Terminal and emergency paths can emit invalid move text | P0 | Source + zero-budget reproduction |
| F07 | Four-move truncation changes the search's guarantees | P1 | Active experimental policy |
| F08 | No unified deadline; command loop cannot service stop during search | P1 | Active source |
| F09 | Worker transport lacks isolation across requests and failure handling | P1 | Source-confirmed mechanisms; conditional failure risks |
| F10 | Stockfish adapter relies on brittle file and text conventions | P1 | Source + actual adapter smoke checks |
| F11 | Draw rules and endgame policy are incomplete | P1 | Active source and inactive stubs |
| F12 | Metrics and duplicated code obscure some experimental conclusions | P2 | Source + observed `nan` report |

### F01 · 🔴 The search explores a different game in important positions

**Where:** `Kernel.cpp:1742–1942`, `2779–2876`, `2935–3129`.

`GetMovesForThisPiece` mostly generates **pseudo-legal** moves: piece movement and occupancy are considered, but ordinary moves are not rejected for leaving the mover's king in check. Kings can move onto attacked squares, and the recursive search can capture a king. A very large king material value and the score-difference threshold serve as a surrogate terminal mechanism.

Stockfish's legal root list protects the first move of the ordinary coordinator path. It does **not** make the deeper kernel tree legal.

**Why the surrogate sometimes looks convincing:** if a move exposes a king and the search sees the opponent capture it on the next ply, the huge score can discourage the move. But the horizon, discarded branches, and terminal positions break that approximation. A king capture is not a chess rule for determining mate.

🧪 **Pinned-piece reproduction**

```text
FEN: 4r1k1/8/8/8/8/8/4R3/4K3 w - - 0 1

8  . . . . r . k .
7  . . . . . . . .
6  . . . . . . . .
5  . . . . . . . .
4  . . . . . . . .
3  . . . . . . . .
2  . . . . R . . .
1  . . . . K . . .
   a b c d e f g h
```

The independent legal list contains **10 moves**. Your generator returns **17**, including `e2a2`, `e2b2`, `e2c2`, `e2d2`, `e2f2`, `e2g2`, and `e2h2`, which expose the white king to the rook.

🧪 **Stalemate reproduction**

```text
FEN: 7k/5Q2/6K1/8/8/8/8/8 b - - 0 1
Legal moves:                  0
Kernel generated moves:       3
Kernel depth-two score:       -10,000,850
Correct terminal result:      draw
```

The three generated king moves are `h8g7`, `h8g8`, and `h8h7`. Your “no moves means stalemate” branch is not reached because the pseudo-legal generator still finds moves. In the focused Fool's Mate position the generator similarly produced **19** moves where legal chess has zero. Its eventual large losing score does not substitute for recognizing the terminal position directly.

**Repair:** add a reliable attack/check predicate and legal filtering. A practical first implementation is: generate candidate → make → test the mover's king → undo → retain only legal candidates. Later, optimize using checkers, pins, and evasions. Determine mate versus stalemate from legal-move count and check status, and use a separate mate score with ply distance.

**Acceptance criterion:** legal move sets and perft agree with an independent implementation, including pins, double check, king moves, castling, and en passant exposing a rook/bishop line.

### F02 · 🔴 Castling needs one correct attack predicate

**Where:** `Kernel.cpp:1493–1740`, `1844–1907`.

Two independently reproduced issues are especially clear:

| Position | Correct behavior | Observed generator behavior |
|---|---|---|
| `4k3/8/8/8/8/8/1r6/R3K3 w Q - 0 1` | White may castle queenside: `e1c1` | The move is missing |
| `4k3/8/8/8/8/8/8/2r1K2R w K - 0 1` | White may not castle while the rook on c1 checks e1 | `e1g1` is generated |

The first failure follows from requiring **b1** to be safe. For orthodox queenside castling it must be empty, but the king passes through d1 and arrives on c1; an attack on b1 alone does not forbid the castle. The second follows from the white-side horizontal attack logic checking black piece codes **6 or 7**, while a black rook's type is **5**. An encountered rook can terminate the scan without being recognized as a threat. The corresponding code is around `1714–1729`.

The official castling rules concern the king's starting, crossing, and destination squares. They do not require every square between king and rook to be unattacked. [FIDE Laws of Chess, Article 3.8](https://handbook.fide.com/chapter/e012023)

Ordinary unattacked castling for both colors passed the focused tests, so “castling never works” would also be inaccurate.

**Repair:** use one general `isSquareAttacked` implementation for king safety and castling. Track explicit castling rights, verify the correct king/rook and required empty squares, then test the king's route using the appropriate occupancy. Add mirrored tests so a color-specific typo cannot hide behind a successful White-only example.

### F03 · 🔴 A pawn's first move does not establish en passant

**Where:** `Kernel.cpp:1777–1785`.

The condition uses the previous move's destination, adjacent pawn presence, and a move counter equal to one. It does not establish that the previous move was a **two-square** pawn advance, nor that the capturing pawn is on the required rank.

🧪 This entirely legal sequence reproduces the fault:

```text
e2e4 a7a6 e4e5 a6a5 e5e6 d7d6

White pawn: e6
Black pawn: d6, having just advanced ONE square

Generated extra move: e6d7, encoded as en passant
```

The legal oracle returns 30 moves; your generator returns 31. This is a rules defect independent of any parameter tuning or selective-search experiment.

**Repair:** represent the en-passant target explicitly, clear it after the next move, and set it only for a qualifying two-square advance. Then apply king-safety filtering to the capture. If deriving it from the previous move, check origin and destination, color, rank, and exact displacement—not just whether the pawn has moved once.

### F04 · 🔴 Black en passant keeps the board right and the score wrong

**Where:** `Kernel.cpp:2316–2330`.

The black branch uses `pieceSquaresTable[1 | 8]` for the moving black pawn and `pieceSquaresTable[1]` for the captured white pawn. Those color choices are reversed.

🧪 Reproduction:

```text
History: a2a3 e7e5 a3a4 e5e4 d2d4
Black to move: e4d3 en passant

Black-relative evaluation after the move:
  incremental update:       +115
  full board recomputation: +135
```

Both individual side totals differ, with a net **20-unit** score error in this position. The board transition and occupancy masks passed their checks. Two additional black-en-passant examples in the seeded sample produced score mismatches as well.

**Repair:** use the moving piece's actual color/table index and the captured piece's actual color/table index. A debug-only full recomputation after every make operation is a direct way to protect this optimization. Include tests with the engine playing either color; the position's moving color and the engine's evaluation perspective are different concepts.

### F05 · 🔴 Accepting a FEN string does not mean the engine uses it

**Where:** `Engine UCI.cpp:496–521`, `694–724`; `Kernel.cpp:3317–3338`.

The UCI parser stores the FEN text, but `getBestMoveFromEngine` extracts only move-history text after `#`. Engine color is inferred from that history's parity. The kernel always starts from the normal initial board and replays the extracted moves. No initial FEN is serialized to it.

🧪 The **freshly compiled, unchanged UCI program**, with the actual adapter and bundled Stockfish, was sent:

```text
uci
isready
position fen 7k/5Q2/6K1/8/8/8/8/8 b - - 0 1
go movetime 1
quit
```

It replied with the handshake and **`bestmove e2e4`**. The supplied position is Black to move with no legal moves; the returned move belongs to the initial position.

**Repair:** create an explicit position input containing initial board/FEN, side to move, castling rights, en-passant target, and clocks. Apply any following move list to that initial state. Deriving side to move from history length is valid only when the history is anchored to the normal initial position.

### F06 · 🔴 Terminal and first-iteration fallback paths need legal output

**Where:** `Engine UCI.cpp:194–206`, `743–744`; `Kernel.cpp:418`, `575–602`, `3374–3407`.

When the root legal list is empty, `getEngineMoveWithThreading` returns a prose report as though it were a coordinate move. The UCI layer then prefixes that text with `bestmove`.

Separately, a zero packed move converts to **`a8a8`**. If the first kernel iteration does not complete, the retained result is still the default `ProcessHandler` object.

🧪 A scratch request to the rebuilt kernel with zero allowed seconds and assigned move `e2e4` returned:

```text
bestMove: a8a8
reported depth: 6
searched nodes: 0
reported nodes/second: nan
```

Zero is outside the normal UCI branch's positive budget choices, so this test proves a missing boundary/fallback behavior; it does not prove that a normal one-second request always fails. The same uninitialized-completed-result path is a risk whenever no iteration finishes in time.

**Repair:** seed the answer from a known legal root move before searching. If there are no legal moves, return the protocol's null move, **`0000`**, and keep explanatory text in a report or `info string`. Keep “search not completed,” “terminal position,” and “draw evaluation” as separate states. [UCI specification](https://backscattering.de/chess/uci/)

### F07 · 🟠 The four-move policy is a selective search, not safe alpha–beta pruning

**Where:** `Kernel.cpp:3007–3020`, `3281–3305`.

You explicitly mark these loops as risky. I agree with that assessment, and I am treating them as an experiment rather than a misunderstanding of what you intended.

The current policy sorts moves using a shallower search, then removes all but four at selected depths. Alpha–beta pruning proves that some branches cannot change the result under the current bounds. This policy instead **predicts** that low-ranked shallow candidates will not matter.

```text
Shallow ordering:    A     B     C     D     E
Shallow scores:     +80   +60   +30   +10   -50
Retained:           ✓     ✓     ✓     ✓     ✗
Deeper truth:       ...                     forced win
```

Sacrifices, quiet defensive moves, and long tactical sequences can rank poorly at the shallow horizon. The same issue applies to pruning the opponent's responses: dropping their strongest deeper refutation can make your move look better than it is.

An additional effect is specific to your parallel design: root truncation happens **inside each assigned group**. With 28 workers and one move per worker it discards no root alternatives; with fewer workers and larger groups it can discard alternatives. Shuffling changes those groups. Thus worker count and random seed can change more than speed—they can change the effective search policy.

**Repair sequence:** establish a reproducible baseline with truncation disabled, measure its tactical and match results, then compare selective versions. Later, consider late-move reductions with verification searches instead of permanently deleting every fifth-ranked move. Always preserve mandatory legal evasions in check. The exact cutoff and reduction rules should earn their place in tests.

### F08 · 🟠 Timing needs one decision deadline and responsive cancellation

**Where:** `Engine UCI.cpp:529–576`, `725–744`; `Kernel.cpp:652–655`, `2784–2785`, `2937–2938`, `3372–3401`.

There are several separate issues:

- The UCI command loop calls the whole search synchronously. During that call it cannot read `stop`, `quit`, or a readiness ping; there is also no `stop` handling branch.
- `go movetime X` is interpreted as though X were both sides' remaining game time and then passed through the clock-allocation thresholds. It is not honored as an explicit per-move limit.
- `go depth`, `nodes`, `infinite`, and other limits are not implemented by this parser. Unspecified clock fields can retain values from a prior `go`.
- The kernel's timer starts **after** its initialization and history replay. Stockfish requests, process creation, file transport, and final logging are outside that budget.
- Stockfish selection is depth-limited with no matching hard time limit. A chosen depth is not a duration guarantee.
- The 5% rule is checked only between completed iterations. It can stop early, but it cannot predict whether the next iteration will run from a small fraction of the budget all the way to the hard limit.

The clock thresholds also leave very little reserve in some situations: a 60-second clock selects a 50-second allowance; a sub-second clock still selects one second. **Allowance is not observed consumption**—the 5% rule often stops earlier—but these values do not define a safe total move deadline.

The protocol requires the engine to remain able to process input during search; its readiness and stop semantics are particularly relevant here. [UCI specification](https://backscattering.de/chess/uci/)

**Repair:** parse a structured search limit, establish a monotonic `steady_clock` deadline at the coordinator, subtract an overhead reserve, and pass that deadline to all work. Keep reading commands while search runs. Use a distinct aborted status instead of returning numeric zero on timeout.

Your outer loop already avoids publishing the just-aborted iteration when it notices timeout. I am **not** claiming that every timeout-zero currently becomes the final move score. The remaining problems are the initial fallback, wasted unwinding/sibling work, and an ambiguous result contract that would become especially hazardous with cached results.

### F09 · 🟠 The worker protocol needs identities and failure boundaries

**Where:** `Engine UCI.cpp:283–305`, `349–368`; `Kernel.cpp:3350–3409`; repository `.gitignore`.

The current sequence—write request, run a synchronous child, then read its result—is understandable and inspectable. Within one normal coordinator call, separate worker indices use separate filenames.

The missing protections are concrete:

| Condition | Current mechanism | Possible consequence |
|---|---|---|
| Clean checkout has no `input` directory | Directory is ignored; UCI code does not create it | Request write fails, then JSON parsing fails |
| Child fails to start or exits early | `system()` result is ignored | Parent may read its own unchanged request or invalid/partial content |
| Two engines use the same working directory | Both use `input/thread_1_serialized_data.json`, etc. | Requests and results can overwrite each other |
| JSON is malformed or absent | Parsing is unchecked inside a thread | An uncaught exception can terminate the coordinator process |
| Child output is stale | No game ID, search ID, worker ID, or response status is verified | A result cannot be reliably associated with its originating search |
| Worker hangs | Parent waits synchronously and later joins all workers | One worker can hold up the whole decision |

The copied request already contains `bestMove` and `bestMoveScore`, so “valid JSON” alone is not evidence that the child produced a result. Successful process completion and an explicit response envelope matter.

**Repair while keeping files:** create directories, check all opens/writes/exits, use a unique directory per search, write responses atomically, validate response IDs/status, and verify the selected move against the original root list. These changes can make the existing prototype much more dependable before transport is replaced.

**Longer term:** use direct process APIs with redirected streams or bring search into one process with private worker state. Avoid treating a shell command string as a process-management API. The current fixed kernel executable path is not quoted as an executable argument, and CWD assumptions would complicate relocation into paths containing spaces.

### F10 · 🟠 The Stockfish adapter works in this environment, but its contract is fragile

**Where:** `Stockfish Handler.hpp:14–36`, `53–117`, `121–175`, `189–243`.

The actual adapter successfully enumerated the 20 initial moves, returned an initial best move, and returned its check sentinel in the focused check test. The bundled binary identified itself as **Stockfish 16**. The default path's extra quoting worked in these tests; I do not classify it as a reproduced launch failure.

The serious limitations are these:

**A shared temporary file.** Every handler uses `temp_command_file.txt`. This is a race if calls overlap in one working directory, including across separate engine processes. The normal active worker search does not invoke this adapter at each node, so this is a concurrency risk at the adapter boundary, not evidence of per-node contention.

**Fixed-layout output parsing.** `getAllPossibleMoves` removes exactly 20 trailing characters and treats colon-containing output as move records. It assumes enough output exists, a particular trailer shape, and a preceding newline. An empty or short result can make `pop_back()` invalid; changed diagnostic output can confuse the parser. Parse complete lines with an expected move-token grammar and a recognized completion line instead.

**No robust error result.** Failed file creation, `popen`, child exit, missing `Final evaluation`, and missing `bestmove` are not represented as ordinary errors. `find()` results are narrowed to `int` in places. In the best-move parser, adding nine to `npos` can wrap before conversion, potentially treating unrelated output as a move. Search for the token, test for absence, then parse and validate it.

**Check is treated as a giant evaluation.** `getNNUEPositionEvaluation` returns magnitude 100,000 when Stockfish says it cannot provide the static evaluation because the side is in check. A check can be harmless or losing for the checking side; it is not generally worth a mate-like score. This particularly distorts the optional NNUE move sorter. Also, counting spaces to determine side to move depends on whitespace conventions; your history-string builder includes a trailing space.

**Two helpers need different judgments.** The adapter's `isCheckmatePosition` can identify mate through zero legal moves plus its check sentinel when the Stockfish output is parsed successfully. The adapter's `isTiePosition` effectively recognizes **stalemate**, not all draws. Meanwhile, `isStalematePosition` is a literal `return 0` stub. The separate `ChessState::isTiePosition` forwards to that stub, although the active UCI post-search route calls the handler directly. These are different call paths and should not be lumped together.

**Duplicated search commands.** `getBestMoveByDepth` writes the full position/search command sequence twice. In the raw reproduction for depth 18, Stockfish produced **two `bestmove` lines**: the first search reached depth 18; the second produced another result after input ended. Your parser chose the first. That observation is more precise than saying the workaround “never works.” Its behavior still depends on asynchronous search and end-of-input timing, rather than explicit request completion.

**Repair:** keep Stockfish alive, synchronize startup, send one position/search request at a time, and read until the response belonging to that search completes. Bound both depth and time where needed. Keep `eval` and `perft` explicitly marked as Stockfish-specific facilities; they are not portable requirements of every UCI engine. [Stockfish command documentation](https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html)

`getSortedMovesByNNUE` also launches a fresh external process for each candidate evaluation. That can be useful for offline experiments; it would be a poor default leaf-evaluation strategy inside a fast search.

### F11 · 🟠 Draws and endgames need chess state, not just move count

**Where:** terminal helpers in both classes, the inactive trie, and `Engine UCI.cpp:615–645`.

The kernel has no active complete repetition mechanism, halfmove-clock draw handling, or general dead-position adjudication. The post-search Stockfish helper does not supply those features merely by enumerating legal moves.

For repetition, equal piece placement is insufficient: side to move, castling rights, and relevant en-passant availability matter. The claimable threefold/50-move rules also differ from the automatic fivefold/75-move rules; platform adjudication must be handled explicitly. [FIDE Laws of Chess, Articles 5 and 9](https://handbook.fide.com/chapter/e012023)

Your current tie-avoidance route asks Stockfish to replace a candidate classified as a tie regardless of whether the engine is winning or losing. A forced draw can be the best available result. A future contempt preference should sit on top of correct adjudication and evaluation, not replace them.

The late-game Stockfish handoff is a legitimate experiment. Counting plies does not identify an endgame, however: a queen trade can create one very early, while a complicated middlegame can persist beyond move 40. A material-based phase value would serve evaluation and phase-specific policies better.

### F12 · 🟡 Some measurements do not mean quite what their labels suggest

**Where:** `Kernel.cpp:532–553`, `722–727`, `2896–2913`, `3170`, `3376–3407`; `Engine UCI.cpp:393–478`.

Your instrumentation is worth keeping. Before trusting comparisons, repair these details:

- `std::accumulate(..., 0)` uses an **int accumulator**, although the arrays store `long long`. Use a matching 64-bit initial value such as `0LL`; large totals otherwise exceed the intended accumulator range.
- A zero-millisecond measured interval produces a non-finite NPS value. The zero-budget request actually reported `nan`.
- Root ordering performs shallow search work before `GetBestMoveWithItsScore` resets the counters. The root ordering's time is included in the iteration interval, but those earlier nodes are omitted from its reported node total.
- A cutoff counter counts **cutoff events**, not the number of all nodes or branches that would have existed without pruning. Label it accordingly.
- If a deeper iteration is interrupted, retained completed-depth statistics and an updated overall end time describe different portions of the attempt. Report completed-iteration time and total decision time separately.
- A reported depth under four-move truncation and pseudo-legal search is not directly comparable to another engine's depth.

Logging also needs a stable game identity. Selecting the newest history directory on subsequent moves can attach a resumed or concurrent game's logs to the wrong game. Second-resolution filenames can collide on sufficiently quick decisions. These are conditional risks, not evidence that the empty history folders contain lost games.

Finally, `ChessState` orchestration is duplicated in both C++ files, with already different Stockfish depth settings. The kernel entry point does not need most of that copy. This duplication mostly increases drift and review burden; I would not sell deleting unused class methods as a major runtime speedup without measurements.

### 🧩 Additional unfinished details worth recording

| Area | Observation | Practical response |
|---|---|---|
| Handler test program | Code after the first `return 0` is unreachable | Turn examples into reachable checks with expected results |
| Handler test history | Removing five characters assumes every move has four characters plus a space | Save/restore string length or append from an unchanged base; promotions have five characters |
| Scratch source | `tempCodeRunnerFile.cpp` contains only `shuffl` | Exclude it from an eventual build target; it is not an engine feature |
| Worker options | Thread count is hard-coded to 28 in active UCI setup; options are not exposed | Add validated runtime configuration and standard options where appropriate |
| Invalid settings | Zero worker count would reach modulo-by-zero; negative counts are not validated | Validate configuration at the boundary |
| Reporting side effects | Numeric-formatting helpers write to `cout` | Keep formatting/report generation independent from the protocol output channel |
| Compiler feedback | Signedness/narrowing, unused values, initializer ordering, and a range-loop temporary are flagged | Triage meaningful warnings; not every warning is a runtime defect |
| Decorative comments | Lines ending in backslashes trigger line-splicing warnings | Remove trailing backslashes from comment separators |

These smaller points belong behind the chess and reliability repairs. They should not dominate the story of the project.

### The inactive trie: what to keep from the experiment

Its 32-way node contains 32 pointers plus a small frequency field—about **264 bytes per node** with the reviewed 64-bit layout. A new 64-square path can therefore cost about **16.5 KiB before prefix sharing and allocator overhead**. That is an illustrative worst-case path cost, not a measured per-position average.

Its destructor deletes the root but does not recursively release descendants. Frequency uses `int8_t`, which is too narrow for general repeated insertions. The commented move-state flag leaves castling rights out of identity. Its en-passant approximation has related first-move limitations, and `boardExist` checks existence rather than implementing a complete three-occurrence claim rule.

There are two instances, suggesting side-to-move separation, but neither is actively consulted by the current search. Thus the descendant leak is **dormant until insertion is used**.

The replacement I recommend is a position-key history for repetition and a separate bounded transposition table for search reuse. Dropping active repetition checks because this particular data structure was expensive does not establish that repetition handling itself must be expensive.

<a id="complexity"></a>

## 6. ⚙️ Complexity, memory, and performance

### What your optimizations actually change

Let `b` represent branching factor, `d` search depth, `P` the number of pieces of the moving side, `m` generated moves at a node, and `W` worker processes. Chess has a fixed-size board; these symbols explain where work grows, rather than pretending that every 64-square operation has a different asymptotic class.

| Mechanism | Work / storage model | Assessment |
|---|---|---|
| Packed move field access | Bounded bit operations; two bytes per move | Useful density and cheap manipulation |
| Occupancy-based piece enumeration | Roughly `P` set-bit iterations rather than 64 square visits | Good sparse enumeration; not a full attack-bitboard engine |
| Incremental material + PST evaluation | Bounded update per move | Strong fit for the hot path, provided invariants hold |
| Make/unmake | Bounded changed state per move | Avoids full position copying at every child |
| Precomputed geometric paths | One-time construction plus occupancy-dependent traversal | Reduces repeated geometry work; table locality remains relevant |
| Full heuristic ordering | Roughly `O(m log m)` sorting plus scoring | Worthwhile only if saved search exceeds ordering cost |
| Plain minimax | Approximately `O(b^d)` nodes | The main growth problem |
| Alpha–beta | Same exponential worst case; much lower work with favorable ordering | The existing bound machinery attacks the right problem |
| Current shallow-search ordering | Additional search per candidate before deeper search | Can help, but repeats work without a transposition table |
| Depth-first search storage | Roughly move lists and local data along the active path, commonly `O(bd)` | No retained full game tree in the active search |
| Separate workers | Private state/tables/allocations per process, multiplied across `W` | Isolation has a resource cost; physical memory is not necessarily `W` times executable size |

The familiar idealized alpha–beta result approaches `O(b^(d/2))` with excellent ordering in a uniform tree. That is a theoretical reference point, not a measured claim about this implementation. Knuth and Moore's analysis is the foundational treatment. [An Analysis of Alpha-Beta Pruning](https://www.sciencedirect.com/science/article/pii/0004370275900193)

The four-move policy should not be advertised simply as “now complexity is `O(4^d)`.” It still performs broader shallow searches, retains broader levels at other remaining depths, and pays move generation and ordering costs. Its reduced work also comes with a changed search result.

### Where memory efficiency is real

The board array is 64 bytes, the per-square `int16_t` move counters occupy 128 bytes, and the two occupancy masks occupy 16 bytes on this target. That is **208 bytes for those three components**, excluding scores, tables, history, vectors, stack, and process/runtime overhead. This is a representation-size observation, not a total engine memory measurement.

Your main search does not store every visited node. That is a much bigger memory decision than shortening a few variable types. The inactive trie would have moved in the other direction by retaining pointer-heavy structure per board path.

### Where likely costs remain

1. **Repeated searches without reuse.** A shallow search used for ordering may explore work that a deeper search repeats. Repeated positions across move orders are also searched again.
2. **Hot-path allocation.** Per-piece move vectors, node-wide vectors, and sorting helper vectors can allocate repeatedly. The cost needs profiling rather than assumption.
3. **Table construction per child process.** Every worker rebuilds geometry/tables and replays history for every decision. Persistence or shared immutable data can remove this repeated setup.
4. **Fragmented tables.** Nested vectors require pointer indirection and many separate allocations. Most non-pawn geometry is duplicated by color.
5. **Clock queries at every recursive entry.** Necessary for responsiveness, but worth measuring. Batched checks need a bounded overshoot policy and separate cancellation checks.
6. **No quiescence search.** Cheap leaf evaluation is fast, but a leaf immediately before a recapture can be strategically meaningless.

Do not optimize these in the order they are easiest to edit. First profile time in generation, ordering, recursive search, setup, and transport. A good histogram can prevent days spent improving a path that uses 1% of decision time.

### Low-level changes I would consider after correctness

| Change | Reason | What must be measured or protected |
|---|---|---|
| Flat immutable move/ray tables with offsets | Better locality; less allocation and duplication | Exact move-set equivalence, startup cost, generation time |
| Reusable per-ply move buffers | Reduce allocator traffic | Capacity assertions or a safe overflow path; do not blindly assume a legal-move bound fits this pseudo-legal generator |
| Incremental position hashing | Constant-sized update for repetition/search reuse | Keys restored exactly across every special move |
| Piece-type bitboards and attack tables | Faster attacks, pins, and move generation may become possible | Benchmark against your rays; extra representations add invariant work |
| Inline named encoding helpers | Preserve packed layout while centralizing masks | Inspect optimized code if a performance difference is suspected |
| Profile-guided optimization | Better code layout/branch choices on representative workloads | Train profiles on varied positions, not a single favorable example |
| CPU-specific slider techniques | Magic tables or suitable hardware instructions can be useful | Hardware compatibility, cache cost, actual engine throughput |

`int8_t` storage can help cache density, but arithmetic generally promotes it to `int`. A reference to a tiny scalar is not inherently faster than passing the value. Conversely, a small `Position` or `Undo` struct does not inherently impose runtime overhead. Decide using generated code and end-to-end measurements where the difference matters.

### What the saved speed numbers establish

The saved `thread_1` report records depth 10 and **2,303,625** counted nodes for its assigned move. The rebuilt source reproduced that move, score, and counted node total in the copied-input smoke check. That is useful reproducibility evidence.

It is **not** a speed comparison with Stockfish or with an earlier Mr. Bits version. Hardware conditions, build flags, warmup, the counting omissions above, and selective search all affect interpretation. I deliberately do not turn a quick local execution into a headline NPS claim.

<a id="parallelism"></a>

## 7. 🧵 Multithreading and communication

### Is the current multithreading “wrong”?

**It is a reasonable prototype arrangement with important limitations.** The expensive search happens in separate kernel processes. Your `std::thread` objects primarily coordinate file transport and wait for those processes.

That achieves CPU parallelism while allowing the kernel's many globals to remain isolated. It is a real benefit. Replacing the child processes with direct calls from 28 threads, while leaving those globals shared, would corrupt board state, scores, and undo operations.

The safe transition is to make each search worker own its mutable position and search context. Only immutable lookup tables should be freely shared at first.

### Files are one cost, not the whole cost

A local JSON request of a few kilobytes may be cheap relative to a long search. Without a phase profile, I cannot honestly say the filesystem is the dominant bottleneck here. Process launch, repeated initialization, history replay, load imbalance, and duplicated search can be more consequential.

The strongest reasons to improve the transport are reliable request identity, cancellation, persistent state, and lower startup overhead. Logging can then happen independently of the channel used to compute a move.

### Two sensible next architectures

| Option | Persistent kernel workers with pipes | One engine process with a worker pool |
|---|---|---|
| Boundary | Separate processes remain alive | Search runs as normal C++ calls |
| Communication | Standard input/output or named pipes | In-memory task queue and result structures |
| Existing globals | Safe if each process handles one search at a time | Must become private per worker/position |
| Immutable tables | Built once per worker, potentially mapped/shared later | Built once and shared read-only |
| Isolation | Worker crashes can be handled by the coordinator | A crash can affect the entire engine |
| Optimization ceiling | Good local IPC; more coordination overhead | Lower transport overhead; easier shared search data |
| Best immediate fit | **Smaller architectural step for this code** | Stronger eventual design if you want to invest in state separation |

My recommendation is to make the position/undo contract explicit, then introduce persistent workers as an incremental step if you want to retain the current executable boundary. You do not need to introduce an HTTP server or a network service for local engine calls. A request-serving process can communicate through pipes.

Passing input through command-line arguments while launching a new process each time would remove some file handling, but it would retain startup costs and make cancellation/session management awkward. “Use the command line” and “keep a process alive over streams” are materially different designs.

```text
                  Proposed local arrangement

UCI reader ──► search coordinator ──► fixed worker pool
    │                │                  │
 stop/quit           │             private positions
    │          search ID + deadline     │
    └──────► cancellation          results + status
                     │                  │
                     └────────┬─────────┘
                              ▼
                  validated move / last complete iteration
                              │
                     bestmove + separate log writer
```

### Root splitting: useful, but currently uneven

Round-robin assignment balances **move count**, not search cost. One forcing tactical move can consume more work than several quiet alternatives. Waiting for all workers makes the slowest group important.

Each worker also deepens independently. Its 5% stopping rule and assigned subtree can produce a completed depth of 8 while another worker reports 10. Both scores use the same units and perspective, but they are not necessarily evaluations at the same horizon. A deeper score is not automatically “better” or numerically comparable as evidence for a different root candidate.

Useful improvements include a dynamic queue of root work, scheduling from the previous iteration's cost estimates, and recording completed depth per candidate. For a reliable baseline, make the coordinator publish the best result from the deepest **common completed root iteration**. More sophisticated asynchronous policies can come later.

Searching a promising root move first can establish a useful bound before parallelizing alternatives. Shared bounds and a shared transposition table may reduce duplicated work, but they introduce synchronization and bound-consistency concerns. Start with private tables or a simple correct design before attempting lock-light shared search machinery.

### Persistent workers need a reset contract

`InitializeEveryThing` currently appends to precomputed vectors and to `previousMoves`. Fresh processes make that tolerable because initialization happens once. Calling it repeatedly in a long-lived worker would accumulate stale history and duplicate table entries unless reset semantics change.

This is an example of why swapping transport alone is not enough. Separate:

- Once-per-process immutable table initialization.
- Per-game state.
- Per-search limits and cancellation.
- Per-position board/history setup.

A request/result should carry a game ID, search ID, position identifier, worker ID, status, best move, score/bound, completed depth, and useful statistics. Late results from an old search must be discardable.

### Priority and worker count

Raising coordinator thread priority mostly raises the priority of work that waits for child processes; it does not create additional compute capacity. With every kernel also set to high process priority, the machine can become less responsive and compete with the bot/client that must deliver a move. Microsoft specifically cautions about CPU consumption by high-priority applications. [Windows `SetPriorityClass` documentation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setpriorityclass)

Use an explicit configurable worker count and measure scaling at 1, 2, 4, and the relevant hardware limits. Do not assume 28 workers or maximum priority is optimal. Measure total decision latency and missed deadlines alongside raw nodes.

<a id="search-roadmap"></a>

## 8. ♟️ Search and evaluation improvements

### 8.1 Establish a trusted baseline before adding selectivity

Keep a deterministic mode with legal moves, full fixed-depth alpha–beta, no four-move deletion, a fixed seed/order, explicit terminal scores, and consistent evaluation. This mode becomes the reference for debugging optimized modes. It does not need to be your fastest tournament mode.

Search scores should have explicit meanings: ordinary evaluation, mate distance, draw, bound, and aborted search. A timeout is not a drawn position. A captured king should never be a legal state in the chess search.

### 8.2 Add quiescence search

The current leaf can end immediately after a capture and before its recapture. This is one explanation for unstable tactical values and for why some odd/even depth results may look dramatically different.

A first quiescence search extends tactically unstable leaves with suitable captures/promotions. If the side is in check, it must search legal evasions; ordinary stand-pat evaluation is not allowed as a substitute for responding to check. Add safeguards against pathological expansion, and test tactical positions.

The comments saying odd depths are “not correct” are too strong. Odd depths are valid. Alternating search behavior and the horizon effect can make evaluations oscillate. Searching only even depths is an experimental policy that also skips useful completed work; it does not solve the underlying tactical horizon.

### 8.3 Add a bounded transposition table

Different move orders can reach the same position. Reuse is especially relevant to your repeated shallow ordering searches.

An entry can contain a position key, searched depth, score, bound type, best move, and generation/age. Bound type matters: an alpha–beta cutoff value is not necessarily an exact score. Normalize mate distance appropriately when storing/retrieving values. Use a consistent score perspective, especially if persistent workers can switch the engine's color between games.

Use a fixed memory budget with a replacement policy. Include side to move, castling rights, and relevant en-passant state in position identity. Handle repetition and halfmove-rule context explicitly so a cached non-draw result does not override a path-dependent draw. A transposition table and repetition history are related tools with different jobs.

### 8.4 Improve ordering without repeatedly paying for full shallow searches

Try previous-iteration principal-variation moves, a valid table move, promising captures/promotions, killer/history heuristics for quiet moves, and an exchange estimate such as SEE. Stage move picking if profiling shows that fully sorting every list wastes work before an early cutoff.

Your current capture-order term subtracts the attacker's value strongly. A queen taking an undefended pawn can therefore rank below a quiet move; that is not necessarily a bug, but it shows why capture ordering should be tested rather than assumed optimal. SEE can help distinguish an expensive-piece capture that is safe from one that loses material.

### 8.5 Then consider PVS, aspiration windows, and verified reductions

| Technique | Potential benefit | Required care |
|---|---|---|
| Principal Variation Search | Narrow-window probes for later candidates | Re-search when the probe indicates an improvement |
| Aspiration windows | Tighter bounds around a prior score | Widen and re-search on failure; preserve a completed fallback |
| Late Move Reductions | Spend less depth on less promising later moves | Verify promising reduced results; protect check evasions and important tactical moves |
| Null-move pruning | Reject some positions quickly via a search heuristic | Zugzwang, check, low-material positions, and exact state restoration |
| Futility / related forward pruning | Avoid low-value shallow work | Carefully bounded conditions and tactical regression tests |

These are experiments with failure modes, not a shopping list that automatically strengthens an engine. Add one at a time and compare against a fixed reference. A shorter node count is not sufficient evidence of a better playing result.

### 8.6 Give evaluation a game phase

The current material-plus-PST model is fast and understandable. It lacks phase interpolation and many strategic terms, including a dedicated pawn structure model, mobility, passed-pawn treatment, and richer king safety.

A practical next step is **tapered evaluation**: maintain middlegame and endgame totals and blend them using a material-derived phase value. A king that should shelter in the middlegame should often become active in an endgame. One fixed king table cannot express both well.

Start with a few terms whose behavior you can explain and test. Maintain incremental material/PST components, cache pawn information if warranted, and measure the cost of attack-dependent terms. Tune coefficients against a clean evaluation or game-results objective rather than changing many numbers after a memorable game.

### 8.7 Make endgames a capability of your engine

First implement terminal states and draw rules correctly. Then add endgame king activity, passed-pawn logic, promotion-race tests, and suitable material-specific knowledge. Tablebases are a later option for exact results in supported material counts and rule contexts.

Keep Stockfish-assisted and self-contained modes explicit. You can retain the assisted mode for testing and experimentation while building evidence about the custom core. Removing assistance is not required to make the existing work worth discussing; transparent mode boundaries are required to assess its strength honestly.

<a id="neural"></a>

## 9. 🧠 Neural networks: a useful path

### Your idea is worth exploring—with a defined role

There are three separate uses for a network:

| Role | Predicts | Effect on search |
|---|---|---|
| **Value / evaluation model** | How favorable a position is | Changes leaf evaluation and potentially improves search decisions |
| **Policy / ordering model** | Which legal moves are promising | Changes the order searched, potentially producing earlier cutoffs |
| **Pruning model** | Which moves can be ignored or reduced | Can miss decisive moves; needs verification and measured risk |

I would begin with evaluation or ordering. A network's confidence that a move is weak is not a mathematical proof that the move cannot change the result. That distinction remains true even with a very good training score.

### Why NNUE fits the way you already think

Your current evaluation updates a few terms because a move changes a few squares. An efficiently updatable network follows a related idea: update a sparse-feature accumulator instead of recomputing a large first layer from scratch. Low-precision inference makes this practical on a CPU. [Stockfish's NNUE technical documentation](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html)

That is a natural extension of your incremental-state work. It would be a substantial additional project, though—not a small substitution of `getNNUEPositionEvaluation()` for your leaf expression. An external Stockfish process per leaf would lose the performance properties you are trying to build.

### A proposed learning project for Mr. Bits

```text
 legal, varied positions
          │
          ▼
 consistent teacher scores / game results
          │
     split by game or source
          │
          ▼
 train a small model ──► held-out evaluation
          │
          ▼
 CPU inference in your engine
          │
          ▼
 refresh vs incremental checks + tactical regression
          │
          ▼
 equal-time matches and an ablation report
```

**Step 1: fix the data semantics.** Use legal positions and an explicit score perspective. Distinguish centipawn evaluation, mate, and game result. Do not use the kernel's captured-king scores or the adapter's “in check” sentinel as ordinary training targets.

**Step 2: create a modest baseline.** A small sparse piece-square feature set is enough to learn the mechanics. Include side-to-move information or choose a consistent perspective. Keep training details, random seeds, dataset provenance, and network version recorded. This is my suggested educational scope, not a promise that a tiny model beats your hand evaluation.

**Step 3: separate training and evaluation data.** Split by game or source before extracting nearby positions; otherwise near-duplicate positions can leak between training and validation. Include tactics, quiet positions, checks, promotions, and varied material. An opening-heavy dataset is a poor test of endgame quality.

**Step 4: implement full inference first.** Verify feature mapping, score orientation, and numerical behavior. Then add incremental accumulation and compare it against full refresh on random sequences, captures, en passant, promotions, king moves, and undo. Your existing style of material/PST invariant checking is exactly the right habit to extend.

**Step 5: optimize for the real workload.** The engine needs low-latency, typically single-position CPU inference. Measure model size, accumulator copying/updating, evaluation time, and resulting search depth under a fixed time budget. A model with lower prediction error can still weaken play by costing too much search.

**Step 6: test value and policy separately.** If trying a policy, use it to rank **legal** moves first. If it later drives reductions, re-search candidates that exceed the relevant bound and retain safe behavior in check and tactical cases. Track tactical misses, not only average move agreement.

The upstream NNUE trainer is a useful reference for tooling and reproducibility. Its full production recipes are not a prerequisite for a smaller personal experiment. [Official NNUE trainer](https://github.com/official-stockfish/nnue-pytorch), [training guide](https://github.com/official-stockfish/nnue-pytorch/blob/master/docs/training.md)

### Could teacher-generated labels compromise the project's identity?

Training on another engine's scores and asking another engine to select live moves are different modes of assistance. Document both honestly. You can own the implementation, feature design, experiments, and training pipeline while crediting a teacher and any reused tools or weights.

Since preserving your authorship matters to you, it is also entirely reasonable to implement the next engine version yourself and use review conversations to challenge decisions and interpret results. This review has not rewritten your engine. A learning path should strengthen your ability to explain the design, not replace that ability with an opaque dependency.

<a id="validation"></a>

## 10. 🧪 Validation and measurement

### What this review actually observed

| Check | Observed result | Limit of the conclusion |
|---|---|---|
| Both main programs: syntax and optimized compilation | Passed under GCC 14.2.0 / C++17, with warnings | Not a portability or sanitizer claim |
| Initial kernel move list | 20 moves; matches legal oracle | Initial position alone is a weak legality test |
| 324 sampled positions / 10,935 generated trials | No board/count undo mismatch; no occupancy-mask mismatch | One-step trials after legal-history setup, not exhaustive recursive correctness |
| Incremental evaluation in random sample | Two mismatching trials, both black en passant | Does not prove no other score defect exists |
| Pseudo-legal move-set comparison in random sample | One mismatching position, missing queenside castle | Full legal move comparison has additional intentional/known differences |
| Focused special moves | Promotions and ordinary castling passed state checks; specific EP/castling faults reproduced | Focused success does not validate every special-move context |
| Kernel-generator traversal, initial position, depth 4 | **197,742** leaves | Pseudo-legal traversal, not a valid legal-perft result |
| Independent legal perft, initial position, depth 4 | **197,281** leaves | Difference is **461**; code needs legality filtering |
| Saved input audit | 30 snapshots; replayed histories and saved assigned/best moves were legal | Snapshots are not match-strength evidence |
| Saved depths / history lengths | Depths 8 or 10; histories from 46 to 80 plies; one assigned root move per file | Files represent different saved positions, not one complete search transaction |
| Rebuilt kernel on copied snapshots 1, 29, 30 | Reproduced saved moves, scores, and counted node totals with a one-second test allowance | Three smoke cases, not a broad strength benchmark |
| Rebuilt UCI startup | Returned identity, `uciok`, and `readyok` | Startup readiness does not prove readiness during search |
| Rebuilt UCI terminal FEN | Incorrectly returned `e2e4` | Reproduces downstream FEN loss |
| Zero-budget rebuilt kernel | Returned `a8a8`, default depth 6, and `nan` NPS | Emergency/boundary behavior, not typical timing behavior |

Perft counts strictly legal move-tree leaves and is particularly useful for move-generation testing. It does not measure positional playing strength. [Stockfish's perft documentation](https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html)

### The minimum lasting test suite I would build

**Rules:** compare exact legal move sets and perft divides against an independent oracle. Include check evasions, pinned pieces, discovered attacks, attacked castling transit squares, attacked b1/b8, lost castling rights, underpromotion, and en passant exposing a king.

**State:** after make/unmake, compare board, occupancy, piece state, rights, en-passant target, side to move, phase, hash, and evaluation with a saved snapshot or fresh recomputation. Also test sequences of nested moves and unwinds; the review's single-move checks do not replace those tests.

**Search:** use mate-in-one, mate avoidance, stalemate traps, recapture sequences, quiet defenses, repetition, and endgame positions. A test should state what property must hold, not merely repeat the implementation's current output.

**Protocol/process:** test FEN with and without suffix moves, exact movetime, stop during search, readiness during search, new game, no legal moves, missing input directory, failed worker, malformed result, overlapping searches, and two games sharing a machine.

**Performance and playing strength:** retain a fixed set of positions, compiler settings, hardware description, worker count, seed, and limits. Separate setup, transport, ordering, main search, and total latency. Use fixed-depth tests for comparable work and fixed-time tests for useful strength.

### How to decide whether an optimization helped

Run an ablation: enable one change, compare it against a fixed baseline, and record correctness, tactics, latency, memory, and match results. Use paired openings with colors reversed and disclose failures and uncertainty. Random public bot games vary too many conditions to attribute a small improvement to one line of code.

Once you have enough games, statistical match testing becomes valuable. Stockfish's testing framework illustrates the use of paired outcome models and sequential tests; you do not need to recreate its distributed infrastructure to adopt controlled comparisons. [Fishtest statistical methods](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html)

<a id="priorities"></a>

## 11. 🚀 A practical improvement sequence

This is how I would sequence the work to make each stage useful and reviewable. No dates are implied; completion criteria matter more than an invented schedule.

| Stage | Deliverable | Done when |
|---|---|---|
| **1 · Correct chess state** | Legal generation, shared attack logic, repaired EP/castling, explicit rights and clocks, mate/stalemate/draw behavior | Targeted tests and legal perft agree with the oracle; make/unmake invariants pass |
| **2 · Reliable decisions** | Real FEN support, legal fallback, typed search status, unified deadline, stop/readiness handling, checked worker responses | Protocol and failure tests return a valid move or proper terminal result without hanging |
| **3 · Trusted experiment mode** | Deterministic full-width baseline, corrected counters, phase timings, configuration instead of source edits | A fixed test run is reproducible and measurements have consistent definitions |
| **4 · Higher-value search** | Quiescence, position hashing/TT, better ordering, principal-variation reuse | Tactical and equal-time comparisons improve without rules regressions |
| **5 · Efficient execution** | Persistent workers or private-state thread pool, shared immutable tables, dynamic scheduling, separate logging | Measured total decision latency/scaling improves; cancellation and result identity remain correct |
| **6 · Better chess knowledge** | Tapered evaluation, tested strategic terms, endgame capability | Wins/tactics and held-out position behavior justify the extra evaluation cost |
| **7 · Advanced experiments** | Verified reductions, PVS/aspiration refinements, optional NNUE/policy work | Each change has an ablation and a documented accuracy/strength/time tradeoff |
| **8 · Public presentation** | Reproducible build, ownership map, examples, known limitations, benchmark method, clear dependency handling | A new reader can build, run, and understand the custom core from a clean checkout |

Some work can overlap. For example, replacing file transport can improve debugging before evaluation tuning. But optimizing a state representation whose rules are still unreliable makes failures harder to interpret, so Stage 1 should remain the foundation.

### If you choose only five next actions

1. **Make the kernel's moves legal and fix the reproduced special-move defects.**
2. **Give every search a legal fallback, an explicit deadline, and a cancellation path.**
3. **Build the deterministic baseline and measure all search work honestly.**
4. **Add quiescence and a bounded transposition table.**
5. **Move to persistent workers or private-state threads, keeping logs separate.**

A neural model is an exciting later milestone. Those five actions create the platform on which its value can actually be measured.

<a id="portfolio"></a>

## 12. 💼 Portfolio value and future documentation

### What I would want an interviewer to see

Your most persuasive story is the chain of decisions:

> “I represented moves compactly, precomputed immutable movement geometry, maintained evaluation incrementally, and searched with reversible state updates and alpha–beta bounds. I then examined which optimizations preserved results and which changed the search, using independent tests and controlled measurements.”

That statement is much stronger when followed by a bit-layout diagram, a make/unmake invariant test, a before/after profile, and a difficult bug you can explain.

The current project already supports the first part of that story. The validation and repair work would support the second. This report should not be used to claim those future repairs are already implemented.

### What I would highlight publicly

| Feature | Evidence worth showing |
|---|---|
| Compact representation | Move-bit layout, piece flags, actual field sizes |
| Precomputation | Ray structure and blocker handling |
| Incremental computation | Score deltas plus recomputation tests |
| Search engineering | Bound propagation, iterative deepening, principal variation once available |
| Concurrency | Actual process/thread ownership diagram and scaling data |
| Experimental judgment | A failed optimization, why it failed, and a measured replacement |
| Reliability | Clean-checkout build, protocol transcripts, known limits, reproducible tests |

Avoid generic claims such as “highly optimized,” “production ready,” or “advanced AI” unless the surrounding evidence defines what those words mean. **A precise, modest claim with a hard example makes a more technical impression than an inflated one.**

### Preserve the project's authorship clearly

Present your custom engine separately from third-party Lichess transport, Stockfish, and the JSON library. That attribution does not diminish your work; it helps readers find it.

Your statement that the original engine implementation was yours is the authorship context for this review. Source inspection alone cannot independently prove whether any historical code used AI. What I can state directly is that **this session did not alter your engine implementation**. This document is an AI-assisted review and should be identified that way if you publish it.

I would preserve an original source snapshot/tag before future development and keep implementation history legible. You asked to arrange publication and Git history later, so I did not reset Git, reorganize the repository, create a remote, or publish anything.

### Preparation for a clean public checkout

When you are ready, the practical work is: define explicit build targets, pin/document dependencies and toolchain assumptions, create required runtime directories, expose supported options, keep test data separate from runtime output, and retain the appropriate third-party notices and provenance.

The account-information filename and ignored local configuration should be considered in the future publication review; I did not read their contents. `.gitignore` is not proof that a sensitive file was never tracked. That is a targeted pre-publication task for later, alongside removing duplicate binary distributions and documenting which Stockfish binary/version is used.

The core currently uses Windows APIs, MinGW facilities such as `bits/stdc++.h`, and GCC builtins. A reproducible Windows/MinGW build would be a perfectly valid first public target. Cross-platform support can be a separate milestone rather than an implied promise.

### A future book-shaped documentation plan 📚

| Chapter | What a reader should learn |
|---|---|
| **1 · The problem and the project** | Why you built Mr. Bits, what is custom, and how it fits the bot |
| **2 · Representing chess compactly** | Piece flags, packed moves, occupancy masks, coordinate mapping |
| **3 · Generating legal moves** | Rays, blockers, attacks, checks, pins, special moves, perft |
| **4 · Changing and restoring state** | Undo records, incremental scores, hashes, invariants |
| **5 · Searching an adversarial tree** | Minimax, alpha–beta, ordering, quiescence, iterative deepening |
| **6 · Working within a clock** | Deadlines, completed iterations, cancellation, external protocol |
| **7 · Parallel search** | Worker ownership, scheduling, IPC, scaling, shared-table tradeoffs |
| **8 · Learning from experiments** | Ablations, tactical suites, match statistics, unsuccessful ideas |
| **9 · Stronger evaluation** | Phase, endgames, data-driven tuning, optional NNUE |
| **10 · Reproducing the project** | Builds, configuration, tests, dependencies, operating limits |

Use your actual code paths and your own explanations as the spine. The repaired en-passant example would make an excellent lesson about why an optimization needs an invariant; the trie experiment would make a good lesson about data-structure fit.

### My personal assessment, bro

I understand why this project matters to you. There is enough technical substance here to have a serious discussion about how you think: how you reduce representation cost, recognize repeated work, maintain state, and explore a very large decision space.

The part I would challenge hardest is the jump from “this was faster in a few experiments” to “this is a better engine.” Some current choices buy speed by changing the game tree or ignoring required state. The next level of the project is proving which savings preserve answers and which risks actually improve play under a clock.

**My recommendation for making it excellent is to preserve the compact core, repair the rules, make experiments reproducible, and let measured results choose the next optimization.** You do not need an unlimited list of clever tricks. You need a foundation that lets the good tricks prove their value.

<a id="appendix"></a>

## 13. 🔎 Source map, evidence, and references

### Navigate the custom implementation

Line numbers refer to the reviewed source snapshot, not to this report.

| Component | Source location |
|---|---|
| UCI `ChessState`, serialization, root workers | `Engine UCI.cpp:39–386` |
| Game/history naming and report writes | `Engine UCI.cpp:393–478` |
| Active phase/thread/time configuration and selection | `Engine UCI.cpp:485–656` |
| UCI input loop | `Engine UCI.cpp:662–751` |
| Kernel constants/global representation | `Kernel.cpp:19–41` |
| Duplicated orchestration class | `Kernel.cpp:45–392` |
| Process/timing/report support | `Kernel.cpp:395–792` |
| Inactive board trie | `Kernel.cpp:794–984` |
| Board, score, and coordinate initialization | `Kernel.cpp:988–1105` |
| Precomputed movement geometry | `Kernel.cpp:1107–1395` |
| Piece-square tables | `Kernel.cpp:1397–1491` |
| Castling safety | `Kernel.cpp:1493–1740` |
| Piece move generation | `Kernel.cpp:1742–1942` |
| Static heuristic ordering | `Kernel.cpp:1947–2039` |
| Apply moves and incremental scores | `Kernel.cpp:2042–2581` |
| Undo board/count changes | `Kernel.cpp:2584–2777` |
| Shallow ordering search and ordering wrapper | `Kernel.cpp:2779–2933` |
| Main recursive search | `Kernel.cpp:2935–3129` |
| Root generation, scoring, ordering | `Kernel.cpp:3131–3315` |
| Initialization and worker entry point | `Kernel.cpp:3317–3413` |
| Stockfish transport | `Stockfish Handler.hpp:14–50` |
| Evaluation parsing | `Stockfish Handler.hpp:53–119` |
| Legal root enumeration | `Stockfish Handler.hpp:121–150` |
| Best-move selection and optional NNUE sorting | `Stockfish Handler.hpp:152–224` |
| Terminal-state helpers | `Stockfish Handler.hpp:227–244` |

### Source fingerprints

These identify the exact four custom C++ files reviewed and help distinguish later edits. They are not signatures proving historical authorship.

```text
Engine UCI.cpp
05ED557F763AAB92BBE06E4B9AAD3DCDDDAC70BFCDE24ADA91D3CFB05F768EF8

Kernel.cpp
A7B5A4AC412BAF5FD97FA59750368E1A277685B57B46C5A237D08953CB3263A9

Stockfish Handler.hpp
BF0844FCF4D22BCA8636E908C1F98513D8AB3C0DE7D726B3E76368DE7BDE7A57

Stockfish Handler Testing.cpp
58D4F6E32143F59A7CC2C43E98613CE5BE737FFAE1F8041E6B7D3A1771C0D1D3
```

### Reproducing the build checks

From the repository root, these checks read the source without replacing executables:

```powershell
g++ -std=c++17 -Wall -Wextra -Wconversion -fsyntax-only 'lichess-bot-master/engines/Kernel.cpp'
g++ -std=c++17 -Wall -Wextra -Wconversion -fsyntax-only 'lichess-bot-master/engines/Engine UCI.cpp'
```

The review's temporary optimized builds additionally used `-O2`. The targeted FENs, move histories, seed, test scope, and observed outputs are recorded above so the findings can become permanent tests. The harness's direct FEN setup and pseudo-legal traversal must not be confused with production UCI support or legal perft.

External links appear beside the relevant protocol, rules, or technical discussion. They support those background statements; the findings about Mr. Bits come from its source and the described executions. The roadmap and architecture choices are my engineering recommendations, not benchmarked outcomes.

---

♟️ **Review complete for this snapshot.** The original implementation remains intact. This is the assessment to build the next experiments and documentation from.
