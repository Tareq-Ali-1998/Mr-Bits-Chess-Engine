# v1.0 - the original Large/top-four experiment

**Version identity:** this policy was previously called `v1`. Its code is preserved as an experiment within the legacy-search/handcrafted-leaf family. [Complete family map](../VERSION_FAMILIES.md).

This is the user-authored move-ordering and pruning experiment from which the later ordering policies were compared. It retains the existing compact moves, incremental state updates, classical leaf score, pseudo-legal generator and worker protocol.

| Location | Active policy |
|---|---|
| Ordinary internal node, remaining depth greater than two | Large scores/orders the candidates, then retain at most four |
| Root iteration depth two | Existing simple heuristic; retain assigned candidates |
| Root iteration depth four or greater | Existing heuristic, then Large ordering; retain at most four |
| Ordinary leaf | Existing handcrafted score |

Root retention applies per worker subset. The neural helper itself only sorts; this version's search code performs the later deletion. A discarded candidate can contain a better tactical continuation, and greater nominal depth does not prove stronger play.

Related commented experiments remain in this historical source. Read the active statements rather than treating every commented alternative as executed behavior. The [v1.1 ordering-only baseline](../v1.1/README.md) retains candidates; [v1.2](../v1.2/README.md) tests a gentler root-only quiet-move allowance.

After stopping an existing bot, choose **`v1.0`** in `Launch Server.bat`. The launcher currently requires both local neural exports for this legacy family, though this version's active sorting path uses Large. The main custom-engine baseline remains separately available as **`original`**.

Source: [Kernel-v1.0.cpp](Kernel-v1.0.cpp). This naming migration makes no playing-strength claim and changes no search policy.
