#pragma once

// V11 only. Include after the public NN wrappers and unchanged V7 Position.hpp.
namespace mrbits::v11_search {

constexpr int q_max_plies = 6;
constexpr int mate_score = 1000000;
constexpr int mateScore = mate_score;
constexpr int mate_distance_limit = 128;
constexpr int non_terminal_score_limit = CHECKMATE_FLAG_SCORE_DIFFERENCE - 1;
constexpr int small_ordering_min_depth = 3;
constexpr double legacy_weight = 0.0;
constexpr double small_weight = 100.0;
constexpr double iteration_soft_fraction = 0.80;
constexpr double initial_iteration_growth = 16.0;
constexpr double iteration_safety_factor = 1.25;
constexpr double iteration_reserve_ms = 5.0;

// One request owns this state; workers already isolate mutable boards by process.
// The cache stores only a raw neural static value, never search/depth/mate bounds.
constexpr size_t evaluation_cache_capacity = 4096;
struct EvaluationKey {
    std::array<uint8_t, 64> pieces{};
    uint8_t whiteToMove = 0, castling = 0;
    int8_t epFile = -1;

    bool operator==(const EvaluationKey& other) const noexcept {
        return pieces == other.pieces && whiteToMove == other.whiteToMove &&
               castling == other.castling && epFile == other.epFile;
    }
};
struct EvaluationCacheEntry {
    EvaluationKey key{};
    float whitePawns = 0;
    bool occupied = false;
};
inline std::array<EvaluationCacheEntry, evaluation_cache_capacity> evaluationCache{};
inline bool cacheEnabled = true, pvsEnabled = true;

inline void SetCacheEnabled(const bool enabled) noexcept { cacheEnabled = enabled; }
inline void SetPvsEnabled(const bool enabled) noexcept { pvsEnabled = enabled; }
inline void ClearEvaluationCache() noexcept {
    for (auto& entry : evaluationCache) entry.occupied = false;
}
inline EvaluationKey MakeEvaluationKey(const mrbits::nn::State& state) noexcept {
    EvaluationKey key;
    for (size_t square = 0; square < key.pieces.size(); ++square)
        key.pieces[square] = static_cast<uint8_t>(board[square / 8][square % 8]) & 15u;
    key.whiteToMove = state.white_to_move ? 1 : 0;
    key.castling = state.castling;
    key.epFile = state.ep_file;
    return key;
}
inline uint64_t HashEvaluationKey(const EvaluationKey& key) noexcept {
    uint64_t hash = 14695981039346656037ull;
    const auto append = [&hash](const uint8_t value) { hash = (hash ^ value) * 1099511628211ull; };
    for (const auto piece : key.pieces) append(piece);
    append(key.whiteToMove); append(key.castling); append(static_cast<uint8_t>(key.epFile));
    return hash;
}
inline size_t EvaluationCacheIndex(const EvaluationKey& key) noexcept {
    return static_cast<size_t>(HashEvaluationKey(key) % evaluation_cache_capacity);
}

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
    uint64_t qCutoffs = 0, qCapHits = 0, qCheckCapHits = 0;
    uint64_t mates = 0, stalemates = 0, deadlineAborts = 0;
    uint64_t legalMoveBatches = 0;
    uint64_t cacheHits = 0, cacheMisses = 0, cacheCollisions = 0, nnForwardCalls = 0;
    uint64_t pvsScouts = 0, pvsResearches = 0;
};
inline Stats stats;

inline void ResetStats() noexcept { stats = {}; }
inline Json StatsJson() {
    return {{"regularNodes", stats.regularNodes}, {"qNodes", stats.qNodes},
            {"staticEvaluations", stats.staticEvaluations},
            {"smallOrderingCalls", stats.smallOrderingCalls},
            {"heuristicOrderingCalls", stats.heuristicOrderingCalls},
            {"qCutoffs", stats.qCutoffs}, {"qCapHits", stats.qCapHits},
            {"qCheckCapHits", stats.qCheckCapHits}, {"mates", stats.mates},
            {"stalemates", stats.stalemates}, {"deadlineAborts", stats.deadlineAborts},
            {"legalMoveBatches", stats.legalMoveBatches},
            {"cacheHits", stats.cacheHits}, {"cacheMisses", stats.cacheMisses},
            {"cacheCollisions", stats.cacheCollisions}, {"nnForwardCalls", stats.nnForwardCalls},
            {"pvsScouts", stats.pvsScouts}, {"pvsResearches", stats.pvsResearches}};
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
    float whitePawns;
    if (cacheEnabled) {
        const auto key = MakeEvaluationKey(state);
        auto& entry = evaluationCache[EvaluationCacheIndex(key)];
        if (entry.occupied && entry.key == key) {
            ++stats.cacheHits;
            whitePawns = entry.whitePawns;
        } else {
            ++stats.cacheMisses;
            if (entry.occupied) ++stats.cacheCollisions;
            ++stats.nnForwardCalls;
            whitePawns = EvaluatePositionWithSmallNeuralNetwork(board, state);
            // Never publish an exception, NaN or infinity into the cache.
            if (!std::isfinite(whitePawns)) throw std::runtime_error("Non-finite v11 neural evaluation");
            entry.key = key;
            entry.whitePawns = whitePawns;
            entry.occupied = true;
        }
    } else {
        ++stats.nnForwardCalls;
        whitePawns = EvaluatePositionWithSmallNeuralNetwork(board, state);
    }
    if (!std::isfinite(whitePawns)) throw std::runtime_error("Non-finite v11 neural evaluation");
    const double neuralEngineCp = static_cast<double>(whitePawns) * 100.0 * (ENGINE_COLOR ? 1.0 : -1.0);
    // Deliberately ignore the legacy running scores. The zero/100 weights above
    // describe this policy in telemetry; they are not a configurable blend here.
    return static_cast<int>(std::lround(std::clamp(neuralEngineCp,
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
        throw std::invalid_argument("Invalid v11 quiescence depth");
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
    if (depth < 0 || depth > 30 || ply < 0) throw std::invalid_argument("Invalid v11 search depth");
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
    bool firstChild = true;
    for (const auto move : moves) {
        if (DeadlineExceeded()) return 0;
        int child;
        {
            const v7_position::UndoMove undo(move);
            // Scout only after the first child established a useful bound. A
            // full-width re-search restores precision for a possible new PV.
            // int64_t subtraction avoids overflow at INT_MIN/INT_MAX windows.
            const bool scout = pvsEnabled && !firstChild &&
                static_cast<int64_t>(beta) - static_cast<int64_t>(alpha) > 1;
            if (scout) {
                ++stats.pvsScouts;
                if (turn) {
                    child = Search(depth - 1, !turn, move, alpha, alpha + 1, ply + 1);
                    if (!DeadlineExceeded() && child > alpha && child < beta) {
                        ++stats.pvsResearches;
                        child = Search(depth - 1, !turn, move, alpha, beta, ply + 1);
                    }
                } else {
                    child = Search(depth - 1, !turn, move, beta - 1, beta, ply + 1);
                    if (!DeadlineExceeded() && child < beta && child > alpha) {
                        ++stats.pvsResearches;
                        child = Search(depth - 1, !turn, move, alpha, beta, ply + 1);
                    }
                }
            } else {
                child = Search(depth - 1, !turn, move, alpha, beta, ply + 1);
            }
        }
        if (DeadlineExceeded()) return 0;
        firstChild = false;
        if (turn) { score = std::max(score, child); alpha = std::max(alpha, child); }
        else { score = std::min(score, child); beta = std::min(beta, child); }
        if (beta <= alpha) {
            processHandler.increaseTheNumberOfPrunedBranchesForACertainDepth(static_cast<int8_t>(depth));
            break;
        }
    }
    return score;
}

} // namespace mrbits::v11_search
