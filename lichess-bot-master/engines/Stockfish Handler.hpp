#ifndef STOCKFISH_HANDLER_H_INCLUDED
#define STOCKFISH_HANDLER_H_INCLUDED

#include <bits/stdc++.h>
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>    // CreateProcess, CreatePipe, Job Objects, GetModuleFileNameA

using namespace std;

// ############################################################ \\
//                            Notes                             \\
// Before, every single question to Stockfish started a new     \\
// Stockfish through cmd.exe and a temporary command file, and  \\
// that cost ~0.3-0.55 s each time. Now ONE Stockfish is        \\
// started once and kept alive for the whole game, and I talk   \\
// to it through two pipes: ~0.2 ms per question.               \\
// StockfishHandler keeps all its old public functions, so      \\
// nothing that uses it had to change.                          \\
// ############################################################ \\

// The folder of the running .exe (lichess-bot-master\engines for Engine UCI). I build every path from it,
// and never from the folder the program was launched from: that was exactly the reason I ended up with
// several Stockfish copies (each launch folder needed its own one).
inline string ExecutableDirectory() {
    char executableFilePath[MAX_PATH * 4];
    DWORD pathLength = GetModuleFileNameA(NULL, executableFilePath, (DWORD)sizeof(executableFilePath));
    string fullPath(executableFilePath, (pathLength > 0 && pathLength < sizeof(executableFilePath)) ? pathLength : 0);
    size_t lastSlashIndex = fullPath.find_last_of("\\/");
    if (lastSlashIndex == string::npos) {
        return ".";
    }
    return fullPath.substr(0, lastSlashIndex);
}

inline string StockfishExecutableFilePath() {
    return ExecutableDirectory() + "\\stockfish\\stockfish-windows-x86-64-avx2.exe";
}

// ############################################################ \\

// The one Stockfish process. It must never be copied: two copies would share and close the same pipes.
// That's why the engine never uses it directly, only through GetTheStockfishProcess() and the cheap
// StockfishHandler at the end of this file.
class StockfishProcess {
  public:
    explicit StockfishProcess(const string& stockfishExecutableFilePath = StockfishExecutableFilePath()) {
        this->stockfishExecutableFilePath = stockfishExecutableFilePath;
    }

    ~StockfishProcess() {
        lock_guard<recursive_mutex> lock(this->queriesMutex);
        this->stopStockfish(true);
        if (this->jobHandle) {
            CloseHandle(this->jobHandle);
            this->jobHandle = NULL;
        }
    }

    StockfishProcess(const StockfishProcess&) = delete;
    StockfishProcess& operator=(const StockfishProcess&) = delete;

    // Engine UCI calls this on "isready", so Stockfish is already running when the first "go" comes.
    void ensureStarted() {
        this->runWithOneRestart([&]() { this->waitUntilReady(); return 0; });
    }

    vector<string> getAllPossibleMoves(const string& movesString) {
        return this->runWithOneRestart([&]() { return this->askForAllPossibleMoves(movesString); });
    }

    string getBestMoveByDepth(const string& movesString, const int& depth) {
        return this->runWithOneRestart([&]() { return this->askForBestMoveByDepth(movesString, depth); });
    }

    // True when the side to move is in check (Stockfish's "eval" then prints "Final evaluation: none (in check)").
    bool isInCheck(const string& movesString) {
        return this->runWithOneRestart([&]() {
            return this->askForFinalEvaluationLine(movesString) == IN_CHECK_EVALUATION_LINE;
        });
    }

    bool isCheckmatePosition(const string& movesString) {
        return this->runWithOneRestart([&]() {
            return this->askForAllPossibleMoves(movesString).empty() &&
                   this->askForFinalEvaluationLine(movesString) == IN_CHECK_EVALUATION_LINE;
        });
    }

    // Exactly like before: this is true ONLY for a stalemate. A threefold repetition, the 50-move rule and
    // insufficient material are not detected here, I have to handle them somewhere else one day.
    bool isTiePosition(const string& movesString) {
        return this->runWithOneRestart([&]() {
            return this->askForAllPossibleMoves(movesString).empty() &&
                   this->askForFinalEvaluationLine(movesString) != IN_CHECK_EVALUATION_LINE;
        });
    }

    bool isStalematePosition(const string& movesString) {
        // Still not implemented, exactly like before.
        return 0;
    }

    // The same numbers as before: White's point of view in pawns, and +-100000 when the side to move is in
    // check (the sign comes from the old rule that counts the spaces in movesString).
    long double getNNUEPositionEvaluation(const string& movesString) {
        return this->runWithOneRestart([&]() { return this->askForEvaluation(movesString); });
    }

    vector<string> getSortedMovesByNNUE(const string& movesString) {
        return this->runWithOneRestart([&]() {

            vector<pair<long double, string>> movesSortingHelperVector;
            for (const string& currentMove : this->askForAllPossibleMoves(movesString)) {
                movesSortingHelperVector.push_back({this->askForEvaluation(movesString + " " + currentMove),
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
                sort(movesSortingHelperVector.begin(), movesSortingHelperVector.end(),
                     greater<pair<long double, string>>());
            }

            vector<string> sortedMoves;
            for (const pair<long double, string>& evaluatedMove : movesSortingHelperVector) {
                sortedMoves.push_back(evaluatedMove.second);
            }
            return sortedMoves;

        });
    }

    string getBestMoveByNNUE(const string& movesString) {
        vector<string> sortedMovesByNNUE = this->getSortedMovesByNNUE(movesString);
        if (sortedMovesByNNUE.size()) {
            return sortedMovesByNNUE[0];
        }
        return "";
    }

    // The following ones are for the tests and for my curiosity, the engine itself doesn't need them.
    DWORD processId() const {
        return this->stockfishProcessId.load();
    }

    int restartCount() const {
        return this->numberOfRestarts.load();
    }

    int timeoutCount() const {
        return this->numberOfTimeouts.load();
    }

    double lastStartupMilliseconds() const {
        return this->lastStartupTimeInMilliseconds.load();
    }

    // Only for comparing with the old handler: it sent "position" a second time while the first search was
    // still running (its trick of sending everything twice), and that changes ~1.5% of Stockfish's best
    // moves a little (the extra moves add to the node counter that Stockfish's draw scores use). With this
    // switch on, I can reproduce the old answers exactly. The engine always keeps it off.
    void setLegacyBestMoveCompat(bool isOn) {
        lock_guard<recursive_mutex> lock(this->queriesMutex);
        this->legacyBestMoveCompat = isOn;
    }

    // If a question takes longer than this, I kill Stockfish (then it's restarted once, and asked again).
    void setTimeouts(DWORD queryTimeoutInMilliseconds, DWORD searchTimeoutInMilliseconds) {
        lock_guard<recursive_mutex> lock(this->queriesMutex);
        this->queryTimeoutInMilliseconds = queryTimeoutInMilliseconds;
        this->searchTimeoutInMilliseconds = searchTimeoutInMilliseconds;
    }

  private:
    struct StockfishDied : runtime_error {
        using runtime_error::runtime_error;
    };

    // A pipe has no read timeout, so a Stockfish that hangs would block the move forever. The watchdog kills
    // Stockfish when the question takes too long: then the read fails like a crash, and the crash is handled
    // by restarting Stockfish once and asking again.
    class Watchdog {
      public:
        Watchdog(StockfishProcess& stockfishProcess, DWORD timeoutInMilliseconds) {
            if (timeoutInMilliseconds) {
                CreateTimerQueueTimer(&this->timer, NULL, &Watchdog::killStockfish, &stockfishProcess,
                                      timeoutInMilliseconds, 0, WT_EXECUTEONLYONCE | WT_EXECUTEINTIMERTHREAD);
            }
        }

        ~Watchdog() {
            if (this->timer) {
                // INVALID_HANDLE_VALUE: wait until a callback that is already running has finished.
                DeleteTimerQueueTimer(NULL, this->timer, INVALID_HANDLE_VALUE);
            }
        }

        Watchdog(const Watchdog&) = delete;
        Watchdog& operator=(const Watchdog&) = delete;

      private:
        HANDLE timer = NULL;

        static VOID CALLBACK killStockfish(PVOID stockfishProcessPointer, BOOLEAN) {
            StockfishProcess* stockfishProcess = static_cast<StockfishProcess*>(stockfishProcessPointer);
            stockfishProcess->timedOut = true;
            HANDLE processHandle = stockfishProcess->stockfishProcessHandle.load();
            if (processHandle) {
                TerminateProcess(processHandle, 0xDEAD);
            }
        }
    };

    static constexpr const char* IN_CHECK_EVALUATION_LINE = "Final evaluation: none (in check)";

    string stockfishExecutableFilePath;
    recursive_mutex queriesMutex;                         // one question at a time
    atomic<HANDLE> stockfishProcessHandle{NULL};          // the watchdog's timer thread reads it too
    bool wasEverStarted = false;
    HANDLE jobHandle = NULL;
    HANDLE stockfishInputPipe = NULL;                     // I write into Stockfish's stdin through this one
    HANDLE stockfishOutputPipe = NULL;                    // and read its stdout from this one
    string unreadOutput;                                  // read from the pipe, not returned as lines yet
    size_t unreadOutputStartIndex = 0;
    atomic<DWORD> stockfishProcessId{0};
    atomic<int> numberOfRestarts{0};
    atomic<int> numberOfTimeouts{0};
    atomic<double> lastStartupTimeInMilliseconds{0.0};
    atomic<bool> timedOut{false};
    DWORD queryTimeoutInMilliseconds = 10000;             // perft, eval, isready and the handshake
    DWORD searchTimeoutInMilliseconds = 300000;           // go depth N
    bool legacyBestMoveCompat = false;

    // If Stockfish is dead (or the watchdog killed it), I start it again and ask once more. If that fails
    // too, I throw, and Engine UCI writes the reason into its log.
    template <class Question>
    auto runWithOneRestart(Question&& question) -> decltype(question()) {
        lock_guard<recursive_mutex> lock(this->queriesMutex);
        for (int attempt = 0; ; attempt++) {
            try {
                if (!this->isAlive()) {
                    if (this->wasEverStarted) {
                        this->numberOfRestarts++;
                    }
                    this->startStockfish();
                }
                return question();
            } catch (const StockfishDied& error) {
                bool wasTimeout = this->timedOut.exchange(false);
                if (wasTimeout) {
                    this->numberOfTimeouts++;
                }
                this->stopStockfish(false);
                if (attempt >= 1) {
                    throw runtime_error(string("Stockfish failed twice: ") + error.what() +
                                        (wasTimeout ? " (watchdog timeout)" : ""));
                }
            }
        }
    }

    bool isAlive() const {
        HANDLE processHandle = this->stockfishProcessHandle.load();
        return processHandle && WaitForSingleObject(processHandle, 0) == WAIT_TIMEOUT;
    }

    void startStockfish() {
        this->stopStockfish(false);
        this->wasEverStarted = true;
        this->timedOut = false;
        auto startTime = chrono::steady_clock::now();

        DWORD fileAttributes = GetFileAttributesA(this->stockfishExecutableFilePath.c_str());
        if (fileAttributes == INVALID_FILE_ATTRIBUTES || (fileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
            throw StockfishDied("Stockfish executable not found: " + this->stockfishExecutableFilePath);
        }

        // My ends of the two pipes are never inheritable. Stockfish's ends become inheritable only around
        // CreateProcess, and PROC_THREAD_ATTRIBUTE_HANDLE_LIST gives Stockfish exactly these handles and
        // nothing else (no copy of my own stdin/stdout, no copy of another child's pipes).
        HANDLE stockfishStdinReadEnd = NULL, stockfishStdoutWriteEnd = NULL;
        HANDLE myWriteEnd = NULL, myReadEnd = NULL;
        if (!CreatePipe(&stockfishStdinReadEnd, &myWriteEnd, NULL, 1 << 16)) {
            throw StockfishDied("CreatePipe(stdin) failed");
        }
        if (!CreatePipe(&myReadEnd, &stockfishStdoutWriteEnd, NULL, 1 << 16)) {
            CloseHandle(stockfishStdinReadEnd);
            CloseHandle(myWriteEnd);
            throw StockfishDied("CreatePipe(stdout) failed");
        }
        HANDLE nulDevice = CreateFileA("NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                                       OPEN_EXISTING, 0, NULL);

        STARTUPINFOEXA startupInformation;
        ZeroMemory(&startupInformation, sizeof(startupInformation));
        startupInformation.StartupInfo.cb = sizeof(startupInformation);
        startupInformation.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startupInformation.StartupInfo.hStdInput = stockfishStdinReadEnd;
        startupInformation.StartupInfo.hStdOutput = stockfishStdoutWriteEnd;
        startupInformation.StartupInfo.hStdError = (nulDevice != INVALID_HANDLE_VALUE) ? nulDevice
                                                                                       : stockfishStdoutWriteEnd;

        HANDLE inheritedHandles[3] = {stockfishStdinReadEnd, stockfishStdoutWriteEnd, nulDevice};
        DWORD numberOfInheritedHandles = (nulDevice != INVALID_HANDLE_VALUE) ? 3 : 2;
        SIZE_T attributeListSize = 0;
        InitializeProcThreadAttributeList(NULL, 1, 0, &attributeListSize);
        vector<char> attributeListBuffer(attributeListSize);
        LPPROC_THREAD_ATTRIBUTE_LIST attributeList =
            reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributeListBuffer.data());
        bool hasAttributeList = InitializeProcThreadAttributeList(attributeList, 1, 0, &attributeListSize) &&
                                UpdateProcThreadAttribute(attributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                                          inheritedHandles,
                                                          numberOfInheritedHandles * sizeof(HANDLE), NULL, NULL);
        DWORD creationFlags = CREATE_NO_WINDOW | CREATE_SUSPENDED;
        if (hasAttributeList) {
            startupInformation.lpAttributeList = attributeList;
            creationFlags |= EXTENDED_STARTUPINFO_PRESENT;
        }

        string commandLine = "\"" + this->stockfishExecutableFilePath + "\"";
        vector<char> commandLineBuffer(commandLine.begin(), commandLine.end());
        commandLineBuffer.push_back('\0');
        size_t lastSlashIndex = this->stockfishExecutableFilePath.find_last_of("\\/");
        string stockfishFolder = (lastSlashIndex == string::npos) ? ""
                                     : this->stockfishExecutableFilePath.substr(0, lastSlashIndex);

        PROCESS_INFORMATION processInformation;
        ZeroMemory(&processInformation, sizeof(processInformation));
        // Inheritable for the shortest possible time. A Kernel worker started at the same moment (the pool
        // starts them in its own thread) still can't get them: the handle list above keeps them out of it.
        SetHandleInformation(stockfishStdinReadEnd, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(stockfishStdoutWriteEnd, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        if (nulDevice != INVALID_HANDLE_VALUE) {
            SetHandleInformation(nulDevice, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        }
        BOOL isCreated = CreateProcessA(this->stockfishExecutableFilePath.c_str(), commandLineBuffer.data(),
                                        NULL, NULL, TRUE, creationFlags, NULL,
                                        stockfishFolder.empty() ? NULL : stockfishFolder.c_str(),
                                        &startupInformation.StartupInfo, &processInformation);
        DWORD creationError = GetLastError();
        if (hasAttributeList) {
            DeleteProcThreadAttributeList(attributeList);
        }
        // Stockfish has its own copies of its ends now.
        CloseHandle(stockfishStdinReadEnd);
        CloseHandle(stockfishStdoutWriteEnd);
        if (nulDevice != INVALID_HANDLE_VALUE) {
            CloseHandle(nulDevice);
        }
        if (!isCreated) {
            CloseHandle(myWriteEnd);
            CloseHandle(myReadEnd);
            throw StockfishDied("CreateProcess failed for " + this->stockfishExecutableFilePath +
                                " (error " + to_string(creationError) + ")");
        }

        // A Job Object with "kill on close": if Engine UCI dies, even with taskkill /F, Windows kills
        // Stockfish too, so no Stockfish is ever left running alone.
        if (!this->jobHandle) {
            this->jobHandle = CreateJobObjectA(NULL, NULL);
            if (this->jobHandle) {
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION jobLimits;
                ZeroMemory(&jobLimits, sizeof(jobLimits));
                jobLimits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                SetInformationJobObject(this->jobHandle, JobObjectExtendedLimitInformation, &jobLimits,
                                        sizeof(jobLimits));
            }
        }
        if (this->jobHandle) {
            AssignProcessToJobObject(this->jobHandle, processInformation.hProcess);
        }
        ResumeThread(processInformation.hThread);
        CloseHandle(processInformation.hThread);

        this->stockfishProcessHandle = processInformation.hProcess;
        this->stockfishProcessId = processInformation.dwProcessId;
        this->stockfishInputPipe = myWriteEnd;
        this->stockfishOutputPipe = myReadEnd;
        this->unreadOutput.clear();
        this->unreadOutputStartIndex = 0;

        {
            // Stockfish prints its name first, so I skip lines until "uciok".
            Watchdog watchdog(*this, this->queryTimeoutInMilliseconds);
            this->writeToStockfish("uci\n");
            this->readUntilLine("uciok");
            this->writeToStockfish("isready\n");
            this->readUntilLine("readyok");
        }
        this->lastStartupTimeInMilliseconds =
            chrono::duration<double, milli>(chrono::steady_clock::now() - startTime).count();
    }

    void stopStockfish(bool isGraceful) {
        if (this->stockfishInputPipe) {
            if (isGraceful) {
                DWORD numberOfWrittenBytes = 0;
                WriteFile(this->stockfishInputPipe, "quit\n", 5, &numberOfWrittenBytes, NULL);
            }
            // Closing Stockfish's stdin is also a "quit" for it.
            CloseHandle(this->stockfishInputPipe);
            this->stockfishInputPipe = NULL;
        }
        HANDLE processHandle = this->stockfishProcessHandle.load();
        if (processHandle) {
            if (WaitForSingleObject(processHandle, isGraceful ? 2000 : 50) != WAIT_OBJECT_0) {
                TerminateProcess(processHandle, 1);
                WaitForSingleObject(processHandle, 2000);
            }
            this->stockfishProcessHandle = NULL;
            CloseHandle(processHandle);
        }
        if (this->stockfishOutputPipe) {
            CloseHandle(this->stockfishOutputPipe);
            this->stockfishOutputPipe = NULL;
        }
        this->unreadOutput.clear();
        this->unreadOutputStartIndex = 0;
        this->stockfishProcessId = 0;
    }

    void writeToStockfish(const string& text) {
        const char* nextByte = text.data();
        size_t numberOfBytesLeft = text.size();
        while (numberOfBytesLeft > 0) {
            DWORD numberOfWrittenBytes = 0;
            if (!WriteFile(this->stockfishInputPipe, nextByte, (DWORD)numberOfBytesLeft, &numberOfWrittenBytes, NULL)) {
                throw StockfishDied("WriteFile failed (error " + to_string(GetLastError()) + ")");
            }
            nextByte += numberOfWrittenBytes;
            numberOfBytesLeft -= numberOfWrittenBytes;
        }
    }

    // One whole line, without its "\n", and without the '\r' that Stockfish writes before it on Windows.
    string readLine() {
        while (true) {
            size_t newLineIndex = this->unreadOutput.find('\n', this->unreadOutputStartIndex);
            if (newLineIndex != string::npos) {
                size_t lineEndIndex = newLineIndex;
                if (lineEndIndex > this->unreadOutputStartIndex && this->unreadOutput[lineEndIndex - 1] == '\r') {
                    lineEndIndex--;
                }
                string line = this->unreadOutput.substr(this->unreadOutputStartIndex,
                                                        lineEndIndex - this->unreadOutputStartIndex);
                this->unreadOutputStartIndex = newLineIndex + 1;
                if (this->unreadOutputStartIndex == this->unreadOutput.size()) {
                    this->unreadOutput.clear();
                    this->unreadOutputStartIndex = 0;
                }
                return line;
            }
            if (this->unreadOutputStartIndex > 0) {
                this->unreadOutput.erase(0, this->unreadOutputStartIndex);
                this->unreadOutputStartIndex = 0;
            }
            char buffer[8192];
            DWORD numberOfReadBytes = 0;
            if (!ReadFile(this->stockfishOutputPipe, buffer, (DWORD)sizeof(buffer), &numberOfReadBytes, NULL)) {
                throw StockfishDied("ReadFile failed (error " + to_string(GetLastError()) + ", Stockfish gone?)");
            }
            this->unreadOutput.append(buffer, numberOfReadBytes);
        }
    }

    void readUntilLine(const char* wantedLine) {
        while (this->readLine() != wantedLine) {
        }
    }

    // "isready" -> "readyok" before every question eats whatever the last answer left behind ("go perft 1"
    // and "eval" end with an empty line). It's safe because no search is running between two questions.
    // (While a "go" runs, "isready" is NOT a barrier: Stockfish answers it at once.)
    void waitUntilReady() {
        Watchdog watchdog(*this, this->queryTimeoutInMilliseconds);
        this->writeToStockfish("isready\n");
        this->readUntilLine("readyok");
    }

    static string getPositionCommand(const string& movesString) {
        if (movesString.size() == 0) {
            return "position startpos\n";
        }
        string moves = movesString;
        for (char& currentCharacter : moves) {
            // A move string must never be able to add a command of its own.
            if (currentCharacter == '\r' || currentCharacter == '\n') {
                currentCharacter = ' ';
            }
        }
        return "position startpos moves " + moves + "\n";
    }

    // "e2e4: 1" or "e7e8q: 1" -> the move. Anything else that perft prints is not a move.
    static bool isPerftMoveLine(const string& line, string& move) {
        size_t colonIndex = line.find(": ");
        if (colonIndex != 4 && colonIndex != 5) {
            return false;
        }
        const string candidateMove = line.substr(0, colonIndex);
        bool isMove = candidateMove[0] >= 'a' && candidateMove[0] <= 'h' &&
                      candidateMove[1] >= '1' && candidateMove[1] <= '8' &&
                      candidateMove[2] >= 'a' && candidateMove[2] <= 'h' &&
                      candidateMove[3] >= '1' && candidateMove[3] <= '8' &&
                      (candidateMove.size() == 4 || candidateMove[4] == 'q' || candidateMove[4] == 'r' ||
                       candidateMove[4] == 'b' || candidateMove[4] == 'n');
        if (isMove) {
            move = candidateMove;
        }
        return isMove;
    }

    vector<string> askForAllPossibleMoves(const string& movesString) {
        this->waitUntilReady();
        Watchdog watchdog(*this, this->queryTimeoutInMilliseconds);
        this->writeToStockfish(getPositionCommand(movesString) + "go perft 1\n");
        vector<string> allPossibleMoves;
        while (true) {
            string line = this->readLine();
            if (line.compare(0, 14, "Nodes searched") == 0) {
                // An empty line follows, the next waitUntilReady() eats it.
                break;
            }
            string currentMove;
            if (isPerftMoveLine(line, currentMove)) {
                allPossibleMoves.push_back(currentMove);
            }
        }
        return allPossibleMoves;
    }

    string askForBestMoveByDepth(const string& movesString, int depth) {
        {
            // "ucinewgame" empties the hash table and the histories, so every search starts exactly like
            // a brand-new Stockfish process, the same as before.
            Watchdog watchdog(*this, this->queryTimeoutInMilliseconds);
            this->writeToStockfish("ucinewgame\nisready\n");
            this->readUntilLine("readyok");
        }
        Watchdog watchdog(*this, this->searchTimeoutInMilliseconds);
        // ONE "go" now. The old handler had to send everything twice, because the end of its command file
        // acted like "quit" and stopped a single search at once. With a pipe there is no end of file.
        string commands = getPositionCommand(movesString) + "go depth " + to_string(depth) + "\n";
        if (this->legacyBestMoveCompat) {
            commands += getPositionCommand(movesString);
        }
        this->writeToStockfish(commands);
        while (true) {
            string line = this->readLine();
            if (line.compare(0, 9, "bestmove ") == 0) {
                size_t bestMoveStartIndex = line.find_first_not_of(' ', 9);
                if (bestMoveStartIndex == string::npos) {
                    return "";
                }
                size_t bestMoveEndIndex = line.find(' ', bestMoveStartIndex);
                return line.substr(bestMoveStartIndex, bestMoveEndIndex == string::npos
                                                           ? string::npos
                                                           : bestMoveEndIndex - bestMoveStartIndex);
            }
        }
    }

    string askForFinalEvaluationLine(const string& movesString) {
        this->waitUntilReady();
        Watchdog watchdog(*this, this->queryTimeoutInMilliseconds);
        this->writeToStockfish(getPositionCommand(movesString) + "eval\n");
        while (true) {
            string line = this->readLine();
            if (line.compare(0, 16, "Final evaluation") == 0) {
                // An empty line may follow, the next waitUntilReady() eats it.
                return line;
            }
        }
    }

    long double askForEvaluation(const string& movesString) {
        string finalEvaluationLine = this->askForFinalEvaluationLine(movesString);
        if (finalEvaluationLine == IN_CHECK_EVALUATION_LINE) {
            // The old rule: the parity of the number of moves decides the sign.
            int numberOfMovesSoFar = 1;
            for (const char& currentCharacter : movesString) {
                numberOfMovesSoFar += (currentCharacter == ' ');
            }
            if (numberOfMovesSoFar & 1) {
                return 100000;
            }
            else {
                return -100000;
            }
        }
        size_t signIndex = finalEvaluationLine.find_first_of("+-", 16);
        if (signIndex == string::npos) {
            // The old fallback: evaluate after Stockfish's best reply (Stockfish 16 never needs it).
            string bestResponseMove = this->askForBestMoveByDepth(movesString, 20);
            return this->askForEvaluation(movesString + " " + bestResponseMove);
        }
        size_t numberEndIndex = finalEvaluationLine.find(' ', signIndex + 1);
        string number = finalEvaluationLine.substr(signIndex + 1, numberEndIndex == string::npos
                                                                      ? string::npos
                                                                      : numberEndIndex - signIndex - 1);
        long double evaluation = (long double)stod(number);
        if (finalEvaluationLine[signIndex] == '-') {
            return -evaluation;
        }
        return evaluation;
    }
};

// ############################################################ \\

// THE one Stockfish of this program. It's created the first time someone asks for it (C++ makes that safe
// even with threads), and it's told to quit when the program exits. Kernel.exe includes this file too, but
// never asks Stockfish anything, so it never starts one.
inline StockfishProcess& GetTheStockfishProcess() {
    static StockfishProcess theStockfishProcess;
    return theStockfishProcess;
}

// ############################################################ \\

// The same class with the same public functions as before, so nothing that uses it had to change. It holds
// nothing: every StockfishHandler (and every copy of it, ChessState copies it into every thread) talks to
// the same one Stockfish. Starting Stockfish in a constructor would have been a disaster here, because
// ChessState objects (with two handlers each) are created dozens of times per move.
class StockfishHandler {
  public:
    long double getNNUEPositionEvaluation(const string& movesString) {
        return GetTheStockfishProcess().getNNUEPositionEvaluation(movesString);
    }

    vector<string> getAllPossibleMoves(const string& movesString) {
        return GetTheStockfishProcess().getAllPossibleMoves(movesString);
    }

    string getBestMoveByDepth(const string& movesString, const int& depth) {
        return GetTheStockfishProcess().getBestMoveByDepth(movesString, depth);
    }

    string getBestMoveByNNUE(const string& movesString) {
        return GetTheStockfishProcess().getBestMoveByNNUE(movesString);
    }

    vector<string> getSortedMovesByNNUE(const string& movesString) {
        return GetTheStockfishProcess().getSortedMovesByNNUE(movesString);
    }

    bool isCheckmatePosition(const string& movesString) {
        return GetTheStockfishProcess().isCheckmatePosition(movesString);
    }

    // The following function will return true ONLY for a Stalemate (see StockfishProcess::isTiePosition).
    bool isTiePosition(const string& movesString) {
        return GetTheStockfishProcess().isTiePosition(movesString);
    }

    bool isStalematePosition(const string& movesString) {
        return GetTheStockfishProcess().isStalematePosition(movesString);
    }

};

#endif // STOCKFISH_HANDLER_H_INCLUDED
