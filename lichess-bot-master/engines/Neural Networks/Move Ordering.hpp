#pragma once

// Include in Kernel.cpp after MakeChanges/ReturnChanges and their global state.
// The caller supplies moves for one side from the current, initialized position.
#include "Small/Small.hpp"
#include "Large/Large.hpp"
#include <cstdlib>
#include <filesystem>

namespace mrbits::kernel_neural {

inline std::string WeightFile(const char* model_name) {
    namespace fs = std::filesystem;
    const fs::path suffix = fs::path(model_name) / "weights.bin";
    if (const char* configured = std::getenv("MRBITS_NEURAL_WEIGHTS_DIR")) {
        if (*configured) return (fs::path(configured) / suffix).string();
    }
    auto find_beside = [&](fs::path base) -> std::string {
        while (!base.empty()) {
            const fs::path candidates[] = {base, base / "Neural Networks", base / "engines" / "Neural Networks"};
            for (const auto& candidate : candidates) {
                std::error_code error;
                if (fs::is_regular_file(candidate / suffix, error)) return (candidate / suffix).string();
            }
            const auto parent = base.parent_path();
            if (parent == base) break;
            base = parent;
        }
        return {};
    };
#if defined(_WIN32)
    std::vector<wchar_t> executable(512);
    for (;;) {
        const DWORD count = GetModuleFileNameW(nullptr, executable.data(), static_cast<DWORD>(executable.size()));
        if (!count) break;
        if (count < executable.size()) {
            const auto found = find_beside(fs::path(std::wstring(executable.data(), count)).parent_path());
            if (!found.empty()) return found;
            break;
        }
        if (executable.size() >= 32768) break;
        executable.resize(executable.size() * 2);
    }
#endif
    std::error_code error;
    const auto current = fs::current_path(error);
    if (!error) {
        const auto found = find_beside(current);
        if (!found.empty()) return found;
    }
    throw std::runtime_error(std::string("Cannot locate ") + model_name +
        "/weights.bin; set MRBITS_NEURAL_WEIGHTS_DIR to the Neural Networks folder");
}

inline const nn::Small& SmallModel() {
    static const auto model = nn::Small::load(WeightFile("Small"));
    return model;
}

inline const nn::Large& LargeModel() {
    static const auto model = nn::Large::load(WeightFile("Large"));
    return model;
}

// Pure value inference: explicit position/state, White-perspective pawn units.
// The model is immutable; each thread reuses its own fixed scratch workspace.
inline float EvaluateSmallPosition(const std::int8_t (&position)[8][8], const nn::State& state) {
    thread_local nn::Small::Workspace workspace;
    const float score = SmallModel().evaluate(position, state, workspace);
    if (!std::isfinite(score)) throw std::runtime_error("Small position evaluation produced a non-finite score");
    return score;
}

inline float EvaluateLargePosition(const std::int8_t (&position)[8][8], const nn::State& state) {
    thread_local nn::Large::Workspace workspace;
    const float score = LargeModel().evaluate(position, state, workspace);
    if (!std::isfinite(score)) throw std::runtime_error("Large position evaluation produced a non-finite score");
    return score;
}

struct ParentPosition {
    std::int8_t cells[8][8];
    std::int16_t move_counts[8][8];
    long long white, black;
    int engine_score, opponent_score;

    ParentPosition() noexcept : white(::whitePieces), black(::blackPieces),
        engine_score(::engineScore), opponent_score(::opponentScore) {
        std::memcpy(cells, ::board, sizeof(cells));
        std::memcpy(move_counts, ::numberOfMovesOfThePieceOnThisSquare, sizeof(move_counts));
    }
    void restore() const noexcept {
        std::memcpy(::board, cells, sizeof(cells));
        std::memcpy(::numberOfMovesOfThePieceOnThisSquare, move_counts, sizeof(move_counts));
        ::whitePieces = white; ::blackPieces = black;
        ::engineScore = engine_score; ::opponentScore = opponent_score;
    }
};

struct RestoreParent {
    const ParentPosition& parent;
    ~RestoreParent() noexcept { parent.restore(); }
};

inline std::uint8_t CastlingRights() noexcept {
    auto unmoved = [](int row, int column, int piece) {
        return (static_cast<unsigned char>(::board[row][column]) & 15) == piece &&
            ::numberOfMovesOfThePieceOnThisSquare[row][column] == 0;
    };
    std::uint8_t mask = 0;
    if (unmoved(7, 4, 15)) {
        if (unmoved(7, 7, 13)) mask |= 1;
        if (unmoved(7, 0, 13)) mask |= 2;
    }
    if (unmoved(0, 4, 7)) {
        if (unmoved(0, 7, 5)) mask |= 4;
        if (unmoved(0, 0, 5)) mask |= 8;
    }
    return mask;
}

inline nn::State ChildState(std::uint16_t move, bool moving_white, int source_type) noexcept {
    const int sr = move & 7, sc = (move >> 3) & 7;
    const int dr = (move >> 6) & 7, dc = (move >> 9) & 7;
    std::int8_t ep_file = -1;
    if (((move >> 12) & 15) == 0 && source_type == 1 && sc == dc &&
        ((moving_white && sr == 6 && dr == 4) || (!moving_white && sr == 1 && dr == 3))) {
        ep_file = static_cast<std::int8_t>(dc);
    }
    return {!moving_white, CastlingRights(), ep_file};
}

struct ScoredMove {
    float score;
    std::size_t original_index;
    std::int16_t move;
};

template <class Model>
void SortMoves(std::vector<std::int16_t>& moves, const Model& model) {
    if (moves.empty()) return;
    const auto first = static_cast<std::uint16_t>(moves.front());
    const bool moving_white = (::board[first & 7][(first >> 3) & 7] & 8) != 0;
    // Validate every source before changing state or the caller's vector.
    for (const auto encoded : moves) {
        const auto move = static_cast<std::uint16_t>(encoded);
        const auto piece = static_cast<unsigned char>(::board[move & 7][(move >> 3) & 7]) & 15;
        const int type = piece & 7;
        if (((move >> 12) & 15) > 7 || type == 0 || type == 2 ||
            ((piece & 8) != 0) != moving_white) {
            throw std::invalid_argument("Neural ordering requires supported moves for one side in the current position");
        }
    }
    thread_local typename Model::Workspace workspace;
    thread_local std::vector<ScoredMove> scored;
    scored.clear();
    scored.reserve(moves.size());
    const ParentPosition parent;
    for (std::size_t index = 0; index < moves.size(); ++index) {
        const auto encoded = moves[index];
        const auto move = static_cast<std::uint16_t>(encoded);
        const int source_type = ::board[move & 7][(move >> 3) & 7] & 7;
        RestoreParent rollback{parent};
        ::MakeChanges(encoded);
        const float score = model.evaluate(::board, ChildState(move, moving_white, source_type), workspace);
        if (!std::isfinite(score)) throw std::runtime_error("Neural ordering produced a non-finite score");
        scored.push_back({score, index, encoded});
    }
    std::sort(scored.begin(), scored.end(), [moving_white](const ScoredMove& a, const ScoredMove& b) noexcept {
        if (a.score != b.score) return moving_white ? a.score > b.score : a.score < b.score;
        return a.original_index < b.original_index;
    });
    for (std::size_t index = 0; index < moves.size(); ++index) moves[index] = scored[index].move;
}

} // namespace mrbits::kernel_neural
