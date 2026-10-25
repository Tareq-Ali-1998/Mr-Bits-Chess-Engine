#ifndef STOCKFISH_HANDLER_H_INCLUDED
#define STOCKFISH_HANDLER_H_INCLUDED

#include <bits/stdc++.h>

using namespace std;

class StockfishHandler {
  private:
    string stockfishExecutableFilePath;
    string tempCommandFilePath;


    void createAndFillTemporaryCommandFile(const string& fullCommand) {
        ofstream tempFile(tempCommandFilePath);
        if (tempFile.is_open()) {
            tempFile << fullCommand;
            tempFile.close();
        }
    }

    void removeTemporaryCommandFile() {
        remove(tempCommandFilePath.c_str());
    }

    string getFullStockfishCommandExecutingResult() {

        string finalCommandToExecute = "\"" + this->stockfishExecutableFilePath + "\" < " +
                                       this->tempCommandFilePath;
        array<char, 256> buffer;
        string result;
        shared_ptr<FILE> pipe(popen(finalCommandToExecute.c_str(), "r"), pclose);
        while (fgets(buffer.data(), buffer.size(), pipe.get()) != nullptr) {
            result += buffer.data();
        }
        return result;

    }


  public:
    StockfishHandler() {
        this->stockfishExecutableFilePath =
            "\"stockfish/stockfish-windows-x86-64-avx2.exe\"";
        this->tempCommandFilePath = "temp_command_file.txt";
    }

    StockfishHandler(const string& stockfishExecutableFilePath) {
        this->stockfishExecutableFilePath = stockfishExecutableFilePath;
        this->tempCommandFilePath = "temp_command_file.txt";
    }

    long double getNNUEPositionEvaluation(const string& movesString) {

        string fullStockfishCommand;
        if (movesString.size() == 0) {
            fullStockfishCommand = "position startpos\neval";
        } else {
            fullStockfishCommand = "position startpos moves " + movesString + "\n" + "eval";
        }
        this->createAndFillTemporaryCommandFile(fullStockfishCommand);
        string stockfishOutput = this->getFullStockfishCommandExecutingResult();
        this->removeTemporaryCommandFile();

        int helperIndex = stockfishOutput.find("Final evaluation: none (in check)");
        if ((helperIndex >= 0) && (helperIndex < stockfishOutput.size())) {

            int numberOfMovesSoFar = 1;
            for (const char& currentCharacter : movesString) {
                if (currentCharacter == ' ') {
                    numberOfMovesSoFar++;
                }
            }

            if (numberOfMovesSoFar & 1) {
                return 100000;
            }
            else {
                return -100000;
            }


        }

        int idx = stockfishOutput.find("Final evaluation");
        long double numberSign;
        for (int i = idx; i < stockfishOutput.size(); i++) {
            if (stockfishOutput[i] == '+') {
                numberSign = 1;
                idx = i + 1;
                break;
            }
            else if (stockfishOutput[i] == '-') {
                numberSign = -1;
                idx = i + 1;
                break;
            }
        }

        int numberLength = 0;
        for (int i = idx; i < stockfishOutput.size(); i++) {
            if (stockfishOutput[i] == ' ') {
                break;
            }
            numberLength++;
        }

        if (stockfishOutput.substr(idx, numberLength) == "Final") {

            string bestResponseMove = this->getBestMoveByDepth(movesString, 20);
            string movesStringAfterTheBestResponseMove = movesString + " " + bestResponseMove;
            return this->getNNUEPositionEvaluation(movesStringAfterTheBestResponseMove);

        }

        cout << setprecision(5) << fixed;
        return ((long double)(stod(stockfishOutput.substr(idx, numberLength)))) * numberSign;

    }

    vector<string> getAllPossibleMoves(const string& movesString) {
        string fullStockfishCommand;
        if (movesString.size() == 0) {
            fullStockfishCommand = "position startpos\ngo perft 1";
        } else {
            fullStockfishCommand = "position startpos moves " + movesString + "\n" + "go perft 1";
        }
        this->createAndFillTemporaryCommandFile(fullStockfishCommand);
        string stockfishOutput = this->getFullStockfishCommandExecutingResult();
        this->removeTemporaryCommandFile();

        for (int i = 0; i < 20; i++) {
            stockfishOutput.pop_back();
        }
        vector<string> allPossibleMoves;
        for (int i = 0; i < stockfishOutput.size(); i++) {
            if (stockfishOutput[i] == ':') {
                int moveEndIndex = i - 1;
                int moveStartIndex;
                for (int j = moveEndIndex; stockfishOutput[j] != '\n'; j--) {
                    moveStartIndex = j;
                }
                string currentMove = stockfishOutput.substr(moveStartIndex, moveEndIndex - moveStartIndex + 1);
                allPossibleMoves.push_back(currentMove);
            }
        }

        return allPossibleMoves;

    }

    string getBestMoveByDepth(const string& movesString, const int& depth) {

        string fullStockfishCommand;
        if (movesString.size() == 0) {
            fullStockfishCommand = "position startpos\ngo depth " + to_string(depth);
        } else {
            fullStockfishCommand = "position startpos moves " + movesString + "\n" + "go depth " + to_string(depth);
        }
        // Here the repetition is important only when getting the depth, I will not forget that ever ;)
        fullStockfishCommand += "\n" + fullStockfishCommand;
        this->createAndFillTemporaryCommandFile(fullStockfishCommand);
        string stockfishOutput = this->getFullStockfishCommandExecutingResult();
        this->removeTemporaryCommandFile();

        int bestMoveStartIndex = stockfishOutput.find("bestmove") + 9;
        string bestMove;
        for (int i = bestMoveStartIndex; i < stockfishOutput.size(); i++) {
            if ((stockfishOutput[i] == ' ') || (stockfishOutput[i] == '\n')) {
                break;
            }
            bestMove += stockfishOutput[i];
        }

        return bestMove;
    }

    string getBestMoveByNNUE(const string& movesString) {

        vector<string> sortedMovesByNNUE = this->getSortedMovesByNNUE(movesString);
        if (sortedMovesByNNUE.size()) {
            return sortedMovesByNNUE[0];
        }

        return "";

    }

    vector<string> getSortedMovesByNNUE(const string& movesString) {

        vector<pair<long double, string>> movesSortingHelperVector;
        vector<string> allPossibleMoves = this->getAllPossibleMoves(movesString);
        if (allPossibleMoves.size() == 0) {
            return {};
        }

        for (const string& currentMove : allPossibleMoves) {
            movesSortingHelperVector.push_back({this->getNNUEPositionEvaluation(movesString + " " + currentMove),
                                               currentMove});
        }

        int numberOfPlayedMoves = 0;
        if (movesString.size()) {
            numberOfPlayedMoves = 1;
            for (const char& currentCharacter : movesString) {
                numberOfPlayedMoves += (currentCharacter == ' ');
            }
        }

        if (numberOfPlayedMoves & 1) {
            sort(movesSortingHelperVector.begin(), movesSortingHelperVector.end());
        }
        else {
            sort(movesSortingHelperVector.begin(), movesSortingHelperVector.end(), greater<pair<long double, string>>());
        }

        vector<string> sortedMoves;
        for (const pair<long double, string>& evaluatedMove : movesSortingHelperVector) {
            sortedMoves.push_back(evaluatedMove.second);
        }

        return sortedMoves;

    }


    // I didn't test all the following three functions, and there can be some potential bugs
    bool isCheckmatePosition(const string& movesString) {
        return ((this->getAllPossibleMoves(movesString).size() == 0) &&
                (abs(this->getNNUEPositionEvaluation(movesString)) == 100000));
    }

    // The following function will return true if it's a Tie even if it's a Stalemate.
    bool isTiePosition(const string& movesString) {
        return ((this->getAllPossibleMoves(movesString).size() == 0) &&
                (abs(this->getNNUEPositionEvaluation(movesString)) != 100000));
    }

    bool isStalematePosition(const string& movesString) {
        // I can implement this one maybe using the NNUE, or relying on some trick or so.
        // The following is a moves string that is definitely a Stalemate position for testing:
        // "g1f3 d7d5 c2c4 d5d4 g2g3 b8c6 d2d3 e7e5 f1g2 f8b4 b1d2 a7a5 e1g1 g8f6 f3e1 e8g8 a2a3 b4d6 a1b1 h7h6 b2b4 a5b4 a3b4 c6b4 d2e4 b4c6 e4f6 d8f6 g2e4 c6e7 c4c5 d6c5 g1g2 c8e6 e1c2 f8e8 g2g1 a8d8 g1g2 c5d6 b1b7 d6c5 b7b1 h6h5 h2h3 e6d5 e4d5 d8d5 g2h2 f6e6 h3h4 d5d8 c1g5 f7f6 b1b7 e6c6 b7b1 f6g5 h4g5 e7d5 f1h1 h5h4 g5g6 d5c3 e2e4 h4g3 h2g2 c3d1 h1h8 g8h8 c2e1 g3f2 b1c1 f2e1q g2h3 e1e3 h3h4 e3c1 h4g4 c6g6 g4h4 d1e3 h4h3 h8g8 h3h4 c1e1 h4h3 e1g1 h3h4 g6f6 h4h3 g1f2"
        return 0;
    }

};

#endif // STOCKFISH_HANDLER_H_INCLUDED
