// Offline diagnostics for the actual four V3 static-evaluation variants.
// The shared fixture loader is the existing V7 oracle; its worker main is never called.
#ifndef MRBITS_TEST_V3_EVAL_PROFILE
#error Define MRBITS_TEST_V3_EVAL_PROFILE as 1, 2, 3, or 4
#endif
#define MRBITS_DIAGNOSTIC_NO_MAIN
#include "kernel_v7_test.cpp"

namespace {
#if MRBITS_TEST_V3_EVAL_PROFILE == 1
constexpr const char* matrix_version = "v3.1";
static_assert(search::small_weight == 100 && search::legacy_weight == 0);
#elif MRBITS_TEST_V3_EVAL_PROFILE == 2
constexpr const char* matrix_version = "v3.2";
static_assert(search::small_weight == 0 && search::legacy_weight == 100);
#elif MRBITS_TEST_V3_EVAL_PROFILE == 3
constexpr const char* matrix_version = "v3.3";
static_assert(search::small_weight == 80 && search::legacy_weight == 20);
#elif MRBITS_TEST_V3_EVAL_PROFILE == 4
constexpr const char* matrix_version = "v3.4";
static_assert(search::small_weight == 20 && search::legacy_weight == 80);
#endif

struct RestoreClassicalScores {
    const int engine = engineScore, opponent = opponentScore;
    ~RestoreClassicalScores() noexcept { engineScore = engine; opponentScore = opponent; }
};

void MatrixValueRequest(const Json& request, Json& response) {
    const auto loaded = LoadFen(request.at("fen").get<std::string>(), request.value("engineWhite", true));
    const Snapshot parent;
    try {
        {
            const RestoreClassicalScores restore;
            if (request.contains("engineScore")) engineScore = request.at("engineScore").get<int>();
            if (request.contains("opponentScore")) opponentScore = request.at("opponentScore").get<int>();
            // Diagnostic perturbations are bounded to avoid overflowing the inherited int subtraction.
            if (std::abs(static_cast<long long>(engineScore) - opponentScore) > 20000000)
                throw std::invalid_argument("Diagnostic score difference is out of range");
            response["legacyCp"] = engineScore - opponentScore;
            search::ResetStats();
            response["score"] = search::EvaluateStatic(loaded.whiteToMove == ENGINE_COLOR, loaded.previousMove);
            response["staticStats"] = search::StatsJson();
            if constexpr (search::small_weight > 0) {
                // Independent underlying network value for Python's blend/sign/rounding oracle.
                response["nnWhitePawns"] = EvaluatePositionWithSmallNeuralNetwork(board,
                    position::NeuralState(loaded.whiteToMove, loaded.previousMove));
            }
        }
        parent.AssertRestored("matrix static evaluation");
        response["restored"] = true;
    } catch (...) {
        response["staticStats"] = search::StatsJson();
        response["restored"] = parent.Matches();
        throw;
    }
}

void MatrixOrderingRequest(const Json& request, Json& response) {
    const auto loaded = LoadFen(request.at("fen").get<std::string>(), request.value("engineWhite", true));
    const Snapshot parent;
    try {
        auto expected = position::LegalMoves(loaded.whiteToMove, loaded.previousMove);
        if (request.value("reverse", false)) std::reverse(expected.begin(), expected.end());
        const auto input = expected;
        // Independently spell the unchanged V3.0 ordering contract, then compare
        // this variant's actual OrderMoves. Every candidate must remain present.
        if (expected.size() > 1) {
            SortTheMovesWithMySimpleHeuristic(expected);
            const auto quiet = std::stable_partition(expected.begin(), expected.end(),
                [](const int16_t move) { return position::IsTactical(move); });
            if (request.value("depth", 3) >= 3 && expected.end() - quiet > 1) {
                std::vector<int16_t> tail(quiet, expected.end());
                SortTheMovesWithSmallNeuralNetwork(tail);
                std::copy(tail.begin(), tail.end(), quiet);
            }
        }
        parent.AssertRestored("reference ordering");
        auto actual = input;
        Budget(); search::ResetStats();
        search::OrderMoves(request.value("depth", 3), actual);
        Check(actual == expected, "Ordering differs from V3.0 reference");
        auto originalSet = input, actualSet = actual;
        std::sort(originalSet.begin(), originalSet.end());
        std::sort(actualSet.begin(), actualSet.end());
        Check(originalSet == actualSet, "Static variant deleted/duplicated candidates");
        response["inputCount"] = input.size();
        response["orderedCount"] = actual.size();
        response["orderingStats"] = search::StatsJson();
        parent.AssertRestored("variant ordering");
        response["restored"] = true;
    } catch (...) { response["restored"] = parent.Matches(); throw; }
}
} // namespace

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    BuildTheTablesOnce();
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        checks = 0;
        Json response = {{"id", nullptr}, {"ok", false}, {"version", matrix_version},
            {"smallWeight", search::small_weight}, {"legacyWeight", search::legacy_weight}};
        try {
            const auto request = Json::parse(line);
            response["id"] = request.value("id", Json(nullptr));
            const ModelEnvironment environment(argv[1], request.value("forbidModel", false));
            const auto operation = request.at("op").get<std::string>();
            if (operation == "value") MatrixValueRequest(request, response);
            else if (operation == "ordering") MatrixOrderingRequest(request, response);
            else if (operation == "position") PositionRequest(request, response);
            else if (operation == "replay") ReplayRequest(request, response);
            else throw std::invalid_argument("Unknown evaluation-matrix diagnostic operation");
            response["ok"] = true;
        } catch (const std::exception& error) { response["error"] = error.what(); }
        response["check_count"] = checks;
        std::cout << response.dump(-1, ' ', false, Json::error_handler_t::replace) << std::endl;
    }
}
