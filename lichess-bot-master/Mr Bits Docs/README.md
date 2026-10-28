# Mr. Bits documentation

**Start here: [choose a Kernel and open the live database viewer](START_HERE_KERNELS_AND_DASHBOARD.md).**

- [ChatGPT Docs](ChatGPT%20Docs/): engineering review and neural-network research.
- [ChatGPT Neural Network Lab](ChatGPT%20Neural%20Network%20Lab/README.md): training tools, data, results, and experiments.
- [Trained networks and C++ guide](ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md): inputs, architectures, measured results, and native inference.
- [IPC and game database plan](IPC%20and%20Game%20Database%20Plan/README%20-%20Start%20Here.md): engine communication and game-recording work.
- [Claude Docs](Claude%20Docs/): existing documents, moved without opening their contents.

The exported C++ evaluators live in [`../engines/Neural Networks/`](../engines/Neural%20Networks/README.md).
The short [neural evaluation and sorting complexity guide](../engines/Neural%20Networks/TIME_COMPLEXITY_README.md) explains the exact bounds for Small and Large.
The [Kernel experiment versions](../engines/Kernels/README.md) now include v1 through v4 with distinct ordering, pruning and leaf-evaluation policies.

## Inspect the game database

Double-click `Launch Dashboard.bat` in `lichess-bot-master` to open **http://127.0.0.1:8765/**. The read-only visual portal shows recorded games, moves, search metrics and version comparisons with five-second refresh. [Dashboard instructions](../database/dashboard/README.md).

The local file is [`../database/mrbits.sqlite`](../database/mrbits.sqlite). Existing CLI inspection remains available:

```powershell
python database\db.py --check
python database\db.py --recent 40
```

Full replay and finished outcomes require both sides' stored moves/results from the existing Lichess sync. Missing records stay empty; the viewer does not invent them.
