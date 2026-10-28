// Isolated test executable. Never starts the engine's main(), bot or Stockfish.
#define main MrBitsProductionMainNotRun
#include "../Kernel.cpp"
#undef main

void Require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

struct Snapshot {
    mrbits::kernel_neural::ParentPosition position;
    std::vector<int16_t> history = previousMoves;
    bool color = ENGINE_COLOR;
    ProcessHandler handler = processHandler;
    std::mt19937 random = rng;
    void unchanged() const {
        Require(std::memcmp(position.cells, board, sizeof(board)) == 0, "Board not restored");
        Require(std::memcmp(position.move_counts, numberOfMovesOfThePieceOnThisSquare,
                            sizeof(numberOfMovesOfThePieceOnThisSquare)) == 0, "Move counters not restored");
        Require(position.white == whitePieces && position.black == blackPieces, "Bitboards not restored");
        Require(position.engine_score == engineScore && position.opponent_score == opponentScore, "Scores not restored");
        Require(history == previousMoves && color == ENGINE_COLOR, "History/color changed");
        Require(handler == processHandler && random == rng, "Telemetry/RNG changed");
    }
};

void SetPosition(const Json& packed, bool engine_white) {
    ResetGameState(engine_white);
    constexpr int types[] = {0,1,3,4,5,6,7};
    whitePieces = blackPieces = 0;
    for (int square = 0; square < 64; ++square) {
        const int code = packed[square];
        const int row = square / 8, column = square % 8;
        board[row][column] = code ? types[(code-1)%6+1] | (code<=6 ? 8 : 0) : 0;
        numberOfMovesOfThePieceOnThisSquare[row][column] = 0;
        if (code) (code<=6 ? whitePieces : blackPieces) |= 1ull << getBitNumberFromItsRowAndColumn[row][column];
    }
    // Encode arbitrary fixture rights using the existing Kernel counter contract.
    for (const auto& home : std::vector<std::array<int,3>>{{7,7,65},{7,0,66},{0,7,67},{0,0,68}}) {
        if (!packed[home[2]].get<int>()) numberOfMovesOfThePieceOnThisSquare[home[0]][home[1]] = 1;
    }
    if (!packed[65].get<int>() && !packed[66].get<int>()) numberOfMovesOfThePieceOnThisSquare[7][4] = 1;
    if (!packed[67].get<int>() && !packed[68].get<int>()) numberOfMovesOfThePieceOnThisSquare[0][4] = 1;
    InitializeEngineScore(); InitializeOpponentScore();
    previousMoves = {1234, 5678}; // Deliberately irrelevant root history.
}

struct SpyModel {
    struct Workspace {};
    const Json& children;
    mutable std::size_t calls = 0;
    float evaluate(const std::int8_t (&cells)[8][8], const mrbits::nn::State& state, Workspace&) const {
        const auto expected = children.at(calls).at("child").get<std::vector<std::uint8_t>>();
        const auto a = mrbits::nn::from_packed(expected.data(), expected.size());
        const auto b = mrbits::nn::from_kernel(cells, state);
        Require(a.size == b.size && std::equal(a.indices,a.indices+a.size,b.indices), "Child features differ from python-chess");
        const float score = static_cast<float>((calls * 17) % 29) - 14;
        ++calls;
        return score;
    }
};
struct TieModel {
    struct Workspace {};
    float evaluate(const std::int8_t (&)[8][8], const mrbits::nn::State&, Workspace&) const { return 0; }
};
struct ThrowModel {
    struct Workspace {};
    float evaluate(const std::int8_t (&)[8][8], const mrbits::nn::State&, Workspace&) const { throw std::runtime_error("injected failure"); }
};
struct NanModel {
    struct Workspace {};
    float evaluate(const std::int8_t (&)[8][8], const mrbits::nn::State&, Workspace&) const { return std::numeric_limits<float>::quiet_NaN(); }
};

template<class Model>
void CheckRealOrder(const Json& fixture, const std::vector<int16_t>& original, const Model& model,
                    void (*sorter)(std::vector<int16_t>&), const char* score_key) {
    typename Model::Workspace scratch;
    std::vector<std::pair<float,std::size_t>> expected;
    for (std::size_t i=0;i<original.size();++i) {
        const auto child = fixture["moves"][i]["child"].get<std::vector<std::uint8_t>>();
        const float score = model.evaluate(mrbits::nn::from_packed(child.data(),child.size()),scratch);
        const float reference = fixture["moves"][i][score_key];
        Require(std::abs(score-reference) <= 0.0002f+0.00002f*std::abs(reference), "Real model score differs from Python FP32");
        expected.emplace_back(score,i);
    }
    const bool white = fixture["parent"][64].get<int>();
    std::sort(expected.begin(),expected.end(),[white](auto a,auto b){
        if (a.first!=b.first) return white ? a.first>b.first : a.first<b.first;
        return a.second<b.second;
    });
    auto actual=original;
    Snapshot parent;
    sorter(actual);
    parent.unchanged();
    for (std::size_t i=0;i<actual.size();++i) Require(actual[i]==original[expected[i].second], "Wrong real neural move order");
}

int main(int argc,char** argv) {
    try {
        if (argc!=2) throw std::runtime_error("Expected fixture JSON path");
        Json fixtures; std::ifstream input(argv[1]); input>>fixtures;
        BuildTheTablesOnce();
        SetPosition(fixtures[0]["parent"],true);
        _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR","Z:/deliberately-missing-neural-test");
        std::vector<int16_t> empty;
        SortTheMovesWithSmallNeuralNetwork(empty); SortTheMovesWithLargeNeuralNetwork(empty);
        auto first=std::vector<int16_t>{fixtures[0]["moves"][0]["move"].get<int16_t>()};
        Snapshot before_failure; bool threw=false;
        try { SortTheMovesWithSmallNeuralNetwork(first); } catch(const std::runtime_error&) { threw=true; }
        Require(threw,"Missing weights were not rejected"); before_failure.unchanged();
        _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR","");
        std::size_t tested=0;
        for (const auto& fixture:fixtures) for (bool engine_white:{false,true}) {
            SetPosition(fixture["parent"],engine_white);
            std::vector<int16_t> moves;
            for (const auto& row:fixture["moves"]) moves.push_back(row["move"]);
            Snapshot parent;
            SpyModel spy{fixture["moves"]}; auto actual=moves;
            mrbits::kernel_neural::SortMoves(actual,spy);
            Require(spy.calls==moves.size(),"Not exactly one evaluation per move"); parent.unchanged();
            std::vector<std::size_t> order(moves.size()); std::iota(order.begin(),order.end(),0);
            bool white=fixture["parent"][64].get<int>();
            std::stable_sort(order.begin(),order.end(),[white](auto a,auto b){
                int x=(a*17)%29, y=(b*17)%29; return white ? x>y : x<y;
            });
            for(std::size_t i=0;i<order.size();++i) Require(actual[i]==moves[order[i]],"Wrong moving-side order");
            actual=moves; mrbits::kernel_neural::SortMoves(actual,TieModel{});
            Require(actual==moves,"Ties did not retain original order"); parent.unchanged();
            for(int failure=0;failure<2;++failure) {
                actual=moves; threw=false;
                try { if(failure) mrbits::kernel_neural::SortMoves(actual,NanModel{});
                      else mrbits::kernel_neural::SortMoves(actual,ThrowModel{}); }
                catch(const std::runtime_error&) { threw=true; }
                Require(threw&&actual==moves,"Failure changed moves or failed to throw"); parent.unchanged();
            }
            CheckRealOrder(fixture,moves,mrbits::kernel_neural::SmallModel(),SortTheMovesWithSmallNeuralNetwork,"small");
            CheckRealOrder(fixture,moves,mrbits::kernel_neural::LargeModel(),SortTheMovesWithLargeNeuralNetwork,"large");
            tested+=moves.size();
        }
        // Both models are already cached. Bad paths must no longer trigger I/O/reload.
        SetPosition(fixtures[0]["parent"],true);
        _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR","Z:/missing-after-first-load");
        SortTheMovesWithSmallNeuralNetwork(first); SortTheMovesWithLargeNeuralNetwork(first);
        _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR","");
        std::cout<<"PASS: "<<fixtures.size()<<" positions, "<<tested
                 <<" children across both engine colors; two real models, independent flags, restoration, failures, ties and lazy caches\n";
    } catch(const std::exception& error) { std::cerr<<"FAIL: "<<error.what()<<'\n'; return 1; }
}
