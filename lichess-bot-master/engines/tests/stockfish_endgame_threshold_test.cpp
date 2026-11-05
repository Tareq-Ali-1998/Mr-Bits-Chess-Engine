// Offline configuration/boundary checks. Never starts Stockfish, workers, a bot or a game.
#include "../Chess State.hpp"

void Require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

int main() {
    ChessState state;
    Require(state.getStockfishEndgameStartPly() == 1000000, "default must effectively disable endgame handoff");
    state.previousMoves.resize(101);
    Require(!state.isStockfishEndgame(), "ordinary game must not cross default threshold");

    state.setStockfishEndgameStartPly(100);
    for (int completedPlies : {0, 99, 100, 101, 102}) {
        state.previousMoves.resize(completedPlies);
        Require(state.isStockfishEndgame() == (completedPlies > 100), "strict boundary must be preserved for both colors");
    }

    state.previousMoves.clear();
    Require(state.getStockfishEndgameStartPly() == 100, "new move history must retain configured policy");
    Require(!state.isStockfishEndgame(), "empty history is not an endgame handoff");

    bool negativeRejected = false;
    try { state.setStockfishEndgameStartPly(-1); }
    catch (const std::invalid_argument&) { negativeRejected = true; }
    Require(negativeRejected && state.getStockfishEndgameStartPly() == 100,
            "invalid configuration must not replace the previous policy");

    state.setStockfishEndgameStartPly(0);
    Require(!state.isStockfishEndgame(), "zero still preserves strict threshold at empty history");
    state.previousMoves.resize(1);
    Require(state.isStockfishEndgame(), "zero enables handoff after the first completed ply");

    state.setStockfishEndgameStartPly(1000000);
    state.previousMoves.resize(150);
    Require(!state.isStockfishEndgame(), "controller can disable handoff again");
    std::cout << "PASS: Stockfish endgame threshold defaults, boundaries and validation\n";
}
