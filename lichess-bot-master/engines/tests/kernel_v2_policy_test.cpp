// Isolated policy checks: never call the renamed worker main or launch helpers.
#define main mrbits_v2_worker_main_not_called_by_this_test
#include "../Kernels/v2/Kernel-v2.cpp"
#undef main

namespace {

int checks = 0;

void Check(bool passed, const string& message) {
    ++checks;
    if (!passed) throw runtime_error(message);
}

struct Snapshot {
    int8_t cells[8][8];
    int16_t counters[8][8];
    long long white = whitePieces, black = blackPieces;
    int engine_score = engineScore, opponent_score = opponentScore;
    bool engine_color = ENGINE_COLOR;
    vector<int16_t> history = previousMoves;
    mt19937 random = rng;
    ProcessHandler handler = processHandler;

    Snapshot() {
        memcpy(cells, board, sizeof(cells));
        memcpy(counters, numberOfMovesOfThePieceOnThisSquare, sizeof(counters));
    }

    void AssertUnchanged(const string& label) const {
        Check(memcmp(cells, board, sizeof(cells)) == 0, label + ": board changed");
        Check(memcmp(counters, numberOfMovesOfThePieceOnThisSquare, sizeof(counters)) == 0,
              label + ": move counters changed");
        Check(white == whitePieces && black == blackPieces, label + ": bitboards changed");
        Check(engine_score == engineScore && opponent_score == opponentScore, label + ": scores changed");
        Check(engine_color == ENGINE_COLOR && history == previousMoves, label + ": color/history changed");
        Check(random == rng, label + ": RNG changed");
        Check(handler == processHandler, label + ": process handler changed");
    }
};

struct EnvironmentRestore {
    bool present = getenv("MRBITS_NEURAL_WEIGHTS_DIR") != nullptr;
    string value = present ? getenv("MRBITS_NEURAL_WEIGHTS_DIR") : "";
    ~EnvironmentRestore() { _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", present ? value.c_str() : ""); }
};

void SetBudget(int milliseconds) {
    processHandler.setAllowedTimeInMilliSeconds(milliseconds);
    processHandler.setAllProcessStartTime();
}

void SameCandidates(const vector<int16_t>& before, const vector<int16_t>& after, const string& label) {
    auto a = before, b = after;
    sort(a.begin(), a.end());
    sort(b.begin(), b.end());
    Check(a == b, label + ": candidate multiset changed");
}

template <class Operation>
void ExpectHeuristic(const vector<int16_t>& input, Operation operation, const string& label) {
    auto expected = input;
    SortTheMovesWithMySimpleHeuristic(expected);
    auto actual = input;
    const Snapshot before;
    operation(actual);
    Check(actual == expected, label + ": did not use the existing heuristic");
    SameCandidates(input, actual, label);
    before.AssertUnchanged(label);
}

void NoLoadAndBudgetChecks(const vector<int16_t>& input) {
    using namespace mrbits::v2_policy;
    // Run these before either lazy model initializes. Any accidental NN load fails.
    Check(_putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", "Z:/mrbits-v2-policy-test-missing-weights") == 0,
          "could not set the missing-weights test environment");
    SetBudget(INT_MAX);
    for (size_t count : {size_t(0), size_t(1)}) {
        vector<int16_t> actual(input.begin(), input.begin() + count);
        const auto expected = actual;
        const Snapshot before;
        OrderRoot(4, actual);
        OrderInternal(3, actual);
        OrderInternal(2, actual);
        Check(actual == expected, "zero/singleton policy changed the list");
        Check(!CanUseNeuralOrdering(count, false) && !CanUseNeuralOrdering(count, true),
              "zero/singleton list admitted neural ordering");
        before.AssertUnchanged("zero/singleton no-load");
    }
    ExpectHeuristic(input, [](auto& moves) { OrderRoot(2, moves); }, "root depth2 no-load");
    ExpectHeuristic(input, [](auto& moves) { OrderInternal(2, moves); }, "internal depth2 no-load");
    auto depth_one = input;
    const Snapshot depth_one_before;
    OrderInternal(1, depth_one);
    Check(depth_one == input, "internal depth1 changed generation order");
    depth_one_before.AssertUnchanged("internal depth1");

    SetBudget(0);
    Check(!CanUseNeuralOrdering(input.size(), false) && !CanUseNeuralOrdering(input.size(), true),
          "expired deadline admitted neural ordering");
    ExpectHeuristic(input, [](auto& moves) { OrderRoot(4, moves); }, "expired root fallback");
    ExpectHeuristic(input, [](auto& moves) { OrderInternal(3, moves); }, "expired internal fallback");

    SetBudget(4);
    Check(!CanUseNeuralOrdering(2, false), "Small minimum reserve was ignored");
    ExpectHeuristic(input, [](auto& moves) { OrderInternal(3, moves); }, "Small reserve fallback");
    SetBudget(99);
    Check(!CanUseNeuralOrdering(2, true), "Large minimum reserve was ignored");
    ExpectHeuristic(input, [](auto& moves) { OrderRoot(4, moves); }, "Large reserve fallback");
    SetBudget(19);
    Check(!CanUseNeuralOrdering(20, false), "Small per-move reserve was ignored");
    SetBudget(199);
    Check(!CanUseNeuralOrdering(20, true), "Large per-move reserve was ignored");
    SetBudget(INT_MAX);
    Check(CanUseNeuralOrdering(input.size(), false) && CanUseNeuralOrdering(input.size(), true),
          "fixed-depth INT_MAX mode did not bypass reserve admission");
}

void ActualModelChecks(const vector<int16_t>& input) {
    using namespace mrbits::v2_policy;
    // The diagnostic executable is under this repository, so the shared resolver
    // finds engines/Neural Networks independently of the launch working directory.
    Check(_putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", "") == 0, "could not clear the test weight override");
    SetBudget(INT_MAX);
    auto heuristic = input;
    SortTheMovesWithMySimpleHeuristic(heuristic);

    auto expected_large = heuristic;
    const Snapshot large_before;
    SortTheMovesWithLargeNeuralNetwork(expected_large);
    large_before.AssertUnchanged("Large reference ordering");
    Check(expected_large != heuristic, "Large fixture does not distinguish NN from heuristic ordering");
    auto actual_large = input;
    OrderRoot(4, actual_large);
    Check(actual_large == expected_large, "root depth4 did not apply actual Large ordering");
    SameCandidates(input, actual_large, "root depth4 Large");
    large_before.AssertUnchanged("root depth4 Large");

    auto expected_small = input;
    const Snapshot small_before;
    SortTheMovesWithSmallNeuralNetwork(expected_small);
    small_before.AssertUnchanged("Small reference ordering");
    Check(expected_small != heuristic, "Small fixture does not distinguish NN from heuristic ordering");
    auto actual_small = input;
    OrderInternal(3, actual_small);
    Check(actual_small == expected_small, "internal depth3 did not apply actual Small ordering");
    SameCandidates(input, actual_small, "internal depth3 Small");
    small_before.AssertUnchanged("internal depth3 Small");
}

} // namespace

int main(int argc, char** argv) {
    Json report = {{"test", "kernel_v2_policy"}, {"engine_processes_started", 0}};
    if (argc > 2) report["v2_source_sha256"] = argv[2];
    int result = 0;
    try {
        const EnvironmentRestore restore_environment;
        BuildTheTablesOnce();
        ResetGameState(true);
        auto input = GetAllPossibleMoves();
        reverse(input.begin(), input.end());
        Check(input.size() == 20, "expected the 20 starting-position candidates");
        NoLoadAndBudgetChecks(input);
        ActualModelChecks(input);
        report["passed"] = true;
        report["candidates_in_fixture"] = input.size();
        report["cases"] = {"empty/singleton no-load", "root2 heuristic no-load",
            "internal2 heuristic no-load", "internal1 generation order", "expired deadline fallback",
            "minimum/per-move reserves", "INT_MAX fixed-depth admission", "actual Large root4 ordering",
            "actual Small internal3 ordering", "candidate/state preservation"};
    } catch (const exception& error) {
        report["passed"] = false;
        report["error"] = error.what();
        result = 1;
    }
    report["checks"] = checks;
    if (argc > 1) {
        ofstream output(argv[1]);
        if (!output) {
            cerr << "Cannot write policy test report\n";
            return 1;
        }
        output << report.dump(2) << '\n';
    }
    cout << report.dump(2) << '\n';
    return result;
}
