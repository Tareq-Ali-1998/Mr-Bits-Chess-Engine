#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <iomanip>
#include <windows.h>    // FindFirstFile, FILE_ATTRIBUTE_DIRECTORY
#include <direct.h>     // _getcwd, _mkdir
#include <algorithm>

// ############################################################ \\

#include "Stockfish Handler.hpp"
#include "json.hpp"

// ############################################################ \\

using Json = nlohmann::json;

// ############################################################ \\

const string ENGINE_NAME = "Mr. Bits";

// ############################################################ \\

string GAME_NAME = "";

// ############################################################ \\

// ############################################################ \\
// Random number generator for shuffling after the new MinGW C++11 update
static std::mt19937 rng(std::random_device{}());

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

    ChessState() : engineColor(1), previousMoves({}), allowedEngineTimeInSeconds(30) {
        this->stockfishHandler = StockfishHandler();
        // this->bestMove = stockfishHandler.getBestMoveByDepth(this->getMovesStringFromPreviousMoves(), 12);
        this->bestMove = "It should be a default value like the previous line but I want to maintain more time";
        this->bestMoveScore = 0;
        this->numberOfThreads = 4;
        this->theNumberOfOpeningMovesToGetFromStockfish = 7;
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

        int theNumberOfThreads;
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

    static ChessState deserializeObject(const Json& serializedObjectAsJson) {

        ChessState deserializedObject = ChessState();
        deserializedObject.engineColor = serializedObjectAsJson["engineColor"];
        deserializedObject.allowedEngineTimeInSeconds = serializedObjectAsJson["allowedEngineTimeInSeconds"];
        deserializedObject.previousMoves = serializedObjectAsJson["previousMoves"];
        deserializedObject.bestMove = serializedObjectAsJson["bestMove"];
        deserializedObject.bestMoveScore = serializedObjectAsJson["bestMoveScore"];
        deserializedObject.movesForThisThread = serializedObjectAsJson["movesForThisThread"];
        deserializedObject.report = serializedObjectAsJson["report"];

        return deserializedObject;

    }

    string getEngineMoveWithThreading() {

        vector<string> allPossibleMoves = this->stockfishHandler.getAllPossibleMoves(
                                              this->getMovesStringFromPreviousMoves());

        if (allPossibleMoves.size() == 0) {
            this->report += "\n          ####################\n";
            this->report += "    There is not a single valid move for this position.";
            this->report += "\n          ####################\n";
            return this->report;

        }
        else if (allPossibleMoves.size() == 1) {
            this->report += "\n          ####################\n";
            this->report += "    There is only one possible move, currently I don't";
            this->report += "care about other details\n    like the current move score.";
            this->report += "\n          ####################\n";
            return allPossibleMoves[0];
        }

        // I should modify all the following function according to each game maybe, it's easy to
        // manipulate with and super important in many other sides.
        if (this->previousMoves.size() < (this->theNumberOfOpeningMovesToGetFromStockfish * 2)) {

            if ((this->allowedEngineTimeInSeconds >= 60) && (this->previousMoves.size() > 80)) {
                return this->stockfishHandler.getBestMoveByDepth(
                    this->getMovesStringFromPreviousMoves(), 26);
            }
            if ((this->allowedEngineTimeInSeconds >= 30) && (this->previousMoves.size() > 80)) {
                return this->stockfishHandler.getBestMoveByDepth(
                    this->getMovesStringFromPreviousMoves(), 24);
            }
            else if ((this->allowedEngineTimeInSeconds >= 20) && (this->previousMoves.size() > 80)) {
                return this->stockfishHandler.getBestMoveByDepth(
                    this->getMovesStringFromPreviousMoves(), 22);
            }
            else if ((this->allowedEngineTimeInSeconds >= 10) && (this->previousMoves.size() > 80)) {
                return this->stockfishHandler.getBestMoveByDepth(
                    this->getMovesStringFromPreviousMoves(), 18);
            }

            // Not to lost on time or so because of deeper Stockfish depths.
            if (this->allowedEngineTimeInSeconds <= 3) {
                return this->stockfishHandler.getBestMoveByDepth(
                    this->getMovesStringFromPreviousMoves(), 14);
            }
            else if (this->allowedEngineTimeInSeconds <= 5) {
                return this->stockfishHandler.getBestMoveByDepth(
                    this->getMovesStringFromPreviousMoves(), 16);
            }

            // seed the random number generator with current time.
            srand(time(0));
            vector<int> possibleDepths = {14, 16, 18, 20};
            int8_t randomChosenDepth = possibleDepths[rand() % 4];
            return this->stockfishHandler.getBestMoveByDepth(
                this->getMovesStringFromPreviousMoves(), randomChosenDepth);
            
        }


        int threadsNumberForThisPosition = min(this->numberOfThreads,
                                               (int)allPossibleMoves.size());

        vector<vector<pair<int, string>>> movesWithTheirScores(threadsNumberForThisPosition);

        vector<vector<string>> movesForEachThread(threadsNumberForThisPosition, vector<string>(0));
        std::shuffle(allPossibleMoves.begin(), allPossibleMoves.end(), rng);

        int helperNum = 1;
        for (const string& currentMove : allPossibleMoves) {
            movesForEachThread[helperNum % threadsNumberForThisPosition].push_back(currentMove);
            helperNum++;
        }

        vector<thread> threads(threadsNumberForThisPosition);
        vector<string> threadsReports(threadsNumberForThisPosition);
        for (int i = 0; i < threads.size(); i++) {
            ChessState currentChessState = *this;
            currentChessState.movesForThisThread = movesForEachThread[i];

            threads[i] = thread([=, &movesWithTheirScores, &threadsReports]() mutable {

                // this_thread::sleep_for(chrono::milliseconds(i * 50));
                // this_thread::sleep_for(chrono::milliseconds(10));

                // Set priority of the thread to high.
                // I should check commenting the following and check what happends then because
                // I was calling the following one in the beginning of the main function here
                // in this file:
                // SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);
                // So I should manipulate those just to learn what's happening.
                SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST);

                // Save the serialized data to a file.
                string jsonFileName = "input/thread_" + to_string(i + 1);
                jsonFileName += "_serialized_data";
                jsonFileName += ".json";
                ofstream file(jsonFileName);
                file << currentChessState.serializeObject().dump(4);
                file.close();

                currentChessState.executeExeFileWithArguments("engines/Kernel.exe", jsonFileName);

                // Read the serialized data from the file.
                ifstream readFile(jsonFileName);
                stringstream buffer;
                buffer << readFile.rdbuf();
                string serializedDataAsString = buffer.str();

                // Deserialize the object from the serialized data.
                Json receivedData = Json::parse(serializedDataAsString);

                ChessState receivedChessState = currentChessState.deserializeObject(receivedData);

                movesWithTheirScores[i].push_back({receivedChessState.bestMoveScore, receivedChessState.bestMove});
                threadsReports[i] = receivedChessState.report;

            });

        }


        for (int i = 0; i < threads.size(); i++) {
            threads[i].join();
        }

        // The following one is just preparing the final report to log into history.
        for (const string& threadReport : threadsReports) {
            this->report += "\n          ####################\n";
            this->report += threadReport;
            this->report += "\n          ####################\n";
        }

        vector<pair<int, string>> allMovesWithTheirScores;
        for (const auto& vec : movesWithTheirScores) {
            for (const auto& currentPair : vec) {
                allMovesWithTheirScores.push_back(currentPair);
            }
        }

        sort(allMovesWithTheirScores.begin(), allMovesWithTheirScores.end(),
             greater<pair<int, string>>());

        this->bestMove = allMovesWithTheirScores[0].second;
        this->bestMoveScore = allMovesWithTheirScores[0].first;

        return allMovesWithTheirScores[0].second;

    }


    /*
     * I will implement a function that sort the moves on depth 6, and then handle
     * the threads' moves distribution process efficiently in a smart way to reduce time.
     * I am definitely sure this will affect the performance a lot.
     */



     void executeExeFileWithArguments(string filePath, const string& jsonFileName) const {
        // This function executes a compiled ".exe" file with a JSON filename as its argument.
        // It is launched a child process via the Windows Command Prompt (cmd.exe) using.
        // the "system" function.

        // Note: CMD is not as flexible as PowerShell when it comes to path syntax — it expects
        // backslashes ('\\') instead of forward slashes ('/') in this case when using
        // the "system(command.c_str())" function.
        // PowerShell accepts both, but since system() uses CMD under the hood, we convert all
        // slashes to backslashes here to ensure compatibility.
        // This has been tested and confirmed.
        replace(filePath.begin(), filePath.end(), '/', '\\');

        string command = ".\\" + filePath;
        command += " ";
        command += "\"";
        command += jsonFileName;
        command += "\"";
        system(command.c_str());
    }

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






void InitializeGameNameAndHistoryFolder(const int& numberOfMovesSoFar) {

    // ensure history exists under cwd
    if (_mkdir("history") != 0 && errno != EEXIST) {
        cout << "Failed to create history folder! Errno: " << errno << endl;
    }

    if (numberOfMovesSoFar < 2) {
        // Generate timestamped game name
        auto now = chrono::system_clock::now();
        time_t now_time = chrono::system_clock::to_time_t(now);
        tm tm_struct = *localtime(&now_time);

        ostringstream oss;
        oss << put_time(&tm_struct, "%Y-%m-%d_%H-%M-%S");
        GAME_NAME = oss.str();
    }
    else {

        // Scan "history" for subdirectories
        vector<string> folderNames;
        WIN32_FIND_DATAA findData;
        HANDLE hFind = FindFirstFileA("history\\*", &findData);
        if (hFind != INVALID_HANDLE_VALUE) {
            do {
                // check for directory and skip "." & ".."
                if (findData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
                    string name = findData.cFileName;
                    if (name != "." && name != "..")
                        folderNames.push_back(name);
                }
            } while (FindNextFileA(hFind, &findData));
            FindClose(hFind);
        }

        if (!folderNames.empty()) {
            // sort lexicographically and pick the last (newest timestamp)
            sort(folderNames.begin(), folderNames.end());
            GAME_NAME = folderNames.back();
        }
        else {
            // fallback: generate a new timestamped name
            auto now       = chrono::system_clock::now();
            time_t t       = chrono::system_clock::to_time_t(now);
            tm tm_struct   = *localtime(&t);

            ostringstream oss;
            oss << put_time(&tm_struct, "%Y-%m-%d_%H-%M-%S");
            GAME_NAME = oss.str();
        }

    }

    // then ensure history\GAME_NAME exists
    string fullPath = string("history\\") + GAME_NAME;
    if (_mkdir(fullPath.c_str()) != 0 && errno != EEXIST) {
        cout << "Failed to create game folder! Errno: " << errno << endl;
    }

}

void PrintToTextFile(const string& content) {
    // build timestamped filename.
    auto now       = chrono::system_clock::now();
    time_t t       = chrono::system_clock::to_time_t(now);
    tm tm_struct   = *localtime(&t);

    ostringstream oss;
    oss << put_time(&tm_struct, "%Y-%m-%d_%H-%M-%S");
    string filename = oss.str() + ".txt";

    // get the repo root (where PowerShell was launched).
    char cwd[1024];
    _getcwd(cwd, sizeof(cwd));
    string rootPath(cwd);

    // write into history/GAME_NAME/
    string filePath = rootPath + "\\history\\" + GAME_NAME + "\\" + filename;
    ofstream outfile(filePath);
    if (!outfile) {
        cout << "Error creating file: " << filename << endl;
        return;
    }
    outfile << content;
    outfile.close();
}





// Function to send the "go" command to my engine's "Kernel.exe" asking for the best move.
string getBestMoveFromEngine(string position, int wtime, int btime, int winc, int binc) {

    // ############################################################ \\
    //                            Notes                             \\
    // This function acting like set out configuration depending on \\
    // the situation.                                               \\
    // ############################################################ \\

    ChessState currentChessState = ChessState();


    // Set the "previousMoves" vector in chess state from the given "position" string
    int startingIndex = 1000000;
    for (int i = 0; i < position.size(); i++) {
        if (position[i] == '#') {
            startingIndex = i + 2;
            break;
        }
    }
    for (int i = startingIndex; i < (int)position.size() - 3;) {
        int len = 0;
        for (int j = i; j < position.size(); j++) {
            if (position[j] == ' ') {
                break;
            }
            len++;
        }
        currentChessState.previousMoves.push_back(position.substr(i, len));
        i += len + 1;
    }
    
    int numberOfMovesSoFar = currentChessState.previousMoves.size();
    InitializeGameNameAndHistoryFolder(numberOfMovesSoFar);

    // Set the engine's color, and we know its color from the number of moves so far.
    bool engineColor = !(currentChessState.previousMoves.size() & 1);
    currentChessState.setEngineColor(engineColor);

    currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(2);
    currentChessState.setNumberOfThreads(28);

    // I have to manipulate the engine's timing system a lot, which is partially represented
    // by the following code snippet. There are so many other places related to the timing
    // system (the engine's Kernel, for example), but this is the main one.
    int allowedEngineTimeInSeconds;
    if (engineColor && wtime >= 300000) {
        allowedEngineTimeInSeconds = 90 + (int)(winc / 2000);
    } else if (engineColor && wtime >= 240000) {
        allowedEngineTimeInSeconds = 80 + (int)(winc / 3000);
    } else if (engineColor && wtime >= 180000) {
        allowedEngineTimeInSeconds = 70 + (int)(winc / 3000);
    } else if (engineColor && wtime >= 120000) {
        allowedEngineTimeInSeconds = 65 + (int)(winc / 3000);
    } else if (engineColor && wtime >= 60000) {
        allowedEngineTimeInSeconds = 50 + (int)(winc / 3000);
    } else if (engineColor && wtime >= 45000) {
        allowedEngineTimeInSeconds = 40;
    } else if (engineColor && wtime >= 15000) {
        allowedEngineTimeInSeconds = 10;
    } else if (engineColor && wtime >= 10000) {
        allowedEngineTimeInSeconds = 5;
    } else if (engineColor && wtime >= 6000) {
        allowedEngineTimeInSeconds = 3;
    } else if (engineColor && wtime >= 4000) {
        allowedEngineTimeInSeconds = 2;
    } else if (engineColor) {
        allowedEngineTimeInSeconds = 1;
    } else if (!engineColor && btime >= 300000) {
        allowedEngineTimeInSeconds = 90 + (int)(binc / 2000);
    } else if (!engineColor && btime >= 240000) {
        allowedEngineTimeInSeconds = 80 + (int)(binc / 3000);
    } else if (!engineColor && btime >= 180000) {
        allowedEngineTimeInSeconds = 70 + (int)(binc / 3000);
    } else if (!engineColor && btime >= 120000) {
        allowedEngineTimeInSeconds = 60 + (int)(binc / 3000);
    } else if (!engineColor && btime >= 60000) {
        allowedEngineTimeInSeconds = 50 + (int)(binc / 3000);
    } else if (!engineColor && btime >= 45000) {
        allowedEngineTimeInSeconds = 40;
    } else if (!engineColor && btime >= 15000) {
        allowedEngineTimeInSeconds = 10;
    } else if (!engineColor && btime >= 10000) {
        allowedEngineTimeInSeconds = 5;
    } else if (!engineColor && btime >= 6000) {
        allowedEngineTimeInSeconds = 3;
    } else if (!engineColor && btime >= 4000) {
        allowedEngineTimeInSeconds = 2;
    } else if (!engineColor) {
        allowedEngineTimeInSeconds = 1;
    }

    currentChessState.setallowedEngineTimeInSeconds(allowedEngineTimeInSeconds);

    /*
     * Set the priority of the parent process (The current process) to high, so that
     * it will be faster than usual, but here comes so many questions about priority
     * inheritance features and operating system knowledge, but after testing, I have
     * by testing realized that setting the child process to a high priority is enough,
     * but because of my funny and just-programming OCD I have decided to set this one
     * also to high.
    */
    SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);
    // Handle for the best move after setting everything

    if (currentChessState.previousMoves.size() <
        (currentChessState.getTheNumberOfOpeningMovesToGetFromStockfish() * 2)) {
        string engineMove = currentChessState.getEngineMoveWithThreading();
        string finalReport = "";
        if (currentChessState.previousMoves.size() < 2) {
            finalReport = "\n     #####  ";
            finalReport += "It is the first engine's move, so lichess specify a small\n";
            finalReport += "time (usually 5 seconds for white)for abandation.";
            finalReport += " #####\n\n";
            finalReport = "\n     #####  Thread allowed time in seconds: ";
            finalReport += to_string(currentChessState.allowedEngineTimeInSeconds);
            finalReport += " seconds.  #####\n\n";
        }
        else {
            finalReport = "\n     #####  Thread allowed time in seconds: ";
            finalReport += to_string(currentChessState.allowedEngineTimeInSeconds);
            finalReport += " seconds.  #####\n\n";
        }
        finalReport += currentChessState.report;
        PrintToTextFile(finalReport);
        return engineMove;
    }
    /*
     * The following condition is a temporarily experiment to let Stockfish plays
     * the end game assuming that the end game is after some chosen move number
     */
    else if (currentChessState.previousMoves.size() > 80) {
        currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(1000000);
        string engineMove = currentChessState.getEngineMoveWithThreading();
        string finalReport = "\n     #####  Thread allowed time in seconds: ";
        finalReport += to_string(currentChessState.allowedEngineTimeInSeconds);
        finalReport += " seconds.  #####\n\n";
        finalReport += "Now it's the end game phase when Stockfish has started ";
        finalReport += "playing from now on.\n";
        PrintToTextFile(finalReport);
        return engineMove;
    }
    /*
     * Now checking if it's a move that leads directly to a stupid tie position
     * problem by my Kernel, and let Stockfish fix that issue by playing the
     * best move.
     */
    string engineMove = currentChessState.getEngineMoveWithThreading();
    if (currentChessState.stockfishHandler.isTiePosition(
            currentChessState.getMovesStringFromPreviousMoves() + " " + engineMove)) {
        int currentNumberOfMovesToGetFromStockfish =
            currentChessState.getTheNumberOfOpeningMovesToGetFromStockfish();
        currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(400);
        engineMove = currentChessState.getEngineMoveWithThreading();
        currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(currentNumberOfMovesToGetFromStockfish);
        string finalReport = "\n     #####  Thread allowed time in seconds: ";
        finalReport += to_string(currentChessState.allowedEngineTimeInSeconds);
        finalReport += " seconds  #####\n\n";
        finalReport += "My Engine's Kernel played a Tie move. Stockfish corrected it\n\n";
        finalReport += currentChessState.report;
        PrintToTextFile(finalReport);
        return engineMove;
    }
    else {
        string finalReport = "\n     #####  Thread allowed time in seconds: ";
        finalReport += to_string(currentChessState.allowedEngineTimeInSeconds);
        finalReport += " seconds  #####\n\n";
        finalReport += currentChessState.report;
        PrintToTextFile(finalReport);
        return engineMove;
    }

}





int main() {
    SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);

    string line;
    string position = "startpos";
    int wtime = 0, btime = 0, winc = 0, binc = 0;
    while (getline(cin, line)) {
        function<vector<string>(const string&, char)> split = [](const string& str, char delimiter)
                   -> vector<string> {
            vector<string> tokens;
            // copies nothing but reads from str
            stringstream ss(str);
            string token;
            while (getline(ss, token, delimiter)) {
                tokens.emplace_back(token);
            }
            return tokens;
        };

        vector<string> tokens = split(line, ' ');
        if (tokens.size() == 0) {
            continue;
        }

        if (tokens[0] == "uci") {
            cout << "id name Mr. Bits Chess Engine\n";
            cout << "id author Tareq Ali\n";
            cout << "uciok\n";
        } else if (tokens[0] == "isready") {
            cout << "readyok\n";
        } else if (tokens[0] == "ucinewgame") {
            position = "startpos";
        } else if (tokens[0] == "position") {
            if (tokens.size() < 2) {
                continue;
            } else if (tokens[1] == "startpos") {
                position = "startpos";
                if (tokens.size() > 2 && tokens[2] == "moves") {
                    position += " moves #";
                    for (int i = 3; i < tokens.size(); ++i) {
                        position += " " + tokens[i];
                    }
                }
                position += " # ";
            } else if (tokens[1] == "fen") {
                position = "fen";
                int i = 2;
                while (i < tokens.size() && tokens[i] != "moves") {
                    position += " " + tokens[i];
                    ++i;
                }
                if (i < tokens.size() && tokens[i] == "moves") {
                    position += " moves #";
                    for (++i; i < tokens.size(); ++i) {
                        position += " " + tokens[i];
                    }
                }
            } else if (tokens[1] == "moves") {
                position += " moves #";
                for (int i = 2; i < tokens.size(); ++i) {
                    position += " " + tokens[i];
                }
            }
        } else if (tokens[0] == "go") {

            if (tokens.size() == 3 && tokens[1] == "movetime") {
                wtime = stoi(tokens[2]);
                btime = stoi(tokens[2]);
            } else {
                for (int i = 1; i < tokens.size(); ++i) {
                    if (tokens[i] == "wtime" && i + 1 < tokens.size()) {
                        wtime = stoi(tokens[i + 1]);
                    } else if (tokens[i] == "btime" && i + 1 < tokens.size()) {
                        btime = stoi(tokens[i + 1]);
                    } else if (tokens[i] == "winc" && i + 1 < tokens.size()) {
                        winc = stoi(tokens[i + 1]);
                    } else if (tokens[i] == "binc" && i + 1 < tokens.size()) {
                        binc = stoi(tokens[i + 1]);
                    }
                }
            }
            string bestMove = getBestMoveFromEngine(position, wtime, btime, winc, binc);
            cout << "bestmove " << bestMove << "\n";
        } else if (tokens[0] == "quit") {
            break;
        }
    }

    return 0;
}
