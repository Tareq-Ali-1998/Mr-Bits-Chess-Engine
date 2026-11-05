# Mr. Bits documentation

**Start here: [choose a Kernel and open the live database viewer](START_HERE_KERNELS_AND_DASHBOARD.md).**

- [ChatGPT Docs](ChatGPT%20Docs/): engineering review and neural-network research.
- [ChatGPT Neural Network Lab](ChatGPT%20Neural%20Network%20Lab/README.md): training tools, data, results, and experiments.
- [Trained networks and C++ guide](ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md): inputs, architectures, measured results, and native inference.
- [IPC and game database plan](IPC%20and%20Game%20Database%20Plan/README%20-%20Start%20Here.md): engine communication and game-recording work.
- [Claude Docs](Claude%20Docs/): existing documents, moved without opening their contents.

The exported C++ evaluators live in [`../engines/Neural Networks/`](../engines/Neural%20Networks/README.md).
The short [neural evaluation and sorting complexity guide](../engines/Neural%20Networks/TIME_COMPLEXITY_README.md) explains the exact bounds for Small and Large.
The [Kernel families](../engines/Kernels/README.md) organize the experiments into legacy handcrafted leaves (v1.0.x), legacy neural leaves (v1.1.x), and legal/quiescence search (v1.2.x). The [version map](../engines/Kernels/VERSION_FAMILIES.md) records every previous label and its current name. Read the [short v2.1/v2.2 guide](../engines/Kernels/V5_V6_README.md) for the full-width and late-move-reduction pair.

The newer [v3.0 guide](../engines/Kernels/v3.0/README.md) covers independent legal generation, mate/stalemate, bounded quiescence, and improved iteration admission. Its original-copy source remains separate from all earlier versions.

Read the new guides in this order: [How V3.0 works — five illustrated parts](../engines/Kernels/v3.0/HOW_V3_0_WORKS.md), [Small/Large operation counts and sorting cost](../engines/Neural%20Networks/OPERATION_COUNTS.md), then [V3.1 — pure Small static evaluation](../engines/Kernels/v3.1/README.md).

Start the scoring comparison with [v3.1: 100% Small](../engines/Kernels/v3.1/README.md), [v3.2: 100% handcrafted](../engines/Kernels/v3.2/README.md), [v3.3: 80% Small / 20% handcrafted](../engines/Kernels/v3.3/README.md), and [v3.4: 20% Small / 80% handcrafted](../engines/Kernels/v3.4/README.md). All retain v3.0's search behavior. The pure-Small v3.1 was reused, so v3.5 is intentionally absent.

Next experiments: [V3.6 — Large top-three with original scoring](../engines/Kernels/v3.6/README.md), [V3.7 — Large top-three with blended scoring](../engines/Kernels/v3.7/README.md), and [V3.8 — PVS plus exact static-value caching](../engines/Kernels/v3.8/README.md). Their short illustrated guides explain the policy, costs, and limitations.

[V3.9 — Small top-ten above depth two](../engines/Kernels/v3.9/README.md) keeps V3.0's scoring and legal/tactical foundation while testing a narrower ordinary tree. At depth two or less, including quiescence, it performs no move sorting. The temporary old v7 folder has been retired; select v3.0 for that same baseline. The proposed search-table design, previously called V13, waits for a worker-memory discussion before implementation.

The [V13 memory proposal](V13_MEMORY_PLAN.md) accounts for all 28 workers together and distinguishes fixed allocations from an estimated RAM allowance. V13 remains a design to discuss, not an implemented kernel.

## Inspect the game database

Double-click `Launch Dashboard.bat` in `lichess-bot-master` to open **http://127.0.0.1:8765/**. The read-only visual portal shows recorded games, moves, search metrics and version comparisons with five-second refresh. [Dashboard instructions](../database/dashboard/README.md).

The local file is [`../database/mrbits.sqlite`](../database/mrbits.sqlite). Existing CLI inspection remains available:

```powershell
python database\db.py --check
python database\db.py --recent 40
```

Full replay and finished outcomes require both sides' stored moves/results from the existing Lichess sync. Missing records stay empty; the viewer does not invent them.
