# 📦 From Lichess JSON to a trustworthy training release

**23 October 2026 · implemented behavior, not just a proposed pipeline**

## One raw line is not one already-clean target

The archive is Zstandard-compressed JSONL. Decompression produces one JSON object per line. Each object contains a FEN and several saved analyses; an analysis can contain several principal variations, or PVs. A PV is a candidate continuation. The official format uses `knodes` for thousands of searched nodes and UCI_Chess960 move notation. [Publisher's format](https://database.lichess.org/#evals)

```json
{
  "fen": "7r/1p3k2/p1bPR3/5p2/2B2P1p/8/PP4P1/3K4 b - -",
  "evals": [
    {
      "depth": 46,
      "knodes": 4189972,
      "pvs": [{"cp": 69, "line": "f7g7 ..."}]
    }
  ]
}
```

The example is abbreviated: `...` is not a legal move token and is not accepted by the parser. We never train on the future line as input. We replay it only to check that the saved continuation is legal.

The score is **White's perspective**. This example becomes `y = +0.69` pawns even though Black is to move. The first PV is the teacher's preferred candidate for that side; do not maximize White scores blindly when selecting a Black move. [Lichess score convention](https://raw.githubusercontent.com/lichess-org/api/master/doc/specs/schemas/CloudEval.yaml)

## The implemented path

```text
compressed bytes
      │  streamed decompression; no giant unpacked file
      ▼
bounded chunks of JSON lines
      │  parallel CPU validation workers
      ▼
accepted candidate records + rejection reasons
      │  SQLite index on disk
      ▼
unique visible inputs with selected labels
      │  deterministic selection over the scanned pool
      ▼
approximately 90/5/5 independent position-hash split
      │
      ├── train.npy
      ├── validation.npy
      ├── test.npy
      └── manifest.json + preparation_progress.json
```

The original file is opened read-only. The output directory must be empty/new; the tool refuses to overwrite another dataset. On interruption/failure it writes `failure.json` with counts. A partial output is not a release. Preparation currently restarts into a new directory; it does not resume a compressed scan halfway through.

## Selection and rejection, in order

1. Parse a JSON object with a four-field FEN.
2. Construct and validate an orthodox board. Reject terminal parents.
3. Require valid integer depth/node metadata for saved analyses.
4. Select the maximum `(depth, knodes)` analysis, then its first PV.
5. Reject selected depth outside 20–80 or search below 1,000 knodes.
6. Reject mate labels, invalid cp values, and `|cp| > 1,500`.
7. Require a nonempty selected PV and legally replay its full line.
8. Encode the original parent board, derive its key, and deduplicate.

We do not search for whichever older analysis happens to pass a threshold after the selected best analysis fails. Replacing a selected mate result with an older finite score would create a misleading target.

These thresholds are conservative working choices. Depth is selective, not exhaustive ply coverage. High node counts do not prove a correct evaluation. A structurally valid board is not proof of historical reachability, and a legal continuation is not proof it is best. We preserve the policy and its consequences so a later controlled teacher audit can improve it.

### What happens to duplicates?

The key is a 128-bit hash of the **actual compact input**. Clocks/history are absent, so two FENs that differ only in unsupported counters have the same visible-state key. Different retained castling or EP state changes the key.

Within the scanned pool, duplicate records compete on `(depth, knodes)`; stronger metadata replaces a previous candidate. Equal-evidence duplicates retain the first label. Conflicting scores are counted in the audit. A detected key collision with different packed bytes aborts preparation.

There are no augmented samples in this version. If we later add symmetry augmentation or ranking pairs, their related states must be grouped/purged before splitting to prevent leakage.

### What does `--sampling reservoir` mean here?

The implementation uses **deterministic bottom-hash selection**, rather than holding a conventional random reservoir in memory:

1. Scan up to `--max-records` raw records; zero means the whole archive.
2. Deduplicate accepted inputs in SQLite.
3. Sort unique keys by their hash value and retain up to `--max-positions`.

This gives an approximately uniform hash-selected subset of the **scanned accepted pool**, assuming the cryptographic hash behaves uniformly. It does not make a short source prefix representative of the whole archive. The separate split hash avoids using the selection priority as a train/test bucket.

`--sampling prefix` instead stops when the requested unique count is reached. It is useful for quick checks and explicitly recorded as prefix sampling. Parallel read-ahead can inspect/hash some extra lines without processing them; the manifest states that boundary. Neither mode silently claims a full-archive checksum.

### Split stability and its limits

Each key is hashed independently with a split seed. Buckets allocate about 90% training, 5% validation, and 5% test. Actual counts vary. The same position and seed always produce the same split, including when the scanned pool changes.

Changing the seed creates a different experiment. Do not merge a previously held-out position into training and then reuse its old metric as independent evidence. Nearby but nonidentical positions can remain correlated; the archive does not supply complete game provenance for grouping every record.

The complete-legal-child benchmark builder checks additional parent/child overlap against forbidden prepared splits. This strengthens a move-ranking evaluation, but still does not establish independence from all near-duplicate games or positions elsewhere on the internet.

## Exact prepared record layout

Each split is one memory-mapped NumPy structured array, loaded with `allow_pickle=False`:

| Field | Type / shape | Bytes |
|---|---|---:|
| `position` | `uint8[78]` | 78 |
| `cp` | little-endian `int32` | 4 |
| `depth` | little-endian `uint16` | 2 |
| `knodes` | little-endian `uint64` | 8 |
| `key` | `uint8[16]` | 16 |
| **Total per row** | Unaligned packed dtype | **108** |

The compact position contains 64 piece codes in a8→h1 order, followed by turn, four retained castling flags, and nine EP choices. Code 0 is empty; White `P,N,B,R,Q,K` are 1–6, Black are 7–12. Input expansion converts these to the frozen 782-feature network input.

Labels remain raw White cp on disk. The training loss converts to pawns. Depth, node count, key, and PV are not model inputs.

## Reproducibility and integrity

The manifest records quality thresholds, feature schema, split seed, source size/name, scanned-content digest, audit counts, split coverage, file sizes and SHA-256 checksums, and a release fingerprint. Creation time and measured runtime are excluded from the stable fingerprint.

The fingerprint identifies the prepared release; it does not prove an external teacher is infallible. Ordinary dataset loading recomputes the metadata fingerprint and checks schema/dtype/count. To verify all data file checksums explicitly:

```bash
.venv/bin/python -c "from chesslab.data import verify_dataset; print(verify_dataset('data/local-100k')['fingerprint'])"
```

The trainer saves the manifest and fingerprint in its run. Resume and ordinary held-out evaluation reject a mismatched data release. Save the configuration, data fingerprint, checkpoint, and evaluation report together.

## Where should we prepare data?

Use the CPU machine that already has the archive and enough local storage. The existing bundled pilot took a short bounded local scan, so the first GPU session can start from prepared files.

For millions of positions, a CPU server near the storage can be convenient. Renting a GPU does not accelerate Python chess legality checks by itself. If you do prepare on the GPU host, include that idle-GPU interval in the bill.

The temporary SQLite index contains **all accepted unique positions in the scanned pool**, not just the selected final sample. Its disk footprint can be much larger than the final 108-byte records. Preparation deletes its own index after a successful release unless `--keep-index` is set. It never recursively deletes a source folder.

Inspect coverage after every preparation run. Aggressive filters can improve apparent cleanliness while removing difficult tactics or important endgames. This first release deliberately excludes mates and decisive cp tails; its metrics therefore describe that supported finite-cp distribution, not all of chess.
