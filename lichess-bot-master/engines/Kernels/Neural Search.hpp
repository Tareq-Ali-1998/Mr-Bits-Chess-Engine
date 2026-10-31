#pragma once

// Shared only by v5/v6. Include after the original Kernel state, move helpers,
// and public Small/Large evaluator wrappers. Existing versions do not use this.
namespace mrbits::neural_search {

constexpr int small_ordering_min_depth = 3;
constexpr long long minimum_ordering_reserve_ms = 5;
constexpr long long moves_per_reserve_ms = 8;
constexpr int lmr_min_depth = 4;
constexpr size_t unreduced_first_moves = 4;
constexpr double legacy_evaluation_weight = 50.0;
constexpr double small_neural_evaluation_weight = 50.0;
constexpr int non_terminal_score_limit = CHECKMATE_FLAG_SCORE_DIFFERENCE - 1;

struct Options {
    bool late_move_reductions = false;
};

struct Stats {
    uint64_t smallOrderingCalls = 0;
    uint64_t heuristicOrderingCalls = 0;
    uint64_t neuralLeafEvaluations = 0;
    uint64_t lmrProbes = 0;
    uint64_t lmrResearches = 0;
    uint64_t deadlineAborts = 0;
};

inline Stats stats;

inline void ResetStats() noexcept { stats = {}; }

inline Json StatsJson() {
    return {{"smallOrderingCalls", stats.smallOrderingCalls},
            {"heuristicOrderingCalls", stats.heuristicOrderingCalls},
            {"neuralLeafEvaluations", stats.neuralLeafEvaluations},
            {"lmrProbes", stats.lmrProbes},
            {"lmrResearches", stats.lmrResearches},
            {"deadlineAborts", stats.deadlineAborts}};
}

// Preserve the original incremental make/undo flow, including on exceptions.
// This stores changed-state information, not a full board copy at every node.
class UndoMove {
    int16_t move_;
    int8_t captured_;
    int16_t captured_move_count_;
    long long white_, black_;
    int engine_score_, opponent_score_;
public:
    explicit UndoMove(const int16_t move) noexcept
        : move_(move),
          captured_(board[(static_cast<uint16_t>(move) >> 6) & 7]
                         [(static_cast<uint16_t>(move) >> 9) & 7]),
          captured_move_count_(numberOfMovesOfThePieceOnThisSquare[(static_cast<uint16_t>(move) >> 6) & 7]
                                                                  [(static_cast<uint16_t>(move) >> 9) & 7]),
          white_(whitePieces), black_(blackPieces),
          engine_score_(engineScore), opponent_score_(opponentScore) {
        MakeChanges(move_);
    }
    UndoMove(const UndoMove&) = delete;
    UndoMove& operator=(const UndoMove&) = delete;
    ~UndoMove() noexcept {
        whitePieces = white_; blackPieces = black_;
        engineScore = engine_score_; opponentScore = opponent_score_;
        ReturnChanges(move_, captured_, captured_move_count_);
    }
};

inline mrbits::nn::State LeafState(const bool turn, const int16_t previousMove) noexcept {
    const bool whiteToMove = turn == ENGINE_COLOR;
    mrbits::nn::State state{whiteToMove, kernel_neural::CastlingRights(), -1};
    const auto move = static_cast<uint16_t>(previousMove);
    const int sr = move & 7, sc = (move >> 3) & 7;
    const int dr = (move >> 6) & 7, dc = (move >> 9) & 7;
    const bool previousWhite = !whiteToMove;
    const int previousPawn = 1 | (previousWhite ? 8 : 0);
    if (((move >> 12) & 15) == 0 && sc == dc &&
        (board[dr][dc] & 15) == previousPawn &&
        ((previousWhite && sr == 6 && dr == 4) || (!previousWhite && sr == 1 && dr == 3))) {
        state.ep_file = static_cast<int8_t>(dc);
    }
    return state;
}

inline int BlendLeafScores(const int legacyEngineCp, const float neuralWhitePawns,
                          const bool engineWhite, const double legacyWeight,
                          const double neuralWeight) {
    const double total = legacyWeight + neuralWeight;
    if (!std::isfinite(legacyWeight) || !std::isfinite(neuralWeight) ||
        legacyWeight < 0 || neuralWeight < 0 || !std::isfinite(total) || total <= 0) {
        throw std::invalid_argument("Leaf weights must be finite, nonnegative, and have a positive sum");
    }
    if (neuralWeight > 0 && !std::isfinite(neuralWhitePawns)) {
        throw std::runtime_error("Small neural evaluation produced a non-finite leaf score");
    }
    const double neuralEngineCp = neuralWeight > 0
        ? static_cast<double>(neuralWhitePawns) * 100.0 * (engineWhite ? 1.0 : -1.0) : 0.0;
    const double value = (legacyWeight / total) * legacyEngineCp +
                         (neuralWeight / total) * neuralEngineCp;
    return static_cast<int>(std::lround(std::clamp(value,
        -static_cast<double>(non_terminal_score_limit),
         static_cast<double>(non_terminal_score_limit))));
}

inline int EvaluateLeaf(const bool turn, const int16_t previousMove) {
    ++stats.neuralLeafEvaluations;
    const float neural = EvaluatePositionWithSmallNeuralNetwork(board, LeafState(turn, previousMove));
    return BlendLeafScores(engineScore - opponentScore, neural, ENGINE_COLOR,
                           legacy_evaluation_weight, small_neural_evaluation_weight);
}

// Geometric guard for LMR, not a replacement for the existing move generator.
// Unknown/missing/duplicate king state disables reductions conservatively.
inline bool KingNeedsProtection(const bool movingWhite) noexcept {
    int kingRow = -1, kingColumn = -1, kingCount = 0;
    const int kingCode = 7 | (movingWhite ? 8 : 0);
    for (int row = 0; row < 8; ++row) for (int column = 0; column < 8; ++column) {
        if ((board[row][column] & 15) == kingCode) {
            kingRow = row; kingColumn = column; ++kingCount;
        }
    }
    if (kingCount != 1) return true;
    const int enemyColorBit = movingWhite ? 0 : 8;
    auto inside = [](int row, int column) {
        return row >= 0 && row < 8 && column >= 0 && column < 8;
    };
    auto enemyAt = [&](int row, int column, int type) {
        return inside(row, column) && (board[row][column] & 15) == (type | enemyColorBit);
    };
    const int pawnRow = kingRow + (movingWhite ? -1 : 1);
    if (enemyAt(pawnRow, kingColumn - 1, 1) || enemyAt(pawnRow, kingColumn + 1, 1)) return true;
    constexpr int knightOffsets[8][2] = {
        {-2,-1}, {-2,1}, {-1,-2}, {-1,2}, {1,-2}, {1,2}, {2,-1}, {2,1}
    };
    for (const auto& offset : knightOffsets) {
        if (enemyAt(kingRow + offset[0], kingColumn + offset[1], 3)) return true;
    }
    for (int dr = -1; dr <= 1; ++dr) for (int dc = -1; dc <= 1; ++dc) {
        if (dr == 0 && dc == 0) continue;
        if (enemyAt(kingRow + dr, kingColumn + dc, 7)) return true;
        const bool diagonal = dr != 0 && dc != 0;
        for (int row = kingRow + dr, column = kingColumn + dc;
             inside(row, column); row += dr, column += dc) {
            const int piece = board[row][column] & 15;
            if (!piece) continue;
            const int type = piece & 7;
            if ((piece & 8) == enemyColorBit &&
                (type == 6 || type == (diagonal ? 4 : 5))) return true;
            break;
        }
    }
    return false;
}

inline bool IsTactical(const int16_t encodedMove) noexcept {
    const auto move = static_cast<uint16_t>(encodedMove);
    const int type = (move >> 12) & 15;
    return (board[(move >> 6) & 7][(move >> 9) & 7] & 7) != 0 ||
           type == 1 || type == 2 || type == 3 || type == 6 || type == 7;
}

inline bool CanUseNeuralOrdering(const size_t moveCount) noexcept {
    if (moveCount < 2) return false;
    const int allowed = processHandler.getProcessAllowedTimeInMilliSeconds();
    if (allowed == INT_MAX) return true;
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::high_resolution_clock::now() - processHandler.getAllProcessStartTime()).count();
    const long long reserve = std::max(minimum_ordering_reserve_ms,
        (static_cast<long long>(moveCount) + moves_per_reserve_ms - 1) / moves_per_reserve_ms);
    return static_cast<long long>(allowed) - elapsed >= reserve;
}

inline void OrderMoves(const int depth, std::vector<int16_t>& moves) {
    if (moves.size() < 2 || depth <= 0) return;
    if (depth >= small_ordering_min_depth && CanUseNeuralOrdering(moves.size())) {
        ++stats.smallOrderingCalls;
        SortTheMovesWithSmallNeuralNetwork(moves);
    } else {
        ++stats.heuristicOrderingCalls;
        SortTheMovesWithMySimpleHeuristic(moves);
    }
}

// This gate reads the PARENT board, before committing the candidate move.
inline bool ShouldReduce(const int depth, const size_t index, const int16_t encodedMove,
                         const bool parentCheck, const bool childCheck) noexcept {
    if (depth < lmr_min_depth || index < unreduced_first_moves || parentCheck || childCheck) return false;
    const auto move = static_cast<uint16_t>(encodedMove);
    if (((move >> 12) & 15) != 0 || IsTactical(encodedMove)) return false;
    const int piece = board[move & 7][(move >> 3) & 7] & 15;
    if ((piece & 7) == 0 || (piece & 7) == 2) return false;
    const int destinationRow = (move >> 6) & 7;
    if ((piece & 7) == 1 && ((piece & 8) ? destinationRow <= 2 : destinationRow >= 5)) return false;
    return true;
}

inline bool NeedsFullDepthResearch(const bool turn, const int probe,
                                   const int alpha, const int beta) noexcept {
    return turn ? probe > alpha : probe < beta;
}

inline bool DeadlineExceeded() noexcept {
    if (!processHandler.processTimeExceeded()) return false;
    ++stats.deadlineAborts;
    return true;
}

inline std::vector<int16_t> GenerateMoves(const bool turn, const int16_t previousMove) {
    std::vector<int16_t> moves;
    long long pieces = (turn == ENGINE_COLOR) ? whitePieces : blackPieces;
    while (pieces) {
        const int bit = MSB(pieces);
        pieces ^= (1ll << bit);
        const int8_t row = getPieceRowFromBit[bit], column = getPieceColumnFromBit[bit];
        const auto current = GetMovesForThisPiece(board[row][column], row, column, previousMove);
        moves.insert(moves.end(), current.begin(), current.end());
    }
    return moves;
}

// Engine-relative max/min alpha-beta. Root callers commit each root move at
// full requested depth; only this INTERNAL search can reduce late quiet moves.
inline int Search(const int depth, const bool turn, const int16_t previousMove,
                  int alpha, int beta, const Options& options) {
    if (depth < 0 || depth > 30) throw std::invalid_argument("Search depth must be in 0..30");
    if (DeadlineExceeded()) return 0;
    processHandler.increaseTheNumberOfStatesForACertainDepth(static_cast<int8_t>(depth));
    const int legacy = engineScore - opponentScore;
    if (std::abs(legacy) > CHECKMATE_FLAG_SCORE_DIFFERENCE) {
        processHandler.increaseTheNumberOfFinalStates();
        return legacy;
    }
    if (depth == 0) {
        processHandler.increaseTheNumberOfFinalStates();
        return EvaluateLeaf(turn, previousMove);
    }
    auto moves = GenerateMoves(turn, previousMove);
    if (moves.empty()) {
        processHandler.increaseTheNumberOfFinalStates();
        return 0; // Existing Kernel no-generated-moves contract, unchanged.
    }
    OrderMoves(depth, moves);
    if (DeadlineExceeded()) return 0;
    const bool canReduce = options.late_move_reductions && depth >= lmr_min_depth &&
                           moves.size() > unreduced_first_moves;
    const bool movingWhite = turn == ENGINE_COLOR;
    const bool parentCheck = canReduce && KingNeedsProtection(movingWhite);
    int currentScore = turn ? INT_MIN : INT_MAX;
    for (size_t index = 0; index < moves.size(); ++index) {
        if (DeadlineExceeded()) return 0;
        const auto move = moves[index];
        const int alphaBefore = alpha, betaBefore = beta;
        const bool eligible = canReduce && ShouldReduce(depth, index, move, parentCheck, false);
        int score;
        {
            const UndoMove undo(move);
            // Pseudo-legal moves can expose their own king (for example a pin).
            // Keep these branches at full depth as well as checking moves.
            const bool reduce = eligible && !KingNeedsProtection(movingWhite) &&
                                            !KingNeedsProtection(!movingWhite);
            if (reduce) {
                ++stats.lmrProbes;
                score = Search(depth - 2, !turn, move, alphaBefore, betaBefore, options);
                if (DeadlineExceeded()) return 0;
                if (NeedsFullDepthResearch(turn, score, alphaBefore, betaBefore)) {
                    ++stats.lmrResearches;
                    score = Search(depth - 1, !turn, move, alphaBefore, betaBefore, options);
                }
            } else {
                score = Search(depth - 1, !turn, move, alphaBefore, betaBefore, options);
            }
        } // Restore the parent before inspecting/updating search bounds.
        if (DeadlineExceeded()) return 0;
        if (turn) {
            currentScore = std::max(currentScore, score);
            alpha = std::max(alpha, score);
        } else {
            currentScore = std::min(currentScore, score);
            beta = std::min(beta, score);
        }
        if (beta <= alpha) {
            processHandler.increaseTheNumberOfPrunedBranchesForACertainDepth(static_cast<int8_t>(depth));
            break;
        }
    }
    return currentScore;
}

} // namespace mrbits::neural_search
