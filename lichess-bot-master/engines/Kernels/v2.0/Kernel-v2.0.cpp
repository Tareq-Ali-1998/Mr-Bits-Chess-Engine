
#include <windows.h>
#include <io.h>      // _setmode, _fileno
#include <fcntl.h>   // _O_BINARY

// ############################################################ \\

// ChessState (the same one as in Engine UCI), Json, ENGINE_NAME, rng, and "Stockfish Handler.hpp".
#include "Chess State.hpp"

// ############################################################ \\

#define MSB 63-__builtin_clzll

// ############################################################ \\

const int PIECE_VALUE[8] = {0, 100, 100, 300, 300, 500, 900, 10000000};
const int CHECKMATE_FLAG_SCORE_DIFFERENCE = 100000;

// ############################################################ \\

bool ENGINE_COLOR = 1;
int8_t board[8][8];
int16_t numberOfMovesOfThePieceOnThisSquare[8][8];
int engineScore;
int opponentScore;
long long whitePieces;
long long blackPieces;
vector<int16_t> previousMoves = {};
int8_t getPieceRowFromBit[64];
int8_t getPieceColumnFromBit[64];
int8_t getBitNumberFromItsRowAndColumn[8][8];
vector<vector<int16_t>> pieceSquaresTable[16];
vector<vector<int16_t>> preCalculatedMoves[8][8][8][2];

// ############################################################ \\

class ProcessHandler {

  private:
    int8_t engineDepth;
    int16_t bestEngineMove;
    int bestEngineMoveScore;
    chrono::time_point<chrono::high_resolution_clock> allProcessStartTime;
    chrono::time_point<chrono::high_resolution_clock> allProcessEndTime;
    chrono::time_point<chrono::high_resolution_clock> lastDepthStartTime;
    chrono::time_point<chrono::high_resolution_clock> lastDepthEndTime;
    int allowedTimeInMilliSeconds;
    long long theNumberOfAllStatesForEachDepth[51]; // That is a super dream, I mean the 51, but it's OK, LOL ;)
    long long theNumberOfPrunedBranchesForEachDepth[51];
    // Here by final states I mean the leaf nodes
    long long theNumberOfAllTheFinalStates;

  public:
    /*
     * Here in my default constructor "bestEngineMove" attribute is zero, and this moves indicates that there is
     * no move, like it's the NULL move, and the situation is a stalemate, and the default depth is 6 which is
     * very fast and relevant enough in terms of time and memory complexity.
     */
    // This is the default constructor
    ProcessHandler() : bestEngineMove(0), bestEngineMoveScore(0), engineDepth(6),
                       allProcessStartTime(chrono::high_resolution_clock::now()),
                       allProcessEndTime(chrono::high_resolution_clock::now()),
                       lastDepthStartTime(chrono::high_resolution_clock::now()),
                       lastDepthEndTime(chrono::high_resolution_clock::now()),
                       allowedTimeInMilliSeconds(10000),
                       theNumberOfAllTheFinalStates(0) {

        memset(this->theNumberOfAllStatesForEachDepth, 0, sizeof(this->theNumberOfAllStatesForEachDepth));
        memset(this->theNumberOfPrunedBranchesForEachDepth, 0, sizeof(this->theNumberOfPrunedBranchesForEachDepth));

    }

    // And this is the copy constructor
    ProcessHandler(const ProcessHandler& objectToCopy) {
        if (this != &objectToCopy) {

            this->engineDepth = objectToCopy.engineDepth;
            this->bestEngineMove = objectToCopy.bestEngineMove;
            this->bestEngineMoveScore = objectToCopy.bestEngineMoveScore;
            this->allProcessStartTime = objectToCopy.allProcessStartTime;
            this->allProcessEndTime = objectToCopy.allProcessEndTime;
            this->lastDepthStartTime = objectToCopy.lastDepthStartTime;
            this->lastDepthEndTime = objectToCopy.lastDepthEndTime;
            this->allowedTimeInMilliSeconds = objectToCopy.allowedTimeInMilliSeconds;
            this->theNumberOfAllTheFinalStates = objectToCopy.theNumberOfAllTheFinalStates;

            for (int8_t depth = 0; depth < 51; depth++) {
                this->theNumberOfAllStatesForEachDepth[depth] =
                    objectToCopy.theNumberOfAllStatesForEachDepth[depth];
                this->theNumberOfPrunedBranchesForEachDepth[depth] =
                    objectToCopy.theNumberOfPrunedBranchesForEachDepth[depth];
            }

        }
    }



    // And here are the setters of my class
    void setEngineDepth(const int8_t& engineDepthh) {
        this->engineDepth = engineDepthh;
    }

    void setBestEngineMove(const int16_t& bestEngineMove) {
        this->bestEngineMove = bestEngineMove;
    }

    void setBestEngineMoveScore(const int& bestEngineMoveScore) {
        this->bestEngineMoveScore = bestEngineMoveScore;
    }

    void setAllProcessStartTime() {
        this->allProcessStartTime = chrono::high_resolution_clock::now();
    }

    void setAllProcessEndTime() {
        this->allProcessEndTime = chrono::high_resolution_clock::now();
    }

    void setLastDepthCalculationStartTime() {
        this->lastDepthStartTime = chrono::high_resolution_clock::now();
    }

    void setLastDepthCalculationsEndTime() {
        this->lastDepthEndTime = chrono::high_resolution_clock::now();
    }

    void setAllowedTime(const int& allowedTimeInSeconds) {
        this->allowedTimeInMilliSeconds = allowedTimeInSeconds * 1000;
    }

    // A fixed-depth search (only in the tests) switches the clock off with INT_MAX milliseconds.
    void setAllowedTimeInMilliSeconds(const int& allowedTimeInMilliSeconds) {
        this->allowedTimeInMilliSeconds = allowedTimeInMilliSeconds;
    }



    // And here are the getters of my class
    int8_t getEngineDepth() const {
        return this->engineDepth;
    }

    int16_t getBestEngineMoveAsInt16_t() const {
        return this->bestEngineMove;
    }

    string getEngineBestMoveAsStandard() const {
        return this->convertMoveFromInt16_tToStandard(this->bestEngineMove);
    }

    int getBestEngineMoveScore() const {
        return this->bestEngineMoveScore;
    }

    chrono::time_point<chrono::high_resolution_clock> getAllProcessStartTime() const {
        return this->allProcessStartTime;
    }

    chrono::time_point<chrono::high_resolution_clock> getAllProcessEndTime() const {
        return this->allProcessEndTime;
    }

    int getProcessAllowedTimeInMilliSeconds () const {
        return this->allowedTimeInMilliSeconds;
    }

    int getTotalConsumedTimeInMilliSeconds() const {
        return chrono::duration_cast<chrono::milliseconds>(this->allProcessEndTime -
                                                           this->allProcessStartTime).count();
    }

    int getLastDepthCalculationConsumedTimeInMilliSeconds() const {
        return chrono::duration_cast<chrono::milliseconds>(this->lastDepthEndTime -
                                                           this->lastDepthStartTime).count();
    }


    long long getTheNumberOfAllTheInnerAndFinalStates() const {
        return accumulate(this->theNumberOfAllStatesForEachDepth, this->theNumberOfAllStatesForEachDepth + 51, 0);
    }

    long long getTheNumberOfAllTheFinalStates() const {
        return this->theNumberOfAllTheFinalStates;
    }

    // The raw counters, for the per-depth numbers of the answer. The index is the REMAINING depth of the
    // node (0 = a leaf), and the move-ordering searches inside the tree count into the same slots.
    long long getTheNumberOfStatesForACertainDepth(const int& depth) const {
        return this->theNumberOfAllStatesForEachDepth[depth];
    }

    long long getTheNumberOfPrunedBranchesForACertainDepth(const int& depth) const {
        return this->theNumberOfPrunedBranchesForEachDepth[depth];
    }

    // The same totals as the two old getters, but summed in 64 bits (those use accumulate(..., 0), so they
    // sum in int and would wrap above 2,147,483,647 nodes).
    long long getTheNumberOfAllTheInnerAndFinalStatesAs64Bit() const {
        return accumulate(this->theNumberOfAllStatesForEachDepth, this->theNumberOfAllStatesForEachDepth + 51, 0LL);
    }

    long long getTheNumberOfAllTheBrunedBranchesAs64Bit() const {
        return accumulate(this->theNumberOfPrunedBranchesForEachDepth,
                          this->theNumberOfPrunedBranchesForEachDepth + 51, 0LL);
    }

    long long getTheNumberOfAllTheInnerStates() const {
        return this->getTheNumberOfAllTheInnerAndFinalStates() - this->getTheNumberOfAllTheFinalStates();
    }

    long long getTheNumberOfAllTheBrunedBranches() const {
        return accumulate(this->theNumberOfPrunedBranchesForEachDepth,
                          this->theNumberOfPrunedBranchesForEachDepth + 51, 0);
    }

    long double getTheNumberOfallCalculatedStatesInASecond() const {
        cout << setprecision(5) << fixed;
        return ((((long double)(this->getTheNumberOfAllTheInnerAndFinalStates())) /
                (this->getLastDepthCalculationConsumedTimeInMilliSeconds())) *
                (1000));
    }



    // And here are the class functions
    void increaseTheNumberOfStatesForACertainDepth(const int8_t& depth) {
        this->theNumberOfAllStatesForEachDepth[depth]++;
    }

    void increaseTheNumberOfFinalStates() {
        this->theNumberOfAllTheFinalStates++;
    }

    void increaseTheNumberOfPrunedBranchesForACertainDepth(const int8_t& depth) {
        this->theNumberOfPrunedBranchesForEachDepth[depth]++;
    }

    /*
     * I should follow the standards again and implement this member function again taking into account
     * all the special moves.
     */
    string convertMoveFromInt16_tToStandard(const int16_t& correspondingMove) const {

        int8_t rowFrom = correspondingMove & 7;
        int8_t columnFrom = (correspondingMove >> 3) & 7;
        int8_t rowTo = (correspondingMove >> 6) & 7;
        int8_t columnTo = (correspondingMove >> 9) & 7;

        string standardMove = "";
        standardMove += (char)(((int)('a')) + columnFrom);
        standardMove += (char)(((int)('8')) - rowFrom);
        standardMove += (char)(((int)('a')) + columnTo);
        standardMove += (char)(((int)('8')) - rowTo);

        int8_t moveType = (correspondingMove >> 12) & 7;
        if (moveType == 1) {
            standardMove += 'q';
        }
        else if (moveType == 2) {
            standardMove += 'n';
        }
        else if (moveType == 6) {
            standardMove += 'r';
        }
        else if (moveType == 7) {
            standardMove += 'b';
        }

        return standardMove;

    }

    /*
     * I should follow the standards again and implement this member function again taking into account
     * all the special moves.
     */
    int16_t convertMoveFromStandardToInt16_t(const string& correspondingMove,
                                              const vector<vector<int8_t>>& currentChessBoard) {

        int16_t columnFrom = correspondingMove[0] - 'a';
        int16_t rowFrom = 8 - (correspondingMove[1] - '0');
        int16_t columnTo = correspondingMove[2] - 'a';
        int16_t rowTo = 8 - (correspondingMove[3] - '0');

        int16_t moveType = 0;
        // And it should be a king also
        if (((currentChessBoard[rowFrom][columnFrom] & 7) == 7) && ((correspondingMove == "e1g1") || (correspondingMove == "e8g8"))) {
            moveType = 4;
        }
        else if (((currentChessBoard[rowFrom][columnFrom] & 7) == 7) && ((correspondingMove == "e1c1") || (correspondingMove == "e8c8"))) {
            moveType = 5;
        }
        else if (correspondingMove.size() == 5) {
            if (correspondingMove.back() == 'q') {
                moveType = 1;
            }
            else if (correspondingMove.back() == 'n') {
                moveType = 2;
            }
            else if (correspondingMove.back() == 'r') {
                moveType = 6;
            }
            else if (correspondingMove.back() == 'b') {
                moveType = 7;
            }
        }
        else if (((currentChessBoard[rowFrom][columnFrom] & 7) == 1) &&
            (columnFrom != columnTo) &&
            (!(currentChessBoard[rowTo][columnTo] & 7))){

            moveType = 3;

        }

        return ((rowFrom) | (columnFrom << 3) | (rowTo << 6) | (columnTo << 9) | (moveType << 12));

    }

    bool processTimeExceeded() const {
        return (chrono::duration_cast<chrono::milliseconds>(chrono::high_resolution_clock::now() -
                this->getAllProcessStartTime()).count() >= this->allowedTimeInMilliSeconds);
    }

    void showFinalReport() {
        cout << "Final Report:" << endl;
        cout << "  The current depth: " << (int16_t)(this->getEngineDepth()) << endl;
        cout << "  The total Process consumed time in milliseconds: " << this->getTotalConsumedTimeInMilliSeconds() << endl;
        cout << "  The last reached depth (depth " << (int16_t)(this->getEngineDepth()) << ") consumed time in milliseconds: " << this->getLastDepthCalculationConsumedTimeInMilliSeconds() << endl;
        cout << "  The number of all the final states (Leaf Nodes): " << this->getTheNumberOfAllTheFinalStates() << endl;
        cout << "  The number of all the inner states: " << this->getTheNumberOfAllTheInnerStates() << endl;
        cout << "  The number of all the inner and final states: " << this->getTheNumberOfAllTheInnerAndFinalStates() << endl;
        cout << "  The number of all calculated states in one second: " << this->getTheNumberOfallCalculatedStatesInASecond() << endl;
        cout << "  The number of all pruned branches: " << this->getTheNumberOfAllTheBrunedBranches() << endl;
        cout << "  The Engine's best move: " << this->getEngineBestMoveAsStandard() << endl;
        cout << "  The Engine's best move score: " << this->getBestEngineMoveScore() << endl;

    }

    string getFinalReportAsString() {

        string s = "Final Report:\n";

        s += "  The current depth: ";
        s += to_string((int16_t)(this->getEngineDepth()));
        s += "\n";

        s += "  The total Process consumed time in milliseconds: ";
        s += to_string(this->getTotalConsumedTimeInMilliSeconds());
        s += "\n";

        s += "  The last reached depth (depth ";
        s += to_string((int16_t)(this->getEngineDepth()));
        s +=  ") consumed time in milliseconds: ";
        s += to_string(this->getLastDepthCalculationConsumedTimeInMilliSeconds());
        s += "\n";

        s += "  The number of all the final states (Leaf Nodes): ";
        s += to_string(this->getTheNumberOfAllTheFinalStates());
        s += "\n";

        s += "  The number of all the inner states: ";
        s += to_string(this->getTheNumberOfAllTheInnerStates());
        s += "\n";

        s += "  The number of all the inner and final states: ";
        s += to_string(this->getTheNumberOfAllTheInnerAndFinalStates());
        s += "\n";

        s += "  The number of all calculated states in one second: ";
        s += to_string(this->getTheNumberOfallCalculatedStatesInASecond());
        s += "\n";

        s += "  The number of all pruned branches: ";
        s += to_string(this->getTheNumberOfAllTheBrunedBranches());
        s += "\n";

        s += "  The Engine's best move: ";
        s += this->getEngineBestMoveAsStandard();
        s += "\n";

        s += "  The Engine's best move score: ";
        s += to_string(this->getBestEngineMoveScore());
        s += "\n";

        return s;

    }

    void resetObjectArraysAndFinalStates() {

        memset(this->theNumberOfAllStatesForEachDepth, 0, sizeof(this->theNumberOfAllStatesForEachDepth));
        memset(this->theNumberOfPrunedBranchesForEachDepth, 0, sizeof(this->theNumberOfPrunedBranchesForEachDepth));
        this->theNumberOfAllTheFinalStates = 0;

    }

    // The following is the part of operator overloading, like the assignment and equality operators
    ProcessHandler operator=(const ProcessHandler& objectToAssignTo) {

        if (this != &objectToAssignTo) {
            this->engineDepth = objectToAssignTo.engineDepth;
            this->bestEngineMove = objectToAssignTo.bestEngineMove;
            this->bestEngineMoveScore = objectToAssignTo.bestEngineMoveScore;
            this->allProcessStartTime = objectToAssignTo.allProcessStartTime;
            this->allProcessEndTime = objectToAssignTo.allProcessEndTime;
            this->lastDepthStartTime = objectToAssignTo.lastDepthStartTime;
            this->lastDepthEndTime = objectToAssignTo.lastDepthEndTime;
            this->allowedTimeInMilliSeconds = objectToAssignTo.allowedTimeInMilliSeconds;
            this->theNumberOfAllTheFinalStates = objectToAssignTo.theNumberOfAllTheFinalStates;

            for (int8_t depth = 0; depth < 51; depth++) {
                this->theNumberOfAllStatesForEachDepth[depth] =
                    objectToAssignTo.theNumberOfAllStatesForEachDepth[depth];
                this->theNumberOfPrunedBranchesForEachDepth[depth] =
                    objectToAssignTo.theNumberOfPrunedBranchesForEachDepth[depth];
            }
        }

        // Enabling chain assignment by returning (*this)
        return *this;

    }

    bool operator==(const ProcessHandler& otherObject) const {

        if (this->engineDepth != otherObject.engineDepth)
            return false;
        if (this->bestEngineMove != otherObject.bestEngineMove)
            return false;
        if (this->bestEngineMoveScore != otherObject.bestEngineMoveScore)
            return false;
        if (this->allProcessStartTime != otherObject.allProcessStartTime)
            return false;
        if (this->allProcessEndTime != otherObject.allProcessEndTime)
            return false;
        if (this->lastDepthStartTime != otherObject.lastDepthStartTime)
            return false;
        if (this->lastDepthEndTime != otherObject.lastDepthEndTime)
            return false;
        if (this->allowedTimeInMilliSeconds != otherObject.allowedTimeInMilliSeconds) {
            return false;
        }
        if (this->theNumberOfAllTheFinalStates != otherObject.theNumberOfAllTheFinalStates) {
            return false;
        }

        for (int8_t depth = 0; depth < 51; depth++) {
            if (this->theNumberOfAllStatesForEachDepth[depth] !=
                otherObject.theNumberOfAllStatesForEachDepth[depth])
                return false;
            if (this->theNumberOfPrunedBranchesForEachDepth[depth] !=
                otherObject.theNumberOfPrunedBranchesForEachDepth[depth])
                return false;
        }

        return true;
    }

} processHandler;

/*
 * Currently, there is one problem with my Trie, which is the castling special move, and I can handle
 * that easily, but I am not using the Trie anymore, because it seems that checking for board cycles will
 * lead to more impact with alpha-beta pruning, and slow down the whole process, and I have tested that a lot
 * in every way.
 */
#include "Trie.hpp"

Trie myTrieForCheckingForBoardCycles[2];

// ############################################################ \\

void PrintTheBoard() {

    for (int8_t row = 0; row < 8; row++) {
        for (int8_t column = 0; column < 8; column++) {
            if (board[row][column] & 7) {
                if (board[row][column] & 8) {
                    cout << "W";
                }
                else {
                    cout << "B";
                }
            }
            else {
                cout << ".";
            }
        }
        cout << endl;
    }

    cout << endl;
}

void InitializeEngineScore() {

    engineScore = 0;
    for (int8_t row = 0; row < 8; row++) {
        for (int8_t column = 0; column < 8; column++) {
            if (!(board[row][column] & 7)) {
                continue;
            }
            bool currentPieceColor = (board[row][column] & 8) ? 1 : 0;
            if (currentPieceColor == ENGINE_COLOR) {
                engineScore += PIECE_VALUE[board[row][column] & 7];
                engineScore += pieceSquaresTable[board[row][column] & 15][row][column];
            }
        }
    }

}

void InitializeOpponentScore() {

    opponentScore = 0;
    for (int8_t row = 0; row < 8; row++) {
        for (int8_t column = 0; column < 8; column++) {
            if (!(board[row][column] & 7)) {
                continue;
            }
            bool currentPieceColor = (board[row][column] & 8) ? 1 : 0;
            if (currentPieceColor != ENGINE_COLOR) {
                opponentScore += PIECE_VALUE[board[row][column] & 7];
                opponentScore += pieceSquaresTable[board[row][column] & 15][row][column];
            }
        }
    }

}

void BoardInitialization() {

    for (int8_t row = 0; row < 8; row++) {
        for (int8_t column = 0; column < 8; column++) {
            board[row][column] = 0;
            numberOfMovesOfThePieceOnThisSquare[row][column] = 0;
        }
    }

    // Initializing black pieces
    board[0][0] = 5; // 00000101: Black Rook
    board[0][1] = 3; // 00000011: Black Knight
    board[0][2] = 4; // 00000100: Black Bishop
    board[0][3] = 6; // 00000110: Black Queen
    board[0][4] = 7; // 00000111: Black King
    board[0][5] = 4; // 00000100: Black Bishop
    board[0][6] = 3; // 00000011: Black Knight
    board[0][7] = 5; // 00000101: Black Rook


    for (int8_t column = 0; column < 8; column++) {
        board[1][column] = 1; // 00000001: Black Pawn
    }


    // Initializing white pieces
    board[7][0] = 13; // 00001101: White Rook
    board[7][1] = 11; // 00001011: White Knight
    board[7][2] = 12; // 00001100: White Bishop
    board[7][3] = 14; // 00001110: White Queen
    board[7][4] = 15; // 00001111: White King
    board[7][5] = 12; // 00001100: White Bishop
    board[7][6] = 11; // 00001011: White Knight
    board[7][7] = 13; // 00001101: White Rook;

    for (int8_t column = 0; column < 8; column++) {
        board[6][column] = 9; // 00001001: White Pawn
    }

}

void BitToSquareAndViceVersaInitialization() {

    int8_t bitNumber = 0;
    for (int row = 0; row < 8; row++) {
        for (int column = 0; column < 8; column++) {
            getPieceRowFromBit[bitNumber] = row;
            getPieceColumnFromBit[bitNumber] = column;
            getBitNumberFromItsRowAndColumn[row][column] = bitNumber;
            bitNumber++;
        }
    }

}

bool ValidSquare(const int8_t& row, const int8_t& column) {

    return ((row >= 0) && (row < 8) && (column >= 0) && (column < 8));

}

void MovesPreCalculation() {

    // This function calculates all the possible moves for a piece in which we know its type, row,
    // column, and color (and here actually the color is important only when calculating the moves
    // of a pawn) assuming that the rest of the board squares are all empty, so finally
    // for each piece we have some number of vectors of move series, where for each one of
    // those inner vectors, we will iterate over all its moves till we find another piece on our way, then we will
    // stop iterating over the rest of the moves of this inner vector in order to just visit the actual important
    // squares (like in the bishop, rook, and queen cases, where they can with some line meet a piece on their way and
    // then stop) when calling the function "GetMovesForThisPieceFunction" that consider also the board information, and
    // then start with a new series of moves (I mean a new inner vector of moves) for that piece.

    // This function does not take into account the three special moves which are castling, "en passant", and
    // the pawn promotion, and I am considering those special moves in my other function
    // "GetMovesForThisPieceFunction" for sure, and the reason behind that is that I need the board details more
    // to check and to handle those special moves.

    // I need this function in order to maintain a better time complexity for calculating the moves, instead
    // of calculating them each time, I have like a guide that will cost the code less in terms of time complexity.
    for (int16_t pieceRow = 0; pieceRow < 8; pieceRow++) {
        for (int16_t pieceColumn = 0; pieceColumn < 8; pieceColumn++) {
            for (int16_t pieceType = 1; pieceType < 8; pieceType++) {

                if (pieceType == 2) {
                    // Currently this piece means nothing in my logic, it was an idea as a flag of a pawn
                    // that is ready to be taken with the "en passant" special move, but for now, I am not
                    // using it in any logic or functionality with my code, so that's why "continue;".
                    continue;
                }

                // Here with the pawns, and since the moves will be better to be in a single vector, I did that
                if (pieceType == 1) {

                    // Handling all the black pawns potential moves
                    vector<int16_t> movesSeriesVector;
                    bool pieceColor = 0;
                    int16_t currentMove;
                    int16_t newColumn = pieceColumn - 1;
                    int16_t newRow = pieceRow + 1;
                    if (ValidSquare(newRow, newColumn)) {
                        currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newColumn = pieceColumn + 1;
                    newRow = pieceRow + 1;
                    if (ValidSquare(newRow, newColumn)) {
                        currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newColumn = pieceColumn;
                    newRow = pieceRow + 1;
                    if (ValidSquare(newRow, newColumn)) {
                        currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    if (pieceRow == 1) {
                        newColumn = pieceColumn;
                        newRow = pieceRow + 2;
                        if (ValidSquare(newRow, newColumn)) {
                            currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                            movesSeriesVector.push_back(currentMove);
                        }
                    }
                    preCalculatedMoves[pieceType][pieceRow][pieceColumn][pieceColor].push_back(movesSeriesVector);

                    // Handling all the white pawns potential moves
                    movesSeriesVector.clear();
                    pieceColor = 1;
                    currentMove;
                    newColumn = pieceColumn - 1;
                    newRow = pieceRow - 1;
                    if (ValidSquare(newRow, newColumn)) {
                        currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newColumn = pieceColumn + 1;
                    newRow = pieceRow - 1;
                    if (ValidSquare(newRow, newColumn)) {
                        currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newColumn = pieceColumn;
                    newRow = pieceRow - 1;
                    if (ValidSquare(newRow, newColumn)) {
                        currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    if (pieceRow == 6) {
                        newColumn = pieceColumn;
                        newRow = pieceRow - 2;
                        if (ValidSquare(newRow, newColumn)) {
                            currentMove = pieceRow | (pieceColumn << 3) | (newRow << 6) | (newColumn << 9);
                            movesSeriesVector.push_back(currentMove);
                        }
                    }
                    preCalculatedMoves[pieceType][pieceRow][pieceColumn][pieceColor].push_back(movesSeriesVector);

                }

                // Here with the night, and since the moves will be better to be in a single vector, I did that
                if (pieceType == 3) {

                    vector<int16_t> movesSeriesVector;
                    int16_t newRow = pieceRow - 2;
                    int16_t newColumn = pieceColumn -1;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);

                    }

                    newRow = pieceRow - 2;
                    newColumn = pieceColumn +1;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newRow = pieceRow - 1;
                    newColumn = pieceColumn -2;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newRow = pieceRow - 1;
                    newColumn = pieceColumn +2;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newRow = pieceRow + 1;
                    newColumn = pieceColumn -2;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newRow = pieceRow + 1;
                    newColumn = pieceColumn +2;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newRow = pieceRow + 2;
                    newColumn = pieceColumn -1;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }

                    newRow = pieceRow + 2;
                    newColumn = pieceColumn +1;
                    if (ValidSquare(newRow, newColumn)) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[3][pieceRow][pieceColumn][0].push_back(movesSeriesVector);
                    preCalculatedMoves[3][pieceRow][pieceColumn][1].push_back(movesSeriesVector);

                }

                // This is the bishop
                if (pieceType == 4) {

                    vector<int16_t> movesSeriesVector;
                    for (int16_t newRow = pieceRow - 1, newColumn = pieceColumn - 1;
                                 (newRow >= 0) && (newColumn >= 0); newRow--, newColumn--) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[4][pieceRow][pieceColumn][0].push_back(movesSeriesVector);

                    movesSeriesVector.clear();
                    for (int16_t newRow = pieceRow - 1, newColumn = pieceColumn + 1;
                                 (newRow >= 0) && (newColumn < 8); newRow--, newColumn++) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[4][pieceRow][pieceColumn][0].push_back(movesSeriesVector);

                    movesSeriesVector.clear();
                    for (int16_t newRow = pieceRow + 1, newColumn = pieceColumn - 1;
                                 (newRow < 8) && (newColumn >= 0); newRow++, newColumn--) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[4][pieceRow][pieceColumn][0].push_back(movesSeriesVector);


                    movesSeriesVector.clear();
                    for (int16_t newRow = pieceRow + 1, newColumn = pieceColumn + 1;
                                 (newRow < 8) && (newColumn < 8); newRow++, newColumn++) {
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[4][pieceRow][pieceColumn][0].push_back(movesSeriesVector);

                    preCalculatedMoves[4][pieceRow][pieceColumn][1] = preCalculatedMoves[4][pieceRow][pieceColumn][0];

                }

                // And here is the rook
                if (pieceType == 5) {

                    vector<int16_t> movesSeriesVector;
                    for (int16_t newRow = pieceRow + 1; newRow < 8; newRow++) {
                        int16_t newColumn = pieceColumn;
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[5][pieceRow][pieceColumn][0].push_back(movesSeriesVector);


                    movesSeriesVector.clear();
                    for (int16_t newRow = pieceRow - 1; newRow >= 0; newRow--) {
                        int16_t newColumn = pieceColumn;
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[5][pieceRow][pieceColumn][0].push_back(movesSeriesVector);


                    movesSeriesVector.clear();
                    for (int16_t newColumn = pieceColumn + 1; newColumn < 8; newColumn++) {
                        int16_t newRow = pieceRow;
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[5][pieceRow][pieceColumn][0].push_back(movesSeriesVector);


                    movesSeriesVector.clear();
                    for (int16_t newColumn = pieceColumn - 1; newColumn >= 0; newColumn--) {
                        int16_t newRow = pieceRow;
                        int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                        movesSeriesVector.push_back(currentMove);
                    }
                    preCalculatedMoves[5][pieceRow][pieceColumn][0].push_back(movesSeriesVector);
                    preCalculatedMoves[5][pieceRow][pieceColumn][1] = preCalculatedMoves[5][pieceRow][pieceColumn][0];

                }

                // And this is the queen
                if (pieceType == 6) {
                    // The queen moves are actually the combination of the bishop and the rook moves
                    preCalculatedMoves[6][pieceRow][pieceColumn][0] = preCalculatedMoves[4][pieceRow][pieceColumn][0];
                    for (const vector<int16_t>& movesRowVector : preCalculatedMoves[5][pieceRow][pieceColumn][0]) {
                        preCalculatedMoves[6][pieceRow][pieceColumn][0].push_back(movesRowVector);
                    }
                    preCalculatedMoves[6][pieceRow][pieceColumn][1] = preCalculatedMoves[6][pieceRow][pieceColumn][0];

                }

                // Here with the king, and since the moves will be better to be in a single vector, I did that
                if (pieceType == 7) {

                    vector<int16_t> movesSeriesVector;
                    for (int16_t newRow = pieceRow - 1; newRow <= pieceRow + 1; newRow++) {
                        for (int16_t newColumn = pieceColumn - 1; newColumn <= pieceColumn + 1; newColumn++) {
                            if ((pieceRow == newRow) && (pieceColumn == newColumn)) {
                                continue;
                            }
                            if (!ValidSquare(newRow, newColumn)) {
                                continue;
                            }

                            int16_t currentMove = pieceRow + (pieceColumn << 3) + (newRow << 6) + (newColumn << 9);
                            movesSeriesVector.push_back(currentMove);
                        }
                    }
                    preCalculatedMoves[7][pieceRow][pieceColumn][0].push_back(movesSeriesVector);
                    preCalculatedMoves[7][pieceRow][pieceColumn][1].push_back(movesSeriesVector);

                }

            }
        }
    }

}

void PieceSquaresTableInitialization() {

    // Here I might implement a single one for each phase of the game, thinking about it obviously says that
    // at the end game for example, this will add a lot of advantages
    for (int8_t piece = 8; piece < 16; piece++) {

        int8_t pieceType = piece & 7;

        if (pieceType == 0) {
            vector<vector<int16_t>> helperVector(8, vector<int16_t>(8, 0));
            pieceSquaresTable[piece] = helperVector;
        }
        else if (pieceType == 1) {
            pieceSquaresTable[piece] = {
                                        {0,  0,  0,  0,  0,  0,  0,  0},
                                        {50, 50, 50, 50, 50, 50, 50, 50},
                                        {10, 10, 20, 30, 30, 20, 10, 10},
                                        {5,  5, 10, 25, 25, 10,  5,  5},
                                        {0,  0,  0, 20, 20,  0,  0,  0},
                                        {5, -5,-10,  0,  0,-10, -5,  5},
                                        {5, 10, 10,-20,-20, 10, 10,  5},
                                        {0,  0,  0,  0,  0,  0,  0,  0},
                                       };
        }
        else if (pieceType == 2) {
            // Just ignore that, there is not such piece right now
            continue;
        }
        else if (pieceType == 3) {
            pieceSquaresTable[piece] = {
                                        {-50,-40,-30,-30,-30,-30,-40,-50},
                                        {-40,-20,  0,  0,  0,  0,-20,-40},
                                        {-30,  0, 10, 15, 15, 10,  0,-30},
                                        {-30,  5, 15, 20, 20, 15,  5,-30},
                                        {-30,  0, 15, 20, 20, 15,  0,-30},
                                        {-30,  5, 10, 15, 15, 10,  5,-30},
                                        {-40,-20,  0,  5,  5,  0,-20,-40},
                                        {-50,-40,-30,-30,-30,-30,-40,-50},
                                       };
        }
        else if (pieceType == 4) {
            pieceSquaresTable[piece] = {
                                        {-20,-10,-10,-10,-10,-10,-10,-20},
                                        {-10,  0,  0,  0,  0,  0,  0,-10},
                                        {-10,  0,  5, 10, 10,  5,  0,-10},
                                        {-10,  5,  5, 10, 10,  5,  5,-10},
                                        {-10,  0, 10, 10, 10, 10,  0,-10},
                                        {-10, 10, 10, 10, 10, 10, 10,-10},
                                        {-10,  5,  0,  0,  0,  0,  5,-10},
                                        {-20,-10,-10,-10,-10,-10,-10,-20},
                                       };
        }
        else if (pieceType == 5) {
            pieceSquaresTable[piece] = {
                                        {0,  0,  0,  0,  0,  0, 0,  0},
                                        {5, 10, 10, 10, 10, 10, 10, 5},
                                        {-5,  0,  0,  0,  0,  0, 0, -5},
                                        {-5,  0,  0,  0,  0,  0, 0, -5},
                                        {-5,  0,  0,  0,  0,  0, 0, -5},
                                        {-5,  0,  0,  0,  0,  0, 0, -5},
                                        {-5,  0,  0,  0,  0,  0, 0, -5},
                                        {0,  0,  0,  5,  5,  0, 0,  0},
                                       };
        }
        else if (pieceType == 6) {
            pieceSquaresTable[piece] = {
                                        {-20,-10,-10, -5, -5,-10,-10,-20},
                                        {-10,  0,  0,  0,  0,  0,  0,-10},
                                        {-10,  0,  5,  5,  5,  5,  0,-10},
                                        {-5,  0,  5,  5,  5,  5,  0, -5},
                                        {0,  0,  5,  5,  5,  5,  0, -5},
                                        {-10,  5,  5,  5,  5,  5,  0,-10},
                                        {-10,  0,  5,  0,  0,  0,  0,-10},
                                        {-20,-10,-10, -5, -5,-10,-10,-20},
                                       };
        }
        else {
            pieceSquaresTable[piece] = {
                                        {-30,-40,-40,-50,-50,-40,-40,-30},
                                        {-30,-40,-40,-50,-50,-40,-40,-30},
                                        {-30,-40,-40,-50,-50,-40,-40,-30},
                                        {-30,-40,-40,-50,-50,-40,-40,-30},
                                        {-20,-30,-30,-40,-40,-30,-30,-20},
                                        {-10,-20,-20,-20,-20,-20,-20,-10},
                                        {20, 20,  0,  0,  0,  0, 20, 20},
                                        {20, 30, 10,  0,  0, 10, 30, 20},
                                       };
        }

        pieceSquaresTable[piece ^ 8] = pieceSquaresTable[piece];
        reverse(pieceSquaresTable[piece ^ 8].begin(), pieceSquaresTable[piece ^ 8].end());

    }

}

bool IsSafeSquareForCastling(const int8_t& row,
                             const int8_t& column,
                             const bool& opponentColor,
                             const bool& castlingType) {

    // This function assumes that the squares between the king and the rook are definitely empty
    if (opponentColor) {

        // Checking opponent's king and pawns threatening
        if (ValidSquare(row + 1, column - 1) &&
            ((board[row + 1][column - 1] == 9) || (board[row + 1][column - 1] == 15))) {

            return 0;

        }
        if (ValidSquare(row + 1, column) &&
            (board[row + 1][column] == 15)) {

            return 0;

        }
        if (ValidSquare(row + 1, column + 1) &&
            ((board[row + 1][column + 1] == 9) || (board[row + 1][column + 1] == 15))) {

            return 0;

        }

        // Now checking for opponent's Knights threatening
        if (ValidSquare(row + 2, column - 1) && (board[row + 2][column - 1] == 11)) {
            return 0;
        }
        if (ValidSquare(row + 2, column + 1) && (board[row + 2][column + 1] == 11)) {
            return 0;
        }
        if (ValidSquare(row + 1, column - 2) && (board[row + 1][column - 2] == 11)) {
            return 0;
        }
        if (ValidSquare(row + 1, column + 2) && (board[row + 1][column + 2] == 11)) {
            return 0;
        }

        // Then two diagonals and one horizontal line, Queen for the three of them and it's too clear for the rest
        int8_t currentColumn;
        for (int8_t currentRow = 1; currentRow < 7; currentRow++) {
            currentColumn = column + currentRow;
            if (ValidSquare(currentRow, currentColumn)) {
                if ((board[currentRow][currentColumn] & 7) && (opponentColor == ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    if (((board[currentRow][currentColumn] & 7) == 4) || ((board[currentRow][currentColumn] & 7) == 6)) {
                        return 0;
                    }
                    else {
                        break;
                    }
                }
                else if ((board[currentRow][currentColumn] & 7) && (opponentColor != ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    break;
                }
            }
            else {
                break;
            }
        }

        for (int8_t currentRow = 1; currentRow < 7; currentRow++) {
            currentColumn = column - currentRow;
            if (ValidSquare(currentRow, currentColumn)) {
                if ((board[currentRow][currentColumn] & 7) && (opponentColor == ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    if (((board[currentRow][currentColumn] & 7) == 4) || ((board[currentRow][currentColumn] & 7) == 6)) {
                        return 0;
                    }
                    else {
                        break;
                    }
                }
                else if ((board[currentRow][currentColumn] & 7) && (opponentColor != ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    break;
                }
            }
            else {
                break;
            }
        }

        for (int8_t currentRow = 1; currentRow < 7; currentRow++) {
            if (ValidSquare(currentRow, column)) {
                if ((board[currentRow][column] & 7) && (opponentColor == ((board[currentRow][column] & 8) ? 1 : 0))) {
                    if (((board[currentRow][column] & 7) == 5) || ((board[currentRow][column] & 7) == 6)) {
                        return 0;
                    }
                    else {
                        break;
                    }
                }
                else if ((board[currentRow][column] & 7) && (opponentColor != ((board[currentRow][column] & 8) ? 1 : 0))) {
                    break;
                }
            }
            else {
                break;
            }
        }

        // This means it's a short castling for Black
        if (castlingType) {

            for (int8_t currentColumn = 3; currentColumn >= 0; currentColumn--) {
                if ((board[0][currentColumn] == 14) || (board[0][currentColumn] == 13)) {
                    return 0;
                }
                if (board[0][currentColumn]) {
                    break;
                }
            }

        }
        // And this means that it's a long castling for Black
        else {
            for (int8_t currentColumn = 5; currentColumn < 8; currentColumn++) {
                if ((board[0][currentColumn] == 14) || (board[0][currentColumn] == 13)) {
                    return 0;
                }
                if (board[0][currentColumn]) {
                    break;
                }
            }
        }

    }
    else {

        // Checking opponent's king and pawns threatening
        if (ValidSquare(row - 1, column - 1) && ((board[row - 1][column - 1] == 1) || (board[row - 1][column - 1] == 7))) {
            return 0;
        }
        if (ValidSquare(row - 1, column) && (board[row - 1][column] == 7)) {
            return 0;
        }
        if (ValidSquare(row - 1, column + 1) && ((board[row - 1][column + 1] == 1) || (board[row - 1][column + 1] == 7))) {
            return 0;
        }

        // Now checking for opponent's Knights threatening
        if (ValidSquare(row - 2, column - 1) && (board[row - 2][column - 1] == 3)) {
            return 0;
        }
        if (ValidSquare(row - 2, column + 1) && (board[row - 2][column + 1] == 3)) {
            return 0;
        }
        if (ValidSquare(row - 1, column - 2) && (board[row - 1][column - 2] == 3)) {
            return 0;
        }
        if (ValidSquare(row - 1, column + 2) && (board[row - 1][column + 2] == 3)) {
            return 0;
        }

        // Then two diagonals and one horizontal line, Queen for the three of them and it's too clear for the rest
        int8_t currentColumn = column;
        for (int8_t currentRow = 6; currentRow >= 0; currentRow--) {
            currentColumn++;
            if (ValidSquare(currentRow, currentColumn)) {
                if ((board[currentRow][currentColumn] & 7) && (opponentColor == ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    if (((board[currentRow][currentColumn] & 7) == 4) || ((board[currentRow][currentColumn] & 7) == 6)) {
                        return 0;
                    }
                    else {
                        break;
                    }
                }
                else if ((board[currentRow][currentColumn] & 7) && (opponentColor != ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    break;
                }
            }
            else {
                break;
            }
        }

        currentColumn = column;
        for (int8_t currentRow = 6; currentRow >= 0; currentRow--) {
            currentColumn--;
            if (ValidSquare(currentRow, currentColumn)) {
                if ((board[currentRow][currentColumn] & 7) && (opponentColor == ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    if (((board[currentRow][currentColumn] & 7) == 4) || ((board[currentRow][currentColumn] & 7) == 6)) {
                        return 0;
                    }
                    else {
                        break;
                    }
                }
                else if ((board[currentRow][currentColumn] & 7) && (opponentColor != ((board[currentRow][currentColumn] & 8) ? 1 : 0))) {
                    break;
                }
            }
            else {
                break;
            }
        }

        for (int8_t currentRow = 6; currentRow >= 0; currentRow--) {
            if (ValidSquare(currentRow, column)) {
                if ((board[currentRow][column] & 7) && (opponentColor == ((board[currentRow][column] & 8) ? 1 : 0))) {
                    if (((board[currentRow][column] & 7) == 5) || ((board[currentRow][column] & 7) == 6)) {
                        return 0;
                    }
                    else {
                        break;
                    }
                }
                else if ((board[currentRow][column] & 7) && (opponentColor != ((board[currentRow][column] & 8) ? 1 : 0))) {
                    break;
                }
            }
            else {
                break;
            }
        }

        // This means it's a short castling for White
        if (castlingType) {

            for (int8_t currentColumn = 3; currentColumn >= 0; currentColumn--) {
                if ((board[7][currentColumn] == 6) || (board[7][currentColumn] == 7)) {
                    return 0;
                }
                if (board[7][currentColumn]) {
                    break;
                }
            }

        }
        // And this means that it's a long castling for White
        else {
            for (int8_t currentColumn = 5; currentColumn < 8; currentColumn++) {
                if ((board[7][currentColumn] == 6) || (board[7][currentColumn] == 7)) {
                    return 0;
                }
                if (board[7][currentColumn]) {
                    break;
                }
            }
        }

    }

    return 1;

}

vector<int16_t> GetMovesForThisPiece(const int8_t& piece,
                                     const int8_t& pieceRow,
                                     const int8_t& pieceColumn,
                                     const int16_t& previousMove) {

    vector<int16_t> pieceMoves;
    int8_t pieceType = piece & 7;
    bool pieceColor = (piece & 8) ? 1 : 0;

    if (pieceType == 1) {

        for (const int16_t& currentMove : preCalculatedMoves[pieceType][pieceRow][pieceColumn][pieceColor][0]) {

                int8_t destinationRow = (currentMove >> 6) & 7;
                int8_t destinationColumn = (currentMove >> 9) & 7;
                int8_t destinationPieceType = board[destinationRow][destinationColumn] & 7;
                bool destinationPieceColor = (board[destinationRow][destinationColumn] & 8) ? 1 : 0;

                // When the pawn will capture an opponent piece
                if ((pieceColumn != destinationColumn) &&
                    (destinationPieceType) &&
                    (pieceColor != destinationPieceColor)) {

                    if ((destinationRow == 0) || (destinationRow == 7)) {
                            pieceMoves.push_back(currentMove | (1 << 12)); // This means a promotion to a Queen
                            pieceMoves.push_back(currentMove | (2 << 12)); // This means a promotion to a Knight
                            pieceMoves.push_back(currentMove | (6 << 12)); // This means a promotion to a Rook
                            pieceMoves.push_back(currentMove | (7 << 12)); // This means a promotion to a Bishop
                    }
                    else {
                        pieceMoves.push_back(currentMove);
                    }


                }
                else if ((pieceColumn != destinationColumn) &&
                         (pieceRow == ((previousMove >> 6) & 7)) &&
                         (destinationColumn == ((previousMove >> 9) & 7)) &&
                         (!destinationPieceType) &&
                         ((board[(previousMove >> 6) & 7][(previousMove >> 9) & 7] & 7) == 1) &&
                         (numberOfMovesOfThePieceOnThisSquare[(previousMove >> 6) & 7][(previousMove >> 9) & 7] == 1)) {

                    // Here, I am handling the "en passant" special move
                    pieceMoves.push_back(currentMove | (3 << 12));

                }
                else if (pieceColumn == destinationColumn) {

                    if (((int)(abs(pieceRow - destinationRow))) == 1) {

                        if (!destinationPieceType) {

                            if ((destinationRow == 0) || (destinationRow == 7)) {
                                pieceMoves.push_back(currentMove | (1 << 12)); // This means a promotion to a Queen
                                pieceMoves.push_back(currentMove | (2 << 12)); // This means a promotion to a Knight
                                pieceMoves.push_back(currentMove | (6 << 12)); // This means a promotion to a Rook
                                pieceMoves.push_back(currentMove | (7 << 12)); // This means a promotion to a Bishop
                            }
                            else {
                                pieceMoves.push_back(currentMove);
                            }

                        }
                        else {
                            break;
                        }

                    }
                    else {

                        if (!(board[destinationRow][destinationColumn] & 7)) {
                            pieceMoves.push_back(currentMove);
                        }

                    }
                }

        }

        return pieceMoves;

    }
    else if ((pieceType == 3) || (pieceType == 7)) {

        for (const int16_t& currentMove : preCalculatedMoves[pieceType][pieceRow][pieceColumn][pieceColor][0]) {

                int8_t destinationRow = (currentMove >> 6) & 7;
                int8_t destinationColumn = (currentMove >> 9) & 7;
                int8_t destinationPieceType = board[destinationRow][destinationColumn] & 7;
                if (destinationPieceType != 0) {

                    bool destinationPieceColor = (board[destinationRow][destinationColumn] & 8) ? 1 : 0;
                    if (pieceColor != destinationPieceColor) {
                        pieceMoves.push_back(currentMove);
                    }
                    continue;

                }
                pieceMoves.push_back(currentMove);

        }

        // And here I am handling the castling special move
        if ((pieceType == 7) &&
            (!numberOfMovesOfThePieceOnThisSquare[pieceRow][pieceColumn])) {

            if (pieceColor) {

                // Short castling for white
                if ((!board[7][5]) &&
                    (!board[7][6]) &&
                    ((board[7][7] & 7) == 5) &&
                    (!numberOfMovesOfThePieceOnThisSquare[7][7]) &&
                    (IsSafeSquareForCastling(7, 6, !pieceColor, 1)) &&
                    (IsSafeSquareForCastling(7, 5, !pieceColor, 1)) &&
                    (IsSafeSquareForCastling(7, 4, !pieceColor, 1))) {

                    pieceMoves.push_back(pieceRow | (pieceColumn << 3) | (7 << 6) | (6 << 9) | (4 << 12));

                }
                // Long castling for white
                if ((!board[7][3]) &&
                    (!board[7][2]) &&
                    (!board[7][1]) &&
                    ((board[7][0] & 7) == 5) &&
                    (!numberOfMovesOfThePieceOnThisSquare[7][0]) &&
                    (IsSafeSquareForCastling(7, 1, !pieceColor, 0)) &&
                    (IsSafeSquareForCastling(7, 2, !pieceColor, 0)) &&
                    (IsSafeSquareForCastling(7, 3, !pieceColor, 0)) &&
                    (IsSafeSquareForCastling(7, 4, !pieceColor, 0))) {

                    pieceMoves.push_back(pieceRow | (pieceColumn << 3) | (7 << 6) | (2 << 9) | (5 << 12));

                }

            }
            else {

                // Short castling for black
                if ((!board[0][5]) &&
                    (!board[0][6]) &&
                    ((board[0][7] & 7) == 5) &&
                    (!numberOfMovesOfThePieceOnThisSquare[0][7]) &&
                    (IsSafeSquareForCastling(0, 6, !pieceColor, 1)) &&
                    (IsSafeSquareForCastling(0, 5, !pieceColor, 1)) &&
                    (IsSafeSquareForCastling(0, 4, !pieceColor, 1))) {

                    pieceMoves.push_back(pieceRow | (pieceColumn << 3) | (6 << 9) | (4 << 12));

                }
                // Long castling for black
                if ((!board[0][3]) &&
                    (!board[0][2]) &&
                    (!board[0][1]) &&
                    ((board[0][0] & 7) == 5) &&
                    (!numberOfMovesOfThePieceOnThisSquare[0][0]) &&
                    (IsSafeSquareForCastling(0, 1, !pieceColor, 0)) &&
                    (IsSafeSquareForCastling(0, 2, !pieceColor, 0)) &&
                    (IsSafeSquareForCastling(0, 3, !pieceColor, 0)) &&
                    (IsSafeSquareForCastling(0, 4, !pieceColor, 0))) {

                    pieceMoves.push_back(pieceRow | (pieceColumn << 3) | (2 << 9) | (5 << 12));

                }

            }

        }

        return pieceMoves;

    }


    // This is for the Queen, Rook, and Bishop pieces
    for (const vector<int16_t>& movesVectorRow : preCalculatedMoves[pieceType][pieceRow]
                                                                   [pieceColumn][pieceColor]) {

        for (const int& currentMove : movesVectorRow) {

            int8_t destinationRow = (currentMove >> 6) & 7;
            int8_t destinationColumn = (currentMove >> 9) & 7;
            int8_t destinationPieceType = board[destinationRow][destinationColumn] & 7;
            if (destinationPieceType != 0) {

                bool destinationPieceColor = (board[destinationRow][destinationColumn] & 8) ? 1 : 0;
                if (pieceColor != destinationPieceColor) {
                    pieceMoves.push_back(currentMove);
                }
                break;

            }
            pieceMoves.push_back(currentMove);

        }

    }

    return pieceMoves;

}

// All the following function can be enhanced but I should be very careful because it couldn't
// pretend a lot of computations, so I will try to play with some of its params to decrease the
// time complexity.
void SortTheMovesWithMySimpleHeuristic(vector<int16_t>& moves) {

    if (moves.size() == 0) {
        return;
    }

    // Exactly here in this point of the code, I will shuffle the moves randomly
    // instead of my simple heuristic sorting.
    // It's worth it to try that one.
    // srand(time(0));
    // random_shuffle(moves.begin(), moves.end());
    // return;

    vector<pair<int, int16_t>> movesSortingHelperVector(moves.size(), {0, 0});
    for (int16_t i = 0; i < moves.size(); i++) {

        int moveType = (moves[i] >> 12) & 7;
        int8_t sourcePieceRow = moves[i] & 7;
        int8_t sourcePieceColumn = (moves[i] >> 3) & 7;
        int8_t destinationPieceRow = (moves[i] >> 6) & 7;
        int8_t destinationPieceColumn = (moves[i] >> 9) & 7;
        int8_t sourcePieceType = board[sourcePieceRow][sourcePieceColumn] & 7;
        int8_t destinationPieceType = board[destinationPieceRow][destinationPieceColumn] & 7;

        switch (moveType) {
            case 0: {
                // Normal move
                if (destinationPieceType) {

                    // Lol, now my Heuristic function encourages trading pieces, in various ways.
                    movesSortingHelperVector[i].first += ((PIECE_VALUE[destinationPieceType]) - PIECE_VALUE[sourcePieceType]) * 2;
                    /*
                    if (PIECE_VALUE[destinationPieceType] < PIECE_VALUE[sourcePieceType]) {
                        movesSortingHelperVector[i].first += (PIECE_VALUE[destinationPieceType]) - PIECE_VALUE[sourcePieceType];
                    }
                    else if (PIECE_VALUE[destinationPieceType] == PIECE_VALUE[sourcePieceColumn]) {
                        movesSortingHelperVector[i].first += (PIECE_VALUE[destinationPieceType] << 1) - PIECE_VALUE[sourcePieceType];
                    }
                    else {
                        movesSortingHelperVector[i].first += (PIECE_VALUE[destinationPieceType] << 2) - PIECE_VALUE[sourcePieceType];
                    }
                    */
                }

                movesSortingHelperVector[i].first += (pieceSquaresTable[board[sourcePieceRow][sourcePieceColumn] & 15][destinationPieceRow][destinationPieceColumn] -
                                                      pieceSquaresTable[board[sourcePieceRow][sourcePieceColumn] & 15][sourcePieceRow][sourcePieceColumn]);
                break;
            }
            case 1:
                // Promoting to a Queen
                movesSortingHelperVector[i].first = 1000;
                break;
            case 2:
                // Promoting to a Knight
                movesSortingHelperVector[i].first = 500;
                break;
            case 3:
                // The "en passant" special move
                movesSortingHelperVector[i].first = 250;
                break;
            case 4:
                // Short castling
                movesSortingHelperVector[i].first = 175;
                break;
            case 5:
                // Long castling
                movesSortingHelperVector[i].first = 150;
                break;
            case 6:
                // Promoting to a Rook
                movesSortingHelperVector[i].first = 500;
                break;
            case 7:
                // Promoting to a Bishop
                movesSortingHelperVector[i].first = 300;
                break;
            default:
                // Actually the code shouldn't ever reach this point so I will
                // do nothing, or I will assert(true) to make sure of that.
                assert(false); // Runtime error here if moveType is not 0–7
                break;
        }

        movesSortingHelperVector[i] = {movesSortingHelperVector[i].first, moves[i]};

    }

    sort(movesSortingHelperVector.begin(), movesSortingHelperVector.end(), greater<pair<int, int16_t>>());
    for (int16_t i = 0; i < moves.size(); i++) {
        moves[i] = movesSortingHelperVector[i].second;
    }

}

// I think the following function has been implemented successfully, but it might contain some bugs.
void MakeChanges(const int16_t& currentMove) {

    int8_t moveType = (currentMove >> 12) & 15;
    int8_t sourcePieceRow = currentMove & 7;
    int8_t sourcePieceColumn = (currentMove >> 3) & 7;
    int8_t destinationPieceRow = (currentMove >> 6) & 7;
    int8_t destinationPieceColumn = (currentMove >> 9) & 7;
    int8_t sourcePieceType = board[sourcePieceRow][sourcePieceColumn] & 7;
    int8_t destinationPieceType = board[destinationPieceRow][destinationPieceColumn] & 7;
    bool sourcePieceColor = (board[sourcePieceRow][sourcePieceColumn] & 8) ? 1 : 0;

    if (moveType == 0) {

        if (sourcePieceColor) {
            // Here I can make an optimization to make just only one XOR for the white pieces using a precalculated
            // array
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {
                int opponentScoreCopy = opponentScore;
                opponentScore -= (PIECE_VALUE[destinationPieceType] + pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn]);
                engineScore += pieceSquaresTable[sourcePieceType | 8][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[sourcePieceType | 8][sourcePieceRow][sourcePieceColumn];

            }
            else {
                engineScore -= PIECE_VALUE[destinationPieceType] + pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];
                opponentScore += pieceSquaresTable[sourcePieceType | 8][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[sourcePieceType | 8][sourcePieceRow][sourcePieceColumn];
            }


        }
        else {

            // Here I can make an optimization to make just only one XOR for the black pieces using a precalculated
            // array
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {
                engineScore -= PIECE_VALUE[destinationPieceType] + pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];
                opponentScore += pieceSquaresTable[sourcePieceType][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[sourcePieceType][sourcePieceRow][sourcePieceColumn];
            }
            else {
                opponentScore -= PIECE_VALUE[destinationPieceType] + pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];
                engineScore += pieceSquaresTable[sourcePieceType][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[sourcePieceType][sourcePieceRow][sourcePieceColumn];
            }

        }

        board[destinationPieceRow][destinationPieceColumn] = board[sourcePieceRow][sourcePieceColumn];
        numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
        board[sourcePieceRow][sourcePieceColumn] = 0;
        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

    }
    else if (moveType == 4) {

        if (sourcePieceColor) {
            // I can make all of these XORs in one XOR operation
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[7][7]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[7][5]);

            if (ENGINE_COLOR) {
                engineScore += pieceSquaresTable[7 | 8][7][6] - pieceSquaresTable[7 | 8][7][4] + pieceSquaresTable[5 | 8][7][5] - pieceSquaresTable[5 | 8][7][7];
            }
            else {
                opponentScore += pieceSquaresTable[7 | 8][7][6] - pieceSquaresTable[7 | 8][7][4] + pieceSquaresTable[5 | 8][7][5] - pieceSquaresTable[5 | 8][7][7];
            }


            board[7][6] = board[7][4];
            board[7][4] = 0;
            board[7][5] = board[7][7];
            board[7][7] = 0;
            numberOfMovesOfThePieceOnThisSquare[7][6] = 1;
            numberOfMovesOfThePieceOnThisSquare[7][5] = 1;

        }
        else {
            // I can make all of these XORs in one XOR operation
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[0][7]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[0][5]);

            if (ENGINE_COLOR) {
                opponentScore += pieceSquaresTable[7][0][6] - pieceSquaresTable[7][0][4] + pieceSquaresTable[5][0][5] - pieceSquaresTable[5][0][7];
            }
            else {
                engineScore += pieceSquaresTable[7][0][6] - pieceSquaresTable[7][0][4] + pieceSquaresTable[5][0][5] - pieceSquaresTable[5][0][7];
            }

            board[0][6] = board[0][4];
            board[0][4] = 0;
            board[0][5] = board[0][7];
            board[0][7] = 0;
            numberOfMovesOfThePieceOnThisSquare[0][6] = 1;
            numberOfMovesOfThePieceOnThisSquare[0][5] = 1;

        }

    }
    else if (moveType == 5) {

        if (sourcePieceColor) {
            // I can make all of these XORs in one XOR operation
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[7][0]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[7][3]);

            if (ENGINE_COLOR) {
                engineScore += pieceSquaresTable[7 | 8][7][2] - pieceSquaresTable[7 | 8][7][4] + pieceSquaresTable[5 | 8][7][3] - pieceSquaresTable[5 | 8][7][0];
            }
            else {
                opponentScore += pieceSquaresTable[7 | 8][7][2] - pieceSquaresTable[7 | 8][7][4] + pieceSquaresTable[5 | 8][7][3] - pieceSquaresTable[5 | 8][7][0];
            }


            board[7][2] = board[7][4];
            board[7][4] = 0;
            board[7][3] = board[7][0];
            board[7][0] = 0;
            numberOfMovesOfThePieceOnThisSquare[7][2] = 1;
            numberOfMovesOfThePieceOnThisSquare[7][3] = 1;

        }
        else {
            // I can make all of these XORs in one XOR operation
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[0][0]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[0][3]);

            if (ENGINE_COLOR) {
                opponentScore += pieceSquaresTable[7][0][2] - pieceSquaresTable[7][0][4] + pieceSquaresTable[5][0][3] - pieceSquaresTable[5][0][0];
            }
            else {
                engineScore += pieceSquaresTable[7][0][2] - pieceSquaresTable[7][0][4] + pieceSquaresTable[5][0][3] - pieceSquaresTable[5][0][0];
            }

            board[0][2] = board[0][4];
            board[0][4] = 0;
            board[0][3] = board[0][0];
            board[0][0] = 0;
            numberOfMovesOfThePieceOnThisSquare[0][2] = 1;
            numberOfMovesOfThePieceOnThisSquare[0][3] = 1;


        }

    }
    else if (moveType == 1) {

        //.. Promoting to a Queen
        if (sourcePieceColor) {

            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                engineScore += PIECE_VALUE[6] - PIECE_VALUE[1] +
                               pieceSquaresTable[6 | 8][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }
            else {

                opponentScore += PIECE_VALUE[6] - PIECE_VALUE[1] +
                                 pieceSquaresTable[6 | 8][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 6 | 8;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }
        else {

            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                opponentScore += PIECE_VALUE[6] - PIECE_VALUE[1] +
                                 pieceSquaresTable[6][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];


            }
            else {

                engineScore += PIECE_VALUE[6] - PIECE_VALUE[1] +
                               pieceSquaresTable[6][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 6;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }

    }
    else if (moveType == 3) {

        // "en passant" special move
        if (sourcePieceColor) {

            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][destinationPieceColumn]);

            if (ENGINE_COLOR) {
                engineScore += pieceSquaresTable[1 | 8][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];
                opponentScore -= PIECE_VALUE[1] + pieceSquaresTable[1][sourcePieceRow][destinationPieceColumn];
            }
            else {
                opponentScore += pieceSquaresTable[1 | 8][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];
                engineScore -= PIECE_VALUE[1] + pieceSquaresTable[1][sourcePieceRow][destinationPieceColumn];
            }

            board[destinationPieceRow][destinationPieceColumn] = board[sourcePieceRow][sourcePieceColumn];
            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[sourcePieceRow][destinationPieceColumn] = 0;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                             numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][destinationPieceColumn] = 0;


        }
        else {

            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][destinationPieceColumn]);

            if (ENGINE_COLOR) {
                opponentScore += pieceSquaresTable[1 | 8][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];
                engineScore -= PIECE_VALUE[1] + pieceSquaresTable[1][sourcePieceRow][destinationPieceColumn];
            }
            else {
                engineScore += pieceSquaresTable[1 | 8][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];
                opponentScore -= PIECE_VALUE[1] + pieceSquaresTable[1][sourcePieceRow][destinationPieceColumn];
            }

            board[destinationPieceRow][destinationPieceColumn] = board[sourcePieceRow][sourcePieceColumn];
            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[sourcePieceRow][destinationPieceColumn] = 0;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                             numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][destinationPieceColumn] = 0;

        }

    }
    else if (moveType == 2) {

        //.. Promoting to a Knight
        if (sourcePieceColor) {

            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                engineScore += PIECE_VALUE[3] - PIECE_VALUE[1] +
                               pieceSquaresTable[3 | 8][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }
            else {

                opponentScore += PIECE_VALUE[3] - PIECE_VALUE[1] +
                                 pieceSquaresTable[3 | 8][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 3 | 8;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }
        else {

            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                opponentScore += PIECE_VALUE[3] - PIECE_VALUE[1] +
                                 pieceSquaresTable[3][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];


            }
            else {

                engineScore += PIECE_VALUE[3] - PIECE_VALUE[1] +
                               pieceSquaresTable[3][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 3;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }

    }
    else if (moveType == 6) {

        //.. Promoting to a Rook
        if (sourcePieceColor) {

            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                engineScore += PIECE_VALUE[5] - PIECE_VALUE[1] +
                               pieceSquaresTable[5 | 8][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }
            else {

                opponentScore += PIECE_VALUE[5] - PIECE_VALUE[1] +
                                 pieceSquaresTable[5 | 8][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 5 | 8;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }
        else {

            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                opponentScore += PIECE_VALUE[5] - PIECE_VALUE[1] +
                                 pieceSquaresTable[5][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];


            }
            else {

                engineScore += PIECE_VALUE[5] - PIECE_VALUE[1] +
                               pieceSquaresTable[5][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 5;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }

    }
    else if (moveType == 7) {

        //.. Promoting to a Bishop
        if (sourcePieceColor) {

            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                engineScore += PIECE_VALUE[4] - PIECE_VALUE[1] +
                               pieceSquaresTable[4 | 8][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }
            else {

                opponentScore += PIECE_VALUE[4] - PIECE_VALUE[1] +
                                 pieceSquaresTable[4 | 8][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1 | 8][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 4 | 8;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }
        else {

            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[sourcePieceRow][sourcePieceColumn]);
            blackPieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            if (destinationPieceType) {
                whitePieces ^= (1ll << getBitNumberFromItsRowAndColumn[destinationPieceRow][destinationPieceColumn]);
            }

            if (ENGINE_COLOR) {

                opponentScore += PIECE_VALUE[4] - PIECE_VALUE[1] +
                                 pieceSquaresTable[4][destinationPieceRow][destinationPieceColumn] -
                                 pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                engineScore -= PIECE_VALUE[destinationPieceType] +
                               pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];


            }
            else {

                engineScore += PIECE_VALUE[4] - PIECE_VALUE[1] +
                               pieceSquaresTable[4][destinationPieceRow][destinationPieceColumn] -
                               pieceSquaresTable[1][sourcePieceRow][sourcePieceColumn];

                opponentScore -= PIECE_VALUE[destinationPieceType] +
                                 pieceSquaresTable[destinationPieceType | 8][destinationPieceRow][destinationPieceColumn];

            }

            board[sourcePieceRow][sourcePieceColumn] = 0;
            board[destinationPieceRow][destinationPieceColumn] = 4;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] =
                                        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] + 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] = 0;

        }

    }



}

// I think the following function has been implemented successfully, but it might contain some bugs.
void ReturnChanges(const int16_t& currentMove, const int8_t& takenPiece, const int16_t& takenPieceNumberOfMoves) {

    int8_t moveType = (currentMove >> 12) & 15;
    int8_t sourcePieceRow = currentMove & 7;
    int8_t sourcePieceColumn = (currentMove >> 3) & 7;
    int8_t destinationPieceRow = (currentMove >> 6) & 7;
    int8_t destinationPieceColumn = (currentMove >> 9) & 7;

    if (moveType == 0) {

        numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
        board[sourcePieceRow][sourcePieceColumn] = board[destinationPieceRow][destinationPieceColumn];
        board[destinationPieceRow][destinationPieceColumn] = takenPiece;
        numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

    }
    else if (moveType == 4) {

        bool sourcePieceColor = (board[destinationPieceRow][destinationPieceColumn] & 8) ? 1 : 0;
        if (sourcePieceColor) {

            board[7][4] = board[7][6];
            board[7][6] = 0;
            board[7][7] = board[7][5];
            board[7][5] = 0;
            numberOfMovesOfThePieceOnThisSquare[7][6] = 0;
            numberOfMovesOfThePieceOnThisSquare[7][5] = 0;

        }
        else {

            board[0][4] = board[0][6];
            board[0][6] = 0;
            board[0][7] = board[0][5];
            board[0][5] = 0;
            numberOfMovesOfThePieceOnThisSquare[0][6] = 0;
            numberOfMovesOfThePieceOnThisSquare[0][5] = 0;

        }

    }
    else if (moveType == 5) {

        bool sourcePieceColor = (board[destinationPieceRow][destinationPieceColumn] & 8) ? 1 : 0;
        if (sourcePieceColor) {

            board[7][4] = board[7][2];
            board[7][2] = 0;
            board[7][0] = board[7][3];
            board[7][3] = 0;
            numberOfMovesOfThePieceOnThisSquare[7][2] = 0;
            numberOfMovesOfThePieceOnThisSquare[7][3] = 0;

        }
        else {

            board[0][4] = board[0][2];
            board[0][2] = 0;
            board[0][0] = board[0][3];
            board[0][3] = 0;
            numberOfMovesOfThePieceOnThisSquare[0][2] = 0;
            numberOfMovesOfThePieceOnThisSquare[0][3] = 0;

        }

    }
    else if (moveType == 1) {
        // Promoting to a Queen
        bool sourcePieceColor = (board[destinationPieceRow][destinationPieceColumn] & 8) ? 1 : 0;
        if (sourcePieceColor) {

            board[sourcePieceRow][sourcePieceColumn] = 1 | 8;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }
        else {

            board[sourcePieceRow][sourcePieceColumn] = 1;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }

    }
    else if (moveType == 3) {
        // "en passant" special move

        bool sourcePieceColor = (board[destinationPieceRow][destinationPieceColumn] & 8) ? 1 : 0;
        if (sourcePieceColor) {

            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][destinationPieceColumn] = 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                                      numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = 0;
            board[sourcePieceRow][sourcePieceColumn] = board[destinationPieceRow][destinationPieceColumn];
            board[destinationPieceRow][destinationPieceColumn] = 0;
            board[sourcePieceRow][destinationPieceColumn] = 1;

        }
        else {

            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][destinationPieceColumn] = 1;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                                      numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = 0;
            board[sourcePieceRow][sourcePieceColumn] = board[destinationPieceRow][destinationPieceColumn];
            board[destinationPieceRow][destinationPieceColumn] = 0;
            board[sourcePieceRow][destinationPieceColumn] = 1 | 8;

        }

    }
    else if (moveType == 2) {

        // Promoting to a Knight
        bool sourcePieceColor = (board[destinationPieceRow][destinationPieceColumn] & 8) ? 1 : 0;
        if (sourcePieceColor) {

            board[sourcePieceRow][sourcePieceColumn] = 1 | 8;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }
        else {

            board[sourcePieceRow][sourcePieceColumn] = 1;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }

    }
    else if (moveType == 6) {

        // Promoting to a Rook
        bool sourcePieceColor = (board[destinationPieceRow][destinationPieceColumn] & 8) ? 1 : 0;
        if (sourcePieceColor) {

            board[sourcePieceRow][sourcePieceColumn] = 1 | 8;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }
        else {

            board[sourcePieceRow][sourcePieceColumn] = 1;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }

    }
    else if (moveType == 7) {

        // Promoting to a Bishop
        bool sourcePieceColor = (board[destinationPieceRow][destinationPieceColumn] & 8) ? 1 : 0;
        if (sourcePieceColor) {

            board[sourcePieceRow][sourcePieceColumn] = 1 | 8;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }
        else {

            board[sourcePieceRow][sourcePieceColumn] = 1;
            board[destinationPieceRow][destinationPieceColumn] = takenPiece;
            numberOfMovesOfThePieceOnThisSquare[sourcePieceRow][sourcePieceColumn] =
                            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] - 1;
            numberOfMovesOfThePieceOnThisSquare[destinationPieceRow][destinationPieceColumn] = takenPieceNumberOfMoves;

        }

    }



}

// Shared neural sort/load/rollback helpers; v4 selects only Small on its active search path.
#include "Neural Networks/Move Ordering.hpp"

void SortTheMovesWithLargeNeuralNetwork(vector<int16_t>& moves) {
    if (moves.empty()) return;
    mrbits::kernel_neural::SortMoves(moves, mrbits::kernel_neural::LargeModel());
}

void SortTheMovesWithSmallNeuralNetwork(vector<int16_t>& moves) {
    if (moves.empty()) return;
    mrbits::kernel_neural::SortMoves(moves, mrbits::kernel_neural::SmallModel());
}

// Returns a White-perspective score in pawn units for the supplied position.
float EvaluatePositionWithSmallNeuralNetwork(const int8_t (&position)[8][8], const mrbits::nn::State& state) {
    return mrbits::kernel_neural::EvaluateSmallPosition(position, state);
}

// Returns a White-perspective score in pawn units for the supplied position.
float EvaluatePositionWithLargeNeuralNetwork(const int8_t (&position)[8][8], const mrbits::nn::State& state) {
    return mrbits::kernel_neural::EvaluateLargePosition(position, state);
}

namespace v4_policy {
constexpr int small_ordering_min_depth = 6;
constexpr double legacy_evaluation_weight = 0.0;
constexpr double small_neural_evaluation_weight = 100.0;
constexpr int non_terminal_score_limit = CHECKMATE_FLAG_SCORE_DIFFERENCE - 1;
static_assert(legacy_evaluation_weight >= 0 && small_neural_evaluation_weight >= 0 &&
              legacy_evaluation_weight + small_neural_evaluation_weight > 0,
              "Leaf weights must be nonnegative with a positive sum");

constexpr bool ShouldOrder(const int depth) noexcept {
    return depth >= small_ordering_min_depth;
}

mrbits::nn::State LeafState(const bool turn, const int16_t previousMove) noexcept {
    // turn means engine-to-move, whereas the NN flag means White-to-move.
    const bool whiteToMove = turn == ENGINE_COLOR;
    mrbits::nn::State state{whiteToMove, mrbits::kernel_neural::CastlingRights(), -1};
    const auto move = static_cast<uint16_t>(previousMove);
    const int sr = move & 7, sc = (move >> 3) & 7;
    const int dr = (move >> 6) & 7, dc = (move >> 9) & 7;
    const bool previousWhite = !whiteToMove;
    const int previousPawn = 1 | (previousWhite ? 8 : 0);
    if (((move >> 12) & 15) == 0 && sc == dc &&
        (board[dr][dc] & 15) == previousPawn &&
        ((previousWhite && sr == 6 && dr == 4) || (!previousWhite && sr == 1 && dr == 3))) {
        // Preserve a double-push EP target even without a legal EP capture.
        state.ep_file = static_cast<int8_t>(dc);
    }
    return state;
}

int BlendLeafScores(const int legacyEngineCp, const float neuralWhitePawns,
                    const bool engineWhite, const double legacyWeight, const double neuralWeight) {
    const double total = legacyWeight + neuralWeight;
    if (!std::isfinite(legacyWeight) || !std::isfinite(neuralWeight) ||
        legacyWeight < 0 || neuralWeight < 0 || !std::isfinite(total) || total <= 0) {
        throw invalid_argument("Leaf weights must be finite, nonnegative, and have a positive sum");
    }
    if (neuralWeight > 0 && !std::isfinite(neuralWhitePawns)) {
        throw runtime_error("Small neural evaluation produced a non-finite leaf score");
    }
    const double neuralEngineCp = neuralWeight > 0
        ? static_cast<double>(neuralWhitePawns) * 100.0 * (engineWhite ? 1.0 : -1.0) : 0.0;
    const double blended = (legacyWeight / total) * legacyEngineCp + (neuralWeight / total) * neuralEngineCp;
    const double bounded = std::clamp(blended, -static_cast<double>(non_terminal_score_limit),
                                    static_cast<double>(non_terminal_score_limit));
    return static_cast<int>(std::lround(bounded));
}

// Called only after the search has handled its existing exact terminal score.
int EvaluateLeaf(const bool turn, const int16_t previousMove) {
    const int legacyEngineCp = engineScore - opponentScore;
    float neuralWhitePawns = 0.0f;
    if constexpr (small_neural_evaluation_weight > 0) {
        neuralWhitePawns = EvaluatePositionWithSmallNeuralNetwork(board, LeafState(turn, previousMove));
    }
    return BlendLeafScores(legacyEngineCp, neuralWhitePawns, ENGINE_COLOR,
                           legacy_evaluation_weight, small_neural_evaluation_weight);
}
} // namespace v4_policy

int MagicForIterativeDeepening(const int8_t& depth, const bool& turn, const int16_t& previousMove, int alpha, int beta) {

    // I am using the following one because it's too important because have I realized that some
    // threads exceeds the process allowed time, and currently I guess the problem is caused because
    // the following condition was missing.
    if (processHandler.processTimeExceeded()) {
        return 0;
    }

    processHandler.increaseTheNumberOfStatesForACertainDepth(depth);
    // Preserve the existing exact king-capture terminal mechanism before approximate evaluation.
    if ((abs(engineScore - opponentScore)) > CHECKMATE_FLAG_SCORE_DIFFERENCE) {
        processHandler.increaseTheNumberOfFinalStates();
        return (engineScore - opponentScore);
    }
    if (depth == 0) {
        processHandler.increaseTheNumberOfFinalStates();
        return v4_policy::EvaluateLeaf(turn, previousMove);
    }

    vector<int16_t> allPossibleMoves;
    if (((turn && ENGINE_COLOR)) || (((!turn)) && (!ENGINE_COLOR))) {

        long long whitePiecesCopy = whitePieces;
        while (whitePiecesCopy) {
            int8_t mostSignificantBit = MSB(whitePiecesCopy);
            whitePiecesCopy ^= (1ll << mostSignificantBit);
            int8_t currentPiece = board[getPieceRowFromBit[mostSignificantBit]]
                                       [getPieceColumnFromBit[mostSignificantBit]];
            vector<int16_t> currentMoves = GetMovesForThisPiece(currentPiece, getPieceRowFromBit[mostSignificantBit],
                                                                getPieceColumnFromBit[mostSignificantBit], previousMove);
            allPossibleMoves.insert(allPossibleMoves.end(), currentMoves.begin(), currentMoves.end());
        }

        // The following case indicates a stalemate
        if (allPossibleMoves.size() == 0) {
            processHandler.increaseTheNumberOfFinalStates();
            return 0;
        }

    }
    else {

        long long blackPiecesCopy = blackPieces;
        while (blackPiecesCopy) {
            int8_t mostSignificantBit = MSB(blackPiecesCopy);
            blackPiecesCopy ^= (1ll << mostSignificantBit);
            int8_t currentPiece = board[getPieceRowFromBit[mostSignificantBit]]
                                                          [getPieceColumnFromBit[mostSignificantBit]];
            vector<int16_t> currentMoves = GetMovesForThisPiece(currentPiece, getPieceRowFromBit[mostSignificantBit],
                                                                getPieceColumnFromBit[mostSignificantBit], previousMove);
            allPossibleMoves.insert(allPossibleMoves.end(), currentMoves.begin(), currentMoves.end());
        }

        // The following case indicates a stalemate
        if (allPossibleMoves.size() == 0) {
            processHandler.increaseTheNumberOfFinalStates();
            return 0;
        }

    }

    if (v4_policy::ShouldOrder(depth)) {
        SortTheMovesWithSmallNeuralNetwork(allPossibleMoves);
    }

    int currentScore = turn ? INT_MIN : INT_MAX;
    for (const int16_t& currentMove : allPossibleMoves) {

        int8_t takenPiece = board[(currentMove >> 6) & 7][(currentMove >> 9) & 7];
        int16_t numberOfMovesOfTheTakenPiece = numberOfMovesOfThePieceOnThisSquare[(currentMove >> 6) & 7]
                                                                                  [(currentMove >> 9) & 7];
        long long whitePiecesBeforeCommittingTheCurrentMove = whitePieces;
        long long blackPiecesBeforeCommittingTheCurrentMove = blackPieces;
        int engineScoreBeforeCommittingTheCurrentMove = engineScore;
        int opponentScoreBeforeCommittingTheCurrentMove = opponentScore;
        MakeChanges(currentMove);
        int correspondingScore = MagicForIterativeDeepening(depth - 1, !turn, currentMove, alpha, beta);
        whitePieces = whitePiecesBeforeCommittingTheCurrentMove;
        blackPieces = blackPiecesBeforeCommittingTheCurrentMove;
        engineScore = engineScoreBeforeCommittingTheCurrentMove;
        opponentScore = opponentScoreBeforeCommittingTheCurrentMove;
        ReturnChanges(currentMove, takenPiece, numberOfMovesOfTheTakenPiece);

        if (turn) {
            currentScore = max(currentScore, correspondingScore);
            alpha = max(alpha, correspondingScore);
        }
        else {
            currentScore = min(currentScore, correspondingScore);
            beta = min(beta, correspondingScore);
        }

        if (beta <= alpha) {
            processHandler.increaseTheNumberOfPrunedBranchesForACertainDepth(depth);
            break;
        }

    }

    return currentScore;

}

void SortTheMovesAccordingToIterativeDeepening(const int8_t& depth, const bool& turn,
    vector<int16_t>& currentMoves) {

    if (currentMoves.size() == 0) {
        return;
    }

    if (depth <= 0) {
        return;
    }

    SortTheMovesWithMySimpleHeuristic(currentMoves);

    int alpha = INT_MIN;
    int beta = INT_MAX;
    vector<pair<int, int16_t>> allPossibleMovesSortingHelperVector;
    int16_t previousMove = previousMoves.size() ? previousMoves.back() : 0;

    for (const int16_t& currentMove : currentMoves) {

        int8_t takenPiece = board[(currentMove >> 6) & 7][(currentMove >> 9) & 7];
        int16_t numberOfMovesOfTheTakenPiece = numberOfMovesOfThePieceOnThisSquare[(currentMove >> 6) & 7]
                                                                                  [(currentMove >> 9) & 7];
        long long whitePiecesBeforeCommittingTheCurrentMove = whitePieces;
        long long blackPiecesBeforeCommittingTheCurrentMove = blackPieces;
        int engineScoreBeforeCommittingTheCurrentMove = engineScore;
        int opponentScoreBeforeCommittingTheCurrentMove = opponentScore;
        MakeChanges(currentMove);
        int correspondingScore = MagicForIterativeDeepening(depth - 1, !turn, currentMove, alpha, beta);
        whitePieces = whitePiecesBeforeCommittingTheCurrentMove;
        blackPieces = blackPiecesBeforeCommittingTheCurrentMove;
        engineScore = engineScoreBeforeCommittingTheCurrentMove;
        opponentScore = opponentScoreBeforeCommittingTheCurrentMove;
        ReturnChanges(currentMove, takenPiece, numberOfMovesOfTheTakenPiece);

        allPossibleMovesSortingHelperVector.push_back({correspondingScore, currentMove});

    }

    if (turn) {
        sort(allPossibleMovesSortingHelperVector.begin(), allPossibleMovesSortingHelperVector.end(), greater<pair<int, int16_t>>());
    }
    else {
        sort(allPossibleMovesSortingHelperVector.begin(), allPossibleMovesSortingHelperVector.end(), less<pair<int, int16_t>>());
    }

    for (int i = 0; i < allPossibleMovesSortingHelperVector.size(); i++) {
        currentMoves[i] = allPossibleMovesSortingHelperVector[i].second;
    }

    // There is also a super smart idea of mine, which when the depth is 8 or more, then
    // delete the moves on which they differ than the best obtained move score by a chosen
    // good-fixed-number, let's name it scoreDifferenceFactor, also then choosing this fixed number
    // is a great metric on which needs a lot of testing.

}

int Magic(const int8_t& depth, const bool& turn, const int16_t& previousMove, int alpha, int beta) {

    if (processHandler.processTimeExceeded()) {
        return 0;
    }

    processHandler.increaseTheNumberOfStatesForACertainDepth(depth);
    // Preserve the existing exact king-capture terminal mechanism before approximate evaluation.
    if ((abs(engineScore - opponentScore)) > CHECKMATE_FLAG_SCORE_DIFFERENCE) {
        processHandler.increaseTheNumberOfFinalStates();
        return (engineScore - opponentScore);
    }
    if (depth == 0) {
        processHandler.increaseTheNumberOfFinalStates();
        return v4_policy::EvaluateLeaf(turn, previousMove);
    }

    vector<int16_t> allPossibleMoves;
    if (((turn && ENGINE_COLOR)) || (((!turn)) && (!ENGINE_COLOR))) {

        long long whitePiecesCopy = whitePieces;
        while (whitePiecesCopy) {
            int8_t mostSignificantBit = MSB(whitePiecesCopy);
            whitePiecesCopy ^= (1ll << mostSignificantBit);
            int8_t currentPiece = board[getPieceRowFromBit[mostSignificantBit]]
                                       [getPieceColumnFromBit[mostSignificantBit]];
            vector<int16_t> currentMoves = GetMovesForThisPiece(currentPiece, getPieceRowFromBit[mostSignificantBit],
                                                                getPieceColumnFromBit[mostSignificantBit], previousMove);
            allPossibleMoves.insert(allPossibleMoves.end(), currentMoves.begin(), currentMoves.end());
        }

        // The following case indicates a stalemate
        if (allPossibleMoves.size() == 0) {
            processHandler.increaseTheNumberOfFinalStates();
            return 0;
        }

    }
    else {

        long long blackPiecesCopy = blackPieces;
        while (blackPiecesCopy) {
            int8_t mostSignificantBit = MSB(blackPiecesCopy);
            blackPiecesCopy ^= (1ll << mostSignificantBit);
            int8_t currentPiece = board[getPieceRowFromBit[mostSignificantBit]]
                                                          [getPieceColumnFromBit[mostSignificantBit]];
            vector<int16_t> currentMoves = GetMovesForThisPiece(currentPiece, getPieceRowFromBit[mostSignificantBit],
                                                                getPieceColumnFromBit[mostSignificantBit], previousMove);
            allPossibleMoves.insert(allPossibleMoves.end(), currentMoves.begin(), currentMoves.end());
        }

        // The following case indicates a stalemate
        if (allPossibleMoves.size() == 0) {
            processHandler.increaseTheNumberOfFinalStates();
            return 0;
        }

    }






    // Generator order below six remaining plies; no move truncation at any depth.
    if (v4_policy::ShouldOrder(depth)) {
        SortTheMovesWithSmallNeuralNetwork(allPossibleMoves);
    }

    int currentScore = turn ? INT_MIN : INT_MAX;
    for (const int16_t& currentMove : allPossibleMoves) {

        int8_t takenPiece = board[(currentMove >> 6) & 7][(currentMove >> 9) & 7];
        int16_t numberOfMovesOfTheTakenPiece = numberOfMovesOfThePieceOnThisSquare[(currentMove >> 6) & 7]
                                                                                  [(currentMove >> 9) & 7];
        long long whitePiecesBeforeCommittingTheCurrentMove = whitePieces;
        long long blackPiecesBeforeCommittingTheCurrentMove = blackPieces;
        int engineScoreBeforeCommittingTheCurrentMove = engineScore;
        int opponentScoreBeforeCommittingTheCurrentMove = opponentScore;
        MakeChanges(currentMove);
        int correspondingScore = Magic(depth - 1, !turn, currentMove, alpha, beta);
        whitePieces = whitePiecesBeforeCommittingTheCurrentMove;
        blackPieces = blackPiecesBeforeCommittingTheCurrentMove;
        engineScore = engineScoreBeforeCommittingTheCurrentMove;
        opponentScore = opponentScoreBeforeCommittingTheCurrentMove;
        ReturnChanges(currentMove, takenPiece, numberOfMovesOfTheTakenPiece);

        if (turn) {
            currentScore = max(currentScore, correspondingScore);
            alpha = max(alpha, correspondingScore);
        }
        else {
            currentScore = min(currentScore, correspondingScore);
            beta = min(beta, correspondingScore);
        }

        if (beta <= alpha) {
            processHandler.increaseTheNumberOfPrunedBranchesForACertainDepth(depth);
            break;
        }

    }

    return currentScore;

}

vector<int16_t> GetAllPossibleMoves() {

    vector<int16_t> allPossibleMoves = {};
    int16_t previousMove = previousMoves.size() ? previousMoves.back() : 0;

    if (ENGINE_COLOR) {

        long long whitePiecesCopy = whitePieces;
        while (whitePiecesCopy) {
            int8_t mostSignificantBit = MSB(whitePiecesCopy);
            whitePiecesCopy ^= (1ll << mostSignificantBit);
            int8_t currentPiece = board[getPieceRowFromBit[mostSignificantBit]][getPieceColumnFromBit[mostSignificantBit]];
            vector<int16_t> currentMoves = GetMovesForThisPiece(currentPiece, getPieceRowFromBit[mostSignificantBit],
                                                                getPieceColumnFromBit[mostSignificantBit], previousMove);
            allPossibleMoves.insert(allPossibleMoves.end(), currentMoves.begin(), currentMoves.end());
        }

    }
    else {

        long long blackPiecesCopy = blackPieces;
        while (blackPiecesCopy) {
            int8_t mostSignificantBit = MSB(blackPiecesCopy);
            blackPiecesCopy ^= (1ll << mostSignificantBit);
            int8_t currentPiece = board[getPieceRowFromBit[mostSignificantBit]][getPieceColumnFromBit[mostSignificantBit]];
            vector<int16_t> currentMoves = GetMovesForThisPiece(currentPiece, getPieceRowFromBit[mostSignificantBit],
                                                                getPieceColumnFromBit[mostSignificantBit], previousMove);
            allPossibleMoves.insert(allPossibleMoves.end(), currentMoves.begin(), currentMoves.end());
        }

    }

    return allPossibleMoves;

}

// The score of every root move of the last GetBestMoveWithItsScore() call, in search order. The search is
// fail-soft alpha-beta, so a root move's score is exact only when it beat the window it was searched with;
// otherwise it's only a bound ("at most this" when the engine is the side to move).
struct RootMoveScore {
    int16_t move;
    int score;
    bool exact;
};
vector<RootMoveScore> rootMoveScoresOfTheLastSearch;

pair<int16_t, int> GetBestMoveWithItsScore(const int8_t& depth, const bool& turn,
                                           vector<int16_t>& currentSortedMoves) {

    processHandler.resetObjectArraysAndFinalStates();
    rootMoveScoresOfTheLastSearch.clear();

    if (currentSortedMoves.size() == 0) {
        return {0, 0};
    }

    int alpha = INT_MIN;
    int beta = INT_MAX;
    pair<int16_t, int> bestMoveWithItsScore;
    int bestScoreSoFar = turn ? INT_MIN : INT_MAX;
    int16_t previousMove = previousMoves.size() ? previousMoves.back() : 0;

    for (const int16_t& currentMove : currentSortedMoves) {

        int8_t takenPiece = board[(currentMove >> 6) & 7][(currentMove >> 9) & 7];
        int16_t numberOfMovesOfTheTakenPiece = numberOfMovesOfThePieceOnThisSquare[(currentMove >> 6) & 7]
                                                                                  [(currentMove >> 9) & 7];
        long long whitePiecesBeforeCommittingTheCurrentMove = whitePieces;
        long long blackPiecesBeforeCommittingTheCurrentMove = blackPieces;
        int engineScoreBeforeCommittingTheCurrentMove = engineScore;
        int opponentScoreBeforeCommittingTheCurrentMove = opponentScore;
        const int alphaBeforeThisMove = alpha;
        const int betaBeforeThisMove = beta;
        MakeChanges(currentMove);
        int correspondingScore = Magic(depth - 1, !turn, currentMove, alpha, beta);
        whitePieces = whitePiecesBeforeCommittingTheCurrentMove;
        blackPieces = blackPiecesBeforeCommittingTheCurrentMove;
        engineScore = engineScoreBeforeCommittingTheCurrentMove;
        opponentScore = opponentScoreBeforeCommittingTheCurrentMove;
        ReturnChanges(currentMove, takenPiece, numberOfMovesOfTheTakenPiece);

        rootMoveScoresOfTheLastSearch.push_back({currentMove, correspondingScore,
                                                 turn ? (correspondingScore > alphaBeforeThisMove)
                                                      : (correspondingScore < betaBeforeThisMove)});

        if ((turn) && (correspondingScore > bestScoreSoFar)) {
            bestScoreSoFar = correspondingScore;
            bestMoveWithItsScore = {currentMove, correspondingScore};
            alpha = max(alpha, correspondingScore);
        }
        else if ((!turn) && (correspondingScore < bestScoreSoFar)) {
            bestScoreSoFar = correspondingScore;
            bestMoveWithItsScore = {currentMove, correspondingScore};
            beta = min(beta, correspondingScore);
        }

    }

    return bestMoveWithItsScore;

}

// Root ordering uses the total iteration depth; every supplied candidate remains available.
void GetBestMoveAndItsScoreToInitializeProcessHandler(const vector<string>& movesForThisThread) {

    vector<int16_t> engineSortedMoves;

    vector<vector<int8_t>> currentChessBoard(8, vector<int8_t>(8));
    for (int8_t row = 0; row < 8; row++) {
        for (int8_t column = 0; column < 8; column++) {
            currentChessBoard[row][column] = board[row][column];
        }
    }
    for (const string& currentMove : movesForThisThread) {
        engineSortedMoves.push_back(processHandler.convertMoveFromStandardToInt16_t(currentMove, currentChessBoard));
    }

    /*
     * The following is definitely a stalemate position on which the engine can't move, but
     * I also have to process when the engine play a move and after it there is no valid
     * opponent move and then it's the real stalemate as a move, like we can say, this move
     * is the move that caused the stalemate, so I have to bruteforce over the moves that are
     * possible for the engine, and after playing every single one of them I should check the
     * number of valid moves for opponent, and here I should use another move generators to
     * generate just the valid moves on which the king don't die and not just depending on
     * the long depth to get the results ;).
     */
    if (engineSortedMoves.size() == 0) {
        processHandler.setBestEngineMove(0);
        processHandler.setBestEngineMoveScore(0);
        return;
    }


    if (v4_policy::ShouldOrder(processHandler.getEngineDepth())) {
        SortTheMovesWithSmallNeuralNetwork(engineSortedMoves);
    }

    pair<int16_t, int> bestMoveWithItsScore = GetBestMoveWithItsScore(processHandler.getEngineDepth(), 1,
                                                                      engineSortedMoves);

    processHandler.setBestEngineMove(bestMoveWithItsScore.first);
    processHandler.setBestEngineMoveScore(bestMoveWithItsScore.second);

}

// ############################################################ \\
//                            Notes                             \\
// Kernel.exe is a worker now. Engine UCI starts it once per    \\
// game, and then, for every move, it writes one request line   \\
// into my stdin (a ChessState in JSON, exactly what the JSON   \\
// file used to hold, plus "type" and "id"), and I answer with  \\
// one line on my stdout. The search itself didn't change at    \\
// all: the old main() loop is RunIterativeDeepening() below.   \\
// ############################################################ \\

#ifndef MRBITS_BUILD_STAMP
#define MRBITS_BUILD_STAMP "dev"
#endif

// The tables are built ONCE per process. This is a hard requirement, not an optimization:
// MovesPreCalculation() only push_backs into preCalculatedMoves and never clears it, so a second call
// would duplicate every bishop, rook and queen ray, with the same move and score but many more nodes.
// (PieceSquaresTableInitialization() and BitToSquareAndViceVersaInitialization() only assign, and none of
// the three reads the board, the masks or ENGINE_COLOR, so building them first is the same as the old order.)
void BuildTheTablesOnce() {
    static bool theTablesAreBuilt = false;
    if (theTablesAreBuilt) {
        return;
    }
    theTablesAreBuilt = true;
    MovesPreCalculation();
    PieceSquaresTableInitialization();
    BitToSquareAndViceVersaInitialization();
}

// Everything a search reads or writes, apart from the tables above. When every move started a brand-new
// process this was free. ENGINE_COLOR must come first, because InitializeEngineScore() and
// InitializeOpponentScore() read it (and so does MakeChanges() while the moves are replayed).
void ResetGameState(const bool& engineColor) {
    ENGINE_COLOR = engineColor;
    processHandler = ProcessHandler();      // depth, best move and score, allowed time, timers, counters
    previousMoves.clear();                  // its back() is the root's "previous move" (en passant)
    rootMoveScoresOfTheLastSearch.clear();
    BoardInitialization();                  // the board and numberOfMovesOfThePieceOnThisSquare
    blackPieces = ((1ll << 16) - 1);
    whitePieces = blackPieces << 48;
    InitializeEngineScore();
    InitializeOpponentScore();
}

void ReplayMoves(const vector<string>& previousMovesAsStandard) {
    vector<vector<int8_t>> currentChessBoard(8, vector<int8_t>(8));
    for (const string& currentMove : previousMovesAsStandard) {
        for (int8_t row = 0; row < 8; row++) {
            for (int8_t column = 0; column < 8; column++) {
                currentChessBoard[row][column] = board[row][column];
            }
        }
        previousMoves.push_back(processHandler.convertMoveFromStandardToInt16_t(currentMove, currentChessBoard));
        MakeChanges(previousMoves.back());
    }
}

// ############################################################ \\

struct IterationSummary {
    int depth;
    bool completed;
    double milliseconds;
    long long nodes;
    long long leafNodes;
    long long pruned;
    int16_t bestMove;
    int score;
};

struct SearchOutcome {
    ProcessHandler theFinalCompletedProcessHandler;
    bool completedAtLeastOneDepth = false;
    vector<RootMoveScore> rootScoresOfTheFinalDepth;
    vector<IterationSummary> perDepth;
};

IterationSummary SummarizeTheIteration(const ProcessHandler& handler, const int& depth, const bool& completed,
                                       const double& milliseconds) {
    IterationSummary summary;
    summary.depth = depth;
    summary.completed = completed;
    summary.milliseconds = milliseconds;
    summary.nodes = handler.getTheNumberOfAllTheInnerAndFinalStatesAs64Bit();
    summary.leafNodes = handler.getTheNumberOfAllTheFinalStates();
    summary.pruned = handler.getTheNumberOfAllTheBrunedBranchesAs64Bit();
    summary.bestMove = handler.getBestEngineMoveAsInt16_t();
    summary.score = handler.getBestEngineMoveScore();
    return summary;
}

// The old main() loop. maxDepth == 0 is exactly the old way (the allowed time is a hard cap checked at every
// node, and a new depth isn't started once 5% of it is used). maxDepth > 0 is only for the tests: the clock
// is switched off and the loop stops after that depth (even depths only, like always).
SearchOutcome RunIterativeDeepening(const vector<string>& movesForThisThread, const int& maxDepth) {

    SearchOutcome outcome;
    if (maxDepth > 0) {
        processHandler.setAllowedTimeInMilliSeconds(INT_MAX);
    }
    const int lastDepth = (maxDepth > 0) ? min(maxDepth, 30) : 30;

    processHandler.setAllProcessStartTime();
    ProcessHandler& theFinalCompletedProcessHandler = outcome.theFinalCompletedProcessHandler;

    for (int8_t depth = 2; depth <= lastDepth; depth += 2) {
        chrono::high_resolution_clock::time_point iterationStartTime = chrono::high_resolution_clock::now();
        processHandler.setEngineDepth(depth);
        processHandler.setLastDepthCalculationStartTime();
        GetBestMoveAndItsScoreToInitializeProcessHandler(movesForThisThread);
        if (processHandler.processTimeExceeded()) {
            theFinalCompletedProcessHandler.setAllProcessEndTime();
            outcome.perDepth.push_back(SummarizeTheIteration(processHandler, depth, false,
                                                             MillisecondsSince(iterationStartTime)));
            break;
        }

        theFinalCompletedProcessHandler = processHandler;
        theFinalCompletedProcessHandler.setAllProcessEndTime();
        theFinalCompletedProcessHandler.setLastDepthCalculationsEndTime();
        outcome.completedAtLeastOneDepth = true;
        outcome.rootScoresOfTheFinalDepth = rootMoveScoresOfTheLastSearch;
        outcome.perDepth.push_back(SummarizeTheIteration(processHandler, depth, true,
                                                         MillisecondsSince(iterationStartTime)));

        if (maxDepth > 0) {
            // A fixed depth ignores the time rule below.
            continue;
        }

        // The following is a temporarily additional condition
        long double totalAllowedTimeInMilliSeconds = theFinalCompletedProcessHandler.getProcessAllowedTimeInMilliSeconds();
        long double totalConsumedTimeInMilliSeconds = theFinalCompletedProcessHandler.getTotalConsumedTimeInMilliSeconds();
        long double consumedTimePercentage = (totalConsumedTimeInMilliSeconds / totalAllowedTimeInMilliSeconds) * 100;
        // I found by testing so far that 8% is a golden choice for the timing system in the Kernel.
        // if (consumedTimePercentage >= 8.0) {
        //    break;
        // }
        // But now I am trying it this way for Blitz testing it because I had some feeling about it, so
        // let's give it more adventure and try some Blitz games this way.
        if (consumedTimePercentage >= 5.0) {
            break;
        }

    }

    return outcome;
}

// ############################################################ \\

double RoundToThreeDecimals(const double& value) {
    return round(value * 1000.0) / 1000.0;
}

// It protects the board indexing in convertMoveFromStandardToInt16_t from garbage input.
bool IsWellFormedStandardMove(const string& move) {
    if ((move.size() != 4) && (move.size() != 5)) {
        return false;
    }
    if ((move[0] < 'a') || (move[0] > 'h') || (move[2] < 'a') || (move[2] > 'h') ||
        (move[1] < '1') || (move[1] > '8') || (move[3] < '1') || (move[3] > '8')) {
        return false;
    }
    return (move.size() == 4) || (string("qrbn").find(move[4]) != string::npos);
}

Json AnswerSearchRequest(const Json& request) {

    chrono::high_resolution_clock::time_point setupStartTime = chrono::high_resolution_clock::now();

    // The request is a ChessState: the previous moves, my color, my allowed time and my root moves.
    ChessState currentChessState = ChessState::deserializeObject(request);
    for (const string& currentMove : currentChessState.previousMoves) {
        if (!IsWellFormedStandardMove(currentMove)) {
            throw invalid_argument("\"previousMoves\" holds a malformed move: \"" + currentMove + "\"");
        }
    }
    for (const string& currentMove : currentChessState.movesForThisThread) {
        if (!IsWellFormedStandardMove(currentMove)) {
            throw invalid_argument("\"movesForThisThread\" holds a malformed move: \"" + currentMove + "\"");
        }
    }
    // 0 = use the allowed time, like always. A fixed depth is only for the tests.
    const int maxDepth = request.value("maxDepth", 0);
    if ((maxDepth < 0) || (maxDepth > 30)) {
        throw invalid_argument("\"maxDepth\" must be 0 (use the allowed time) or 2..30");
    }

    ResetGameState(currentChessState.engineColor);
    processHandler.setAllowedTime(currentChessState.allowedEngineTimeInSeconds);
    ReplayMoves(currentChessState.previousMoves);
    const double setupMilliseconds = MillisecondsSince(setupStartTime);

    chrono::high_resolution_clock::time_point searchStartTime = chrono::high_resolution_clock::now();
    SearchOutcome outcome = RunIterativeDeepening(currentChessState.movesForThisThread, maxDepth);
    const double searchMilliseconds = MillisecondsSince(searchStartTime);

    const ProcessHandler& theFinalCompletedProcessHandler = outcome.theFinalCompletedProcessHandler;
    const bool hasNoMoves = currentChessState.movesForThisThread.empty();
    const bool isOk = (!hasNoMoves) && outcome.completedAtLeastOneDepth;

    Json answer;
    answer["type"] = "result";
    answer["id"] = request.contains("id") ? request["id"] : Json(nullptr);
    answer["status"] = hasNoMoves ? "no_moves" : (isOk ? "ok" : "no_completed_depth");
    if (isOk) {
        answer["bestMove"] = theFinalCompletedProcessHandler.getEngineBestMoveAsStandard();
        answer["score"] = theFinalCompletedProcessHandler.getBestEngineMoveScore();
        answer["depth"] = (int)theFinalCompletedProcessHandler.getEngineDepth();
    }
    else {
        // The old file answered "a8a8" with score 0 here (the empty move printed as a square pair).
        answer["bestMove"] = nullptr;
        answer["score"] = nullptr;
        answer["depth"] = 0;
    }
    answer["setupMs"] = RoundToThreeDecimals(setupMilliseconds);
    answer["searchMs"] = RoundToThreeDecimals(searchMilliseconds);
    // The last completed depth's main search: the same numbers as the old text report.
    answer["nodes"] = isOk ? theFinalCompletedProcessHandler.getTheNumberOfAllTheInnerAndFinalStatesAs64Bit() : 0;
    answer["leafNodes"] = isOk ? theFinalCompletedProcessHandler.getTheNumberOfAllTheFinalStates() : 0;
    answer["pruned"] = isOk ? theFinalCompletedProcessHandler.getTheNumberOfAllTheBrunedBranchesAs64Bit() : 0;

    long long totalNodes = 0;
    Json perDepth = Json::array();
    for (const IterationSummary& iteration : outcome.perDepth) {
        totalNodes += iteration.nodes;
        Json depthRecord;
        depthRecord["depth"] = iteration.depth;
        depthRecord["completed"] = iteration.completed;
        depthRecord["ms"] = RoundToThreeDecimals(iteration.milliseconds);
        depthRecord["nodes"] = iteration.nodes;
        depthRecord["leafNodes"] = iteration.leafNodes;
        depthRecord["pruned"] = iteration.pruned;
        if (iteration.completed) {
            depthRecord["bestMove"] = processHandler.convertMoveFromInt16_tToStandard(iteration.bestMove);
            depthRecord["score"] = iteration.score;
        }
        perDepth.push_back(depthRecord);
    }
    // Every iteration, an aborted last one included.
    answer["totalNodes"] = totalNodes;
    answer["perDepth"] = perDepth;

    Json rootScores = Json::array();
    set<string> searchedRootMoves;
    for (const RootMoveScore& rootMoveScore : outcome.rootScoresOfTheFinalDepth) {
        string move = processHandler.convertMoveFromInt16_tToStandard(rootMoveScore.move);
        searchedRootMoves.insert(move);
        Json rootScore;
        rootScore["move"] = move;
        rootScore["score"] = rootMoveScore.score;
        rootScore["exact"] = rootMoveScore.exact;
        rootScores.push_back(rootScore);
    }
    answer["rootScores"] = rootScores;
    // v4 retains every supplied root candidate at every depth; ordinary alpha-beta search is unchanged.
    Json unsearchedRootMoves = Json::array();
    if (isOk) {
        for (const string& currentMove : currentChessState.movesForThisThread) {
            if (!searchedRootMoves.count(currentMove)) {
                unsearchedRootMoves.push_back(currentMove);
            }
        }
    }
    answer["unsearchedRootMoves"] = unsearchedRootMoves;

    return answer;

}

// The only writer of my stdout. fwrite uses this executable's own C runtime (the same one as the _setmode
// below), so every line ends in a bare "\n" even when libstdc++-6.dll comes from somewhere else (Git Bash
// puts Git's own one first on PATH, and then cout would ignore the _setmode and send "\r\n").
void WriteProtocolLine(const string& line) {
    fwrite(line.data(), 1, line.size(), stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

int RunWorkerMode() {

    // My stdout carries the answer lines only: from here on, anything written to cout goes to stderr.
    streambuf* originalCoutBuffer = cout.rdbuf(cerr.rdbuf());
    _setmode(_fileno(stdout), _O_BINARY);
    _setmode(_fileno(stdin), _O_BINARY);

    chrono::high_resolution_clock::time_point initializationStartTime = chrono::high_resolution_clock::now();
    BuildTheTablesOnce();
    const double initializationMilliseconds = MillisecondsSince(initializationStartTime);

    string line;
    while (getline(cin, line)) {

        if ((!line.empty()) && (line.back() == '\r')) {
            line.pop_back();
        }
        if (line.find_first_not_of(" \t") == string::npos) {
            continue;
        }

        Json answer;
        Json id = nullptr;
        bool isQuitRequested = false;
        try {
            Json request = Json::parse(line);
            if (!request.is_object()) {
                throw invalid_argument("a request must be a JSON object");
            }
            if (request.contains("id")) {
                id = request["id"];
            }
            string requestType = request.at("type").get<string>();
            if (requestType == "search") {
                answer = AnswerSearchRequest(request);
            }
            else if (requestType == "hello") {
                answer["type"] = "ready";
                answer["protocol"] = 1;
                answer["engineVersion"] = string("kernel-") + MRBITS_BUILD_STAMP;
                answer["pid"] = (long long)GetCurrentProcessId();
                answer["initMs"] = RoundToThreeDecimals(initializationMilliseconds);
            }
            else if (requestType == "quit") {
                isQuitRequested = true;
            }
            else {
                throw invalid_argument("unknown request type \"" + requestType + "\"");
            }
        }
        catch (const exception& error) {
            answer = Json::object();
            answer["type"] = "error";
            answer["id"] = id;
            answer["message"] = error.what();
        }

        if (isQuitRequested) {
            break;
        }
        // "replace": an invalid UTF-8 byte echoed in an error message must never throw here.
        WriteProtocolLine(answer.dump(-1, ' ', false, Json::error_handler_t::replace));
    }

    cout.rdbuf(originalCoutBuffer);
    return 0;
}

int main(int argc, char* argv[]) {

    // Set the priority of the parent process (The current process)
    SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);

    // The old way ("Kernel.exe <file.json>") is gone. An old Engine UCI that still calls me like that gets a
    // clear error at once, instead of a worker that waits for its input forever.
    if (argc >= 2) {
        cerr << "Kernel.exe doesn't read JSON files any more: Engine UCI starts it as a worker, with no arguments."
             << endl;
        return 1;
    }

    return RunWorkerMode();
}
