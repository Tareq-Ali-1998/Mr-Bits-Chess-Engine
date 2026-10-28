#ifndef CHESS_STATE_H_INCLUDED
#define CHESS_STATE_H_INCLUDED

#include <bits/stdc++.h>
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>

// ############################################################ \\

#include "Stockfish Handler.hpp"
#include "Kernel Workers.hpp"
#include "Engine Log.hpp"
#include "json.hpp"

using namespace std;

// ############################################################ \\
//                            Notes                             \\
// The one ChessState of Mr. Bits. Engine UCI and Kernel had    \\
// the same class twice (the only difference was the Stockfish  \\
// depths inside getEngineMoveWithThreading, which Kernel never \\
// calls), so now both of them include this file. Engine UCI    \\
// uses all of it; Kernel uses it to read its requests.         \\
// ############################################################ \\

using Json = nlohmann::json;

// ############################################################ \\

inline const string ENGINE_NAME = "Mr. Bits";

// ############################################################ \\
// Random number generator for shuffling after the new MinGW C++11 update
inline std::mt19937 rng(std::random_device{}());

// ############################################################ \\

inline string TrimSpaces(const string& text) {
    size_t firstIndex = text.find_first_not_of(" \t\r\n");
    if (firstIndex == string::npos) {
        return "";
    }
    size_t lastIndex = text.find_last_not_of(" \t\r\n");
    return text.substr(firstIndex, lastIndex - firstIndex + 1);
}

template <class TimePoint>
double MillisecondsSince(const TimePoint& startTime) {
    return chrono::duration<double, milli>(TimePoint::clock::now() - startTime).count();
}

// ############################################################ \\

class ChessState {

  public:

    StockfishHandler stockfishHandler;
    vector<string> previousMoves;
    // The following is the flag engineColor, it's True or 1, if the engine is
    // white, and the default value of the engine is white
    bool engineColor;
    int allowedEngineTimeInSeconds;
    string bestMove;
    int bestMoveScore;
    int numberOfThreads;
    string report;
    vector<string> movesForThisThread;
    int theNumberOfOpeningMovesToGetFromStockfish;

    // What happened in the last move, for the database (Engine UCI only).
    // decisionPath: kernel / stockfish_opening / stockfish_endgame / only_move / no_kernel_answer / no_legal_move
    // (getBestMoveFromEngine turns it into stalemate_override when Stockfish corrects a tie move).
    string decisionPath;
    int stockfishDepthUsed;
    int numberOfLegalMoves;
    Json kernelWorkersAnswers;
    double legalMovesMilliseconds;
    double kernelWorkersMilliseconds;

    ChessState() : previousMoves({}), engineColor(1), allowedEngineTimeInSeconds(30) {
        this->stockfishHandler = StockfishHandler();
        // this->bestMove = stockfishHandler.getBestMoveByDepth(this->getMovesStringFromPreviousMoves(), 12);
        this->bestMove = "It should be a default value like the previous line but I want to maintain more time";
        this->bestMoveScore = 0;
        this->numberOfThreads = 4;
        this->theNumberOfOpeningMovesToGetFromStockfish = 7;
        this->decisionPath = "";
        this->stockfishDepthUsed = 0;
        this->numberOfLegalMoves = 0;
        this->kernelWorkersAnswers = Json::array();
        this->legalMovesMilliseconds = 0;
        this->kernelWorkersMilliseconds = 0;
    }

    void setallowedEngineTimeInSeconds(const int& allowedEngineTimeInSeconds) {
        this->allowedEngineTimeInSeconds = allowedEngineTimeInSeconds;
    }

    void setEngineColor(const bool& engineColor) {
        this->engineColor = engineColor;
    }

    void setTheNumberOfOpeningMovesToGetFromStockfish(
        const int& theNumberOfOpeningMovesToGetFromStockfish) {
        this->theNumberOfOpeningMovesToGetFromStockfish =
            theNumberOfOpeningMovesToGetFromStockfish;
    }

    int getTheNumberOfOpeningMovesToGetFromStockfish() {
        return this->theNumberOfOpeningMovesToGetFromStockfish;
    }

    void setBestMove(const string& bestMove) {
        this->bestMove = bestMove;
    }

    void setBestMoveScore(const int& bestMoveScore) {
        this->bestMoveScore = bestMoveScore;
    }

    void setNumberOfThreads(const int& numberOfThreads) {
        this->numberOfThreads = numberOfThreads;
    }

    void sayHelloAndGetEngineColorAndTheAllowedMoveTimeAndTheNumberOfThreadsAndMoreInfo() {

        cout << "\nHello, I am " << ENGINE_NAME << " chess engine, and "
                "I am better than Stockfish chess engine, so\n"
                "let's play our game ;) .\n"
                "Yes I am talking to you my opponent, if you want to choose "
                "White press 1, otherwise press 0:\n";
        int choice;
        cin >> choice;

        cout << endl << "Please input the number of threads:" << endl;
        cin >> this->numberOfThreads;

        cout << endl << "Please enter the maximum allowed time for a single thread in seconds:\n";
        cin >> this->allowedEngineTimeInSeconds;

        cout << endl << "Please enter how many opening moves you want me (The engine moves\nonly not including your moves) to use depending on Stockfish:\n";
        cin >> this->theNumberOfOpeningMovesToGetFromStockfish;

        if (choice) {
            cout << "\n" << ENGINE_NAME << " engine is Black, and you are White, let's"
                    " move on ;) :\n\n\n";
        }
        else {
            cout << "\n" << ENGINE_NAME << " engine is White, you are Black, let's"
                    " move on ;) :\n\n";
        }
        cout << "##################################################" << endl << endl;

        this->engineColor = (!((bool)(choice)));

    }

    bool engineTurnNow() {
        return (((((int)(this->previousMoves.size())) & 1) && (!this->engineColor)) ||
                ((!(((int)(this->previousMoves.size())) & 1)) && (engineColor)));
    }

    string getMovesStringFromPreviousMoves() const {
        string movesString = "";
        for (const string& currentMove : this->previousMoves) {
            movesString += currentMove;
            movesString += " ";
        }
        return movesString;
    }

    bool isValidMove(const string& correspondingMove) {

        string movesString = this->getMovesStringFromPreviousMoves();

        vector<string> validMoves = this->stockfishHandler.getAllPossibleMoves(movesString);

        for (const string& validMove : validMoves) {
            if (correspondingMove == validMove) {
                return 1;
            }
        }

        return 0;

    }

    // This JSON object is also the request that Engine UCI sends to every Kernel worker (one line each).
    Json serializeObject() const {

        Json serializedObjectAsJson;
        serializedObjectAsJson["engineColor"] = this->engineColor;
        serializedObjectAsJson["allowedEngineTimeInSeconds"] = this->allowedEngineTimeInSeconds;
        serializedObjectAsJson["previousMoves"] = this->previousMoves;
        serializedObjectAsJson["bestMove"] = this->bestMove;
        serializedObjectAsJson["bestMoveScore"] = this->bestMoveScore;
        serializedObjectAsJson["movesForThisThread"] = this->movesForThisThread;
        serializedObjectAsJson["report"] = this->report;

        return serializedObjectAsJson;

    }

    // at() instead of [] so that a missing key throws (and the Kernel worker answers with an error),
    // instead of reading garbage.
    static ChessState deserializeObject(const Json& serializedObjectAsJson) {

        ChessState deserializedObject = ChessState();
        deserializedObject.engineColor = serializedObjectAsJson.at("engineColor");
        deserializedObject.allowedEngineTimeInSeconds = serializedObjectAsJson.at("allowedEngineTimeInSeconds");
        deserializedObject.previousMoves = serializedObjectAsJson.at("previousMoves");
        deserializedObject.bestMove = serializedObjectAsJson.at("bestMove");
        deserializedObject.bestMoveScore = serializedObjectAsJson.at("bestMoveScore");
        deserializedObject.movesForThisThread = serializedObjectAsJson.at("movesForThisThread");
        deserializedObject.report = serializedObjectAsJson.at("report");

        return deserializedObject;

    }

    string getStockfishBestMoveByDepth(const int& depth) {
        // After ply 80 Stockfish plays the end game on purpose; before that, it's the opening.
        this->decisionPath = (this->previousMoves.size() > 80) ? "stockfish_endgame" : "stockfish_opening";
        this->stockfishDepthUsed = depth;
        return this->stockfishHandler.getBestMoveByDepth(this->getMovesStringFromPreviousMoves(), depth);
    }

    string getEngineMoveWithThreading() {

        chrono::steady_clock::time_point legalMovesStartTime = chrono::steady_clock::now();
        vector<string> allPossibleMoves = this->stockfishHandler.getAllPossibleMoves(
                                              this->getMovesStringFromPreviousMoves());
        this->legalMovesMilliseconds += MillisecondsSince(legalMovesStartTime);
        this->numberOfLegalMoves = (int)allPossibleMoves.size();

        if (allPossibleMoves.size() == 0) {
            // There is not a single valid move for this position, the game is over. "0000" is UCI's answer
            // for that (before, the report text itself was returned as the move).
            this->decisionPath = "no_legal_move";
            return "0000";
        }
        else if (allPossibleMoves.size() == 1) {
            // There is only one possible move, currently I don't care about other details like the
            // current move score.
            this->decisionPath = "only_move";
            return allPossibleMoves[0];
        }

        // I should modify all the following function according to each game maybe, it's easy to
        // manipulate with and super important in many other sides.
        if (this->previousMoves.size() < (this->theNumberOfOpeningMovesToGetFromStockfish * 2)) {

            if ((this->allowedEngineTimeInSeconds >= 60) && (this->previousMoves.size() > 80)) {
                return this->getStockfishBestMoveByDepth(26);
            }
            if ((this->allowedEngineTimeInSeconds >= 30) && (this->previousMoves.size() > 80)) {
                return this->getStockfishBestMoveByDepth(24);
            }
            else if ((this->allowedEngineTimeInSeconds >= 20) && (this->previousMoves.size() > 80)) {
                return this->getStockfishBestMoveByDepth(22);
            }
            else if ((this->allowedEngineTimeInSeconds >= 10) && (this->previousMoves.size() > 80)) {
                return this->getStockfishBestMoveByDepth(18);
            }

            // Not to lost on time or so because of deeper Stockfish depths.
            if (this->allowedEngineTimeInSeconds <= 3) {
                return this->getStockfishBestMoveByDepth(14);
            }
            else if (this->allowedEngineTimeInSeconds <= 5) {
                return this->getStockfishBestMoveByDepth(16);
            }

            // seed the random number generator with current time.
            srand(time(0));
            vector<int> possibleDepths = {14, 16, 18, 20};
            int8_t randomChosenDepth = possibleDepths[rand() % 4];
            return this->getStockfishBestMoveByDepth(randomChosenDepth);

        }

        // Before, every thread wrote a JSON file, started a brand-new Kernel.exe through cmd.exe and read the
        // file back. Now the Kernel workers are already running (Kernel Workers.hpp), so every bucket of moves
        // goes to one worker as one request line, and all the workers think at the same time.
        KernelWorkerPool& kernelWorkerPool = GetTheKernelWorkerPool();
        string kernelWorkersError;
        if (!kernelWorkerPool.waitUntilStarted(kernelWorkersError)) {
            WriteToUciLog("!! Kernel workers: " + kernelWorkersError);
        }

        // Only the workers that are alive and ready get moves, so a worker that died while it was waiting can
        // never take its share of the root moves with it.
        vector<int> workerSlots = kernelWorkerPool.getUsableWorkerSlots();
        int threadsNumberForThisPosition = min(min(this->numberOfThreads, (int)workerSlots.size()),
                                               (int)allPossibleMoves.size());
        workerSlots.resize(max(threadsNumberForThisPosition, 0));

        if (threadsNumberForThisPosition == 0) {
            // Not a single Kernel worker is running (none could start, or all of them died), so Stockfish plays
            // this move instead of a crash.
            WriteToUciLog("!! no Kernel worker is running: Stockfish (depth 14) plays this move");
            string stockfishMove = this->getStockfishBestMoveByDepth(14);
            this->decisionPath = "no_kernel_answer";
            return stockfishMove;
        }

        vector<vector<string>> movesForEachThread(threadsNumberForThisPosition, vector<string>(0));
        std::shuffle(allPossibleMoves.begin(), allPossibleMoves.end(), rng);

        int helperNum = 1;
        for (const string& currentMove : allPossibleMoves) {
            movesForEachThread[helperNum % threadsNumberForThisPosition].push_back(currentMove);
            helperNum++;
        }

        vector<string> requestLines(threadsNumberForThisPosition);
        vector<long long> requestIds(threadsNumberForThisPosition);
        for (int i = 0; i < threadsNumberForThisPosition; i++) {
            Json request = this->serializeObject();
            request["movesForThisThread"] = movesForEachThread[i];
            request["type"] = "search";
            requestIds[i] = kernelWorkerPool.getNewRequestId();
            request["id"] = requestIds[i];
            requestLines[i] = request.dump();
        }

        // A worker stops by itself at its allowed time; the 2 extra seconds are only for a worker that hangs.
        chrono::steady_clock::time_point kernelWorkersStartTime = chrono::steady_clock::now();
        vector<KernelWorkerPool::WorkerAnswer> answers = kernelWorkerPool.askAllWorkers(
                                                             workerSlots, requestLines, requestIds,
                                                             this->allowedEngineTimeInSeconds * 1000 + 2000);
        this->kernelWorkersMilliseconds += MillisecondsSince(kernelWorkersStartTime);

        vector<pair<int, string>> allMovesWithTheirScores;
        this->kernelWorkersAnswers = Json::array();
        for (int i = 0; i < threadsNumberForThisPosition; i++) {

            Json workerRecord;
            // The worker's own number (1..28), so the database can follow one worker from move to move.
            workerRecord["worker"] = workerSlots[i] + 1;
            workerRecord["rootMoves"] = movesForEachThread[i];
            workerRecord["milliseconds"] = answers[i].milliseconds;
            string status = answers[i].status;      // answered / timeout / dead
            if (status == "answered") {
                const Json& answer = answers[i].message;
                workerRecord["answer"] = answer;
                if (answer.value("type", "") == "error") {
                    status = "error";
                    workerRecord["error"] = answer.value("message", "");
                }
                else {
                    status = answer.value("status", "error");
                }
            }

            // An answer counts only if it's one of this worker's own moves.
            if (status == "ok") {
                const Json& answer = answers[i].message;
                string workerBestMove = (answer.contains("bestMove") && answer["bestMove"].is_string())
                                            ? answer["bestMove"].get<string>() : "";
                bool isOneOfThisThreadMoves = false;
                for (const string& currentMove : movesForEachThread[i]) {
                    if (TrimSpaces(currentMove) == TrimSpaces(workerBestMove)) {
                        isOneOfThisThreadMoves = true;
                    }
                }
                if (isOneOfThisThreadMoves && answer.contains("score") && answer["score"].is_number_integer()) {
                    allMovesWithTheirScores.push_back({answer["score"].get<int>(), workerBestMove});
                }
                else {
                    status = "rejected";
                    workerRecord["error"] = isOneOfThisThreadMoves ? string("its score isn't an integer")
                                                                   : "bestMove '" + workerBestMove +
                                                                     "' isn't one of this worker's moves";
                }
            }
            if (status != "ok") {
                WriteToUciLog("!! Kernel worker " + to_string(workerSlots[i] + 1) + ": " + status +
                              (workerRecord.contains("error") ? " (" + workerRecord["error"].get<string>() + ")" : ""));
            }
            workerRecord["status"] = status;
            this->kernelWorkersAnswers.push_back(workerRecord);

        }

        if (allMovesWithTheirScores.empty()) {
            // Not a single Kernel worker gave a usable answer, so Stockfish plays this move instead of a
            // garbage move or a crash.
            WriteToUciLog("!! no usable Kernel answer: Stockfish (depth 14) plays this move");
            string stockfishMove = this->getStockfishBestMoveByDepth(14);
            this->decisionPath = "no_kernel_answer";
            return stockfishMove;
        }

        sort(allMovesWithTheirScores.begin(), allMovesWithTheirScores.end(),
             greater<pair<int, string>>());

        this->bestMove = allMovesWithTheirScores[0].second;
        this->bestMoveScore = allMovesWithTheirScores[0].first;
        this->decisionPath = "kernel";

        return allMovesWithTheirScores[0].second;

    }


    /*
     * I will implement a function that sort the moves on depth 6, and then handle
     * the threads' moves distribution process efficiently in a smart way to reduce time.
     * I am definitely sure this will affect the performance a lot.
     */


    // I should Check the logic of the following three functions more, they are not 100% accurate.
    // The following three functions should be reimplemented on the StockfishHandler class.
    bool isCheckmatePosition() {
        return this->stockfishHandler.isCheckmatePosition(
                                        this->getMovesStringFromPreviousMoves());
    }

    bool isTiePosition() {
        return this->stockfishHandler.isStalematePosition(
                                        this->getMovesStringFromPreviousMoves());
    }

    bool isStalematePosition() {
        return 0;
    }

};

#endif // CHESS_STATE_H_INCLUDED
