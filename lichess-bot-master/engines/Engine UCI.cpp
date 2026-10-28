#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <iomanip>
#include <windows.h>    // GetModuleFileNameA, CreateDirectoryA
#include <direct.h>     // _getcwd
#include <algorithm>
#include <mutex>
#include <cctype>

// ############################################################ \\

// ChessState, the Kernel workers, the one Stockfish, the log (and Json, ENGINE_NAME, rng).
#include "Chess State.hpp"
// Every move goes into lichess-bot-master\database\mrbits.sqlite.
#include "Game Database.hpp"

// ############################################################ \\

// The lichess game id. lichess-bot sends it through "setoption name GameId value ..." when it creates the
// engine for a game (see extra_game_handlers.py), and every move of the game is stored under it.
string GAME_ID = "";
// The id this game is stored under: GAME_ID, or a local one when nobody sent a game id (a test by hand).
string DATABASE_GAME_ID = "";

// The opponent, as python-chess sends it through "setoption name UCI_Opponent value <title> <rating>
// <computer|human> <name>" right after every "ucinewgame".
Json OPPONENT = nullptr;

// A label for the log and the database. Changing it (g++ -DMRBITS_BUILD_STAMP=...) also gives the .exe a new
// hash, which matters on this PC: Windows Smart App Control judges every new .exe on its first launch, and
// if it blocks one build, a rebuild with a new stamp gets a new verdict.
#ifndef MRBITS_BUILD_STAMP
#define MRBITS_BUILD_STAMP "dev"
#endif

// The number of Kernel workers (they were the 28 threads, each with its own brand-new Kernel.exe).
const int NUMBER_OF_KERNEL_WORKERS = 28;

// ############################################################ \\

// Every path comes from the folder of this .exe (ExecutableDirectory() is in "Stockfish Handler.hpp"), and
// never from the folder the engine was launched from. That was the reason for my Stockfish copies.
string RootDirectory() {
    string executableDirectory = ExecutableDirectory();
    size_t lastSlashIndex = executableDirectory.find_last_of("\\/");
    if (lastSlashIndex == string::npos) {
        return executableDirectory + "\\..";
    }
    return executableDirectory.substr(0, lastSlashIndex);
}

string KernelExecutableFilePath() {
    return ExecutableDirectory() + "\\Kernel.exe";
}

string LogsDirectory() {
    return ExecutableDirectory() + "\\logs";
}

// The tests point MRBITS_DATABASE_FILE at a temporary database, so they never touch the real games.
string DatabaseFilePath() {
    const char* databaseFilePathForTheTests = getenv("MRBITS_DATABASE_FILE");
    if (databaseFilePathForTheTests && *databaseFilePathForTheTests) {
        return databaseFilePathForTheTests;
    }
    return RootDirectory() + "\\database\\mrbits.sqlite";
}

string DatabaseSchemaFilePath() {
    return RootDirectory() + "\\database\\schema.sql";
}

bool DoesPathExist(const string& path) {
    return GetFileAttributesA(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

string ToLowerCase(string text) {
    for (char& currentCharacter : text) {
        currentCharacter = (char)tolower((unsigned char)currentCharacter);
    }
    return text;
}

long long UnixTimeInMilliseconds() {
    return chrono::duration_cast<chrono::milliseconds>(chrono::system_clock::now().time_since_epoch()).count();
}

// ############################################################ \\

// One UCI line to lichess-bot, flushed at once. Without the flush, the line waits in the buffer until the next
// getline(cin) (cin is tied to cout), so everything done after printing it would still be on my clock.
void SendUciLine(const string& line) {
    cout << line << "\n" << flush;
    WriteToUciLog("<< " + line);
}

// A problem goes to the log AND to the database's events table.
void RecordEvent(const string& level, const string& source, const string& message, const int& ply = 0) {
    WriteToUciLog("!! " + source + ": " + message);
    GetTheGameDatabase().recordEvent(DATABASE_GAME_ID.empty() ? GAME_ID : DATABASE_GAME_ID, ply, level, source,
                                     message);
}

// "setoption name GameId value tN252leL". The name can have spaces, and the value is everything after
// " value " (it can be empty). UCI option names are case-insensitive.
void ApplySetOptionLine(const string& line) {
    size_t namePosition = line.find(" name ");
    if (namePosition == string::npos) {
        WriteToUciLog("   malformed setoption ignored");
        return;
    }
    size_t nameStartIndex = namePosition + 6;
    size_t valuePosition = line.find(" value ", nameStartIndex);
    string optionName, optionValue;
    if (valuePosition != string::npos) {
        optionName = TrimSpaces(line.substr(nameStartIndex, valuePosition - nameStartIndex));
        optionValue = TrimSpaces(line.substr(valuePosition + 7));
    }
    else {
        optionName = TrimSpaces(line.substr(nameStartIndex));
        // "setoption name GameId value" with nothing after "value"
        if (optionName.size() >= 6 && ToLowerCase(optionName.substr(optionName.size() - 6)) == " value") {
            optionName = TrimSpaces(optionName.substr(0, optionName.size() - 6));
        }
    }
    // "<empty>" (and "none") is how an empty default can come back from python-chess.
    if (optionValue == "<empty>" || optionValue == "none") {
        optionValue = "";
    }

    if (ToLowerCase(optionName) == "gameid") {
        GAME_ID = optionValue;
        DATABASE_GAME_ID = "";
        WriteToUciLog("   GameId = '" + GAME_ID + "'");
    }
    else if (ToLowerCase(optionName) == "uci_opponent") {
        // python-chess 1.10.0 sends "<title|none> <rating|none> <computer|human> <name, may contain spaces>".
        istringstream fields(optionValue);
        string title, rating, kind, name;
        fields >> title >> rating >> kind;
        getline(fields, name);
        // A rating is plain digits, 9 at most, so stoi() can never throw here.
        bool isRating = !rating.empty() && rating.size() <= 9 &&
                        all_of(rating.begin(), rating.end(), [](unsigned char c) { return isdigit(c) != 0; });
        OPPONENT = Json::object();
        OPPONENT["title"] = (title.empty() || title == "none") ? Json(nullptr) : Json(title);
        OPPONENT["rating"] = isRating ? Json(stoi(rating)) : Json(nullptr);
        OPPONENT["isBot"] = (kind == "computer") ? Json(true) : ((kind == "human") ? Json(false) : Json(nullptr));
        OPPONENT["name"] = TrimSpaces(name).empty() ? Json(nullptr) : Json(TrimSpaces(name));
        WriteToUciLog("   UCI_Opponent = " + OPPONENT.dump());
    }
    else {
        WriteToUciLog("   ignored unknown option '" + optionName + "'");
    }
}

// ############################################################ \\

// moveRecord gets everything the database stores about this move (Engine UCI adds the rest after "bestmove").
string getBestMoveFromEngine(string position, int wtime, int btime, int winc, int binc, Json& moveRecord) {

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

    // Set the engine's color, and we know its color from the number of moves so far.
    bool engineColor = !(currentChessState.previousMoves.size() & 1);
    currentChessState.setEngineColor(engineColor);

    currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(2);
    currentChessState.setNumberOfThreads(NUMBER_OF_KERNEL_WORKERS);

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

    string engineMove;
    double tieCheckMilliseconds = 0;
    if (currentChessState.previousMoves.size() <
        (currentChessState.getTheNumberOfOpeningMovesToGetFromStockfish() * 2)) {
        engineMove = currentChessState.getEngineMoveWithThreading();
    }
    /*
     * The following condition is a temporarily experiment to let Stockfish plays
     * the end game assuming that the end game is after some chosen move number
     */
    else if (currentChessState.previousMoves.size() > 80) {
        currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(1000000);
        engineMove = currentChessState.getEngineMoveWithThreading();
    }
    /*
     * Now checking if it's a move that leads directly to a stupid tie position
     * problem by my Kernel, and let Stockfish fix that issue by playing the
     * best move.
     */
    else {
        engineMove = currentChessState.getEngineMoveWithThreading();
        // Only a Kernel move is checked: the other paths are Stockfish's own moves, or the only legal move
        // (and Stockfish would give that same move back).
        chrono::steady_clock::time_point tieCheckStartTime = chrono::steady_clock::now();
        bool isTieMove = (currentChessState.decisionPath == "kernel") &&
                         currentChessState.stockfishHandler.isTiePosition(
                             currentChessState.getMovesStringFromPreviousMoves() + " " + engineMove);
        tieCheckMilliseconds = MillisecondsSince(tieCheckStartTime);
        if (isTieMove) {
            int currentNumberOfMovesToGetFromStockfish =
                currentChessState.getTheNumberOfOpeningMovesToGetFromStockfish();
            currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(400);
            engineMove = currentChessState.getEngineMoveWithThreading();
            currentChessState.setTheNumberOfOpeningMovesToGetFromStockfish(currentNumberOfMovesToGetFromStockfish);
            // My Engine's Kernel played a Tie move. Stockfish corrected it.
            currentChessState.decisionPath = "stalemate_override";
        }
    }

    // What the database keeps about this move. (Before, a text report went into history\<game>\<time>.txt.)
    moveRecord["ply"] = (int)currentChessState.previousMoves.size() + 1;
    moveRecord["ourColor"] = engineColor ? "white" : "black";
    moveRecord["allowedSeconds"] = allowedEngineTimeInSeconds;
    moveRecord["path"] = currentChessState.decisionPath;
    moveRecord["legalMoves"] = currentChessState.numberOfLegalMoves;
    moveRecord["workers"] = currentChessState.kernelWorkersAnswers.size();
    moveRecord["bestMove"] = engineMove;
    moveRecord["bestScore"] = (currentChessState.decisionPath == "kernel") ? Json(currentChessState.bestMoveScore)
                                                                          : Json(nullptr);
    moveRecord["stockfishDepth"] = (currentChessState.decisionPath.rfind("stockfish", 0) == 0 ||
                                    currentChessState.decisionPath == "stalemate_override" ||
                                    currentChessState.decisionPath == "no_kernel_answer")
                                       ? Json(currentChessState.stockfishDepthUsed) : Json(nullptr);
    moveRecord["legalMovesMs"] = currentChessState.legalMovesMilliseconds;
    moveRecord["kernelMs"] = currentChessState.kernelWorkersMilliseconds;
    moveRecord["tieCheckMs"] = tieCheckMilliseconds;
    moveRecord["kernelWorkers"] = currentChessState.kernelWorkersAnswers;

    return engineMove;

}

// ############################################################ \\

// Called before the engine exits, normally or not: the Kernel workers stop, and the last moves are written.
void ShutDownTheHelpers() {
    GetTheKernelWorkerPool().shutdown();
    GetTheGameDatabase().close(3000);
}

int main() {
    SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);

    OpenUciLogFile(LogsDirectory());
    char workingDirectory[1024] = "";
    _getcwd(workingDirectory, sizeof(workingDirectory));
    WriteToUciLog("== Engine UCI (build " MRBITS_BUILD_STAMP ") started, pid " + to_string(GetCurrentProcessId()));
    WriteToUciLog("   exe dir   : " + ExecutableDirectory());
    WriteToUciLog("   root dir  : " + RootDirectory());
    WriteToUciLog("   cwd       : " + string(workingDirectory));
    WriteToUciLog("   stockfish : " + StockfishExecutableFilePath() +
                  (DoesPathExist(StockfishExecutableFilePath()) ? "" : "   <-- MISSING"));
    WriteToUciLog("   kernel    : " + KernelExecutableFilePath() +
                  (DoesPathExist(KernelExecutableFilePath()) ? "" : "   <-- MISSING"));

    // Nothing starts here yet: the Kernel workers start on "ucinewgame" (so lichess-bot's quick check of the
    // engine at startup costs nothing), and the database opens in its own thread.
    GetTheKernelWorkerPool().configure(KernelExecutableFilePath(), LogsDirectory() + "\\kernel_workers_stderr.log",
                                       NUMBER_OF_KERNEL_WORKERS);
    GetTheGameDatabase().open(DatabaseFilePath(), DatabaseSchemaFilePath());
    int lastStockfishRestartCount = 0;

    string line;
    string position = "startpos";
    int wtime = 0, btime = 0, winc = 0, binc = 0;
    while (getline(cin, line)) {
        while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) {
            line.pop_back();
        }
        WriteToUciLog(">> " + line);

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
            SendUciLine("id name Mr. Bits Chess Engine");
            SendUciLine("id author Tareq Ali");
            // python-chess refuses to send an option the engine didn't declare, so both are declared here.
            SendUciLine("option name GameId type string default <empty>");
            SendUciLine("option name UCI_Opponent type string default <empty>");
            SendUciLine("uciok");
        } else if (tokens[0] == "isready") {
            // The one Stockfish of this game starts here, before the first "go". lichess-bot also sends
            // "isready" when it checks the engine at startup, so a missing or blocked Stockfish shows up there:
            // without Stockfish there are no legal moves, so I don't answer "readyok" at all, and lichess-bot
            // stops right away instead of the first game dying on its first move.
            try {
                GetTheStockfishProcess().ensureStarted();
            } catch (const exception& error) {
                RecordEvent("error", "stockfish", string("could not start: ") + error.what() + "  -> exiting without readyok");
                ShutDownTheHelpers();
                return 1;
            }
            SendUciLine("readyok");
        } else if (tokens[0] == "setoption") {
            ApplySetOptionLine(line);
        } else if (tokens[0] == "ucinewgame") {
            // GAME_ID stays: python-chess sends GameId BEFORE "ucinewgame" (and UCI_Opponent right after it).
            position = "startpos";
            DATABASE_GAME_ID = "";
            OPPONENT = nullptr;
            // The Kernel workers start now, in the background: they are ready long before the first Kernel
            // move (ply 5 or 6, after Stockfish's two opening moves), and that move waits for them if they aren't.
            GetTheKernelWorkerPool().startInTheBackground();
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

            // The "go" parameters exactly as they were sent, for the database (the code below copies
            // "movetime" into wtime and btime).
            Json goParameters = Json::object();
            for (int i = 1; i + 1 < tokens.size(); ++i) {
                if (tokens[i] == "wtime" || tokens[i] == "btime" || tokens[i] == "winc" || tokens[i] == "binc" ||
                    tokens[i] == "movetime") {
                    goParameters[tokens[i]] = stoi(tokens[i + 1]);
                }
            }

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

            if (DATABASE_GAME_ID.empty()) {
                DATABASE_GAME_ID = GAME_ID.empty() ? "local-" + to_string(UnixTimeInMilliseconds()) : GAME_ID;
            }
            long long goReceivedAt = UnixTimeInMilliseconds();
            chrono::steady_clock::time_point goReceivedTime = chrono::steady_clock::now();
            Json moveRecord = Json::object();
            string bestMove;
            try {
                bestMove = getBestMoveFromEngine(position, wtime, btime, winc, binc, moveRecord);
            } catch (const exception& error) {
                // Stockfish failed twice in a row, for example. Without it I can't play this move, so I stop,
                // and the log and the database say why.
                RecordEvent("error", "engine", string("go failed: ") + error.what() + "  -> exiting");
                ShutDownTheHelpers();
                return 1;
            }
            double moveTimeInMilliseconds = MillisecondsSince(goReceivedTime);
            SendUciLine("bestmove " + bestMove);

            // Everything below happens after "bestmove" is sent, so it's not on my clock. (The only slow part is
            // restarting a worker that died, ~30 ms each, and an opponent's answer takes longer than that anyway.)
            WriteToUciLog("   go -> bestmove took " + to_string((long long)moveTimeInMilliseconds) + " ms (" +
                          moveRecord.value("path", "") + ", game '" + DATABASE_GAME_ID + "')");
            moveRecord["gameId"] = DATABASE_GAME_ID;
            moveRecord["receivedAt"] = goReceivedAt;
            moveRecord["go"] = goParameters;
            moveRecord["totalMs"] = moveTimeInMilliseconds;
            moveRecord["engineVersion"] = MRBITS_BUILD_STAMP;
            moveRecord["opponent"] = OPPONENT;
            GetTheGameDatabase().recordMove(moveRecord);

            int ply = moveRecord.value("ply", 0);
            int numberOfFailedWorkers = 0;
            for (const Json& workerRecord : moveRecord["kernelWorkers"]) {
                numberOfFailedWorkers += (workerRecord.value("status", "") != "ok");
            }
            if (numberOfFailedWorkers > 0) {
                RecordEvent("warning", "kernel workers", to_string(numberOfFailedWorkers) + " of " +
                            to_string(moveRecord["kernelWorkers"].size()) + " gave no usable answer", ply);
            }
            if (moveRecord.value("path", "") == "no_kernel_answer") {
                RecordEvent("error", "kernel workers", "no usable answer at all: Stockfish played the move", ply);
            }
            // The workers that timed out or died are replaced now, so the next move has all of them again.
            string respawnError;
            int numberOfReplacedWorkers = GetTheKernelWorkerPool().respawnTheDeadWorkers(respawnError);
            if (numberOfReplacedWorkers > 0 && respawnError.empty()) {
                RecordEvent("info", "kernel workers", "restarted " + to_string(numberOfReplacedWorkers) + " worker(s)",
                            ply);
            }
            else if (numberOfReplacedWorkers > 0) {
                RecordEvent("warning", "kernel workers", "tried to restart " + to_string(numberOfReplacedWorkers) +
                            " worker(s): " + respawnError, ply);
            }
            int stockfishRestartCount = GetTheStockfishProcess().restartCount();
            if (stockfishRestartCount != lastStockfishRestartCount) {
                RecordEvent("warning", "stockfish", "Stockfish was restarted (" + to_string(stockfishRestartCount) +
                            " time(s) in this game)", ply);
                lastStockfishRestartCount = stockfishRestartCount;
            }
        } else if (tokens[0] == "quit") {
            WriteToUciLog("== quit");
            break;
        } else {
            WriteToUciLog("   ignored command");
        }
    }

    ShutDownTheHelpers();
    WriteToUciLog("== exit");
    return 0;
}
