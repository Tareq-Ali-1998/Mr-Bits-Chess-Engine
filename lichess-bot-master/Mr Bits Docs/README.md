# Mr. Bits documentation

**Start here: [choose a Kernel and open the live database viewer](START_HERE_KERNELS_AND_DASHBOARD.md).**

- [ChatGPT Docs](ChatGPT%20Docs/): engineering review and neural-network research.
- [ChatGPT Neural Network Lab](ChatGPT%20Neural%20Network%20Lab/README.md): training tools, data, results, and experiments.
- [Trained networks and C++ guide](ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md): inputs, architectures, measured results, and native inference.
- [IPC and game database plan](IPC%20and%20Game%20Database%20Plan/README%20-%20Start%20Here.md): engine communication and game-recording work.
- [Claude Docs](Claude%20Docs/): existing documents, moved without opening their contents.

The exported C++ evaluators live in [`../engines/Neural Networks/`](../engines/Neural%20Networks/README.md).
The short [neural evaluation and sorting complexity guide](../engines/Neural%20Networks/TIME_COMPLEXITY_README.md) explains the exact bounds for Small and Large.
The [Kernel experiment versions](../engines/Kernels/README.md) now include v1 through v11 with distinct ordering, pruning and leaf-evaluation policies. Read the [short v5/v6 guide](../engines/Kernels/V5_V6_README.md) for the full-width and late-move-reduction pair.

The newer [v7 guide](../engines/Kernels/v7/README.md) covers independent legal generation, mate/stalemate, bounded quiescence, and improved iteration admission. Its original-copy source remains separate from all earlier versions.

Read the new guides in this order: [How V7 works — five illustrated parts](../engines/Kernels/v7/HOW_V7_WORKS.md), [Small/Large operation counts and sorting cost](../engines/Neural%20Networks/OPERATION_COUNTS.md), then [V8 — pure Small static evaluation](../engines/Kernels/v8/README.md).

Next experiments: [V9 — Large top-three with original scoring](../engines/Kernels/v9/README.md), [V10 — Large top-three with blended scoring](../engines/Kernels/v10/README.md), and [V11 — PVS plus exact static-value caching](../engines/Kernels/v11/README.md). Their short illustrated guides explain the policy, costs, and limitations.

## Inspect the game database

Double-click `Launch Dashboard.bat` in `lichess-bot-master` to open **http://127.0.0.1:8765/**. The read-only visual portal shows recorded games, moves, search metrics and version comparisons with five-second refresh. [Dashboard instructions](../database/dashboard/README.md).

The local file is [`../database/mrbits.sqlite`](../database/mrbits.sqlite). Existing CLI inspection remains available:

```powershell
python database\db.py --check
python database\db.py --recent 40
```

Full replay and finished outcomes require both sides' stored moves/results from the existing Lichess sync. Missing records stay empty; the viewer does not invent them.
