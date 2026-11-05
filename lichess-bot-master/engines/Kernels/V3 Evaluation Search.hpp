#pragma once

// V3.1--V3.4: V7/V3.0 search with compile-time static evaluation weights.
// Include after the public NN wrappers and unchanged V7 Position.hpp.
#ifndef MRBITS_V3_SMALL_PERCENT
#error Define MRBITS_V3_SMALL_PERCENT before including V3 Evaluation Search.hpp
#endif
namespace mrbits::v3_eval_search {

constexpr int q_max_plies = 6;
constexpr int mate_score = 1000000;
constexpr int mateScore = mate_score;
constexpr int mate_distance_limit = 128;
constexpr int non_terminal_score_limit = CHECKMATE_FLAG_SCORE_DIFFERENCE - 1;
constexpr int small_ordering_min_depth = 3;
static_assert(MRBITS_V3_SMALL_PERCENT >= 0 && MRBITS_V3_SMALL_PERCENT <= 100,
              "Small evaluation percentage must be in 0..100");
constexpr double small_weight = MRBITS_V3_SMALL_PERCENT;
constexpr double legacy_weight = 100.0 - small_weight;
constexpr double iteration_soft_fraction = 0.80;
constexpr double initial_iteration_growth = 16.0;
constexpr double iteration_safety_factor = 1.25;
constexpr double iteration_reserve_ms = 5.0;

inline bool ShouldStartNextIteration(const double allowedMs, const double elapsedMs,
                                    const double lastIterationMs, const double previousIterationMs) noexcept {
    if (!std::isfinite(allowedMs) || !std::isfinite(elapsedMs) ||
        !std::isfinite(lastIterationMs) || !std::isfinite(previousIterationMs) ||
        allowedMs <= 0 || elapsedMs < 0 || lastIterationMs < 0 || previousIterationMs < 0)
        return false;
    const double remaining = allowedMs - elapsedMs;
    if (elapsedMs >= allowedMs * iteration_soft_fraction || remaining <= iteration_reserve_ms) return false;
    const double last = std::max(lastIterationMs, 0.25);
    const double growth = previousIterationMs > 0
        ? std::clamp(last / std::max(previousIterationMs, 0.25), 2.0, 64.0)
        : initial_iteration_growth;
    const double estimate = std::max(2.0 * last, last * growth) * iteration_safety_factor;
    return std::isfinite(estimate) && remaining >= estimate + iteration_reserve_ms;
}

struct Stats {
    uint64_t regularNodes = 0, qNodes = 0, staticEvaluations = 0;
    uint64_t smallOrderingCalls = 0, heuristicOrderingCalls = 0;
    uint64_t smallStaticEvaluations = 0, legacyStaticEvaluations = 0;
    uint64_t qCutoffs = 0, qCapHits = 0, qCheckCapHits = 0;
    uint64_t mates = 0, stalemates = 0, deadlineAborts = 0;
    uint64_t legalMoveBatches = 0;
};
inline Stats stats;

inline void ResetStats() noexcept { stats = {}; }
inline Json StatsJson() {
    return {{"regularNodes", stats.regularNodes}, {"qNodes", stats.qNodes},
            {"staticEvaluations", stats.staticEvaluations},
            {"smallStaticEvaluations", stats.smallStaticEvaluations},
            {"legacyStaticEvaluations", stats.legacyStaticEvaluations},
            {"smallOrderingCalls", stats.smallOrderingCalls},
            {"heuristicOrderingCalls", stats.heuristicOrderingCalls},
            {"qCutoffs", stats.qCutoffs}, {"qCapHits", stats.qCapHits},
            {"qCheckCapHits", stats.qCheckCapHits}, {"mates", stats.mates},
            {"stalemates", stats.stalemates}, {"deadlineAborts", stats.deadlineAborts},
            {"legalMoveBatches", stats.legalMoveBatches}};
}

inline bool DeadlineExceeded() noexcept {
    if (!processHandler.processTimeExceeded()) return false;
    ++stats.deadlineAborts;
    return true;
}

inline int MateScore(const bool turn, const int ply) noexcept {
    const int distance = std::clamp(ply, 0, mate_distance_limit);
    return turn ? -mate_score + distance : mate_score - distance;
}

// Static scoring only: keep V3.0 ordering, legal moves, Q and timing unchanged.
// A zero-weight component is absent from this function at compile time.
inline int EvaluateStatic(const bool turn, const int16_t previousMove) {
    ++stats.staticEvaluations;
    double neuralEngineCp = 0.0, legacyCp = 0.0;
    if constexpr (small_weight > 0.0) {
        ++stats.smallStaticEvaluations;
        const auto state = v7_position::NeuralState(turn == ENGINE_COLOR, previousMove);
        const float whitePawns = EvaluatePositionWithSmallNeuralNetwork(board, state);
        if (!std::isfinite(whitePawns)) throw std::runtime_error("Non-finite V3 static neural evaluation");
        neuralEngineCp = static_cast<double>(whitePawns) * 100.0 * (ENGINE_COLOR ? 1.0 : -1.0);
    }
    if constexpr (legacy_weight > 0.0) {
        ++stats.legacyStaticEvaluations;
        legacyCp = static_cast<double>(engineScore - opponentScore);
    }
    double value;
    if constexpr (small_weight == 0.0) value = legacyCp;
    else if constexpr (legacy_weight == 0.0) value = neuralEngineCp;
    else value = (legacy_weight * legacyCp + small_weight * neuralEngineCp) / 100.0;
    return static_cast<int>(std::lround(std::clamp(value,
        -static_cast<double>(non_terminal_score_limit), static_cast<double>(non_terminal_score_limit))));
}

inline bool CanUseNeuralOrdering(const size_t count) noexcept {
    if (count < 2) return false;
    const int allowed = processHandler.getProcessAllowedTimeInMilliSeconds();
    if (allowed == INT_MAX) return true;
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::high_resolution_clock::now() - processHandler.getAllProcessStartTime()).count();
    const long long reserve = std::max(5LL, (static_cast<long long>(count) + 7) / 8);
    return static_cast<long long>(allowed) - elapsed >= reserve;
}

// Cheap tactical moves first; Small scores only the quiet tail when admitted.
// Every input move is retained. Call with legal moves for the current node.
inline void OrderMoves(const int depth, std::vector<int16_t>& moves) {
    if (moves.size() < 2) return;
    ++stats.heuristicOrderingCalls;
    SortTheMovesWithMySimpleHeuristic(moves);
    const auto quietBegin = std::stable_partition(moves.begin(), moves.end(),
        [](const int16_t move) { return v7_position::IsTactical(move); });
    const size_t quietCount = static_cast<size_t>(moves.end() - quietBegin);
    if (depth < small_ordering_min_depth || !CanUseNeuralOrdering(quietCount)) return;
    std::vector<int16_t> quiet(quietBegin, moves.end());
    ++stats.smallOrderingCalls;
    SortTheMovesWithSmallNeuralNetwork(quiet);
    std::copy(quiet.begin(), quiet.end(), quietBegin);
}

inline int TerminalScore(const bool turn, const bool inCheck, const int ply) noexcept {
    processHandler.increaseTheNumberOfFinalStates();
    if (inCheck) { ++stats.mates; return MateScore(turn, ply); }
    ++stats.stalemates;
    return 0;
}

inline int Quiescence(const bool turn, const int16_t previousMove, int alpha, int beta,
                      const int qRemaining, const int ply = 0) {
    if (qRemaining < 0 || qRemaining > q_max_plies || ply < 0)
        throw std::invalid_argument("Invalid v7 quiescence depth");
    if (DeadlineExceeded()) return 0;
    ++stats.qNodes;
    processHandler.increaseTheNumberOfStatesForACertainDepth(0);
    const bool white = turn == ENGINE_COLOR;
    const bool inCheck = v7_position::InCheck(white);
    auto moves = v7_position::LegalMoves(white, previousMove);
    ++stats.legalMoveBatches;
    // Terminal recognition precedes both neural loading and the extension cap.
    if (moves.empty()) return TerminalScore(turn, inCheck, ply);
    if (DeadlineExceeded()) return 0;
    if (qRemaining == 0) {
        ++stats.qCapHits;
        if (inCheck) ++stats.qCheckCapHits;
        processHandler.increaseTheNumberOfFinalStates();
        return EvaluateStatic(turn, previousMove);
    }

    int score = turn ? INT_MIN : INT_MAX;
    if (!inCheck) {
        score = EvaluateStatic(turn, previousMove);
        if (DeadlineExceeded()) return 0;
        if ((turn && score >= beta) || (!turn && score <= alpha)) {
            ++stats.qCutoffs;
            processHandler.increaseTheNumberOfFinalStates();
            processHandler.increaseTheNumberOfPrunedBranchesForACertainDepth(0);
            return score;
        }
        if (turn) alpha = std::max(alpha, score);
        else beta = std::min(beta, score);
        moves.erase(std::remove_if(moves.begin(), moves.end(),
            [](const int16_t move) { return !v7_position::IsTactical(move); }), moves.end());
        if (moves.empty()) {
            processHandler.increaseTheNumberOfFinalStates();
            return score;
        }
    }
    // In check, every legal evasion is eligible, including quiet king/block moves.
    if (moves.size() > 1) {
        ++stats.heuristicOrderingCalls;
        SortTheMovesWithMySimpleHeuristic(moves);
    }
    for (const auto move : moves) {
        if (DeadlineExceeded()) return 0;
        int child;
        {
            const v7_position::UndoMove undo(move);
            child = Quiescence(!turn, move, alpha, beta, qRemaining - 1, ply + 1);
        }
        if (DeadlineExceeded()) return 0;
        if (turn) { score = std::max(score, child); alpha = std::max(alpha, child); }
        else { score = std::min(score, child); beta = std::min(beta, child); }
        if (beta <= alpha) {
            ++stats.qCutoffs;
            processHandler.increaseTheNumberOfPrunedBranchesForACertainDepth(0);
            break;
        }
    }
    return score;
}

inline int Search(const int depth, const bool turn, const int16_t previousMove,
                  int alpha, int beta, const int ply = 0) {
    if (depth < 0 || depth > 30 || ply < 0) throw std::invalid_argument("Invalid v7 search depth");
    if (depth == 0) return Quiescence(turn, previousMove, alpha, beta, q_max_plies, ply);
    if (DeadlineExceeded()) return 0;
    ++stats.regularNodes;
    processHandler.increaseTheNumberOfStatesForACertainDepth(static_cast<int8_t>(depth));
    const bool white = turn == ENGINE_COLOR;
    const bool inCheck = v7_position::InCheck(white);
    auto moves = v7_position::LegalMoves(white, previousMove);
    ++stats.legalMoveBatches;
    if (moves.empty()) return TerminalScore(turn, inCheck, ply);
    if (DeadlineExceeded()) return 0;
    OrderMoves(depth, moves);
    if (DeadlineExceeded()) return 0;
    int score = turn ? INT_MIN : INT_MAX;
    for (const auto move : moves) {
        if (DeadlineExceeded()) return 0;
        int child;
        {
            const v7_position::UndoMove undo(move);
            child = Search(depth - 1, !turn, move, alpha, beta, ply + 1);
        }
        if (DeadlineExceeded()) return 0;
        if (turn) { score = std::max(score, child); alpha = std::max(alpha, child); }
        else { score = std::min(score, child); beta = std::min(beta, child); }
        if (beta <= alpha) {
            processHandler.increaseTheNumberOfPrunedBranchesForACertainDepth(static_cast<int8_t>(depth));
            break;
        }
    }
    return score;
}

} // namespace mrbits::v3_eval_search
