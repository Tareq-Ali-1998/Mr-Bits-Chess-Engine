#ifndef MR_BITS_TRIE_HPP_INCLUDED
#define MR_BITS_TRIE_HPP_INCLUDED

// Uses the existing Kernel.cpp STL declarations and globals: rng, board,
// and numberOfMovesOfThePieceOnThisSquare. Include at the original class location.
// The global Trie instances remain defined in Kernel.cpp.

class Trie {

  private:
    class TrieNode {

      public:
        int8_t nodeFrequency;
        TrieNode* children[32];

        TrieNode() : nodeFrequency(1) {
            memset(this->children, 0, sizeof(this->children));
        }

    }* root;
    vector<int8_t> smartBoardSquaresOrdering;

  public:
    Trie() : root(new TrieNode()) {
        for (int8_t row = 0; row < 8; row++) {
            for (int8_t column = 0; column < 8; column++) {
                this->smartBoardSquaresOrdering.push_back(row + (column << 3));
            }
        }
        std::shuffle(this->smartBoardSquaresOrdering.begin(), this->smartBoardSquaresOrdering.end(), rng);
    }

    ~Trie() {
      if (root != nullptr) {
        delete root;
      }
    }

    void insertBoard(const int16_t& previousMove) {

        bool enPassantPossible = 0;
        int8_t previousMoveDestinationRow = (previousMove >> 6) & 7;
        int8_t previousMoveDestinationColumn = (previousMove >> 9) & 7;
        if (((board[previousMoveDestinationRow][previousMoveDestinationColumn] & 7) == 1) &&
            (numberOfMovesOfThePieceOnThisSquare[previousMoveDestinationRow][previousMoveDestinationColumn] == 1) &&
            ((previousMoveDestinationRow == 3) || (previousMoveDestinationRow == 4))) {

            enPassantPossible = 1;

        }

        TrieNode* currentNode = this->root;

        for (const int8_t& square : smartBoardSquaresOrdering) {

            int8_t currentCellRow = square & 7;
            int8_t currentCellColumn = (square >> 3) & 7;
            int8_t currentCellInfo = board[currentCellRow][currentCellColumn];

            // The following condition is true for all the pieces except when it comes to the castling special move
            if (numberOfMovesOfThePieceOnThisSquare[currentCellRow][currentCellColumn]) {
                //currentCellInfo |= 16;
            }

            if (((currentCellInfo & 7) == 1) && (enPassantPossible) &&
                (previousMoveDestinationRow == currentCellRow) &&
                ((currentCellInfo & 8) != (board[previousMoveDestinationRow][previousMoveDestinationColumn] & 8)) &&
                (abs(previousMoveDestinationColumn - currentCellColumn) == 1)) {

                currentCellInfo ^= 3;

            }

            if (currentNode->children[currentCellInfo] == nullptr) {
                currentNode->children[currentCellInfo] = new TrieNode();
            }
            else {
                currentNode->children[currentCellInfo]->nodeFrequency++;
            }

            currentNode = currentNode->children[currentCellInfo];
        }

    }

    void deleteBoard(const int16_t& previousMove) {

        stack<pair<TrieNode*, int8_t>> toDelete;

        bool enPassantPossible = 0;
        int8_t previousMoveDestinationRow = (previousMove >> 6) & 7;
        int8_t previousMoveDestinationColumn = (previousMove >> 9) & 7;
        if (((board[previousMoveDestinationRow][previousMoveDestinationColumn] & 7) == 1) &&
            (numberOfMovesOfThePieceOnThisSquare[previousMoveDestinationRow][previousMoveDestinationColumn] == 1) &&
            ((previousMoveDestinationRow == 3) || (previousMoveDestinationRow == 4))) {

            enPassantPossible = 1;

        }

        TrieNode* currentNode = this->root;

        for (const int8_t& square : smartBoardSquaresOrdering) {

            int8_t currentCellRow = square & 7;
            int8_t currentCellColumn = (square >> 3) & 7;
            int8_t currentCellInfo = board[currentCellRow][currentCellColumn];

            // The following condition is true for all the pieces except when it comes to the castling special move
            if (numberOfMovesOfThePieceOnThisSquare[currentCellRow][currentCellColumn]) {
                //currentCellInfo |= 16;
            }

            if (((currentCellInfo & 7) == 1) && (enPassantPossible) &&
                (previousMoveDestinationRow == currentCellRow) &&
                ((currentCellInfo & 8) != (board[previousMoveDestinationRow][previousMoveDestinationColumn] & 8)) &&
                (abs(previousMoveDestinationColumn - currentCellColumn) == 1)) {

                currentCellInfo ^= 3;

            }

            currentNode->children[currentCellInfo]->nodeFrequency--;
            if (currentNode->children[currentCellInfo]->nodeFrequency == 0) {
                toDelete.push({currentNode, currentCellInfo});
            }
            currentNode = currentNode->children[currentCellInfo];


        }

        while (toDelete.size()) {

            TrieNode* nodeToDelete;
            int8_t nodeToDeleteIndex;
            tie(nodeToDelete, nodeToDeleteIndex) = toDelete.top();
            toDelete.pop();
            delete nodeToDelete->children[nodeToDeleteIndex];
            nodeToDelete->children[nodeToDeleteIndex] = nullptr;

        }

    }

    bool boardExist(const int16_t& previousMove) {

        bool enPassantPossible = 0;
        int8_t previousMoveDestinationRow = (previousMove >> 6) & 7;
        int8_t previousMoveDestinationColumn = (previousMove >> 9) & 7;
        if (((board[previousMoveDestinationRow][previousMoveDestinationColumn] & 7) == 1) &&
            (numberOfMovesOfThePieceOnThisSquare[previousMoveDestinationRow][previousMoveDestinationColumn] == 1) &&
            ((previousMoveDestinationRow == 3) || (previousMoveDestinationRow == 4))) {

            enPassantPossible = 1;

        }

        TrieNode* currentNode = this->root;

        for (const int8_t& square : smartBoardSquaresOrdering) {

            int8_t currentCellRow = square & 7;
            int8_t currentCellColumn = (square >> 3) & 7;
            int8_t currentCellInfo = board[currentCellRow][currentCellColumn];

            // The following condition is true for all the pieces except when it comes to the castling special move
            if (numberOfMovesOfThePieceOnThisSquare[currentCellRow][currentCellColumn]) {
                //currentCellInfo |= 16;
            }

            if (((currentCellInfo & 7) == 1) && (enPassantPossible) &&
                (previousMoveDestinationRow == currentCellRow) &&
                ((currentCellInfo & 8) != (board[previousMoveDestinationRow][previousMoveDestinationColumn] & 8)) &&
                (abs(previousMoveDestinationColumn - currentCellColumn) == 1)) {

                currentCellInfo ^= 3;

            }

            if (currentNode->children[currentCellInfo] == nullptr) {
                return 0;
            }
            currentNode = currentNode->children[currentCellInfo];

        }

        return 1;

    }

};

#endif // MR_BITS_TRIE_HPP_INCLUDED
