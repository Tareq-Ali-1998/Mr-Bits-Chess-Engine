// Offline diagnostics: include a worker with its main renamed; never start it.
#ifdef NDEBUG
#error Compile diagnostics without -DNDEBUG.
#endif
#define main mrbits_v56_worker_main_not_called_by_this_test
#ifdef MRBITS_TEST_V6
#include "../Kernels/v2.2/Kernel-v2.2.cpp"
#else
#include "../Kernels/v2.1/Kernel-v2.1.cpp"
#endif
#undef main

namespace {
namespace policy = mrbits::neural_search;
int checks = 0;
void Check(bool okay, const string& message) {
    ++checks;
    if (!okay) throw runtime_error(message);
}
int16_t Move(int sr, int sc, int dr, int dc, int type = 0) {
    return static_cast<int16_t>(sr | sc << 3 | dr << 6 | dc << 9 | type << 12);
}
void Budget(int milliseconds = INT_MAX) {
    processHandler.setAllowedTimeInMilliSeconds(milliseconds);
    processHandler.setAllProcessStartTime();
}
struct Snapshot {
    mrbits::kernel_neural::ParentPosition position;
    vector<int16_t> history = previousMoves;
    bool engineWhite = ENGINE_COLOR;
    mt19937 random = rng;
    void unchanged(const string& label) const {
        Check(memcmp(position.cells, board, sizeof(board)) == 0, label + ": board changed");
        Check(memcmp(position.move_counts, numberOfMovesOfThePieceOnThisSquare,
                     sizeof(numberOfMovesOfThePieceOnThisSquare)) == 0, label + ": counters changed");
        Check(position.white == whitePieces && position.black == blackPieces, label + ": occupancy changed");
        Check(position.engine_score == engineScore && position.opponent_score == opponentScore,
              label + ": evaluation state changed");
        Check(history == previousMoves && engineWhite == ENGINE_COLOR && random == rng,
              label + ": history/color/random changed");
    }
};
vector<int16_t> BoardScanMoves(bool turn, int16_t previousMove) {
    vector<int16_t> moves;
    const bool white = turn == ENGINE_COLOR;
    for (int row = 0; row < 8; ++row) for (int column = 0; column < 8; ++column) {
        const int piece = board[row][column] & 15;
        if (piece && static_cast<bool>(piece & 8) == white) {
            const auto next = GetMovesForThisPiece(board[row][column], row, column, previousMove);
            moves.insert(moves.end(), next.begin(), next.end());
        }
    }
    return moves;
}
// Independent exhaustive minimax: scan all squares, no ordering, alpha/beta,
// reductions or production UndoMove. It shares the existing generator/evaluator
// deliberately, so it validates the new search under the inherited rules.
int Reference(int depth, bool turn, int16_t previousMove) {
    const int score = engineScore - opponentScore;
    if (abs(score) > CHECKMATE_FLAG_SCORE_DIFFERENCE) return score;
    if (depth == 0) return policy::EvaluateLeaf(turn, previousMove);
    const auto moves = BoardScanMoves(turn, previousMove);
    if (moves.empty()) return 0;
    int best = turn ? INT_MIN : INT_MAX;
    for (const int16_t move : moves) {
        const mrbits::kernel_neural::ParentPosition restore;
        MakeChanges(move);
        const int next = Reference(depth - 1, !turn, move);
        restore.restore();
        best = turn ? max(best, next) : min(best, next);
    }
    return best;
}
void NoLoadChecks() {
    _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", "Z:/mrbits-v56-deliberately-absent-weights");
    for (bool engineWhite : {false, true}) for (bool turn : {false, true}) {
        for (int sign : {-1, 1}) for (int depth : {0, 6}) {
            ResetGameState(engineWhite); Budget();
            engineScore = sign > 0 ? 10000001 : 0;
            opponentScore = sign < 0 ? 10000001 : 0;
            Check(Magic(depth, turn, 0, INT_MIN, INT_MAX) == sign * 10000001,
                  "terminal did not bypass neural evaluation");
            Check(MagicForIterativeDeepening(depth, turn, 0, INT_MIN, INT_MAX) == sign * 10000001,
                  "iterative terminal did not bypass neural evaluation");
        }
    }
    ResetGameState(true); Budget();
    auto moves = GetAllPossibleMoves();
    for (size_t count : {size_t(0), size_t(1)}) {
        vector<int16_t> subset(moves.begin(), moves.begin() + count), before = subset;
        policy::OrderMoves(6, subset);
        Check(before == subset, "empty/singleton loaded model or changed order");
    }
    const Snapshot before;
    auto expected = moves;
    SortTheMovesWithMySimpleHeuristic(expected);
    policy::OrderMoves(2, moves);
    Check(moves == expected, "near-leaf heuristic ordering failed");
    Budget(0); policy::OrderMoves(6, moves);
    Check(moves == expected && !policy::CanUseNeuralOrdering(moves.size()), "expired ordering fallback failed");
    Check(Magic(4, true, 0, INT_MIN, INT_MAX) == 0, "expired search did not abort");
    before.unchanged("expired and no-load operations");
    Budget(4);
    Check(!policy::CanUseNeuralOrdering(20), "minimum reserve not applied");
    Budget();
    Check(policy::CanUseNeuralOrdering(20) && !policy::CanUseNeuralOrdering(1), "fixed-depth ordering admission");
    for (bool root : {false, true}) {
        ResetGameState(true); Budget(); const Snapshot exceptionBefore;
        bool threw = false;
        try {
            if (root) {
                auto roots = GetAllPossibleMoves();
                (void)GetBestMoveWithItsScore(2, true, roots);
            } else {
                (void)Magic(1, true, 0, INT_MIN, INT_MAX);
            }
        } catch (const runtime_error&) { threw = true; }
        Check(threw, "missing weights did not propagate");
        exceptionBefore.unchanged(root ? "root exception rollback" : "internal exception rollback");
    }
}
void FlagsBlendAndGates() {
    for (bool engineWhite : {false, true}) for (bool turn : {false, true}) {
        ResetGameState(engineWhite); Budget();
        const auto state = policy::LeafState(turn, 0);
        Check(state.white_to_move == (turn == engineWhite) && state.castling == 15 && state.ep_file == -1,
              "initial leaf state flags");
        const Snapshot before;
        const float white = EvaluatePositionWithSmallNeuralNetwork(board, state);
        const int expected = policy::BlendLeafScores(engineScore - opponentScore, white, engineWhite, 50, 50);
        Check(policy::EvaluateLeaf(turn, 0) == expected, "leaf blend/sign");
        Check(Magic(0, turn, 0, INT_MIN, INT_MAX) == expected, "actual leaf result");
        before.unchanged("real leaf");
    }
    Check(policy::BlendLeafScores(200, 3, true, 50, 50) == 250, "White blend");
    Check(policy::BlendLeafScores(200, 3, false, 50, 50) == -50, "Black blend");
    Check(policy::BlendLeafScores(200, 3, true, 1, 1) == 250, "normalized blend");
    Check(policy::BlendLeafScores(0, numeric_limits<float>::max(), true, 0, 1) == 99999, "nonterminal clamp");
    for (float bad : {numeric_limits<float>::quiet_NaN(), numeric_limits<float>::infinity()}) {
        bool threw = false;
        try { (void)policy::BlendLeafScores(0, bad, true, 1, 1); }
        catch (const runtime_error&) { threw = true; }
        Check(threw, "non-finite score accepted");
    }
    for (auto weights : {pair<double,double>{0,0}, {-1,1}, {1,-1}, {numeric_limits<double>::infinity(),1}}) {
        bool threw = false;
        try { (void)policy::BlendLeafScores(0, 0, true, weights.first, weights.second); }
        catch (const invalid_argument&) { threw = true; }
        Check(threw, "invalid blend weights accepted");
    }
    ResetGameState(true); MakeChanges(Move(6,4,4,4)); previousMoves = {Move(1,0,3,0)};
    Check(policy::LeafState(false, Move(6,4,4,4)).ep_file == 4, "branch EP ignored");
    Check(policy::LeafState(true, Move(6,4,4,4)).ep_file == -1, "wrong-color EP accepted");
    Check(policy::LeafState(false, Move(6,4,4,4,1)).ep_file == -1, "special tag EP accepted");
    ENGINE_COLOR = false;
    Check(policy::LeafState(true, Move(6,4,4,4)).ep_file == 4, "Black-engine branch EP");
    ResetGameState(true); MakeChanges(Move(1,4,3,4));
    Check(policy::LeafState(true, Move(1,4,3,4)).ep_file == 4, "Black double-push EP");
    ResetGameState(true);
    numberOfMovesOfThePieceOnThisSquare[7][7] = 1;
    Check(policy::LeafState(true, 0).castling == 14, "rook-moved castling mask");
    numberOfMovesOfThePieceOnThisSquare[7][4] = 1;
    Check(policy::LeafState(true, 0).castling == 12, "king-moved castling mask");
    ResetGameState(true);
    const auto quiet = Move(7,1,5,2);
    Check(policy::ShouldReduce(4,4,quiet,false,false), "eligible quiet rejected");
    Check(!policy::ShouldReduce(3,4,quiet,false,false), "shallow reduction");
    Check(!policy::ShouldReduce(4,3,quiet,false,false), "first-four reduction");
    Check(!policy::ShouldReduce(4,4,quiet,true,false), "check evasion reduced");
    Check(!policy::ShouldReduce(4,4,quiet,false,true), "checking move reduced");
    for (int tag : {1,2,3,4,5,6,7}) {
        Check(!policy::ShouldReduce(6,8,Move(7,1,5,2,tag),false,false), "special move reduced");
    }
    board[5][2] = 3;
    Check(!policy::ShouldReduce(6,8,quiet,false,false), "capture reduced");
    board[5][2] = 0;
    board[3][0] = 9;
    Check(!policy::ShouldReduce(6,8,Move(3,0,2,0),false,false), "advanced White pawn reduced");
    board[4][0] = 1;
    Check(!policy::ShouldReduce(6,8,Move(4,0,5,0),false,false), "advanced Black pawn reduced");
    for (int probe : {-100,0,100}) {
        Check(policy::NeedsFullDepthResearch(true,probe,0,1000) == (probe > 0), "max research strict alpha");
        Check(policy::NeedsFullDepthResearch(false,probe,-1000,0) == (probe < 0), "min research strict beta");
    }
    Check(policy::NeedsFullDepthResearch(true, INT_MIN+1, INT_MIN, INT_MAX), "INT_MIN comparison");
    Check(!policy::NeedsFullDepthResearch(true, INT_MIN, INT_MIN, INT_MAX), "equal INT_MIN comparison");
    Check(policy::NeedsFullDepthResearch(false, INT_MAX-1, INT_MIN, INT_MAX), "INT_MAX comparison");
    Check(!policy::NeedsFullDepthResearch(false, INT_MAX, INT_MIN, INT_MAX), "equal INT_MAX comparison");
    ResetGameState(true);
    Check(!policy::KingNeedsProtection(true) && !policy::KingNeedsProtection(false), "starting king guard");
    board[7][4] = 0;
    Check(policy::KingNeedsProtection(true), "missing king guard");
    board[7][4] = 15; board[4][4] = 15;
    Check(policy::KingNeedsProtection(true), "duplicate king guard");
    for (bool white : {false,true}) {
        const int ownKing = white ? 15 : 7, enemy = white ? 0 : 8;
        auto clear = [&] {
            memset(board,0,sizeof(board));
            board[4][4]=ownKing;
            board[white ? 0 : 7][0]=7|enemy;
        };
        clear(); board[2][3]=3|enemy;
        Check(policy::KingNeedsProtection(white), "knight attack guard");
        clear(); board[4][0]=5|enemy;
        Check(policy::KingNeedsProtection(white), "rook attack guard");
        board[4][2]=1|(white ? 8 : 0);
        Check(!policy::KingNeedsProtection(white), "rook ray blocker guard");
        clear(); board[2][2]=4|enemy;
        Check(policy::KingNeedsProtection(white), "bishop attack guard");
        clear(); board[4][7]=6|enemy;
        Check(policy::KingNeedsProtection(white), "queen attack guard");
        clear(); board[white ? 3 : 5][3]=1|enemy;
        Check(policy::KingNeedsProtection(white), "pawn attack direction guard");
        clear(); board[white ? 0 : 7][0]=0; board[3][3]=7|enemy;
        Check(policy::KingNeedsProtection(white), "adjacent enemy king guard");
    }
}
void SpecialMoveRollbackChecks() {
    auto empty = [](bool engineWhite) {
        ResetGameState(engineWhite);
        memset(board,0,sizeof(board));
        memset(numberOfMovesOfThePieceOnThisSquare,0,sizeof(numberOfMovesOfThePieceOnThisSquare));
        board[7][4]=15; board[0][4]=7;
    };
    auto finish = [] {
        whitePieces=blackPieces=0;
        for (int row=0; row<8; ++row) for (int column=0; column<8; ++column) {
            if (!board[row][column]) continue;
            const auto bit=static_cast<long long>(1ULL << getBitNumberFromItsRowAndColumn[row][column]);
            if (board[row][column]&8) whitePieces |= bit;
            else blackPieces |= bit;
        }
        InitializeEngineScore(); InitializeOpponentScore();
    };
    auto roundTrip = [&](int16_t move, const string& name) {
        finish();
        const Snapshot before;
        { const policy::UndoMove restore(move); }
        before.unchanged(name+" normal undo");
        bool threw=false;
        try { const policy::UndoMove restore(move); throw runtime_error("test unwind"); }
        catch (const runtime_error&) { threw=true; }
        Check(threw,name+" throw fixture");
        before.unchanged(name+" exception undo");
    };
    for (bool white : {false,true}) for (bool engineWhite : {false,true}) {
        const int row=white ? 7 : 0, color=white ? 8 : 0;
        for (int tag : {4,5}) {
            empty(engineWhite); board[row][tag==4 ? 7 : 0]=5|color;
            roundTrip(Move(row,4,row,tag==4 ? 6 : 2,tag),"castling");
        }
        empty(engineWhite);
        const int sr=white ? 3 : 4, dr=white ? 2 : 5;
        board[sr][4]=1|color; board[sr][3]=1|(white ? 0 : 8);
        numberOfMovesOfThePieceOnThisSquare[sr][4]=3;
        numberOfMovesOfThePieceOnThisSquare[sr][3]=1;
        roundTrip(Move(sr,4,dr,3,3),"en passant");
        for (int tag : {1,2,6,7}) for (bool capture : {false,true}) {
            empty(engineWhite);
            const int from=white ? 1 : 6, to=white ? 0 : 7, destinationColumn=capture ? 2 : 1;
            board[from][1]=1|color; numberOfMovesOfThePieceOnThisSquare[from][1]=4;
            if (capture) {
                board[to][destinationColumn]=5|(white ? 0 : 8);
                numberOfMovesOfThePieceOnThisSquare[to][destinationColumn]=3;
            }
            roundTrip(Move(from,1,to,destinationColumn,tag),"promotion");
        }
    }
    empty(true);
    board[0][4]=5; board[0][0]=7; board[6][4]=13;
    finish();
    Check(!policy::KingNeedsProtection(true),"pinned-rook fixture starts protected");
    const Snapshot before;
    {
        const policy::UndoMove restore(Move(6,4,6,0));
        Check(policy::KingNeedsProtection(true),"own-king exposure guard missed opened rook ray");
    }
    before.unchanged("king-exposing quiet");
}
void RealSearchChecks(Json& report) {
    Json references = Json::array();
    for (bool engineWhite : {false, true}) for (bool turn : {false, true}) {
        ResetGameState(engineWhite); Budget();
        const Snapshot before;
        const auto reference = Reference(2,turn,0);
        before.unchanged("exhaustive reference");
        policy::ResetStats();
        const auto actual = policy::Search(2,turn,0,INT_MIN,INT_MAX,{false});
        Check(actual == reference, "full-width alpha-beta differs from exhaustive minimax");
        Check(policy::stats.lmrProbes == 0, "disabled LMR executed");
        const auto wrapped = Magic(2,turn,0,INT_MIN,INT_MAX);
        Check(wrapped == reference, "version wrapper shallow score differs");
        Check(MagicForIterativeDeepening(2,turn,0,INT_MIN,INT_MAX) == reference, "iterative wrapper differs");
        before.unchanged("full shallow search");
        references.push_back({{"engineWhite",engineWhite},{"engineToMove",turn},{"depth",2},{"score",actual}});
    }
    report["exhaustive_minimax_comparisons"] = references;
    ResetGameState(true); Budget();
    auto moves = GetAllPossibleMoves(), original = moves, neural = moves;
    SortTheMovesWithSmallNeuralNetwork(neural);
    policy::ResetStats();
    const Snapshot beforeOrder;
    policy::OrderMoves(3,moves);
    Check(moves == neural, "depth3 did not use actual Small ordering");
    auto sortedA=original, sortedB=moves;
    sort(sortedA.begin(),sortedA.end()); sort(sortedB.begin(),sortedB.end());
    Check(sortedA == sortedB, "ordering deleted a candidate");
    Check(policy::stats.smallOrderingCalls == 1, "neural ordering counter");
    beforeOrder.unchanged("neural ordering");
    ResetGameState(true); Budget(); processHandler.setEngineDepth(4);
    vector<string> root;
    const auto rootMoves = GetAllPossibleMoves();
    for (auto move : rootMoves) root.push_back(processHandler.convertMoveFromInt16_tToStandard(move));
    const Snapshot beforeRoot;
    GetBestMoveAndItsScoreToInitializeProcessHandler(root);
    Check(rootMoveScoresOfTheLastSearch.size() == root.size(), "root candidates omitted");
    Check(policy::stats.lmrProbes == 0, "root was reduced at total depth4");
    beforeRoot.unchanged("full-depth root");
    report["root_candidates_searched"] = root.size();
    Json real = Json::array();
    uint64_t probes=0, researches=0;
    for (bool engineWhite : {false,true}) for (bool turn : {false,true}) {
        ResetGameState(engineWhite); Budget(); policy::ResetStats();
        const Snapshot before;
        const int score=policy::Search(4,turn,0,INT_MIN,INT_MAX,{true});
        before.unchanged("actual selective search");
        const auto counters=policy::StatsJson();
        probes += policy::stats.lmrProbes; researches += policy::stats.lmrResearches;
        real.push_back({{"engineWhite",engineWhite},{"engineToMove",turn},{"score",score},{"counters",counters}});
    }
    Check(probes > 0, "real fixtures never exercised LMR");
    Check(researches > 0, "real fixtures never exercised full-depth re-search");
    report["shared_core_lmr_diagnostics_explicit_option_true"] = real;
    ResetGameState(true); Budget(); policy::ResetStats();
    const Snapshot beforeWrapped;
    const int wrappedScore=Magic(4,true,0,INT_MIN,INT_MAX);
#ifdef MRBITS_TEST_V6
    Check(policy::stats.lmrProbes > 0,"production v6 wrapper did not enable reductions");
#else
    Check(policy::stats.lmrProbes == 0,"production v5 wrapper unexpectedly enabled reductions");
#endif
    report["production_search_wrapper"]={{"score",wrappedScore},{"counters",policy::StatsJson()}};
    Check(MagicForIterativeDeepening(4,true,0,INT_MIN,INT_MAX)==wrappedScore,
          "iterative wrapper uses a different selective-search option");
    beforeWrapped.unchanged("production wrapper at active LMR depth");
    ResetGameState(true); Budget(10); policy::ResetStats();
    const Snapshot beforeTimeout;
    (void)policy::Search(10,true,0,INT_MIN,INT_MAX,{true});
    Check(processHandler.processTimeExceeded(), "timed fixture did not reach deadline");
    Check(policy::stats.neuralLeafEvaluations > 0 && policy::stats.deadlineAborts > 0,
          "timeout fixture did not enter/abort active search");
    beforeTimeout.unchanged("in-search deadline rollback");
    // Repeated request metadata must describe completed work, never stale counts.
    ChessState requestState;
    requestState.engineColor=true; requestState.allowedEngineTimeInSeconds=1;
    requestState.movesForThisThread={"e2e4","d2d4"};
    Json request=requestState.serializeObject(); request["maxDepth"]=2;
    const auto completed=AnswerSearchRequest(request);
    Check(completed["status"]=="ok" && completed["searchPolicy"]["scope"]=="last_completed_iteration",
          "completed request policy scope");
    Check(completed["searchPolicy"]["counters"]["neuralLeafEvaluations"].get<int>()>0,
          "completed request leaf counters missing");
    Check(completed["perDepth"][0]["searchPolicy"]==completed["searchPolicy"]["counters"],
          "per-depth and last-completed counters disagree");
    // The inherited fixed-depth API accepts1 but completes no even-depth iteration.
    request["maxDepth"]=1;
    const auto noIteration=AnswerSearchRequest(request);
    Check(noIteration["status"]=="no_completed_depth" && noIteration["searchPolicy"]["counters"].is_null(),
          "no-iteration request retained previous completion counters");
    Check(policy::StatsJson()["neuralLeafEvaluations"]==0,"request reset retained old global stats");
    request["maxDepth"]=0; request["allowedEngineTimeInSeconds"]=0;
    const auto expired=AnswerSearchRequest(request);
    Check(expired["status"]=="no_completed_depth" && expired["searchPolicy"]["counters"].is_null(),
          "aborted request retained completed policy counters");
    Check(expired["perDepth"].size()==1 && expired["perDepth"][0]["completed"]==false,
          "interrupted iteration not recorded separately");
    report["request_policy_metadata_checked"]=true;
}
} // namespace

int main(int argc, char** argv) {
    Json report={{"scope","offline renamed-main diagnostics; no bot, worker main, Stockfish or network"}};
#ifdef MRBITS_TEST_V6
    report["variant"]="v2.2";
#else
    report["variant"]="v2.1";
#endif
    int exitCode=0;
    try {
        if (argc != 2) throw invalid_argument("Expected Neural Networks directory");
        BuildTheTablesOnce();
        NoLoadChecks();
        _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR",argv[1]);
        FlagsBlendAndGates();
        SpecialMoveRollbackChecks();
        RealSearchChecks(report);
        report["passed"]=true;
    } catch (const exception& error) {
        report["passed"]=false; report["error"]=error.what(); exitCode=1;
    }
    report["checks"]=checks;
    cout << report.dump(2) << '\n';
    return exitCode;
}
