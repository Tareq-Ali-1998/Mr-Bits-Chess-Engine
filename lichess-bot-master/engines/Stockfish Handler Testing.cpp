#include "stockfish Handler.hpp"

using namespace std;


int main() {

    cout << "##################################################\n";
    cout << "####        Stockfish Handler Testing         ####\n";
    cout << "##################################################\n\n";



    StockfishHandler stockfishHandler;
    string movesString = "g1f3 d7d5 c2c4 d5d4 g2g3 b8c6 d2d3 e7e5 f1g2 f8b4 b1d2 a7a5 e1g1 g8f6 f3e1 e8g8 a2a3 b4d6 a1b1 h7h6 b2b4 a5b4 a3b4 c6b4 d2e4 b4c6 e4f6 d8f6 g2e4 c6e7 c4c5 d6c5";

    long double NNUEPostionEvaluation = stockfishHandler.getNNUEPositionEvaluation(movesString);
    cout << "NNUE Postion Evaluation: " << NNUEPostionEvaluation << endl;

    cout << "Now the moves:" << endl;
    vector<string> possibleMoves = stockfishHandler.getAllPossibleMoves(movesString);
    for (const string& currentMove : possibleMoves) {
        movesString += " " + currentMove;
        NNUEPostionEvaluation = stockfishHandler.getNNUEPositionEvaluation(movesString);
        cout << "Move " << currentMove << " NNUE Postion Evaluation: " << NNUEPostionEvaluation << endl;
        for (int8_t i = 0; i < 5; i++) {
            movesString.pop_back();
        }
    }

    string bestMove = stockfishHandler.getBestMoveByDepth(movesString, 20);
    cout << endl << endl << "Best Move:" << bestMove;


    return 0;


    cout << "Possible moves: " << possibleMoves.size() << endl;
    if (possibleMoves.size()) {
        cout << "Moves are:\n";
    }
    for (const string& currentMove : possibleMoves) {
        cout << "  * " << currentMove << " ";
    }
    
    bool isTiePosition = stockfishHandler.isTiePosition(movesString);
    if (isTiePosition) {
        cout << "Tie position, Stalemate or Threefold repetition or another" << endl;
    }



    cout << "\n##################################################\n";
    return 0;
}