#ifndef STOCKFISH_PROCESS_HPP_INCLUDED
#define STOCKFISH_PROCESS_HPP_INCLUDED

// ############################################################################
//  StockfishProcess: ONE Stockfish kept alive and fed through pipes
//  (plan 02, Phase 1b prototype). Windows only.
//
//  * Started once with CreateProcess (no cmd.exe, no popen, no temp file),
//    stdin/stdout redirected to two anonymous pipes, stderr to NUL.
//  * Handshake: "uci" -> "uciok", "isready" -> "readyok" (the startup banner
//    is swallowed while waiting for "uciok").
//  * Same queries and the same answers as the old StockfishHandler:
//      getAllPossibleMoves  "go perft 1", lines "e2e4: 1" up to "Nodes searched"
//      getBestMoveByDepth   "ucinewgame"+"isready" first (= fresh-process state),
//                           then ONE "go depth N" up to "bestmove"
//      isCheckmatePosition  no legal move AND "Final evaluation: none (in check)"
//      isTiePosition        no legal move AND not in check  (= stalemate only!)
//      isStalematePosition  always false (the old stub, kept on purpose)
//      getNNUEPositionEvaluation / getSortedMovesByNNUE / getBestMoveByNNUE
//  * Every query first sends "isready" and reads up to "readyok": that drains
//    whatever an earlier answer left behind (perft and eval end with a blank
//    line). Note: "isready" is NOT a barrier while a "go" is running, which is
//    why each "go" is read up to its own terminator.
//  * Whole lines are read, '\r' is stripped (Stockfish writes CRLF).
//  * One mutex around every public query.
//  * If Stockfish died (or a query hit its watchdog timeout), it is restarted
//    ONCE and the query is retried. A second failure throws std::runtime_error
//    so the caller can fall back to the old popen handler for that move.
//  * The class is NOT copyable. Engine UCI must use ONE shared instance:
//    SharedStockfish(), or the copyable facade PersistentStockfishHandler.
//
//  Build (MinGW-w64 g++ 14.2): g++ -std=c++17 -O2 your.cpp -static
//  (without -static ship libstdc++-6.dll, libgcc_s_seh-1.dll, libwinpthread-1.dll).
// ############################################################################

#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include <algorithm>
#include <functional>

class StockfishProcess {
  public:
    // Folder of the running .exe (plan 02 Phase 1a): never the working directory.
    static std::string ExecutableDirectory() {
        char buffer[MAX_PATH * 4];
        DWORD n = GetModuleFileNameA(NULL, buffer, (DWORD)sizeof(buffer));
        std::string path(buffer, (n > 0 && n < sizeof(buffer)) ? n : 0);
        size_t slash = path.find_last_of("\\/");
        return (slash == std::string::npos) ? std::string(".") : path.substr(0, slash);
    }

    static std::string DefaultExecutablePath() {
        return ExecutableDirectory() + "\\stockfish\\stockfish-windows-x86-64-avx2.exe";
    }

    explicit StockfishProcess(const std::string& executablePath = DefaultExecutablePath())
        : exePath(executablePath) {}

    ~StockfishProcess() {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        stopProcess(true);
        if (hJob) {
            CloseHandle(hJob);
            hJob = NULL;
        }
    }

    StockfishProcess(const StockfishProcess&) = delete;
    StockfishProcess& operator=(const StockfishProcess&) = delete;

    // ---------------------------------------------------------------- queries

    // Start Stockfish now (e.g. on "uci"/"isready"), so the first move doesn't pay for it.
    void ensureStarted() {
        withRestart([&]() { sync(); return 0; });
    }

    std::vector<std::string> getAllPossibleMoves(const std::string& movesString) {
        return withRestart([&]() { return perftQuery(movesString); });
    }

    std::string getBestMoveByDepth(const std::string& movesString, const int& depth) {
        return withRestart([&]() { return depthQuery(movesString, depth); });
    }

    // Side to move is in check (Stockfish's eval prints "Final evaluation: none (in check)").
    bool isInCheck(const std::string& movesString) {
        return withRestart([&]() { return finalEvaluationLine(movesString) == kInCheckLine; });
    }

    bool isCheckmatePosition(const std::string& movesString) {
        return withRestart([&]() {
            return perftQuery(movesString).empty() && finalEvaluationLine(movesString) == kInCheckLine;
        });
    }

    // Same as the old handler: TRUE ONLY FOR STALEMATE (no 3-fold / 50-move / material draws).
    bool isTiePosition(const std::string& movesString) {
        return withRestart([&]() {
            return perftQuery(movesString).empty() && finalEvaluationLine(movesString) != kInCheckLine;
        });
    }

    // Same as the old handler: a stub that always answers false.
    bool isStalematePosition(const std::string&) { return false; }

    // Same numbers as the old handler: white's view in pawns; +-100000 when the side to move is in
    // check (sign from the old parity rule on the number of spaces in movesString).
    long double getNNUEPositionEvaluation(const std::string& movesString) {
        return withRestart([&]() { return evaluationQuery(movesString); });
    }

    std::vector<std::string> getSortedMovesByNNUE(const std::string& movesString) {
        return withRestart([&]() {
            std::vector<std::pair<long double, std::string>> scored;
            for (const std::string& move : perftQuery(movesString))
                scored.push_back({evaluationQuery(movesString + " " + move), move});
            int playedMoves = 0;
            if (!movesString.empty())
                playedMoves = 1 + (int)std::count(movesString.begin(), movesString.end(), ' ');
            if (playedMoves & 1)
                std::sort(scored.begin(), scored.end());
            else
                std::sort(scored.begin(), scored.end(), std::greater<std::pair<long double, std::string>>());
            std::vector<std::string> sorted;
            for (const auto& entry : scored) sorted.push_back(entry.second);
            return sorted;
        });
    }

    std::string getBestMoveByNNUE(const std::string& movesString) {
        std::vector<std::string> sorted = getSortedMovesByNNUE(movesString);
        return sorted.empty() ? std::string() : sorted[0];
    }

    // ------------------------------------------------------------ diagnostics

    DWORD processId() const { return pid.load(); }
    int restartCount() const { return restarts.load(); }
    double lastStartupMilliseconds() const { return lastStartupMs.load(); }
    int timeoutCount() const { return timeouts.load(); }
    // Legacy compatibility (equivalence tests only): replay the old handler's command order
    // "position, go depth N, position". The old file's 2nd "position" runs while search 1 is running and
    // adds N to the searching thread's node counter (Position::do_move), which changes value_draw()
    // (search.cpp:90) and so sometimes the bestmove. Default OFF = the clean Stockfish answer.
    void setLegacyBestMoveCompat(bool on) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        legacyBestMoveCompat = on;
    }
    // Watchdogs: a query that takes longer gets Stockfish killed (then: restart + one retry).
    void setTimeouts(DWORD queryMs, DWORD searchMs) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        queryTimeoutMs = queryMs;
        searchTimeoutMs = searchMs;
    }

  private:
    struct Died : std::runtime_error {
        using std::runtime_error::runtime_error;
    };

    // Kills Stockfish if the guarded scope takes longer than the timeout. That turns a hang
    // into a broken pipe, which the restart logic handles. 0 = no watchdog.
    class Watchdog {
      public:
        Watchdog(StockfishProcess& owner, DWORD milliseconds) {
            if (milliseconds)
                CreateTimerQueueTimer(&timer, NULL, &Watchdog::fire, &owner, milliseconds, 0,
                                      WT_EXECUTEONLYONCE | WT_EXECUTEINTIMERTHREAD);
        }
        ~Watchdog() {
            if (timer) DeleteTimerQueueTimer(NULL, timer, INVALID_HANDLE_VALUE); // waits for a running callback
        }
        Watchdog(const Watchdog&) = delete;
        Watchdog& operator=(const Watchdog&) = delete;

      private:
        static VOID CALLBACK fire(PVOID parameter, BOOLEAN) {
            StockfishProcess* owner = static_cast<StockfishProcess*>(parameter);
            owner->timedOut = true;
            HANDLE process = owner->hProcess.load();
            if (process) TerminateProcess(process, 0xDEAD);
        }
        HANDLE timer = NULL;
    };

    static constexpr const char* kInCheckLine = "Final evaluation: none (in check)";

    std::string exePath;
    std::recursive_mutex mutex;
    std::atomic<HANDLE> hProcess{NULL}; // also read by the watchdog's timer thread
    bool everStarted = false;
    HANDLE hJob = NULL;
    HANDLE hToChild = NULL;   // our write end of Stockfish's stdin
    HANDLE hFromChild = NULL; // our read end of Stockfish's stdout
    std::string pending;      // bytes read from the pipe but not yet returned as lines
    size_t pendingOffset = 0;
    std::atomic<DWORD> pid{0};
    std::atomic<int> restarts{0};
    std::atomic<int> timeouts{0};
    std::atomic<double> lastStartupMs{0.0};
    std::atomic<bool> timedOut{false};
    DWORD queryTimeoutMs = 10000;   // perft, eval, isready, handshake
    DWORD searchTimeoutMs = 300000; // go depth N
    bool legacyBestMoveCompat = false;

    template <class Function>
    auto withRestart(Function&& function) -> decltype(function()) {
        std::lock_guard<std::recursive_mutex> lock(mutex);
        for (int attempt = 0;; attempt++) {
            try {
                if (!isAlive()) {
                    if (everStarted) restarts++; // died since the last query, or failed just now
                    startProcess();
                }
                return function();
            } catch (const Died& error) {
                bool wasTimeout = timedOut.exchange(false);
                if (wasTimeout) timeouts++;
                stopProcess(false);
                if (attempt >= 1)
                    throw std::runtime_error(std::string("Stockfish failed twice: ") + error.what() +
                                             (wasTimeout ? " (watchdog timeout)" : ""));
            }
        }
    }

    bool isAlive() const {
        HANDLE process = hProcess.load();
        return process && WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
    }

    void startProcess() {
        stopProcess(false);
        everStarted = true;
        timedOut = false;
        auto t0 = std::chrono::steady_clock::now();
        DWORD fileAttributes = GetFileAttributesA(exePath.c_str());
        if (fileAttributes == INVALID_FILE_ATTRIBUTES || (fileAttributes & FILE_ATTRIBUTE_DIRECTORY))
            throw Died("Stockfish executable not found: " + exePath);

        // Our ends are never inheritable; the child's ends become inheritable only around
        // CreateProcess, and PROC_THREAD_ATTRIBUTE_HANDLE_LIST gives Stockfish exactly these three.
        HANDLE childIn = NULL, childOut = NULL;
        HANDLE toChild = NULL, fromChild = NULL;
        if (!CreatePipe(&childIn, &toChild, NULL, 1 << 16)) throw Died("CreatePipe(stdin) failed");
        if (!CreatePipe(&fromChild, &childOut, NULL, 1 << 16)) {
            CloseHandle(childIn);
            CloseHandle(toChild);
            throw Died("CreatePipe(stdout) failed");
        }
        HANDLE nul = CreateFileA("NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                                 OPEN_EXISTING, 0, NULL);

        STARTUPINFOEXA startup;
        ZeroMemory(&startup, sizeof(startup));
        startup.StartupInfo.cb = sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = childIn;
        startup.StartupInfo.hStdOutput = childOut;
        startup.StartupInfo.hStdError = (nul != INVALID_HANDLE_VALUE) ? nul : childOut;

        HANDLE inherited[3] = {childIn, childOut, nul};
        DWORD inheritedCount = (nul != INVALID_HANDLE_VALUE) ? 3 : 2;
        SIZE_T attributeSize = 0;
        InitializeProcThreadAttributeList(NULL, 1, 0, &attributeSize);
        std::vector<char> attributeBuffer(attributeSize);
        LPPROC_THREAD_ATTRIBUTE_LIST attributes =
            reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributeBuffer.data());
        bool haveAttributes = InitializeProcThreadAttributeList(attributes, 1, 0, &attributeSize) &&
                              UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                                        inherited, inheritedCount * sizeof(HANDLE), NULL, NULL);
        DWORD flags = CREATE_NO_WINDOW | CREATE_SUSPENDED;
        if (haveAttributes) {
            startup.lpAttributeList = attributes;
            flags |= EXTENDED_STARTUPINFO_PRESENT;
        }

        std::string commandLine = "\"" + exePath + "\"";
        std::vector<char> commandBuffer(commandLine.begin(), commandLine.end());
        commandBuffer.push_back('\0');
        size_t slash = exePath.find_last_of("\\/");
        std::string folder = (slash == std::string::npos) ? std::string() : exePath.substr(0, slash);

        PROCESS_INFORMATION info;
        ZeroMemory(&info, sizeof(info));
        // Inheritable for the shortest possible time. A CreateProcess/system() with bInheritHandles=TRUE
        // running in ANOTHER thread inside this window would also inherit these handles (and then
        // Stockfish's death would only be noticed when that other child exits), so start Stockfish
        // while no other thread launches processes, or serialize all launches with one mutex.
        SetHandleInformation(childIn, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(childOut, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        if (nul != INVALID_HANDLE_VALUE) SetHandleInformation(nul, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        BOOL created = CreateProcessA(exePath.c_str(), commandBuffer.data(), NULL, NULL, TRUE, flags, NULL,
                                      folder.empty() ? NULL : folder.c_str(), &startup.StartupInfo, &info);
        DWORD createError = GetLastError();
        if (haveAttributes) DeleteProcThreadAttributeList(attributes);
        CloseHandle(childIn); // the child has its own copies now
        CloseHandle(childOut);
        if (nul != INVALID_HANDLE_VALUE) CloseHandle(nul);
        if (!created) {
            CloseHandle(toChild);
            CloseHandle(fromChild);
            throw Died("CreateProcess failed for " + exePath + " (error " + std::to_string(createError) + ")");
        }

        // A job with KILL_ON_JOB_CLOSE: if Engine UCI dies, Windows kills Stockfish too.
        if (!hJob) {
            hJob = CreateJobObjectA(NULL, NULL);
            if (hJob) {
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
                ZeroMemory(&limits, sizeof(limits));
                limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                SetInformationJobObject(hJob, JobObjectExtendedLimitInformation, &limits, sizeof(limits));
            }
        }
        if (hJob) AssignProcessToJobObject(hJob, info.hProcess); // best effort
        ResumeThread(info.hThread);
        CloseHandle(info.hThread);

        hProcess = info.hProcess;
        pid = info.dwProcessId;
        hToChild = toChild;
        hFromChild = fromChild;
        pending.clear();
        pendingOffset = 0;

        {
            Watchdog watchdog(*this, queryTimeoutMs);
            writeAll("uci\n");
            readUntilLine("uciok");
            writeAll("isready\n");
            readUntilLine("readyok");
        }
        lastStartupMs = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    }

    void stopProcess(bool graceful) {
        if (hToChild) {
            if (graceful) {
                DWORD written = 0;
                WriteFile(hToChild, "quit\n", 5, &written, NULL);
            }
            CloseHandle(hToChild); // end-of-file on Stockfish's stdin = "quit" as well
            hToChild = NULL;
        }
        HANDLE process = hProcess.load();
        if (process) {
            if (WaitForSingleObject(process, graceful ? 2000 : 50) != WAIT_OBJECT_0) {
                TerminateProcess(process, 1);
                WaitForSingleObject(process, 2000);
            }
            hProcess = NULL;
            CloseHandle(process);
        }
        if (hFromChild) {
            CloseHandle(hFromChild);
            hFromChild = NULL;
        }
        pending.clear();
        pendingOffset = 0;
        pid = 0;
    }

    void writeAll(const std::string& text) {
        const char* data = text.data();
        size_t left = text.size();
        while (left > 0) {
            DWORD written = 0;
            if (!WriteFile(hToChild, data, (DWORD)left, &written, NULL))
                throw Died("WriteFile failed (error " + std::to_string(GetLastError()) + ")");
            data += written;
            left -= written;
        }
    }

    // One whole line, without "\n" and without the '\r' before it.
    std::string readLine() {
        for (;;) {
            size_t newline = pending.find('\n', pendingOffset);
            if (newline != std::string::npos) {
                size_t end = newline;
                if (end > pendingOffset && pending[end - 1] == '\r') end--;
                std::string line = pending.substr(pendingOffset, end - pendingOffset);
                pendingOffset = newline + 1;
                if (pendingOffset == pending.size()) {
                    pending.clear();
                    pendingOffset = 0;
                }
                return line;
            }
            if (pendingOffset > 0) {
                pending.erase(0, pendingOffset);
                pendingOffset = 0;
            }
            char buffer[8192];
            DWORD got = 0;
            if (!ReadFile(hFromChild, buffer, (DWORD)sizeof(buffer), &got, NULL))
                throw Died("ReadFile failed (error " + std::to_string(GetLastError()) + ", Stockfish gone?)");
            pending.append(buffer, got);
        }
    }

    void readUntilLine(const char* wanted) {
        while (readLine() != wanted) {}
    }

    // Drain leftovers of earlier answers. Valid because no search is running between queries.
    void sync() {
        Watchdog watchdog(*this, queryTimeoutMs);
        writeAll("isready\n");
        readUntilLine("readyok");
    }

    static std::string positionCommand(const std::string& movesString) {
        if (movesString.empty()) return "position startpos\n";
        std::string moves = movesString;
        for (char& c : moves)
            if (c == '\r' || c == '\n') c = ' '; // never let a move string inject a command
        return "position startpos moves " + moves + "\n";
    }

    static bool isPerftMoveLine(const std::string& line, std::string& move) {
        size_t colon = line.find(": ");
        if (colon != 4 && colon != 5) return false;
        const std::string m = line.substr(0, colon);
        bool ok = m[0] >= 'a' && m[0] <= 'h' && m[1] >= '1' && m[1] <= '8' && m[2] >= 'a' && m[2] <= 'h' &&
                  m[3] >= '1' && m[3] <= '8' &&
                  (m.size() == 4 || m[4] == 'q' || m[4] == 'r' || m[4] == 'b' || m[4] == 'n');
        if (ok) move = m;
        return ok;
    }

    std::vector<std::string> perftQuery(const std::string& movesString) {
        sync();
        Watchdog watchdog(*this, queryTimeoutMs);
        writeAll(positionCommand(movesString) + "go perft 1\n");
        std::vector<std::string> moves;
        for (;;) {
            std::string line = readLine();
            if (line.compare(0, 14, "Nodes searched") == 0) break; // one blank line follows; sync() eats it
            std::string move;
            if (isPerftMoveLine(line, move)) moves.push_back(move);
        }
        return moves;
    }

    std::string depthQuery(const std::string& movesString, int depth) {
        {
            // ucinewgame = Search::clear(): empty TT + histories, exactly like a fresh process.
            Watchdog watchdog(*this, queryTimeoutMs);
            writeAll("ucinewgame\nisready\n");
            readUntilLine("readyok");
        }
        Watchdog watchdog(*this, searchTimeoutMs);
        std::string commands = positionCommand(movesString) + "go depth " + std::to_string(depth) + "\n"; // ONCE
        if (legacyBestMoveCompat) commands += positionCommand(movesString);
        writeAll(commands);
        for (;;) {
            std::string line = readLine();
            if (line.compare(0, 9, "bestmove ") == 0) {
                size_t start = line.find_first_not_of(' ', 9);
                if (start == std::string::npos) return std::string();
                size_t end = line.find(' ', start);
                return line.substr(start, end == std::string::npos ? std::string::npos : end - start);
            }
        }
    }

    std::string finalEvaluationLine(const std::string& movesString) {
        sync();
        Watchdog watchdog(*this, queryTimeoutMs);
        writeAll(positionCommand(movesString) + "eval\n");
        for (;;) {
            std::string line = readLine();
            if (line.compare(0, 16, "Final evaluation") == 0) return line; // blank line may follow; sync() eats it
        }
    }

    long double evaluationQuery(const std::string& movesString) {
        std::string line = finalEvaluationLine(movesString);
        if (line == kInCheckLine) {
            int numberOfMovesSoFar = 1 + (int)std::count(movesString.begin(), movesString.end(), ' ');
            return (numberOfMovesSoFar & 1) ? 100000.0L : -100000.0L; // the old handler's parity rule
        }
        size_t sign = line.find_first_of("+-", 16);
        if (sign == std::string::npos) { // the old handler's fallback (dead with Stockfish 16)
            std::string reply = depthQuery(movesString, 20);
            return evaluationQuery(movesString + " " + reply);
        }
        size_t end = line.find(' ', sign + 1);
        std::string number = line.substr(sign + 1, end == std::string::npos ? std::string::npos : end - sign - 1);
        long double value = (long double)std::stod(number);
        return line[sign] == '-' ? -value : value;
    }
};

// The ONE Stockfish of this process: created on first use (thread-safe), told "quit" at exit.
inline StockfishProcess& SharedStockfish() {
    static StockfishProcess instance;
    return instance;
}

// Copyable facade with the old StockfishHandler's public functions, so ChessState can keep
// holding it by value and copying it into threads: every copy talks to SharedStockfish().
// Drop-in: replace  #include "Stockfish Handler.hpp"  by  #include "StockfishProcess.hpp"
// and add  using StockfishHandler = PersistentStockfishHandler;  (plus bits/stdc++ and
// using namespace std, which Engine UCI.cpp got from the old header).
class PersistentStockfishHandler {
  public:
    long double getNNUEPositionEvaluation(const std::string& m) { return SharedStockfish().getNNUEPositionEvaluation(m); }
    std::vector<std::string> getAllPossibleMoves(const std::string& m) { return SharedStockfish().getAllPossibleMoves(m); }
    std::string getBestMoveByDepth(const std::string& m, const int& depth) { return SharedStockfish().getBestMoveByDepth(m, depth); }
    std::string getBestMoveByNNUE(const std::string& m) { return SharedStockfish().getBestMoveByNNUE(m); }
    std::vector<std::string> getSortedMovesByNNUE(const std::string& m) { return SharedStockfish().getSortedMovesByNNUE(m); }
    bool isCheckmatePosition(const std::string& m) { return SharedStockfish().isCheckmatePosition(m); }
    bool isTiePosition(const std::string& m) { return SharedStockfish().isTiePosition(m); }
    bool isStalematePosition(const std::string& m) { return SharedStockfish().isStalematePosition(m); }
};

#endif // STOCKFISH_PROCESS_HPP_INCLUDED
