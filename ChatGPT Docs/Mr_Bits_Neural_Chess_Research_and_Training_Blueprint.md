<style>
:root { color-scheme:light dark; --ink-blue:#2563eb; --ink-green:#15803d; --ink-gold:#a16207; --ink-red:#b91c1c; }
body { max-width:1100px; margin:3rem auto; padding:0 1.4rem; font-family:Inter,Segoe UI,Arial,sans-serif; line-height:1.78; }
h1,h2,h3 { line-height:1.25; letter-spacing:-.02em; }
h1 { color:var(--ink-blue); font-size:2.6rem; }
h2 { border-bottom:2px solid #64748b55; padding-bottom:.55rem; margin-top:3rem; }
h3 { margin-top:2rem; }
table { border-collapse:collapse; width:100%; margin:1.2rem 0; font-size:.94em; }
th,td { border:1px solid #64748b55; padding:.65rem .8rem; text-align:left; vertical-align:top; }
th { background:#64748b18; }
blockquote { border-left:5px solid var(--ink-blue); background:#2563eb0d; padding:.8rem 1.2rem; margin:1.5rem 0; }
pre { overflow:auto; border:1px solid #64748b44; border-radius:9px; padding:1rem; background:#64748b0d; line-height:1.45; }
code { font-family:Cascadia Code,Consolas,monospace; font-size:.91em; }
a { color:var(--ink-blue); }
.good { color:var(--ink-green); font-weight:700; }
.watch { color:var(--ink-gold); font-weight:700; }
.critical { color:var(--ink-red); font-weight:700; }
.note { color:var(--ink-blue); font-weight:700; }
@media (prefers-color-scheme:dark) { :root { --ink-blue:#93c5fd; --ink-green:#86efac; --ink-gold:#fde68a; --ink-red:#fca5a5; } }
@media print { body { max-width:none; margin:0; font-size:10.5pt; } h2,h3 { break-after:avoid; } pre,blockquote { break-inside:avoid; } }
</style>

# ♟️🧠 Mr. Bits Neural Chess Lab

## From a board to a score—and from a score to better search

**A research paper and practical training blueprint for Tareq Ali**  
**Research checked:** 22 October 2026 · **Prepared by:** ChatGPT / Codex

<p><span class="good">🟢 Ready-made labels exist</span> · <span class="note">🔵 Scalar evaluation is a valid goal</span> · <span class="watch">🟡 Strong play must be measured</span> · <span class="critical">🔴 Top-five pruning can miss the only good move</span></p>

> **Bro, the biggest answer is encouraging: we do not need to spend years evaluating billions of positions ourselves. Strong engines have already done enormous amounts of that work, and useful labeled datasets are public.**
>
> Your proposed interface—board and relevant state in, one evaluation out—is a sound project. My recommended first experiment is a small general evaluator trained on searched teacher scores, used to order legal moves while retaining the search's ability to examine alternatives. Then we can test phase specialists and more selective search against evidence.

**The research question:** can a compact learned evaluator help Mr. Bits choose where to spend its search time, improving playing strength under the same wall-clock limit?

This paper proposes a study; **it does not report a trained model, new Elo result, measured training throughput, or guaranteed improvement**. Published facts have nearby source links. Architecture sizes, sampling policies, thresholds, budgets, and rollout stages marked as proposals are our experimental choices.

Your engine source and the earlier review remain unchanged. No data purchase, bulk download, cloud provisioning, or training run was performed for this paper. `Claude Docs` was not read.

The diagrams use plain text and render in ordinary Markdown-to-HTML converters. CSS adds optional colors; the text and emoji remain readable without it.

---

## 🧭 Reading map

1. [What we should build first](#first-model)
2. [The deep-learning concepts you actually need](#primer)
3. [What the network must know about a position](#inputs)
4. [What an evaluation label means](#labels)
5. [Where to get the data](#datasets)
6. [Turning downloaded data into trustworthy samples](#data-pipeline)
7. [Choosing a network architecture](#architecture)
8. [Training objectives and practical settings](#training)
9. [One network or four phase specialists?](#specialists)
10. [Your top-five idea: benefits, risks, and a better progression](#search)
11. [Building a measurable “trust factor”](#trust)
12. [Training on the GPU, playing inside C++](#deployment)
13. [Hardware, time, and a few-hundred-dollar budget](#budget)
14. [How we will decide whether it works](#evaluation)
15. [The project sequence and final recommendation](#roadmap)
16. [Glossary and source guide](#references)

**For a first read:** Chapters 1, 4, 5, 9, 10, and 15 answer your main questions. The remaining chapters explain how to make the experiment reproducible.

<a id="first-model"></a>

## 1. 🎯 What we should build first

### The recommended first version

| Decision | First experiment |
|---|---|
| Main output | One White-perspective, pawn-like evaluation |
| Training method | Supervised learning from an engine's already searched evaluations |
| Starting data | A carefully prepared subset of Lichess's evaluated-position export |
| First architecture | Small general multilayer perceptron, with a compact/incremental alternative tested afterward |
| First scale | Tiny correctness sample, then about 1–5 million clean positions; grow only when experiments justify it |
| First search use | Shadow scoring, then legal-move ordering |
| First comparison | The same corrected Mr. Bits search with and without the learned component |
| Later specialization | Shared general features with phase-specific heads, compared with the general baseline |
| Runtime | Weights loaded once; inference inside the persistent C++ process |
| Purchase decision | Start with free labeled data; spend selectively on experiments and hard-case labels |

This first model is a **baseline**, meaning a reference experiment we can understand and compare against. It is not a promise that a small dense network is the final strongest architecture.

### Your proposed loop is a valid interface

```text
                      current legal position
                               │
                    generate all legal moves
                               │
           ┌───────────────────┼───────────────────┐
           ▼                   ▼                   ▼
       make move A         make move B         make move C
           │                   │                   │
       child board         child board         child board
           │                   │                   │
       value network       value network       value network
           │                   │                   │
        score A             score B             score C
           └───────────────────┼───────────────────┘
                               ▼
                  prioritize work in the search
```

The network does not have to output a move. The search can compare scalar scores. DeepMind's ChessBench study explicitly includes a state-value approach that evaluates legal successor positions, alongside action-value and move-prediction approaches. That is direct precedent for the interface you described. Its results establish possibility at its studied scale, not the strength our first model will achieve. [ChessBench paper, Section 2.3](https://arxiv.org/html/2402.04494v2)

### What I would change in your hypothesis

“We keep only the best five and therefore become stronger” contains two separate claims:

1. We search fewer branches, potentially allowing greater depth.
2. The branches we removed do not contain a move or defense that matters.

The first can be true while the second fails. Once a necessary move is removed, extra depth cannot recover it. The experiment should therefore optimize **useful strength per second**, measuring both saved work and missed opportunities.

The earlier [engineering review](Mr_Bits_Independent_Engineering_Review.md) explains the rules and timing repairs that should precede serious strength comparisons. We can research and prepare the model in parallel with those repairs, as you suggested.

<a id="primer"></a>

## 2. 🧩 The deep-learning concepts you actually need

Imagine showing a student many chess diagrams, each with a teacher's score. The student learns a function that approximately reproduces those judgments on new diagrams.

```text
             one training example

  x: board + state       y: teacher evaluation
           │                    │
           ▼                    │
       network                  │
           │                    │
           ▼                    ▼
      prediction ───────► compare prediction with label
                                  │
                                  ▼
                          calculate training loss
                                  │
                                  ▼
                         adjust network weights
```

| Term | Meaning in this project |
|---|---|
| **Sample** | A position and its target score, plus provenance |
| **Input / features, `x`** | Numeric encoding of pieces, turn, and supported flags |
| **Label / target, `y`** | The score we want the model to approximate |
| **Prediction, `fθ(x)`** | The score the current model produces |
| **Parameters / weights, `θ`** | Numbers learned during training |
| **Loss** | A numerical penalty for a wrong prediction |
| **Optimizer** | The algorithm that changes weights to reduce loss |
| **Batch** | A group of samples processed in one training step |
| **Epoch** | One pass through the chosen training dataset |
| **Validation set** | Unseen examples used to choose settings/checkpoints |
| **Test set** | A separate, locked evaluation of the selected model |
| **Inference** | Using trained weights to predict; no weight updates happen |
| **Overfitting** | Learning the training examples too specifically and failing on new ones |

For example, if the teacher says `+0.80` and the model predicts `+0.20`, the error is `−0.60` pawn-like units. Training changes many weights so similar examples may improve. It does not insert a precise chess rule saying “this bishop is worth 0.60 more.”

The labels do not have to be perfect to be useful. They do need consistent meanings, sensible quality, and sufficient coverage of positions the model will see during play.

### Teacher, student, and distillation

**Teacher:** a strong engine performing search.  
**Student:** our much cheaper neural evaluator.  
**Distillation:** training the student to approximate the teacher's results.

```text
OFFLINE, before play                       ONLINE, during play

positions → teacher search → saved scores  position → student → approximate score
                    │                                     │
                    └────── training data ─► weights ──────┘
```

The teacher's search happens while generating the dataset. Our student later makes a direct prediction without repeating that search. This is how a network can learn from expensive computations without incurring their full cost on every runtime call.

It is a compression of knowledge, not a guarantee that every long tactical sequence has been memorized or understood.

<a id="inputs"></a>

## 3. 🗺️ What the network must know about a position

Your “board plus a few flags” idea is close. A few details are essential.

### A proposed basic encoding: 782 values

| Input | Encoding | Values |
|---|---|---:|
| Piece placement | Twelve binary planes: six piece types × two colors, each with 64 squares | 768 |
| Side to move | One binary value | 1 |
| Castling rights | Four flags for White/Black, king/queen side | 4 |
| En-passant target | One-hot: none, or file a–h | 9 |
| **Total** | **Core position encoding** | **782** |

“One-hot” means exactly one entry is 1 and the others are 0. En passant needs the target file, not just a yes/no flag. In standard chess, the target rank follows from the side to move.

An empty square has no active piece-plane entry. Piece placement is parsed from FEN or obtained from your board representation; the first model does not need to learn how to read a FEN string as a language.

**Side to move is indispensable.** The same pieces with the opposite side to move can change a position dramatically.

**Castling rights are not “can castle immediately.”** Rights can exist while pieces block the route or the king is in check. The chess engine still determines legal moves.

### Halfmove clocks and repetition

A full position record can include a halfmove clock, relevant to draw rules. For sources that provide it, we can add a normalized clock and a “known” flag—**784 inputs** in that extended design. If another feature such as material phase is added, increment the input definition and version accordingly.

The Lichess evaluation export lacks the last two FEN counters. Do not invent a real halfmove clock of zero merely because a parser needs a placeholder. Record it as unknown. Our first 782-input model makes a position-value approximation without that missing information; the engine handles exact terminal/draw state separately.

Repetition requires game/search history. FEN by itself does not contain that history, and one repetition counter is not a complete replacement. The same visible board can therefore have different rule-relevant contexts. [python-chess position/FEN documentation](https://python-chess.readthedocs.io/en/latest/core.html#chess.Board.fen)

```text
            ENGINE owns the complete legal state

 board + turn + rights + EP + clocks + repetition history
                 │                         │
                 │                         └── exact legality / terminal rules
                 ▼
          supported NN features
                 │
                 ▼
          approximate evaluation
```

The network must not be responsible for deciding whether a king can be captured, whether a draw claim exists, or whether a castle is legal. Those remain engine rules.

### A useful augmentation, used carefully

One experiment is to flip ranks and swap piece colors, swap the side to move and castling rights, transform the en-passant square, and negate the White-perspective score. This creates a color-reversed version of a sample.

Test that transformation against a legal chess library. Do not casually apply image-style rotations or horizontal flips: pawn direction and standard castling geometry make arbitrary image augmentation invalid. Keep transformed relatives in the same data split to avoid leakage.

<a id="labels"></a>

## 4. 🏷️ What an evaluation label means

### Your desired output is feasible

We can define our public interface as:

```text
V_white(position) → pawn-like score

positive: predicted advantage for White
negative: predicted advantage for Black
```

If a source provides White-perspective centipawns, the display conversion is simply `pawns = cp / 100`. Thus `125 cp` becomes `+1.25`.

However, `+9` should mean “a very large predicted White advantage on the chosen teacher's scale,” not necessarily “exactly one extra queen.” Modern Stockfish's displayed scale is normalized and is not a literal material ledger. Teacher versions and score conventions must be recorded. [Stockfish score interpretation](https://official-stockfish.github.io/docs/stockfish-wiki/Stockfish-FAQ.html#interpretation-of-the-stockfish-evaluation)

### Static evaluation and searched evaluation are different targets

| Target | What produced it | What the student learns |
|---|---|---|
| Static teacher score | Direct evaluator call on this board | Approximation of that evaluator |
| Searched teacher score | Teacher explores continuations, then backs up a result | Approximation of a stronger, budget-dependent judgment |
| Game outcome | A human or engine game ended 1–0, ½–½, or 0–1 | Outcome prediction under the data's playing conditions |
| Tablebase result | Exact result for supported positions under a specified rule model | Exact WDL/other tablebase target in that restricted domain |

For your goal, **searched teacher labels are the main recommendation**. Their cost has already been paid in the public datasets discussed next.

### About your experience with NNUE alone

Your observation makes sense: a one-pass static score can miss tactics that a search finds. Stockfish's documentation itself describes `eval` as a rough static assessment and points to `go` for a searched assessment. [Stockfish `eval` documentation](https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html#eval)

But “NNUE” describes an efficiently updatable network design; it does not mean “perfect score without search,” nor does a disappointing static test establish that this architecture is unsuitable. Stockfish's original NNUE introduction describes training on searched evaluations and using the learned evaluator within search. [Stockfish NNUE introduction](https://stockfishchess.org/blog/2020/introducing-nnue-evaluation/)

There is also a project-specific confounder: your `Stockfish Handler.hpp:65–79` substitutes a magnitude-100,000 score when static evaluation reports a check position, and `202–214` counts spaces to determine move-order direction. Those can distort an experiment independently of the network. I would retest using a correct direct interface before drawing conclusions about NNUE quality. This identifies a possible confounder; it does not prove what happened in every earlier test you ran.

### Perspective must be explicit

Some scores favor White; others favor the side to move. Conversion is straightforward once the convention is known:

```text
teacher score is side-to-move centipawns:

cp_white = cp_stm             if White is to move
cp_white = -cp_stm            if Black is to move
```

With our White-perspective model, White selects larger child scores and Black selects smaller child scores. With a side-to-move model, the child's player is the opponent, so a parent-facing value requires sign reversal for signed scores. Use `1 − p` for expected game score or a symmetric transformed-score target; for full WDL, swap win and loss while retaining draw. A win probability alone cannot simply be complemented because draws exist.

| Child prediction in White's perspective | White prefers | Black prefers |
|---|---|---|
| A: `+0.70`, B: `+0.20`, C: `−0.40` | A | C |

Never infer the sign from spaces in a move string. Use the board's actual turn.

### Mate is a different label type

“Mate in 3” is not `+3` pawns or `+3` centipawns. Keep `score_kind = cp` and `score_kind = mate` separate. For the first centipawn-regression model, mate records can be excluded from the regression batch while retained in tactical tests and a separate label table.

The engine must still recognize immediate mate and terminal positions exactly. Later, a separate mate/outcome head can be studied; a scalar approximate evaluator cannot certify a forced mate merely by outputting a large number.

### Probability-style labels need their own contract

A true WDL prediction has three values: probability of win, draw, and loss. Its expected game score is `P(win) + 0.5 × P(draw)`, which is not the same as probability of winning.

Other datasets transform an engine score through a sigmoid, producing a number between 0 and 1. That is not automatically a calibrated probability of a real game outcome. Preserve the source transformation; do not silently mix it with centipawns, native WDL, or game results.

<a id="datasets"></a>

## 5. 🌍 Where to get the data

### Route A · Lichess evaluated positions: the best first scalar-label source

The official export lists **416,442,401 evaluated positions**, updated **5 October 2026**, under CC0. It provides compressed JSON Lines: one position with grouped analyses containing depth, kilo-nodes, and PV scores. Its recommended scalar selection is the highest-depth analysis and its first PV. FEN contains four fields; PV move strings use UCI_Chess960 notation. These are mixed engine/browser analyses, so search quality is heterogeneous. [Official evaluation export](https://database.lichess.org/#evals)

Direct archive: [lichess_db_eval.jsonl.zst](https://database.lichess.org/lichess_db_eval.jsonl.zst). This is a large binary download; this research did not download it, and I am not quoting an unverified archive size.

The exporter's code preserves the analysis/PV structure. Lichess's cloud JSON serialization explicitly emits White-perspective `cp` and `mate` fields. [Official exporter](https://raw.githubusercontent.com/lichess-org/database/master/src/main/scala/Evals.scala), [score serialization](https://raw.githubusercontent.com/lichess-org/lila/master/modules/evalCache/src/main/JsonView.scala)

**Our proposed use:** read a small sample, select one suitable non-mate target per position, preserve quality metadata, and create an auditable training subset. No new engine search is required for those existing targets.

### Route B · Official Lichess Parquet mirror: convenient, with a major trap

The official Hugging Face card describes the same **416,442,401 positions** flattened into **1,003,347,246 rows**, updated **7 October 2026**. The row schema is `fen`, `line`, `depth`, `knodes`, nullable `cp`, and nullable `mate`. The dataset identifies CC0 licensing. Use the actual repository identifier **`Lichess/chess-position-evaluations`**; the card's example currently contains a different, stale-looking identifier. [Dataset card](https://huggingface.co/datasets/Lichess/chess-position-evaluations/raw/main/README.md)

**A billion rows does not mean a billion independent board values.** Different rows can be different candidate moves from the same parent position. The viewer demonstrates repeated FENs with different lines and scores. [Official dataset viewer](https://huggingface.co/datasets/Lichess/chess-position-evaluations)

Here is the conceptual issue, using invented numbers:

```text
Same parent board S, White to move

row 1: S, candidate A, score +0.50
row 2: S, candidate B, score -3.00
row 3: S, candidate C, score +0.10

Wrong scalar training:
    network(S) should equal +0.50 AND -3.00 AND +0.10

Correct interpretations:
    V(S) ≈ best backed-up score: +0.50
    Q(S, A) ≈ +0.50; Q(S, B) ≈ -3.00; Q(S, C) ≈ +0.10
```

`V(S)` is a **state value**. `Q(S, move)` is a **move-conditioned action value**. Both are scalar learning problems. An action-value model does not have to output the best move either.

For Black to move with White-perspective scores, mover-optimal selection is the minimum. For a beginner pipeline, the nested raw export is easier to interpret correctly because it retains analysis grouping and PV order. A flattened importer needs a tested reconstruction policy; simply keeping the first encountered row or averaging every row is not that policy.

A useful later alternative is to apply a labeled candidate's first move and train on the resulting child position. That target is then a searched estimate conditional on the move, with the appropriate perspective conversion. Validate the PV notation, legality, and search-horizon interpretation first. Never give the future PV itself to a runtime board-only model as an input feature.

### Route C · ChessBench: particularly relevant to your move-ranking goal

DeepMind released data for state values, action values, and move prediction. The study used Stockfish 16 with a 50 ms annotation budget per state or state-action pair, producing approximately **530 million states** and **15.3 billion action-value examples**. These are already computed teacher labels; they are not perfect chess values or 15.3 billion independent board positions. [ChessBench paper](https://arxiv.org/html/2402.04494v2)

The authors' download table lists **36 GB** for state-value training and **1.1 TB across 2,148 shards** for action-value training. Code, weights, and data have different stated licenses: the data combines CC0 Lichess portions with CC-BY 4.0 for the remainder. Check the release terms for what we actually redistribute. [Official downloads and license notes](https://github.com/google-deepmind/searchless_chess#downloading-the-datasets)

| Dataset task | Record | How it helps us |
|---|---|---|
| State value | `(fen, win_prob)` | Train a board-to-score student |
| Action value | `(fen, move, win_prob)` | Train/evaluate candidate ranking or convert to child examples |
| Behavioral cloning | `(fen, move)` | Predict a move; not needed for your first scalar model |

These schemas come from the authors' implementation. [Record definitions](https://raw.githubusercontent.com/google-deepmind/searchless_chess/main/src/constants.py)

Two concrete training downloads are the [state-value file](https://storage.googleapis.com/searchless_chess/data/train/state_value_data.bag) and [first action-value shard](https://storage.googleapis.com/searchless_chess/data/train/action_value-00000-of-02148_data.bag). These use the project's `.bag` format and reader, not Parquet. Choose a bounded acquisition plan; do not assume an arbitrary downloaded prefix is a complete readable training shard.

The `win_prob` label uses the transform `p = 1 / (1 + exp(-0.00368208 × cp))`. It is a transformed engine score, not Stockfish's native WDL triplet. If conversion back to that source's cp is needed, invert its exact transform for suitable interior values and retain its provenance. At 0, 1, or numerical saturation, original score magnitude and mate distance are not recoverable; epsilon clipping only invents a finite approximation. Exclude such cases from finite-cp regression or keep their bounded target. [Authors' conversion code](https://raw.githubusercontent.com/google-deepmind/searchless_chess/main/src/utils.py)

The model convention is side to move. For an action example, legally applying the move gives a child whose side-to-move target is `1 − p`; a White-perspective model must then normalize by the child's turn. Check this with concrete test positions. [Authors' successor evaluation](https://raw.githubusercontent.com/google-deepmind/searchless_chess/main/src/engines/neural_engines.py)

**Do not download the whole action-value corpus to begin.** Use the official reader and a deliberately sized training subset. Large arbitrary shards need not contain every sibling of a parent; verify legal-action coverage before using a group to measure top-five recall. The released evaluator checks that coverage. [Authors' ranking evaluator](https://raw.githubusercontent.com/google-deepmind/searchless_chess/main/src/metrics_evaluator.py)

### Route D · Stockfish training binpacks: strong advanced material

The official Stockfish collection contains binary training packs and currently identifies its data license as **ODbL**. One listed smaller file, `fishpack32.binpack`, is **5.58 GB**. These are training records, not network-weight files or ready-made CSV rows. [Official binpack collection](https://huggingface.co/datasets/official-stockfish/master-binpacks/tree/main)

Use the project's loader and study each dataset's score/result conventions. Internal training scores should not automatically be interpreted as the latest displayed UCI centipawns. Teacher provenance, variants, rescoring, and transforms can differ. This route becomes attractive if we pursue an incrementally updatable evaluator and want to learn the established tooling. [Official NNUE trainer](https://github.com/official-stockfish/nnue-pytorch), [dataset documentation](https://github.com/official-stockfish/nnue-pytorch/wiki/Training-datasets)

### What about millions of ordinary games?

Games supply positions; they do not automatically supply the evaluation of every position. Annotated PGNs can provide some labels, but missing evaluation comments are not zeros. Lichess's ordinary rated-game export has evaluations in only about **6% of games**; annotations such as `[%eval 2.35]` are White-perspective pawn scores attached to the position after the preceding move. [Lichess export format and notes](https://database.lichess.org/)

Game results are another possible supervision signal, but a player can win after having been lost. Outcome prediction is useful research; it does not turn every position in a winning game into a correct positive engine evaluation.

Puzzle data is useful for tactical tests, but its usual CSV is not a general FEN-to-centipawn dataset. Also, the published puzzle FEN precedes the opponent's setup move; present the position after that first move when testing the actual puzzle decision. [Official puzzle export specification](https://github.com/lichess-org/database/blob/master/web/index.html.tpl)

### Should we buy a dataset?

**My recommendation is to spend $0 on a dataset initially.** I did not verify a commercial evaluated-position product with a clear advantage over these free sources for our first experiment. That does not mean no such product exists.

Buying a game collection is a different purchase. For example, ChessBase's Mega Database 2026 product advertises games and annotations; its product description does not establish a dense, uniformly labeled machine-learning dataset with the score protocol we need. [Vendor's product page](https://shop.chessbase.com/en/products/mega_database_2026)

If we later consider a paid supplier, request a sample and insist on: legal FENs, teacher build/network, score perspective, score units, mate handling, search budget, duplicate policy, phase coverage, and explicit permitted uses. Clean packaging is valuable only when the labels' meanings are clear.

<a id="data-pipeline"></a>

## 6. 🧼 Turning downloaded data into trustworthy samples

The important deliverable is not “a billion rows on disk.” It is a smaller, versioned dataset whose inputs and labels mean what we think they mean.

### The proposed preparation pipeline

```text
public source + pinned snapshot
              │
              ▼
stream records / read selected complete shards
              │
              ▼
validate chess state and parse score type
              │
              ▼
recover STATE value or MOVE-conditioned value explicitly
              │
              ▼
normalize viewpoint, units, and known/unknown fields
              │
              ▼
deduplicate and preserve source/quality metadata
              │
              ▼
split without shared positions or related augmentations
              │
              ▼
stratify / build compact training shards
              │
              ▼
audit sample, freeze manifest, train pilot
```

### Step 1 · Freeze provenance before transforming anything

Record the source URL, repository revision or dated release, downloaded-file checksum, parser version, and selection policy. For labels with known teachers, record the engine build, network, score transform, search budget, and thread/hash settings. Use `unknown` when a source does not provide something; do not retroactively label every Lichess record “Stockfish 16.”

This allows us to explain later why a particular target exists and to reproduce a training subset.

### Step 2 · Validate positions and move notation

Use a mature legal chess implementation for data preparation. Check piece placement, active color, rights, en-passant state, and standard-chess legality. Filter unsupported variants when metadata identifies them; quarantine inconsistent records. A valid-looking FEN alone does not prove a record's original variant or teacher settings.

Parse the source's PV notation correctly, especially castling. UCI_Chess960 can encode castling differently from your engine's current coordinate convention. The test is the resulting board and rights, not whether a four-character string looks plausible.

### Step 3 · Select the correct target before sampling

For the first raw-Lichess scalar pipeline, the proposed rule is:

1. Inspect the grouped analyses for a position.
2. Select the highest-depth suitable analysis, using a documented tie policy such as node count.
3. Take its first PV for the parent state-value target.
4. Retain the score kind and source quality metadata.
5. Route mate records to a separate collection.

If the selected strongest analysis's first PV reports mate, route that parent out of finite-centipawn regression. Do not substitute an older finite score just to keep the record.

This follows the source's scalar-selection guidance. It does not make heterogeneous labels exact or uniformly searched.

A pilot might compare an unfiltered baseline against a proposed quality filter such as `depth ≥ 18` and `knodes ≥ 100`—the latter means 100,000 searched nodes. These thresholds are **experimental choices**, not a scientific boundary between good and bad labels. Report how many positions survive and which phases disappear.

### Step 4 · Normalize once, then verify the sign

Use an explicit internal label contract such as:

```text
position features: supported board state
target_kind:       cp_white
target_cp:         signed numeric value
mate:              separate field / separate table
halfmove_known:    true or false
source:            named, versioned dataset
quality:           depth, nodes, and any known teacher details
```

Before training, manually inspect a few material-imbalanced, quiet positions with both sides to move. Then compare imported labels with a controlled teacher on a small audit set. Opening positions alone do not catch a sign flip.

Do not feed `line`, teacher-selected move, search depth, or future game result as a feature to a board-only runtime model. Depth/nodes can be used for filtering or experimental sample weights; they are not secret runtime information the model should depend on.

### Step 5 · Deduplicate without hiding conflicts

Repeated openings can overwhelm the data. Deduplicate equivalent visible inputs according to a versioned state-key policy. Keep distinct known rule states distinct; do not erase halfmove information from one source while claiming exact equivalence with another.

If repeated analyses disagree substantially, retain the disagreement in an audit table. Prefer a documented stronger analysis for the main target or reanalyze the case. Blind averaging can mix different candidate moves, teacher scales, and tactical horizons into a label no teacher actually intended.

### Step 6 · Split before model selection and augmentation

Where game identifiers exist, split by game/source group rather than random adjacent positions. For cache records without game IDs, a stable hash of the canonical position can create disjoint position splits, although this does not guarantee unrelated game trajectories.

For sibling-ranking data, assign whole parent groups to a split. Then remove cross-split overlap of the actual input positions, including child conversions and color-reversed variants. Lock the test set first and purge leaking training records. A parent-group split alone does not prevent a transposed child from reappearing in training.

A proposed starting partition is **90% training / 5% validation / 5% test**. Exact proportions matter less than independence, useful phase coverage, and never tuning on the locked test results.

### Step 7 · Sample the problem we want to solve

Stratify by score magnitude, side to move, material/phase, and tactical status. For example, examine coverage across `0–50`, `50–200`, `200–600`, and `600–1500` absolute centipawns, crossed with phase and whether a side is in check.

Do not let trivial queen-up positions dominate a model intended to distinguish several nearly equal middlegame moves. Also do not remove every tactical example if the network will rank arbitrary children immediately after captures or sacrifices.

The same network can be tested for two jobs, but the distributions differ:

| Deployment | Typical inputs | Data consequence |
|---|---|---|
| Static leaf evaluator after quiescence | Often tactically quieter leaves | Quiet-position supervision can be a useful experiment |
| Ranker of all legal child positions | Exchanges, checks, sacrifices, quiet moves | Must include and test those unstable children |

The official NNUE loader has optional filtering for cases such as checks and capturing moves. That is a choice within its training/search pipeline, not a universal instruction to remove all tactical data from our ranker. [Training-data filter implementation](https://github.com/official-stockfish/nnue-pytorch/blob/master/data_loader/cpp/training_data_loader.cpp)

### Step 8 · Keep storage compact

Your bit-packing instincts are useful here. Four bits per square can represent an orthodox piece code, so a board can occupy 32 bytes before flags, targets, metadata, and alignment. A hypothetical 64-byte training record makes ten million examples about **640 MB decimal**, excluding container overhead.

By comparison, expanding only twelve board planes to float32 for all ten million positions uses **30.72 GB**. Store compact shards and expand batches. Avoid parsing FEN repeatedly inside the training hot loop.

These are size calculations for a proposed representation, not a measured dataset compressor. Keep human-readable provenance separately rather than discarding it for a few saved bytes.

### Step 9 · Add targeted labels where they are valuable

We do not need to relabel the whole public corpus. Useful new labels include:

- Cases where our model disagrees with a stronger, pinned teacher.
- Positions where the proposed top-five policy drops a necessary move.
- Underrepresented endgames, sacrifices, promotions, or defenses.
- Complete legal sibling sets for a manageable ranking benchmark.
- Positions encountered by the corrected Mr. Bits search, which differ from ordinary game positions.

Run persistent teacher processes through a correct interface. Benchmark independent single-thread workers against fewer multithreaded workers; record hash behavior and clear or control cross-position reuse according to the labeling protocol. Fixed node budgets can make work definitions clearer than an undocumented “depth 22,” but neither makes labels exact.

This targeted loop is a form of **active data collection**: spend new computation on mistakes and missing coverage rather than duplicating what the public data already supplies.

<a id="architecture"></a>

## 7. 🏗️ Choosing a network architecture

### Model A · A small dense baseline we can understand

**Proposal:**

```text
782 inputs → 256 hidden units → 64 hidden units → 1 scalar
               ReLU               ReLU          linear output
```

A hidden unit combines inputs through learned weights and a nonlinear activation. ReLU retains positive values and replaces negative values with zero; the final output stays linear so both positive and negative scores are possible.

Including biases, this proposed core has **216,961 parameters**. Float32 parameter storage is about **0.87 MB decimal**, excluding optimizer state, activations, and implementation overhead. Changing the input feature count changes these numbers.

This model is intentionally small enough to debug and export. It might be insufficiently expressive for the strongest evaluator we want; that is something the learning curves and chess tests will tell us.

### Model B · A sparse, incrementally updated evaluator

Most piece-square inputs are zero. Instead of multiplying every one of the first layer's weights by zero, sum the learned columns corresponding to active features. Then maintain that first-layer sum as pieces move.

```text
first-layer accumulator:

move a piece:  subtract old square's feature column
               add new square's feature column

capture:       subtract captured piece's column
promotion:     replace pawn feature with promoted piece feature
castling:      update king and rook features
turn/rights/EP: update changed auxiliary features
```

That is closely related to the incremental score maintenance you already implemented. NNUE designs exploit sparse, slightly changing inputs and efficient low-precision inference. [NNUE architecture principles](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html#what-is-nnue)

A first educational incremental model can use simple piece-square features; more expressive king-relative features can be studied later. Start with correct full refresh, compare sparse evaluation against it, then add incremental updates. Do not begin by debugging data, quantization, SIMD, and incremental undo simultaneously.

**Important:** training our own model does not remove the fundamental limitations of a one-pass evaluator. Existing NNUE systems also learn from large amounts of searched data. The opportunity is a well-measured learned component that fits *your* engine, not a guarantee that a new network automatically beats those evaluators.

### Model C · A compact convolutional network

A CNN processes the board as a grid and shares pattern detectors across squares. This can help learn local structures, while multiple layers communicate over longer distances. Global state features can be injected through extra inputs or heads.

A proposed comparison is a modest CNN with a few residual blocks, tested against the small dense baseline. Its parameter count alone does not determine CPU latency; many grid operations can cost more than a sparse incremental evaluator.

This may be useful for root/upper-level ranking or a later distillation teacher. It is not my default recommendation for every node of your current CPU alpha–beta search.

### Model D · Transformer or GPU-centered engine

Transformers and large GPU evaluators are legitimate research directions. They introduce different latency, batching, and search-design tradeoffs. ChessBench's large-model research is evidence for that route, not a reason our first project needs hundreds of millions of parameters.

| Candidate | Main attraction | Main concern for Mr. Bits |
|---|---|---|
| Small dense value model | Simple baseline, scalar output, easy inspection | Dense work at every call may still be too expensive |
| Sparse incremental value model | Fits reversible board updates and CPU inference | Feature/accumulator/quantization correctness |
| Small CNN | Spatial inductive bias | Batch-one latency and long-range/tactical limitations |
| Larger transformer/CNN | Greater capacity, useful GPU batches | Training cost, runtime latency, and search redesign |

The 96 GB training GPU should not choose the runtime model for us. Its capacity makes experimentation easier; the final model is constrained by **decision quality and inference cost inside the engine**.

### Two promising extensions after the baseline

**Residual evaluation:** let a network learn a correction to an existing, correctly calibrated material/PST evaluation. This is an optional experiment, not necessarily better than learning the full target. The base terms must be correct first.

**Scalar action value:** use `(position, candidate move)` as input and output a score, preserving your preference against a best-move output. A shared board representation may reduce repeated work across candidates. We should compare it with the simpler child-position evaluator rather than assume it is better.

<a id="training"></a>

## 8. 🏋️ Training objectives and practical settings

### First objective: approximate consistent teacher scores

For the centipawn dataset:

```text
target_pawns = cp_white / 100
prediction   = model(board_features)
error        = prediction - target_pawns
```

A proposed first loss is **Huber regression**. Near the target it penalizes squared error; for large errors it grows more gently, reducing the influence of a few enormous labels.

We can compare unclipped targets with a documented range such as **±15 pawns** for ordinary-score regression. That cutoff is a tunable proposal. Clipping deliberately loses information about the ordering of very large advantages, so do not present a clipped model as measuring arbitrary winning margins accurately.

Mate remains separately typed. Exact terminal results override approximate predictions in the engine.

### Lower average error is not the entire objective

Suppose a model is excellent on easy winning positions but frequently reverses the best two defenses in a difficult middlegame. Its average loss can look good while the engine loses more games.

Later, add **sibling ranking**: learn the relative order of legal children from the same parent. Turn White-perspective scores into mover-utility scores:

```text
U(parent, move) = V_white(child)     for a White parent
U(parent, move) = -V_white(child)    for a Black parent
```

If a teacher reliably prefers candidate A over B, penalize the student for ranking B higher. A pairwise logistic ranking loss is one option. Ignore or down-weight near ties and teacher disagreements; there is little value in learning a noisy 0.01-pawn order with great confidence.

Our experimental objective could become:

```text
total loss = value loss + λ × sibling-ranking loss
```

Start with value loss alone, then sweep a few ranking weights. The “right λ” is not known in advance, and a lower combined training loss is not proof of stronger play.

### Probability and outcome heads are optional

A second head can predict a documented score transform or WDL. That may stabilize very large advantage targets or allow game outcomes to contribute. Keep each target's semantics separate and record how losses are mixed.

Do not train a generic probability label and later pretend an arbitrary inverse sigmoid is a universally correct centipawn conversion. ChessBench's particular conversion can be inverted for its own target, with endpoint protection; it does not make other datasets share that scale.

### A proposed first training configuration

| Item | Initial experiment | Why it is provisional |
|---|---|---|
| Framework | PyTorch in a tested GPU image | Versions and custom kernels must support the actual hardware |
| Model | Core 782→256→64→1 | A debug/reference model, not a strength claim |
| Optimizer | AdamW | A practical starting optimizer |
| Learning rate | Start around `3e-4`, compare neighboring values | Training stability and validation determine the choice |
| Batch size | Begin around 4,096 and benchmark | Bigger batches are not automatically more effective |
| Loss | Huber on normalized White scores | Compare outlier policy and per-phase errors |
| Data scale | About 1–5 million cleaned examples after a small smoke run | First prove the pipeline and generalization |
| Training length | A few passes with checkpoints | Select on validation, not a fixed promise about epochs |
| Numerical precision | Establish a full-precision reference, then benchmark supported mixed precision | Numerical parity and actual speed matter |
| Random seeds | More than one for promising configurations | Avoid choosing a lucky training run |

These settings are an executable hypothesis to refine, not a recipe guaranteed to produce a strong engine.

### What to record at every checkpoint

Save weights, optimizer state, preprocessing version, dataset manifest, split definition, seed, training step, loss configuration, and validation metrics. Store the board orientation and output convention with the model. “model_final_v7.bin” without those details is not a reproducible result.

Inspect validation loss by score bucket, phase, tactical status, and side to move. If training loss improves while unseen-position behavior degrades, investigate overfitting, duplicate leakage, label conflicts, or distribution shift before adding more GPU hours.

### Scale only after a useful pilot

```text
hundreds/thousands of records  → prove parsing, labels, signs, and one training step
around 100,000 clean records   → debug learning and Python/C++ parity
1–5 million records           → establish a general baseline
20–50 million records         → test a scaling hypothesis
100 million and beyond        → only if held-out results justify the cost
```

The stages are proposals. Data diversity and label quality can matter more than another order of magnitude of highly repetitive positions.

<a id="specialists"></a>

## 9. 🧠🧠🧠 One network or four phase specialists?

Your opening/middlegame/endgame/general idea is worth testing. It should be tested **against** one well-trained general model so we can distinguish a useful specialization from extra complexity.

### Three experiments, in a useful order

| Experiment | Structure | What we learn |
|---|---|---|
| **G · General** | One model trained across phases | Establishes a reference and data pipeline |
| **H · Shared heads** | One feature trunk plus general/opening/middle/end heads | Tests specialization without relearning all features four times |
| **I · Independent specialists** | Four separate models with a selector/blender | Tests whether independent capacity pays for extra training/calibration |

```text
                               ┌── general score head
board + state → shared features ├── opening score head
                               ├── middlegame score head
                               └── endgame score head
                                          │
                                 phase-aware selection/blend
                                          │
                                          ▼
                                 one comparable score
```

Stockfish's documented use of shared feature processing with piece-count-selected subnetworks provides a precedent for specialization without four fully independent networks. Our four-head design and its gate are proposals, not a copy of that exact architecture. [NNUE multiple subnetworks](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html#multiple-subnetworks)

### “Opening” and “endgame” need better definitions than move numbers

A proposed material phase uses weight 4 per queen, 2 per rook, and 1 per bishop or knight across both colors. Initial total: 24. A normalized, clipped material fraction can describe how much non-pawn material remains.

That can help distinguish many endgames, but it cannot distinguish an opening from a middlegame with no exchanges. An opening gate could also consider development and king/rook state. Use features actually available at runtime; the four-field evaluation FEN does not supply a trustworthy game move number.

Test transition positions. Trading queens can change the selected head in one move. If the heads have different scales or biases, the search can mistake a model handoff for a chess improvement.

### How I would train the specialists

1. Train and freeze a general reference model.
2. Train a shared model with a general head and phase heads, using the same target convention.
3. Use overlapping phase supervision or a trained blend around boundaries.
4. Compare per-phase held-out errors, sibling ranking, latency, and engine matches.
5. Try independent specialists only if there is evidence that the shared approach lacks useful capacity.

Independent models do **not** require four forward passes every time if we select only one. Their costs are additional training, storage, calibration, and gate behavior. Evaluating all four as an ensemble is a different, more expensive experiment.

The general model is also a useful fallback. A phase gate should not force us to trust a poorly validated specialist merely because a material threshold was crossed.

<a id="search"></a>

## 10. 🌲 Your top-five idea: benefits, risks, and a better progression

### Why the idea is attractive

Reducing branching factor can produce enormous savings in an idealized tree. That is why spending some computation on better ordering or selectivity can pay off.

But a reduced tree is only useful if it retains the moves and defenses that affect the decision. A neural evaluator is a predictor of those values, not a proof about discarded branches.

### A sixth-ranked sacrifice is permanently lost

The following is an invented illustration, not a measured model result:

| Candidate | Predicted immediate child value | What deeper chess might reveal |
|---|---:|---|
| A | +0.50 | Comfortable but equal |
| B | +0.40 | Equal |
| C | +0.35 | Equal |
| D | +0.20 | Slightly worse |
| E | +0.10 | Equal |
| F | −2.00 | A sacrifice leading to forced mate |

If F is permanently deleted, searching A–E to depth 20 cannot discover F's win. For the opponent, a low-ranked quiet defense can be equally important. A model trained on searched targets may recognize some sacrifices directly; it will not recognize all of them.

This is the main reason I would separate **ordering**, **reduction**, and **pruning**:

| Mechanism | What happens to a low-ranked legal move? | Consequence |
|---|---|---|
| Ordering | Searched later | Still available to the search |
| Reduction | Initially searched less deeply | Can be re-searched if it appears promising |
| Permanent pruning | Never searched | A mistaken exclusion cannot be repaired by later depth |

With an otherwise correct complete fixed-depth alpha–beta baseline, ordering alone preserves the minimax result for that evaluated tree. Under a time limit, ordering can change which iteration completes and which result is returned. That is precisely where practical benefit must be measured.

### The integration progression I recommend

```text
0. SHADOW             record scores; search decision logic unchanged
       │
1. ORDER              prioritize candidates; retain legal alternatives
       │
2. LEAF EVALUATION    compare learned evaluation inside unchanged search
       │
3. VERIFIED REDUCE    lower-ranked quiet moves get less depth first
       │                 └── re-search if they improve the relevant bound
       │
4. EXPERIMENTAL PRUNE only after error, latency, and match evidence
```

Shadow mode helps detect score-sign bugs and disagreement cases before the scores influence search decisions. Collecting these predictions through offline replay is useful: live prediction/logging overhead can change completed depth and results under a clock, even when decision logic is unchanged. Account for that overhead explicitly. Ordering measures whether the scores produce earlier useful cutoffs. Learned leaf evaluation is a separate ablation: it changes evaluation quality even if ordering is unchanged.

Verified reductions are a later search experiment. Modern Stockfish performs quiescence at the normal depth boundary and re-searches promising reduced moves; its source provides a useful design precedent. Its tuned rules and constants should not be copied into this engine without understanding their assumptions. [Stockfish search implementation](https://github.com/official-stockfish/Stockfish/blob/master/src/search.cpp)

### First guardrails for selective experiments

Initially, do not use learned permanent pruning at the root or on the principal variation. Keep legal evasions when in check, forced moves, promotions, and important tactical candidates available. Treat checks and captures conservatively and retain correct quiescence behavior.

Those protections reduce risk; they do not make arbitrary learned pruning correct. A quiet move can still be the only defense. A losing-looking move can still be the best practical resource.

### “Best five” can be a diagnostic before it becomes a policy

Measure what happens if the teacher's preferred move has to appear in the model's first 1, 3, 5, or 10 candidates. Also measure whether *any near-optimal* move survives; a harmless tie should not count as a tactical disaster.

Then inspect the misses. If the failures are mostly forced defenses, endgames, or sacrifices, the next action may be better data or a different deployment—not a larger fixed K everywhere.

A later **adaptive candidate set** could retain at least several candidates, all protected tactical moves, and additional moves close to the predicted best. Low-confidence positions would retain more. The score gaps and confidence thresholds would be selected on held-out search positions and tested in matches. No fixed “0.5 pawn gap” is universally safe.

### Neural work must save more than it costs

Scoring every child before searching any child adds generation, make/unmake, feature, and inference work. It can also evaluate candidates that an early alpha–beta cutoff would have made unnecessary.

For an illustrative node with 35 children and **hypothetical** two-microsecond evaluation calls, scoring them all costs 70 microseconds before search. These numbers are not a benchmark. They show why batch-one latency and staged move picking matter.

One practical experiment is to use a richer ranker only near the root or at larger remaining depth, with a cheaper ordering mechanism deeper down. Another is to cache evaluations by position. Both need measured hit rates, correct rule context, and bounded memory.

Do not label a depth increase as a strength increase until tactics and equal-time games support that conclusion.

<a id="trust"></a>

## 11. 🎚️ Building a measurable “trust factor”

Your intuition is useful: the search should not rely on a model equally in every situation. We need to turn that intuition into something testable.

### Three different things people call confidence

| Quantity | Meaning | What it does **not** establish |
|---|---|---|
| Evaluation magnitude | The model predicts a large advantage | That the prediction or move ordering is correct |
| Win/draw/loss estimate | Predicted outcome distribution under a particular target | Probability that the model itself is accurate |
| Error/retention estimate | Observed reliability on similar held-out cases | A mathematical guarantee for a new search position |

A large gap between the top two predictions can be wrong with great confidence. Different models can share the same blind spot. We should not interpret a sigmoid output of 0.99 as permission to prune 99% of moves.

### A proposed calibration study

On an unseen dataset with complete sibling labels, create buckets by:

- Phase and material.
- Quiet versus tactically unstable position.
- Predicted gap between retained and excluded candidates.
- Search depth/context where the model will be used.
- Agreement of independently trained models, if that experiment is affordable.

For each bucket record best/near-best move retention, value regret, and serious tactical misses. Use that evidence to select an ordering or reduction policy. Leave a separate test split untouched while choosing the policy.

```text
predicted scores + position context
                 │
                 ▼
       measured reliability bucket
                 │
        ┌────────┼─────────┐
        ▼        ▼         ▼
      unclear   moderate   strong held-out evidence
        │        │         │
   retain more  order      consider a verified reduction
                normally  with protected alternatives
```

Do not call the right-hand branch “safe pruning.” Its evidence can weaken when the engine starts visiting a different distribution of positions.

### Why very high recall is still not a guarantee

Suppose, only as an illustration, that a necessary move survives a filter with probability 0.99 at each of 20 relevant decisions, independently. Joint survival would be `0.99^20 ≈ 81.8%`. Real chess errors are correlated, so this is not a performance forecast. It demonstrates why an attractive single-step average can conceal sequence-level risk.

A small tactical failure rate can dominate match results if those failures lose a king or a queen. Report the tail failures separately from average error.

### Optional trust experiments after the baseline

**Ensembles:** train different seeds or architectures and compare their predictions. Disagreement can suggest caution, but agreement is not proof. Evaluate the extra inference cost.

**An error head:** train another output to estimate a teacher-relative error statistic. Validate its calibration on new positions; it can underestimate unfamiliar tactical cases.

**Score blending:** compare `λ × learned_score + (1−λ) × handcrafted_score` after putting both on a comparable scale. Treat λ as a validation-selected policy. Blending a correct model with a buggy or mis-scaled evaluator does not protect correctness.

None of these is needed for the first model. A deterministic general baseline plus conservative ordering is the clearer first experiment.

<a id="deployment"></a>

## 12. 🔧 Training on the GPU, playing inside C++

### Two workloads, two different machines if we want

```text
TRAINING LAB                                PLAYING ENGINE

compact dataset shards                      board + legal state
         │                                         │
CPU decode / batch preparation                     ▼
         │                                  C++ feature encoder
         ▼                                         │
GPU forward + loss + backward                       ▼
         │                                  loaded model weights
         ▼                                         │
trained checkpoint                                 ▼
         │                                  one evaluation score
         ▼                                         │
validate + export ─────── weights + metadata ───────► search
```

Training on an NVIDIA GPU does not require running every chess evaluation on a GPU afterward. Stockfish itself uses CPU evaluation and GPU-based network training; its normal search is not accelerated merely by renting a GPU. [Stockfish CPU/GPU explanation](https://official-stockfish.github.io/docs/stockfish-wiki/Stockfish-FAQ.html#can-stockfish-use-my-gpu)

For your current style of CPU alpha–beta search, load weights once and evaluate in the same C++ process. A Python launch, temporary file exchange, or remote request per node would be an expensive boundary.

### GPU inference is a different search experiment

GPUs can process batches efficiently, but a depth-first search often wants one answer before deciding its next step. Moving small requests to a GPU adds transfers, scheduling, and waiting. A root-only batch or a redesigned batching search may be useful; it should be compared with a compact CPU evaluator at equal total decision time.

Do not assume a GPU's high training throughput implies good single-node inference latency.

### The export contract

The model artifact should identify:

| Field | Why it matters |
|---|---|
| Architecture and dimensions | C++ must interpret tensor shapes correctly |
| Feature version and square order | A flipped board can still produce plausible-looking wrong scores |
| Side and castling/EP conventions | Correct behavior depends on them |
| Output perspective, scale, and clipping policy | Search comparisons must mean the same thing as training |
| Tensor types/layout | Float and quantized weights are not interchangeable |
| Model/data/checkpoint identifiers | Reproduce and compare results |
| Integrity checksum | Detect an incomplete or wrong artifact |

First compare Python and C++ full-precision outputs on a fixed set including both colors, checks, EP, promotions, castling, and endgames. A proposed initial numerical target is a small documented tolerance, such as `1e-4` pawn-like units for the dense float32 reference, adjusted if numerical accumulation order requires it. That is a test criterion to examine, not a promised precision result.

### Optimize one layer of difficulty at a time

1. Correct ordinary forward evaluation.
2. Correct sparse first-layer summation.
3. Correct incremental updates and full refresh equivalence.
4. Correct make/unmake restoration across nested search.
5. Quantization with explicit overflow/range checks.
6. SIMD and code-layout tuning if profiling justifies them.

Quantized accumulators may need wider types than the stored weights. Use measured ranges and mathematical bounds; do not choose `int8_t` everywhere simply because it is small. Compare quantized outputs and move-ranking changes with the float reference, then run engine tests.

### Where this fits the current kernel

Share immutable model weights, but keep mutable position features and accumulators private to each worker. Your process isolation already separates the kernel globals; an eventual thread pool needs explicit ownership.

Keep a last-completed search result and legal fallback, regardless of model behavior. If an export version is incompatible or evaluation produces a non-finite result, use a controlled fallback and diagnostic path rather than returning an invalid move.

These are proposed interfaces and validation steps. This paper does not insert an AI-written neural implementation into your original engine; you can build the implementation yourself while using the research and review process to examine its behavior.

<a id="budget"></a>

## 13. 💻 Hardware, time, and a few-hundred-dollar budget

### Your proposed GPU is a capable training platform

Nebius documents an RTX PRO 6000 Blackwell Server Edition platform with **96 GB GDDR7**. Its single-GPU preset includes **24 vCPUs and 218 GiB host RAM**. Catalog availability includes `us-central1` and the separately named platform in `uk-south2` / `eu-south1`; actual quota and live capacity in your account were not checked. [Nebius GPU/platform catalog](https://docs.nebius.com/compute/virtual-machines/types)

For the small models proposed here, memory capacity is generous. The likely challenges are clean labels, input throughput, experiment design, and eventual CPU inference cost. We should not inflate the network just to occupy the GPU.

### Check actual software compatibility before a long job

NVIDIA identifies this GPU as compute capability **12.0**, distinct from other Blackwell GPU families. A custom extension compiled for a different target is not automatically compatible. [NVIDIA capability table](https://developer.nvidia.com/cuda/gpus)

PyTorch 2.7 introduced Blackwell support and CUDA 12.8 wheels; that is historical evidence of support, **not a recommendation to pin an old release today**. Use a currently tested image and record its digest, driver, CUDA, framework, and any extension revisions. [PyTorch's Blackwell-support announcement](https://pytorch.org/blog/pytorch-2-7/)

Our first cloud check should run GPU forward/backward computation, save/reload a checkpoint, and export a model that matches the CPU reference. Detecting compatibility or data-loader issues during a tiny pilot is much cheaper than discovering them after reserving a large run.

### Published pricing snapshot

As checked on **22 October 2026**, Nebius lists RTX PRO 6000 at **$1.80 per GPU-hour on demand** and dynamic preemptible pricing **from $0.79**. The minimum spot price is not guaranteed during a run. Prices exclude applicable tax; stopped VMs stop compute charges, while persistent storage remains chargeable. Use your actual selected configuration's total quoted rate when planning. [Nebius pricing](https://docs.nebius.com/compute/resources/pricing)

### Training-time arithmetic: measure the missing variable

```text
training examples processed = selected positions × passes

training hours ≈ examples processed / measured examples per second / 3600
compute dollars ≈ measured hours × actual hourly rate
```

Suppose we select 50 million positions and train for five passes: **250 million examples processed**.

| Hypothetical measured throughput | Arithmetic training time | Arithmetic GPU charge at $1.80/h |
|---:|---:|---:|
| 1,000 examples/s | 69.44 hours | $125.00 |
| 10,000 examples/s | 6.94 hours | $12.50 |

**These are sensitivity examples, not speed predictions for the RTX PRO 6000.** Actual time includes preprocessing, validation, checkpointing, compilation, and I/O. The number of passes required is also an experimental outcome.

A small model can be input-bound. Measure end-to-end throughput with real batches from the intended data format; a synthetic all-in-GPU benchmark can conceal the real bottleneck.

### Teacher labeling is a separate CPU workload

```text
labeling hours ≈ labels needed × measured seconds per label
                 / effective concurrent workers / 3600
```

Illustration: one million labels at 0.2 seconds each, spread effectively across 16 independent workers, is about **3.47 hours** before overhead. At two seconds each it is **34.72 hours**. Neither figure is a promised Stockfish throughput.

If “one million examples” means one million *parents with 35 children each*, that is 35 million labels. The first example becomes about **121.5 hours**. This is why complete sibling labeling should start with a focused benchmark and why existing action-value data is valuable.

A GPU does not automatically speed up normal Stockfish search. Use the GPU for training and select a sensible CPU resource for new Stockfish labels. Benchmark 1,000–10,000 representative positions before extrapolating, including difficult middlegames and endgames.

### A proposed $300 experiment envelope

| Purpose | Example ceiling |
|---|---:|
| GPU pilots and comparisons, up to 100 hours at the listed on-demand GPU rate | $180 |
| CPU preparation and targeted labels | $60 |
| Storage/data movement reserve | $30 |
| Contingency | $30 |
| **Total planning envelope** | **$300** |

This is a proposed allocation, not a quote for a completed strong model. Storage rates, regional configuration, tax, credits, and actual runtime can change the bill. Credits are useful, but idle compute still consumes resources.

The first milestone should use only a small fraction of the envelope: confirm data semantics, one learning run, and C++ inference parity. Keep frequent resumable checkpoints if using preemptible capacity. Stop compute when it is no longer needed and keep track of retained volumes.

### Where money has the highest value initially

My preference is: **free public labels → careful preparation → modest model comparisons → targeted hard-case teacher searches → controlled engine testing**.

Buying another large collection of unlabeled games would not address the current bottleneck. Paying for a better-labeled, independently validated hard-case set might become worthwhile after the first model tells us what it lacks.

<a id="evaluation"></a>

## 14. 🧪 How we will decide whether it works

“Very good” needs a measurable definition. For this project, the model is useful when it improves the complete engine's decision quality under the same time limit while meeting the intended runtime budget.

### Four levels of evaluation

| Level | Questions | Measurements |
|---|---|---|
| **1 · Data and numerical correctness** | Are state, labels, signs, and runtime outputs consistent? | Parser audits, duplicate/leak checks, Python/C++ parity, incremental/full refresh parity |
| **2 · Position understanding** | Does it generalize beyond training examples? | MAE/Huber error by phase, score bucket, color, and tactical status |
| **3 · Search usefulness** | Does it prioritize the moves that matter? | Best/near-best recall@K, value regret, tactical misses, cutoffs, latency |
| **4 · Playing strength** | Does the full engine make better decisions under a clock? | Paired engine matches, multiple openings/colors, uncertainty, deadline failures |

### Metrics for your actual top-five question

**Best-move recall@5:** fraction of test parents whose teacher-best move appears in the student's top five.

**Near-best recall@5:** fraction retaining any move within a chosen teacher-score tolerance of best. Define the tolerance before examining the final test; exact ties and several mating moves deserve sensible handling.

**Value regret:** teacher best mover-utility minus teacher mover-utility of the student's chosen candidate. It measures loss relative to that teacher, not exact game-theoretic loss.

**Catastrophic exclusions:** separately count missed mating moves, sole defenses, queen-losing decisions, and important endgame resources. Averages should not hide them.

Only evaluate these metrics where the reference has adequate legal-action coverage. Missing labels for the move the model selected are not proof that it selected a bad move.

### A diagnostic test collection

Include quiet positional choices, recaptures, sacrifices, forced defenses, double check, discovered attacks, EP tactics, underpromotion, stalemate traps, zugzwang, and promotion races. Include both sides to move and phase transitions.

Use public puzzles carefully: keep the actual test positions and transformed relatives out of training, and acknowledge remaining source-overlap uncertainty when complete original game grouping is unavailable. A famous benchmark that leaked into training does not establish generalization.

### Runtime measurement must include the neural overhead

Measure:

- CPU single-position inference, including feature work.
- Sibling batches where applicable.
- Position generation and make/unmake overhead.
- Search nodes, cutoff behavior, completed depth, and total decision time.
- Memory and worker scaling.
- Missed deadlines and fallback use.

A lower node count can simply mean more work per node. A deeper reported search can simply mean more aggressive exclusions. Both need end-to-end interpretation.

### Keep the ablations small and interpretable

| Version | Change from corrected reference |
|---|---|
| B0 | Handcrafted evaluation, existing validated ordering |
| N1 | General model scores in shadow mode |
| N2 | Neural ordering only; all legal alternatives retained |
| N3 | Learned leaf evaluation only, with the same search/quiescence rules |
| N4 | Best validated ordering/evaluation combination |
| N5 | Add calibrated, verified reductions |
| H/I | Compare phase-head or independent-specialist models against the same winning integration |

Run multiple seeds for promising training configurations. Use paired openings with colors reversed and equal wall-clock limits. Record version, hardware, worker count, and all failed/time-forfeit games. Do not announce an Elo gain based on a few attractive wins.

Statistical testing can support larger experiments once the pipeline is stable. The Stockfish testing framework documents paired outcome models and sequential methods; adopting controlled comparisons does not require building its distributed infrastructure. [Fishtest statistical methods](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html)

### Go / no-go decisions

| Evidence | Decision |
|---|---|
| Labels or viewpoints disagree | Fix data/interface; do not scale training |
| Validation looks good but runtime is too slow | Reduce model cost or change where it is called |
| Average error improves but tactical exclusions worsen | Improve coverage/integration; do not promote pruning |
| General model beats a specialist on its own phase | Keep the general model until the specialist earns its cost |
| Equal-time games show no reliable benefit | Retain the result as an experiment; do not claim improvement |
| Correctness, latency, tactics, and match evidence support a change | Promote it with recorded limits and a reproducible model |

<a id="roadmap"></a>

## 15. 🚀 The project sequence and final recommendation

### A sequence with concrete deliverables

| Stage | Deliverable | Exit criterion |
|---|---|---|
| **A · Define the contract** | Input schema, output perspective, target types, supported rules, first source | We can explain every field and score without ambiguity |
| **B · Prove data correctness** | Small parsed set, audit report, dedup/split policy | Signs, PV selection, mates, legal state, and metadata pass checks |
| **C · Train a general baseline** | Checkpoint, manifest, validation report | The model learns unseen positions beyond a trivial baseline |
| **D · Integrate without selectivity** | C++ forward path, parity checks, shadow and ordering modes | Correct outputs and measured affordable latency |
| **E · Measure engine benefit** | Tactical suite, ablations, paired matches | Evidence supports a useful role under equal time |
| **F · Test specialists** | General vs shared-head vs independent comparison | Phase gains survive calibration, latency, and match tests |
| **G · Study selective search** | Calibrated reductions and hard-case data loop | Added selectivity earns its risk through independent tests |
| **H · Publish the research story** | Model card, dataset recipe, limitations, reproducibility guide | Another engineer can reproduce the experiment and distinguish custom work from dependencies |

These stages can overlap with the engine repairs in the previous report. Serious strength testing depends on a legal, reliable search; data and training exploration can begin earlier without pretending that it has already improved the engine.

### My recommended route for us

1. **Begin with the free, nested Lichess evaluations** and build a small, clean scalar dataset.
2. **Train one general White-perspective value model** with an explicit target contract.
3. **Use ChessBench as a second reference and a ranking-data route**, keeping its probability transform and viewpoint separate.
4. **Load the model directly into C++ and measure it**, first in shadow mode and then for ordering.
5. **Compare shared phase heads with the general model**, rather than committing to four independent networks before a baseline exists.
6. **Invest new labeling effort in misses and complete sibling sets**, then study verified reductions.

### The research contribution can be yours even when data is public

Using published teacher labels does not make your feature encoding, model comparisons, inference implementation, search integration, or experiments less meaningful. Credit dataset creators and tools, retain the applicable notices, and describe assistance honestly.

The strongest portfolio artifact would be a reproducible investigation: what you tried, how the scores were defined, where the model failed, how inference cost changed the search, and what the engine matches actually showed.

You do not need to imitate a huge research lab's full training scale to make this valuable. A compact, understandable model that measurably improves your engine would be an excellent result. If a model fails, explaining *why* and testing a better hypothesis is also substantive engineering.

### My answer to the biggest questions, bro ❤️

**Where does `y` come from?** From already searched public evaluations—primarily Lichess and ChessBench—or from targeted new teacher analysis where coverage is missing.

**Can the output be a score rather than a move?** Yes. That is exactly the state-value design proposed here.

**Will it match a strong engine's deep search everywhere?** No. We are approximating that judgment, and tactics remain a reason to keep search.

**Can we train on the 96 GB Blackwell GPU?** It is a capable platform, subject to a compatible image and measured pipeline. Its size does not guarantee model quality or a particular completion time.

**Should we train four networks?** Start with one, then compare shared phase heads and independent specialists. Keep the design that earns its complexity.

**Should we immediately trust only five moves?** Measure that behavior first. Use ordering and verified reductions before permanent learned exclusions.

**Will the engine be stronger?** That is the hypothesis the project should test. The ingredients are available, the scalar-model idea is valid, and there is a practical way to investigate it without buying a huge dataset or repeating years of labeling computation.

**My strongest recommendation:** build a small, auditable student of searched evaluations, keep the legal search as its partner, and let equal-time evidence decide how much authority the network earns.

<a id="references"></a>

## 16. 📖 Glossary and source guide

### Chess-learning vocabulary

| Term | Meaning here |
|---|---|
| **FEN** | Text encoding of a chess position; full FEN has counters that some exports omit |
| **Centipawn, cp** | One hundredth of a pawn-like evaluation unit under a specified convention |
| **PV** | Principal variation: an engine's suggested continuation |
| **MultiPV** | Several candidate continuations with scores; not necessarily every legal move |
| **State value, V** | Evaluation assigned to a position under a specified target |
| **Action value, Q** | Evaluation conditional on a particular move from a position |
| **WDL** | Win/draw/loss targets or predictions; distinct from confidence that the model is correct |
| **Quiescence** | Search extending unstable leaf positions through suitable tactical continuations |
| **NNUE** | An efficiently updatable network family suited to sparse, incrementally changing inputs |
| **Head** | A task- or phase-specific output layer/path sharing earlier features |
| **Distillation** | Learning to approximate an expensive teacher with a cheaper student |
| **Calibration** | Checking whether reported reliability or probability matches held-out behavior |
| **Recall@K** | How often a desired move is among K retained candidates |
| **Regret** | Quality difference between the reference best choice and the selected choice |
| **Ablation** | A controlled comparison isolating one component or change |
| **Distribution shift** | Runtime positions differ from the data used to train or calibrate |
| **Quantization** | Using lower-precision representations to reduce inference/storage cost |
| **Data leakage** | Training or model selection uses information that should be reserved for evaluation |

### Primary sources to begin with

These links also appear beside the relevant claims. Read them as original specifications and research, not as guarantees about the proposed Mr. Bits model.

| Topic | Source |
|---|---|
| Ready-made centipawn labels | [Lichess evaluated-position export](https://database.lichess.org/#evals) |
| Flattened schema and row count | [Official Lichess Hugging Face card](https://huggingface.co/datasets/Lichess/chess-position-evaluations/raw/main/README.md) |
| White-perspective serialization | [Lichess JSON implementation](https://raw.githubusercontent.com/lichess-org/lila/master/modules/evalCache/src/main/JsonView.scala) |
| State/action-value research | [ChessBench paper](https://arxiv.org/html/2402.04494v2) |
| Downloads, readers, and release terms | [ChessBench project](https://github.com/google-deepmind/searchless_chess) |
| Binary NNUE training data | [Official Stockfish collection](https://huggingface.co/datasets/official-stockfish/master-binpacks/tree/main) |
| Incremental neural evaluation | [Stockfish NNUE technical guide](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html) |
| Evaluation versus search commands | [Stockfish command guide](https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html) |
| GPU configuration | [Nebius platform catalog](https://docs.nebius.com/compute/virtual-machines/types) |
| Current cost reference | [Nebius pricing](https://docs.nebius.com/compute/resources/pricing) |

Counts, prices, file sizes, and repository details are a **22 October 2026 research snapshot** and can change. The model architecture, preparation rules, training settings, trust policy, budgets, and rollout are proposals to test. No pretrained result is being claimed for Mr. Bits by this paper.

---

♟️ **The next concrete milestone:** a small dataset whose labels we trust, one compact baseline we understand, and a complete path from Python training to a verified C++ score. That foundation gives the ambitious experiments somewhere solid to grow.
