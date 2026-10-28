# Mr. Bits documentation

- [ChatGPT Docs](ChatGPT%20Docs/): engineering review and neural-network research.
- [ChatGPT Neural Network Lab](ChatGPT%20Neural%20Network%20Lab/README.md): training tools, data, results, and experiments.
- [Trained networks and C++ guide](ChatGPT%20Neural%20Network%20Lab/docs/TRAINED_NETWORKS_AND_CPP_GUIDE.md): inputs, architectures, measured results, and native inference.
- [IPC and game database plan](IPC%20and%20Game%20Database%20Plan/README%20-%20Start%20Here.md): engine communication and game-recording work.
- [Claude Docs](Claude%20Docs/): existing documents, moved without opening their contents.

The exported C++ evaluators live in [`../engines/Neural Networks/`](../engines/Neural%20Networks/README.md).
The short [neural evaluation and sorting complexity guide](../engines/Neural%20Networks/TIME_COMPLEXITY_README.md) explains the exact bounds for Small and Large.
The [Kernel experiment versions](../engines/Kernels/README.md) contain `v1`, `v2`, and `v3`, initially identical copies with the two neural sorters available but uncalled.

## Inspect the game database

The local file is [`../database/mrbits.sqlite`](../database/mrbits.sqlite). The custom chessboard/dashboard is still planned; there is no game-viewer portal to launch yet.

From a terminal in `lichess-bot-master`:

```powershell
python database\db.py --check
python database\db.py --recent 40
```

The second command lists recent engine moves/events. For visual table inspection, open the SQLite file in [DB Browser for SQLite](https://sqlitebrowser.org/), choose **Browse Data**, then `v_games`, `v_engine_moves`, or `v_moves`. This is a table browser, not a chess replay interface. Games must be recorded or imported before they appear.
