#pragma once

// V12 only. V7 legality/undo, strict Small top-ten above the last two plies.
// Include after the public NN wrappers and V7 Position.hpp.
namespace mrbits::v12_search {

constexpr int q_max_plies = 6;
constexpr int mate_score = 1000000;
constexpr int mateScore = mate_score;
constexpr int mate_distance_limit = 128;
constexpr int non_terminal_score_limit = CHECKMATE_FLAG_SCORE_DIFFERENCE - 1;
constexpr int small_ordering_min_depth = 3;
constexpr size_t beam_width = 10;
constexpr double legacy_weight = 50.0;
constexpr double small_weight = 50.0;
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
    uint64_t smallRankedMoves = 0, beamOrderingBatches = 0;
    uint64_t beamDiscardedMoves = 0, beamTruncations = 0;
    uint64_t rootCandidatesBefore = 0, rootCandidatesRetained = 0, rootCandidatesDiscarded = 0;
    uint64_t qCutoffs = 0, qCapHits = 0, qCheckCapHits = 0;
    uint64_t mates = 0, stalemates = 0, deadlineAborts = 0;
    uint64_t legalMoveBatches = 0;
};
inline Stats stats;

inline void ResetStats() noexcept { stats = {}; }
inline Json StatsJson() {
    return {{"regularNodes", stats.regularNodes}, {"qNodes", stats.qNodes},
            {"staticEvaluations", stats.staticEvaluations},
            {"smallOrderingCalls", stats.smallOrderingCalls},
            {"heuristicOrderingCalls", stats.heuristicOrderingCalls},
            {"smallRankedMoves", stats.smallRankedMoves},
            {"beamOrderingBatches", stats.beamOrderingBatches},
            {"beamDiscardedMoves", stats.beamDiscardedMoves},
            {"beamTruncations", stats.beamTruncations},
            {"rootCandidatesBefore", stats.rootCandidatesBefore},
            {"rootCandidatesRetained", stats.rootCandidatesRetained},
            {"rootCandidatesDiscarded", stats.rootCandidatesDiscarded},
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

inline int EvaluateStatic(const bool turn, const int16_t previousMove) {
    ++stats.staticEvaluations;
    const auto state = v7_position::NeuralState(turn == ENGINE_COLOR, previousMove);
    const float whitePawns = EvaluatePositionWithSmallNeuralNetwork(board, state);
    if (!std::isfinite(whitePawns)) throw std::runtime_error("Non-finite v12 neural evaluation");
    const double neuralEngineCp = static_cast<double>(whitePawns) * 100.0 * (ENGINE_COLOR ? 1.0 : -1.0);
    const double blended = (legacy_weight * static_cast<double>(engineScore - opponentScore) +
                            small_weight * neuralEngineCp) / (legacy_weight + small_weight);
    return static_cast<int>(std::lround(std::clamp(blended,
        -static_cast<double>(non_terminal_score_limit), static_cast<double>(non_terminal_score_limit))));
}

// Remaining depth, not distance from the root. At depths 0/1/2 this is a
// strict no-op: no model load, heuristic, partition, sort, or truncation.
// Above that, rank the ENTIRE legal list from the actual mover's perspective,
// including captures/promotions/check evasions, then retain at most ten.
// A singleton needs neither scoring nor sorting. No time/heuristic fallback;
// callers check the deadline before and after this indivisible ordering batch.
inline void OrderMoves(const int depth, std::vector<int16_t>& moves) {
    if (depth < small_ordering_min_depth || moves.size() < 2) return;
    const size_t before = moves.size();
    SortTheMovesWithSmallNeuralNetwork(moves);
    ++stats.smallOrderingCalls;
    ++stats.beamOrderingBatches;
    stats.smallRankedMoves += before;
    if (before > beam_width) {
        stats.beamDiscardedMoves += before - beam_width;
        ++stats.beamTruncations;
        moves.resize(beam_width);
    }
}

inline void OrderRootMoves(const int depth, std::vector<int16_t>& moves) {
    const size_t before = moves.size();
    OrderMoves(depth, moves);
    stats.rootCandidatesBefore += before;
    stats.rootCandidatesRetained += moves.size();
    stats.rootCandidatesDiscarded += before - moves.size();
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
        throw std::invalid_argument("Invalid v12 quiescence depth");
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
    // Quiescence is below ordinary depth zero: preserve generation order.
    // Outside check remove_if preserves the surviving tactical order; in check
    // every legal evasion remains eligible. No sorting and no beam in Q.
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
    if (depth < 0 || depth > 30 || ply < 0) throw std::invalid_argument("Invalid v12 search depth");
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

} // namespace mrbits::v12_search
