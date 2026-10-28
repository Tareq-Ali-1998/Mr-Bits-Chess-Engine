// Persistent reconstruction of the earlier temporary 84-case v4 harness.
// Uses the actual Small weights and an isolated renamed main, never Stockfish.
#ifdef NDEBUG
#error These diagnostic tests require assertions; compile without -DNDEBUG.
#endif
#define main mrbits_v4_worker_main_not_called_by_this_test
#include "../Kernels/v4/Kernel-v4.cpp"
#undef main

int main(int argc, char** argv) {
    assert(argc == 2);
    BuildTheTablesOnce();
    _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", "Z:/mrbits-absent-neural-weights-for-terminal-test");
    int cases = 0;
    for (bool engineWhite : {false, true}) for (bool turn : {false, true}) {
        for (int sign : {-1, 1}) for (int depth : {0, 6}) {
            ResetGameState(engineWhite);
            processHandler.setAllowedTimeInMilliSeconds(INT_MAX);
            processHandler.setAllProcessStartTime();
            engineScore = sign > 0 ? 10000001 : 0;
            opponentScore = sign < 0 ? 10000001 : 0;
            assert(Magic(depth, turn, 0, INT_MIN, INT_MAX) == sign * 10000001);
            assert(MagicForIterativeDeepening(depth, turn, 0, INT_MIN, INT_MAX) == sign * 10000001);
            cases += 2;
        }
    }
    _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", argv[1]);
    assert(!v4_policy::ShouldOrder(5) && v4_policy::ShouldOrder(6) && !v4_policy::ShouldOrder(0));
    ++cases;
    assert(v4_policy::BlendLeafScores(200, 3.0f, true, 0, 100) == 300);
    assert(v4_policy::BlendLeafScores(200, 3.0f, false, 0, 100) == -300);
    assert(v4_policy::BlendLeafScores(200, 3.0f, true, 100, 0) == 200);
    assert(v4_policy::BlendLeafScores(200, 3.0f, false, 100, 0) == 200);
    assert(v4_policy::BlendLeafScores(200, 3.0f, true, 25, 75) == 275);
    assert(v4_policy::BlendLeafScores(200, 3.0f, true, 1, 3) == 275);
    assert(v4_policy::BlendLeafScores(200, 3.0f, false, 25, 75) == -175);
    assert(v4_policy::BlendLeafScores(0, 0.1256f, true, 0, 100) == 13);
    assert(v4_policy::BlendLeafScores(0, -0.1256f, true, 0, 100) == -13);
    assert(v4_policy::BlendLeafScores(0, numeric_limits<float>::max(), true, 0, 100) == 99999);
    assert(v4_policy::BlendLeafScores(0, -numeric_limits<float>::max(), true, 0, 100) == -99999);
    assert(v4_policy::BlendLeafScores(200, numeric_limits<float>::quiet_NaN(), true, 100, 0) == 200);
    cases += 12;
    for (float value : {numeric_limits<float>::quiet_NaN(), numeric_limits<float>::infinity()}) {
        bool threw = false;
        try { v4_policy::BlendLeafScores(0, value, true, 0, 100); }
        catch (const runtime_error&) { threw = true; }
        assert(threw); ++cases;
    }
    for (auto weights : {pair<double, double>{0, 0}, {-1, 100}, {1, -1},
                          {numeric_limits<double>::infinity(), 1}}) {
        bool threw = false;
        try { v4_policy::BlendLeafScores(0, 0, true, weights.first, weights.second); }
        catch (const invalid_argument&) { threw = true; }
        assert(threw); ++cases;
    }
    for (bool engineWhite : {false, true}) for (bool turn : {false, true}) {
        ResetGameState(engineWhite);
        processHandler.setAllowedTimeInMilliSeconds(INT_MAX);
        processHandler.setAllProcessStartTime();
        engineScore = 999; opponentScore = 111; previousMoves = {123, 456};
        const auto state = v4_policy::LeafState(turn, 0);
        assert(state.white_to_move == (turn == engineWhite));
        assert(state.castling == 15 && state.ep_file == -1);
        const mrbits::kernel_neural::ParentPosition before;
        const auto history = previousMoves; const auto random = rng;
        const auto nodes = processHandler.getTheNumberOfAllTheInnerAndFinalStatesAs64Bit();
        const float white = EvaluatePositionWithSmallNeuralNetwork(board, state);
        const int expected = v4_policy::BlendLeafScores(888, white, engineWhite, 0, 100);
        assert(v4_policy::EvaluateLeaf(turn, 0) == expected);
        assert(memcmp(before.cells, board, sizeof(board)) == 0);
        assert(memcmp(before.move_counts, numberOfMovesOfThePieceOnThisSquare, sizeof(numberOfMovesOfThePieceOnThisSquare)) == 0);
        assert(before.white == whitePieces && before.black == blackPieces);
        assert(before.engine_score == engineScore && before.opponent_score == opponentScore);
        assert(previousMoves == history && rng == random && ENGINE_COLOR == engineWhite);
        assert(processHandler.getTheNumberOfAllTheInnerAndFinalStatesAs64Bit() == nodes);
        assert(Magic(0, turn, 0, INT_MIN, INT_MAX) == expected);
        assert(MagicForIterativeDeepening(0, turn, 0, INT_MIN, INT_MAX) == expected);
        cases += 4;
    }
    auto move = [](int sr, int sc, int dr, int dc, int type = 0) {
        return static_cast<int16_t>(sr | (sc << 3) | (dr << 6) | (dc << 9) | (type << 12));
    };
    ResetGameState(true); MakeChanges(move(6, 4, 4, 4)); previousMoves = {move(1, 0, 3, 0)};
    assert(v4_policy::LeafState(false, move(6, 4, 4, 4)).ep_file == 4);
    assert(!v4_policy::LeafState(false, move(6, 4, 4, 4)).white_to_move);
    assert(v4_policy::LeafState(true, move(6, 4, 4, 4)).ep_file == -1);
    assert(v4_policy::LeafState(false, move(6, 4, 4, 4, 1)).ep_file == -1);
    assert(v4_policy::LeafState(false, 0).ep_file == -1);
    ENGINE_COLOR = false;
    assert(v4_policy::LeafState(true, move(6, 4, 4, 4)).ep_file == 4);
    board[4][4] = 11;
    assert(v4_policy::LeafState(true, move(6, 4, 4, 4)).ep_file == -1);
    cases += 7;
    ResetGameState(true); MakeChanges(move(1, 4, 3, 4));
    assert(v4_policy::LeafState(true, move(1, 4, 3, 4)).ep_file == 4); ++cases;
    ResetGameState(true); MakeChanges(move(6, 4, 5, 4));
    assert(v4_policy::LeafState(false, move(6, 4, 5, 4)).ep_file == -1); ++cases;
    ResetGameState(true); board[6][4] = 0; board[4][3] = 9;
    assert(v4_policy::LeafState(false, move(6, 4, 4, 3)).ep_file == -1); ++cases;
    ResetGameState(true);
    assert(v4_policy::LeafState(true, 0).castling == 15);
    numberOfMovesOfThePieceOnThisSquare[7][7] = 1;
    assert(v4_policy::LeafState(true, 0).castling == 14);
    numberOfMovesOfThePieceOnThisSquare[7][4] = 1;
    assert(v4_policy::LeafState(true, 0).castling == 12);
    numberOfMovesOfThePieceOnThisSquare[0][4] = 1;
    assert(v4_policy::LeafState(true, 0).castling == 0);
    ResetGameState(true); board[0][7] = 12;
    assert(v4_policy::LeafState(true, 0).castling == 11); cases += 5;
    ResetGameState(true);
    auto moves = GetAllPossibleMoves(); const auto original = moves;
    const mrbits::kernel_neural::ParentPosition beforeSort;
    const auto history = previousMoves; const auto random = rng;
    SortTheMovesWithSmallNeuralNetwork(moves);
    auto sortedA = original, sortedB = moves;
    sort(sortedA.begin(), sortedA.end()); sort(sortedB.begin(), sortedB.end());
    assert(sortedA == sortedB);
    assert(memcmp(beforeSort.cells, board, sizeof(board)) == 0);
    assert(memcmp(beforeSort.move_counts, numberOfMovesOfThePieceOnThisSquare, sizeof(numberOfMovesOfThePieceOnThisSquare)) == 0);
    assert(beforeSort.white == whitePieces && beforeSort.black == blackPieces);
    assert(beforeSort.engine_score == engineScore && beforeSort.opponent_score == opponentScore);
    assert(previousMoves == history && rng == random); ++cases;
    ResetGameState(true);
    processHandler.setAllowedTimeInMilliSeconds(INT_MAX); processHandler.setAllProcessStartTime();
    processHandler.setEngineDepth(2);
    vector<string> root; const auto originalRoot = GetAllPossibleMoves();
    for (auto encoded : originalRoot) root.push_back(processHandler.convertMoveFromInt16_tToStandard(encoded));
    GetBestMoveAndItsScoreToInitializeProcessHandler(root);
    assert(rootMoveScoresOfTheLastSearch.size() == root.size());
    for (size_t i = 0; i < originalRoot.size(); ++i) assert(rootMoveScoresOfTheLastSearch[i].move == originalRoot[i]);
    ++cases;
    cout << "PASS " << cases << " diagnostics; terminal priority, real Small leaves, color, flags, blends, thresholds, state restoration, all "
         << root.size() << " starting root moves retained in generator order.\n";
    return 0;
}
