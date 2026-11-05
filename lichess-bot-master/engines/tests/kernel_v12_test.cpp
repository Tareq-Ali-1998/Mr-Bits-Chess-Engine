// Offline V12 JSONL diagnostics. Never invoke the renamed worker main or Stockfish.
#define main mrbits_worker_main_not_called_by_this_test
#include "../Kernels/v3.9/Kernel-v3.9.cpp"
#undef main

#include <sstream>

namespace {
namespace position = mrbits::v7_position;
namespace search = mrbits::v12_search;
uint64_t checks = 0;

void Check(const bool passed, const std::string& message) {
    ++checks;
    if (!passed) throw std::runtime_error(message);
}

struct Snapshot {
    int8_t cells[8][8];
    int16_t counters[8][8];
    long long white = whitePieces, black = blackPieces;
    int engine = engineScore, opponent = opponentScore;
    bool engineWhite = ENGINE_COLOR;
    std::vector<int16_t> history = previousMoves;
    std::mt19937 random = rng;

    Snapshot() {
        std::memcpy(cells, board, sizeof(cells));
        std::memcpy(counters, numberOfMovesOfThePieceOnThisSquare, sizeof(counters));
    }
    bool Matches() const {
        return std::memcmp(cells, board, sizeof(cells)) == 0 &&
            std::memcmp(counters, numberOfMovesOfThePieceOnThisSquare, sizeof(counters)) == 0 &&
            white == whitePieces && black == blackPieces && engine == engineScore &&
            opponent == opponentScore && engineWhite == ENGINE_COLOR &&
            history == previousMoves && random == rng;
    }
    void AssertRestored(const std::string& label) const {
        Check(std::memcmp(cells, board, sizeof(cells)) == 0, label + ": board changed");
        Check(std::memcmp(counters, numberOfMovesOfThePieceOnThisSquare, sizeof(counters)) == 0,
              label + ": move counters changed");
        Check(white == whitePieces && black == blackPieces, label + ": occupancy masks changed");
        Check(engine == engineScore && opponent == opponentScore, label + ": scores changed");
        Check(engineWhite == ENGINE_COLOR && history == previousMoves, label + ": color/history changed");
        Check(random == rng, label + ": RNG changed");
    }
};

void CheckIncrementalScores(const std::string& label) {
    int expectedEngine = 0, expectedOpponent = 0;
    for (int row = 0; row < 8; ++row) for (int column = 0; column < 8; ++column) {
        const int piece = board[row][column] & 15;
        if (!piece) continue;
        const int value = PIECE_VALUE[piece & 7] + pieceSquaresTable[piece][row][column];
        if (static_cast<bool>(piece & 8) == ENGINE_COLOR) expectedEngine += value;
        else expectedOpponent += value;
    }
    Check(engineScore == expectedEngine, label + ": incremental engine score disagrees with full recomputation");
    Check(opponentScore == expectedOpponent, label + ": incremental opponent score disagrees with full recomputation");
}

void Budget(const bool expired = false) {
    processHandler.setAllowedTimeInMilliSeconds(expired ? 0 : INT_MAX);
    processHandler.setAllProcessStartTime();
}

int PieceCode(const char symbol) {
    int type = 0;
    switch (static_cast<char>(std::tolower(static_cast<unsigned char>(symbol)))) {
        case 'p': type = 1; break;
        case 'n': type = 3; break;
        case 'b': type = 4; break;
        case 'r': type = 5; break;
        case 'q': type = 6; break;
        case 'k': type = 7; break;
        default: throw std::invalid_argument("Invalid piece in diagnostic FEN");
    }
    return type | (std::isupper(static_cast<unsigned char>(symbol)) ? 8 : 0);
}

struct LoadedPosition {
    bool whiteToMove;
    int16_t previousMove;
};

LoadedPosition LoadFen(const std::string& fen, const bool engineWhite) {
    ResetGameState(engineWhite);
    std::string placement, turn, castling, ep, extra;
    int halfmoves = 0, fullmoves = 0;
    std::istringstream input(fen);
    if (!(input >> placement >> turn >> castling >> ep >> halfmoves >> fullmoves) ||
        (input >> extra) || (turn != "w" && turn != "b") || halfmoves < 0 || fullmoves < 1) {
        throw std::invalid_argument("Expected a complete standard-chess FEN");
    }
    std::memset(board, 0, sizeof(board));
    std::memset(numberOfMovesOfThePieceOnThisSquare, 0, sizeof(numberOfMovesOfThePieceOnThisSquare));
    uint64_t white = 0, black = 0;
    int row = 0, column = 0;
    for (const char symbol : placement) {
        if (symbol == '/') {
            if (column != 8 || row >= 7) throw std::invalid_argument("Invalid FEN rank width");
            ++row; column = 0;
        } else if (symbol >= '1' && symbol <= '8') {
            column += symbol - '0';
            if (column > 8) throw std::invalid_argument("Invalid FEN rank width");
        } else {
            if (row > 7 || column > 7) throw std::invalid_argument("Invalid FEN square");
            const int piece = PieceCode(symbol);
            board[row][column] = static_cast<int8_t>(piece);
            numberOfMovesOfThePieceOnThisSquare[row][column] = 1;
            const uint64_t bit = uint64_t{1} << getBitNumberFromItsRowAndColumn[row][column];
            if (piece & 8) white |= bit; else black |= bit;
            ++column;
        }
    }
    if (row != 7 || column != 8) throw std::invalid_argument("FEN does not have eight complete ranks");
    whitePieces = static_cast<long long>(white);
    blackPieces = static_cast<long long>(black);
    bool rights[4] = {};
    if (castling != "-") {
        for (const char flag : castling) {
            const auto index = std::string("KQkq").find(flag);
            if (index == std::string::npos || rights[index]) throw std::invalid_argument("Invalid FEN castling flags");
            rights[index] = true;
        }
    }
    if (rights[0] || rights[1]) numberOfMovesOfThePieceOnThisSquare[7][4] = 0;
    if (rights[2] || rights[3]) numberOfMovesOfThePieceOnThisSquare[0][4] = 0;
    if (rights[0]) numberOfMovesOfThePieceOnThisSquare[7][7] = 0;
    if (rights[1]) numberOfMovesOfThePieceOnThisSquare[7][0] = 0;
    if (rights[2]) numberOfMovesOfThePieceOnThisSquare[0][7] = 0;
    if (rights[3]) numberOfMovesOfThePieceOnThisSquare[0][0] = 0;
    const bool whiteToMove = turn == "w";
    int16_t previousMove = 0;
    if (ep != "-") {
        if (ep.size() != 2 || ep[0] < 'a' || ep[0] > 'h' || ep[1] != (whiteToMove ? '6' : '3')) {
            throw std::invalid_argument("Invalid FEN en-passant target");
        }
        const int file = ep[0] - 'a';
        previousMove = position::Encode(whiteToMove ? 1 : 6, file, whiteToMove ? 3 : 4, file);
    }
    previousMoves.clear();
    if (previousMove) previousMoves.push_back(previousMove);
    InitializeEngineScore();
    InitializeOpponentScore();
    Budget();
    search::ResetStats();
    CheckIncrementalScores("loaded FEN");
    return {whiteToMove, previousMove};
}

std::string Uci(const int16_t move) {
    return processHandler.convertMoveFromInt16_tToStandard(move);
}

uint64_t Perft(const bool white, const int16_t previousMove, const int depth) {
    if (depth == 0) return 1;
    const auto moves = position::LegalMoves(white, previousMove);
    uint64_t nodes = 0;
    for (const auto move : moves) {
        const position::UndoMove undo(move);
        nodes += Perft(!white, move, depth - 1);
    }
    return nodes;
}

struct DeliberateRollbackException {};

Json MoveNames(const std::vector<int16_t>& moves) {
    Json names = Json::array();
    for (const auto move : moves) names.push_back(Uci(move));
    return names;
}

void StaticFields(const LoadedPosition loaded, Json& response) {
    const bool turn = loaded.whiteToMove == ENGINE_COLOR;
    response["legacyCp"] = engineScore - opponentScore;
    response["staticScore"] = search::EvaluateStatic(turn, loaded.previousMove);
    response["nnWhitePawns"] = EvaluatePositionWithSmallNeuralNetwork(board,
        position::NeuralState(loaded.whiteToMove, loaded.previousMove));
}

void PositionRequest(const Json& request, Json& response) {
    const auto loaded = LoadFen(request.at("fen").get<std::string>(), request.value("engineWhite", true));
    const Snapshot parent;
    try {
        const auto moves = position::LegalMoves(loaded.whiteToMove, loaded.previousMove);
        response["legal"] = MoveNames(moves);
        response["inCheck"] = position::InCheck(loaded.whiteToMove);
        for (const auto move : moves) {
            {
                const position::UndoMove undo(move);
                CheckIncrementalScores("child " + Uci(move));
            }
            parent.AssertRestored("child " + Uci(move));
            try {
                const position::UndoMove undo(move);
                throw DeliberateRollbackException{};
            } catch (const DeliberateRollbackException&) {}
            parent.AssertRestored("exception " + Uci(move));
        }
        if (request.contains("perftDepth")) {
            response["perft"] = Perft(loaded.whiteToMove, loaded.previousMove, request.at("perftDepth").get<int>());
            parent.AssertRestored("perft");
        }
        const bool turn = loaded.whiteToMove == ENGINE_COLOR;
        if (request.value("staticOnly", false)) StaticFields(loaded, response);
        if (request.contains("qDepth")) {
            Budget(); search::ResetStats();
            response["qScore"] = search::Quiescence(turn, loaded.previousMove, INT_MIN, INT_MAX,
                request.at("qDepth").get<int>(), request.value("ply", 0));
            response["qStats"] = search::StatsJson();
        }
        if (request.contains("searchDepth")) {
            Budget(request.value("expired", false)); search::ResetStats();
            response["searchScore"] = search::Search(request.at("searchDepth").get<int>(), turn,
                loaded.previousMove, INT_MIN, INT_MAX, request.value("ply", 0));
            response["searchStats"] = search::StatsJson();
        }
        parent.AssertRestored("all position work");
        response["restored"] = true;
    } catch (...) {
        response["restored"] = parent.Matches();
        throw;
    }
}

std::vector<int16_t> Candidates(const Json& request, const LoadedPosition loaded) {
    auto moves = position::LegalMoves(loaded.whiteToMove, loaded.previousMove);
    if (request.contains("moves")) {
        std::vector<int16_t> subset;
        for (const auto& name : request.at("moves")) {
            const auto found = std::find_if(moves.begin(), moves.end(), [&](const auto move) {
                return Uci(move) == name.get<std::string>();
            });
            if (found == moves.end()) throw std::invalid_argument("Illegal diagnostic candidate");
            if (std::find(subset.begin(), subset.end(), *found) != subset.end())
                throw std::invalid_argument("Duplicate diagnostic candidate");
            subset.push_back(*found);
        }
        moves = std::move(subset);
    }
    if (request.value("reverse", false)) std::reverse(moves.begin(), moves.end());
    return moves;
}

// Independent direct child inference uses legal-position undo, not SortMoves,
// OrderMoves, or OrderRootMoves. Python performs its own stable score ordering.
void OrderingRequest(const Json& request, Json& response) {
    const auto loaded = LoadFen(request.at("fen").get<std::string>(), request.value("engineWhite", true));
    const Snapshot parent;
    try {
        auto moves = Candidates(request, loaded);
        response["inputMoves"] = MoveNames(moves);
        response["inCheck"] = position::InCheck(loaded.whiteToMove);
        if (request.value("facts", false)) {
            Json scores = Json::array();
            for (const auto move : moves) {
                float value;
                {
                    const position::UndoMove undo(move);
                    value = EvaluatePositionWithSmallNeuralNetwork(board,
                        position::NeuralState(!loaded.whiteToMove, move));
                    Check(std::isfinite(value), "Independent inference was non-finite");
                    CheckIncrementalScores("independent inference child");
                }
                scores.push_back({{"move", Uci(move)}, {"whitePawns", value}});
                parent.AssertRestored("independent inference child");
            }
            response["smallScores"] = scores;
        }
        Budget(request.value("expired", false)); search::ResetStats();
        if (request.value("rootOrdering", false)) search::OrderRootMoves(request.value("depth", 2), moves);
        else search::OrderMoves(request.value("depth", 2), moves);
        response["ordered"] = MoveNames(moves);
        response["orderStats"] = search::StatsJson();
        parent.AssertRestored("ordering");
        response["restored"] = true;
    } catch (...) { response["restored"] = parent.Matches(); throw; }
}

void RootRequest(const Json& request, Json& response) {
    const auto loaded = LoadFen(request.at("fen").get<std::string>(), request.value("engineWhite", true));
    const Snapshot parent;
    try {
        auto moves = Candidates(request, loaded);
        response["inputMoves"] = MoveNames(moves);
        Budget(request.value("expired", false)); search::ResetStats();
        const int8_t depth = request.value("depth", 2);
        const auto best = GetBestMoveWithItsScore(depth, loaded.whiteToMove == ENGINE_COLOR, moves);
        response["retained"] = MoveNames(moves);
        response["bestMove"] = best.first ? Uci(best.first) : "";
        response["bestScore"] = best.second;
        response["rootStats"] = search::StatsJson();
        Json scores = Json::array();
        for (const auto& entry : rootMoveScoresOfTheLastSearch)
            scores.push_back({{"move", Uci(entry.move)}, {"score", entry.score}, {"exact", entry.exact}});
        response["rootScores"] = scores;
        parent.AssertRestored("root search");
        response["restored"] = true;
    } catch (...) { response["restored"] = parent.Matches(); throw; }
}

void ReplayRequest(const Json& request, Json& response) {
    const Json actual = {{"type", "search"}, {"id", request.value("id", Json(nullptr))},
        {"engineColor", request.value("engineWhite", true)},
        {"allowedEngineTimeInSeconds", request.value("allowedSeconds", 60)},
        {"previousMoves", request.value("moves", std::vector<std::string>{})},
        {"movesForThisThread", request.value("roots", std::vector<std::string>{})},
        {"bestMove", ""}, {"bestMoveScore", 0}, {"report", ""},
        {"maxDepth", request.value("maxDepth", 2)}};
    response["answer"] = AnswerSearchRequest(actual);
}
} // namespace

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    if (_putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", argv[1]) != 0) return 2;
    BuildTheTablesOnce();
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        checks = 0;
        Json response = {{"id", nullptr}, {"ok", false}};
        try {
            const auto request = Json::parse(line);
            response["id"] = request.value("id", Json(nullptr));
            const bool forbidden = request.value("forbidModel", false);
            const std::string weights = forbidden ? std::string(argv[1]) + "/__intentionally_missing_models__" : argv[1];
            _putenv_s("MRBITS_NEURAL_WEIGHTS_DIR", weights.c_str());
            const auto operation = request.at("op").get<std::string>();
            if (operation == "position") PositionRequest(request, response);
            else if (operation == "ordering") OrderingRequest(request, response);
            else if (operation == "root") RootRequest(request, response);
            else if (operation == "replay") ReplayRequest(request, response);
            else throw std::invalid_argument("Unknown V12 diagnostic operation");
            response["ok"] = true;
        } catch (const std::exception& error) { response["error"] = error.what(); }
        response["check_count"] = checks;
        std::cout << response.dump(-1, ' ', false, Json::error_handler_t::replace) << std::endl;
    }
}
