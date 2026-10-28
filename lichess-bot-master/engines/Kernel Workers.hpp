#ifndef KERNEL_WORKERS_H_INCLUDED
#define KERNEL_WORKERS_H_INCLUDED

#include <bits/stdc++.h>
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>    // CreateProcess, CreatePipe, Job Objects

#include "json.hpp"

using namespace std;

// ############################################################ \\
//                            Notes                             \\
// Before, every Kernel move started 28 brand-new Kernel.exe    \\
// processes through cmd.exe, and they talked to Engine UCI     \\
// through JSON files in the input folder. Now the Kernel       \\
// workers are started once per game and kept alive: for every  \\
// move, Engine UCI writes one line (the request) into each     \\
// worker's stdin and reads one line (the answer) from its      \\
// stdout. No files, no cmd.exe, no new process per move.       \\
// ############################################################ \\

// One Kernel.exe worker with its two pipes.
class KernelWorkerProcess {
  public:
    KernelWorkerProcess() {
    }

    ~KernelWorkerProcess() {
        this->kill(2000);
        this->closeAllHandles();
    }

    KernelWorkerProcess(const KernelWorkerProcess&) = delete;
    KernelWorkerProcess& operator=(const KernelWorkerProcess&) = delete;

    // Every Kernel worker start goes through this mutex, as a second protection next to the handle list in
    // start(): while a worker's own pipe ends are inheritable (a few microseconds), no other worker can be
    // started, so no other worker can ever hold them (and then the death of that worker would go unnoticed).
    static mutex& processStartMutex() {
        static mutex theProcessStartMutex;
        return theProcessStartMutex;
    }

    bool start(const string& kernelExecutableFilePath, HANDLE jobHandle, const string& errorLogFilePath,
               string& error) {

        // Two pipes, and all four ends are NON-inheritable at first.
        HANDLE workerStdinReadEnd = NULL, workerStdoutWriteEnd = NULL;
        if (!CreatePipe(&workerStdinReadEnd, &this->workerInputPipe, NULL, 1 << 16)) {
            error = "CreatePipe(stdin) failed, error " + to_string(GetLastError());
            return false;
        }
        if (!CreatePipe(&this->workerOutputPipe, &workerStdoutWriteEnd, NULL, 1 << 16)) {
            error = "CreatePipe(stdout) failed, error " + to_string(GetLastError());
            CloseHandle(workerStdinReadEnd);
            this->closeAllHandles();
            return false;
        }
        // The worker's stderr goes to one log file shared by all the workers (normally it stays empty).
        HANDLE errorLogFile = CreateFileA(errorLogFilePath.empty() ? "NUL" : errorLogFilePath.c_str(),
                                          FILE_APPEND_DATA | SYNCHRONIZE,
                                          FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                                          OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (errorLogFile == INVALID_HANDLE_VALUE) {
            errorLogFile = CreateFileA("NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                                       OPEN_EXISTING, 0, NULL);
        }

        lock_guard<mutex> lock(processStartMutex());

        // Only now the worker's three ends become inheritable, and PROC_THREAD_ATTRIBUTE_HANDLE_LIST gives the
        // worker exactly these three handles and nothing else: not my own stdin/stdout (python-chess's pipes),
        // not another worker's pipes, not Stockfish's.
        SetHandleInformation(workerStdinReadEnd, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(workerStdoutWriteEnd, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(errorLogFile, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        HANDLE inheritedHandles[3] = {workerStdinReadEnd, workerStdoutWriteEnd, errorLogFile};
        SIZE_T attributeListSize = 0;
        InitializeProcThreadAttributeList(NULL, 1, 0, &attributeListSize);
        vector<char> attributeListBuffer(attributeListSize);
        LPPROC_THREAD_ATTRIBUTE_LIST attributeList =
            reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributeListBuffer.data());
        bool hasAttributeList = InitializeProcThreadAttributeList(attributeList, 1, 0, &attributeListSize) &&
                                UpdateProcThreadAttribute(attributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                                          inheritedHandles, sizeof(inheritedHandles), NULL, NULL);

        STARTUPINFOEXA startupInformation;
        ZeroMemory(&startupInformation, sizeof(startupInformation));
        startupInformation.StartupInfo.cb = sizeof(startupInformation);
        startupInformation.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startupInformation.StartupInfo.hStdInput = workerStdinReadEnd;
        startupInformation.StartupInfo.hStdOutput = workerStdoutWriteEnd;
        startupInformation.StartupInfo.hStdError = errorLogFile;
        // DETACHED_PROCESS: no console window (and no conhost.exe) per worker. CREATE_SUSPENDED: the worker
        // doesn't run a single instruction before it's inside the Job Object.
        DWORD creationFlags = DETACHED_PROCESS | CREATE_SUSPENDED;
        if (hasAttributeList) {
            startupInformation.lpAttributeList = attributeList;
            creationFlags |= EXTENDED_STARTUPINFO_PRESENT;
        }

        // The full path, quoted, in a writable buffer (CreateProcess may modify it), and no cmd.exe at all.
        string commandLine = "\"" + kernelExecutableFilePath + "\"";
        vector<char> commandLineBuffer(commandLine.begin(), commandLine.end());
        commandLineBuffer.push_back('\0');

        PROCESS_INFORMATION processInformation;
        ZeroMemory(&processInformation, sizeof(processInformation));
        BOOL isCreated = CreateProcessA(kernelExecutableFilePath.c_str(), commandLineBuffer.data(), NULL, NULL,
                                        TRUE, creationFlags, NULL, NULL, &startupInformation.StartupInfo,
                                        &processInformation);
        DWORD creationError = GetLastError();
        if (hasAttributeList) {
            DeleteProcThreadAttributeList(attributeList);
        }
        // The worker has its own copies now. Closing mine right away is what makes its death visible: then
        // the worker holds the only write end of its stdout, so my ReadFile fails as soon as it dies.
        CloseHandle(workerStdinReadEnd);
        CloseHandle(workerStdoutWriteEnd);
        CloseHandle(errorLogFile);
        if (!isCreated) {
            error = "CreateProcess failed for " + kernelExecutableFilePath + " (error " + to_string(creationError) +
                    (creationError == 4551 ? ": Smart App Control blocked this Kernel.exe, rebuild it" : "") + ")";
            this->closeAllHandles();
            return false;
        }

        // Inside the Job Object, Windows kills the worker when Engine UCI ends, even with taskkill /F.
        if (jobHandle && !AssignProcessToJobObject(jobHandle, processInformation.hProcess)) {
            error = "AssignProcessToJobObject failed (error " + to_string(GetLastError()) +
                    "), this worker runs without the job";
        }
        ResumeThread(processInformation.hThread);
        CloseHandle(processInformation.hThread);

        this->processHandle = processInformation.hProcess;
        this->processId = processInformation.dwProcessId;
        this->unreadOutput.clear();
        this->unreadOutputStartIndex = 0;
        return true;

    }

    // One request line. It fails when the worker is gone (ERROR_NO_DATA / ERROR_BROKEN_PIPE).
    bool writeLine(const string& line) {
        if (!this->workerInputPipe) {
            return false;
        }
        string bytes = line + "\n";
        const char* nextByte = bytes.data();
        size_t numberOfBytesLeft = bytes.size();
        while (numberOfBytesLeft > 0) {
            DWORD numberOfWrittenBytes = 0;
            if (!WriteFile(this->workerInputPipe, nextByte, (DWORD)numberOfBytesLeft, &numberOfWrittenBytes, NULL)) {
                return false;
            }
            nextByte += numberOfWrittenBytes;
            numberOfBytesLeft -= numberOfWrittenBytes;
        }
        return true;
    }

    // One whole answer line, without its "\n" (and without a '\r' before it). It blocks until the line is
    // there, and returns false when the worker is gone (ReadFile fails with ERROR_BROKEN_PIPE).
    bool readLine(string& line) {
        while (true) {
            size_t newLineIndex = this->unreadOutput.find('\n', this->unreadOutputStartIndex);
            if (newLineIndex != string::npos) {
                size_t lineEndIndex = newLineIndex;
                if (lineEndIndex > this->unreadOutputStartIndex && this->unreadOutput[lineEndIndex - 1] == '\r') {
                    lineEndIndex--;
                }
                line = this->unreadOutput.substr(this->unreadOutputStartIndex,
                                                 lineEndIndex - this->unreadOutputStartIndex);
                this->unreadOutputStartIndex = newLineIndex + 1;
                if (this->unreadOutputStartIndex == this->unreadOutput.size()) {
                    this->unreadOutput.clear();
                    this->unreadOutputStartIndex = 0;
                }
                return true;
            }
            if (this->unreadOutputStartIndex > 0) {
                this->unreadOutput.erase(0, this->unreadOutputStartIndex);
                this->unreadOutputStartIndex = 0;
            }
            if (!this->workerOutputPipe) {
                return false;
            }
            char buffer[1 << 16];
            DWORD numberOfReadBytes = 0;
            if (!ReadFile(this->workerOutputPipe, buffer, (DWORD)sizeof(buffer), &numberOfReadBytes, NULL)) {
                return false;
            }
            this->unreadOutput.append(buffer, numberOfReadBytes);
        }
    }

    // Closing the worker's stdin is a "quit" for it: its getline() sees the end of the input.
    void closeInput() {
        if (this->workerInputPipe) {
            CloseHandle(this->workerInputPipe);
            this->workerInputPipe = NULL;
        }
    }

    // TerminateProcess. It also unblocks the reader thread that waits in readLine(): the worker held the only
    // write end of its stdout, so the read fails at once.
    void kill(DWORD waitInMilliseconds = 0) {
        if (this->processHandle && WaitForSingleObject(this->processHandle, 0) == WAIT_TIMEOUT) {
            TerminateProcess(this->processHandle, 1);
            if (waitInMilliseconds) {
                WaitForSingleObject(this->processHandle, waitInMilliseconds);
            }
        }
    }

    bool waitForExit(DWORD waitInMilliseconds) {
        return !this->processHandle || WaitForSingleObject(this->processHandle, waitInMilliseconds) == WAIT_OBJECT_0;
    }

    // Only when no thread is inside readLine() or writeLine() any more.
    void closeAllHandles() {
        if (this->workerInputPipe) {
            CloseHandle(this->workerInputPipe);
            this->workerInputPipe = NULL;
        }
        if (this->workerOutputPipe) {
            CloseHandle(this->workerOutputPipe);
            this->workerOutputPipe = NULL;
        }
        if (this->processHandle) {
            CloseHandle(this->processHandle);
            this->processHandle = NULL;
        }
    }

    DWORD getProcessId() const {
        return this->processId;
    }

  private:
    HANDLE processHandle = NULL;
    HANDLE workerInputPipe = NULL;          // I write into the worker's stdin through this one
    HANDLE workerOutputPipe = NULL;         // and read its stdout from this one
    DWORD processId = 0;
    string unreadOutput;                    // read from the pipe, not returned as lines yet
    size_t unreadOutputStartIndex = 0;
};

// ############################################################ \\

// The pool of Kernel workers. A pipe has no read timeout, so every worker gets ONE reader thread that
// does nothing but read its answers and put them in its inbox. A move then waits for all the answers
// with a deadline, and a worker that is still silent at the deadline is killed (that also ends its
// reader's blocked read) and started again after "bestmove" is sent.
class KernelWorkerPool {
  public:
    struct WorkerAnswer {
        string status = "dead";             // answered / timeout / dead
        nlohmann::json message;             // the worker's answer line, parsed
        double milliseconds = 0;            // request written -> answer read
    };

    ~KernelWorkerPool() {
        this->shutdown();
    }

    // Engine UCI calls this once at startup: it starts nothing yet.
    void configure(const string& kernelExecutableFilePath, const string& errorLogFilePath, const int& numberOfWorkers) {
        this->kernelExecutableFilePath = kernelExecutableFilePath;
        this->errorLogFilePath = errorLogFilePath;
        this->numberOfWorkers = numberOfWorkers;
    }

    // Starts all the workers in a background thread and returns at once (Engine UCI calls it on
    // "ucinewgame", so the workers are ready long before the first Kernel move, at ply 5 or 6).
    void startInTheBackground() {
        lock_guard<mutex> lock(this->startMutex);
        if (this->isStartRequested || this->numberOfWorkers <= 0) {
            return;
        }
        this->isStartRequested = true;
        this->startingThread = thread([this]() { this->startAllWorkers(); });
    }

    // Waits until the start has finished (and starts it now, if nobody did). Returns false with the reason
    // when not every worker is ready; the workers that are ready are still used.
    bool waitUntilStarted(string& error) {
        this->startInTheBackground();
        {
            lock_guard<mutex> lock(this->startMutex);
            if (this->startingThread.joinable()) {
                this->startingThread.join();
            }
        }
        lock_guard<mutex> lock(this->poolMutex);
        error = this->startError;
        return error.empty();
    }

    // The slots (0..N-1) of the workers that can take a request right now: started, ready, and still alive. A
    // worker that died while it was waiting (its reader already saw the end of its output) is left out, so its
    // share of the root moves goes to the others instead of never being searched.
    vector<int> getUsableWorkerSlots() {
        lock_guard<mutex> lock(this->poolMutex);
        vector<int> usableWorkerSlots;
        for (int slot = 0; slot < (int)this->workers.size(); slot++) {
            const Worker& worker = *this->workers[slot];
            if (worker.process && worker.isReady && !worker.needsRespawn && !worker.isReaderFinished) {
                usableWorkerSlots.push_back(slot);
            }
        }
        return usableWorkerSlots;
    }

    long long getNewRequestId() {
        return ++this->lastRequestId;
    }

    // requestLines[i] goes to the worker in workerSlots[i], and carries the id requestIds[i]. It returns when
    // every asked worker has answered, has died, or the deadline has passed (answers[i] is workerSlots[i]'s).
    vector<WorkerAnswer> askAllWorkers(const vector<int>& workerSlots, const vector<string>& requestLines,
                                       const vector<long long>& requestIds, const int& timeoutInMilliseconds) {

        int numberOfAskedWorkers = (int)requestLines.size();
        vector<WorkerAnswer> answers(numberOfAskedWorkers);
        vector<bool> isWaitingForAnswer(numberOfAskedWorkers, false);
        vector<chrono::steady_clock::time_point> requestTimes(numberOfAskedWorkers);
        chrono::steady_clock::time_point deadline = chrono::steady_clock::now() +
                                                    chrono::milliseconds(timeoutInMilliseconds);
        int numberOfMissingAnswers = 0;

        for (int i = 0; i < numberOfAskedWorkers; i++) {
            int slot = workerSlots[i];
            Worker* worker = NULL;
            {
                lock_guard<mutex> lock(this->poolMutex);
                if (slot >= 0 && slot < (int)this->workers.size() && this->workers[slot]->process &&
                    this->workers[slot]->isReady && !this->workers[slot]->needsRespawn) {
                    worker = this->workers[slot].get();
                }
            }
            if (!worker) {
                answers[i].status = "dead";
                continue;
            }
            requestTimes[i] = chrono::steady_clock::now();
            if (!worker->process->writeLine(requestLines[i])) {
                answers[i].status = "dead";
                lock_guard<mutex> lock(this->poolMutex);
                worker->needsRespawn = true;
                continue;
            }
            isWaitingForAnswer[i] = true;
            numberOfMissingAnswers++;
        }

        unique_lock<mutex> lock(this->poolMutex);
        while (true) {
            for (int i = 0; i < numberOfAskedWorkers && numberOfMissingAnswers > 0; i++) {
                if (!isWaitingForAnswer[i]) {
                    continue;
                }
                Worker& worker = *this->workers[workerSlots[i]];
                while (!worker.inbox.empty()) {
                    pair<nlohmann::json, chrono::steady_clock::time_point> receivedMessage = worker.inbox.front();
                    worker.inbox.pop_front();
                    const nlohmann::json& message = receivedMessage.first;
                    bool isTheAnswer = message.is_object() && message.contains("id") &&
                                       message["id"].is_number_integer() &&
                                       message["id"].get<long long>() == requestIds[i] && message.contains("type") &&
                                       (message["type"] == "result" || message["type"] == "error");
                    if (isTheAnswer) {
                        answers[i].status = "answered";
                        answers[i].message = message;
                        answers[i].milliseconds = chrono::duration<double, milli>(receivedMessage.second -
                                                                                  requestTimes[i]).count();
                        isWaitingForAnswer[i] = false;
                        numberOfMissingAnswers--;
                        break;
                    }
                    // Otherwise it's a late answer to an older request, or a stray line: never this move's answer.
                }
                if (isWaitingForAnswer[i] && worker.isReaderFinished) {
                    // The end of its output: the worker exited or crashed.
                    answers[i].status = "dead";
                    worker.needsRespawn = true;
                    isWaitingForAnswer[i] = false;
                    numberOfMissingAnswers--;
                }
            }
            if (numberOfMissingAnswers == 0 || chrono::steady_clock::now() >= deadline) {
                break;
            }
            this->poolConditionVariable.wait_until(lock, deadline);
        }

        vector<Worker*> lateWorkers;
        for (int i = 0; i < numberOfAskedWorkers; i++) {
            if (isWaitingForAnswer[i]) {
                answers[i].status = "timeout";
                this->workers[workerSlots[i]]->needsRespawn = true;
                lateWorkers.push_back(this->workers[workerSlots[i]].get());
            }
        }
        lock.unlock();
        // Killed now, so they stop using the CPU, but without waiting here: the move is waiting.
        for (Worker* lateWorker : lateWorkers) {
            lateWorker->process->kill(0);
        }
        return answers;

    }

    // Engine UCI calls this after "bestmove" is sent: it replaces every worker that timed out or died.
    // Returns how many were replaced, and the reason when some of them couldn't start.
    int respawnTheDeadWorkers(string& error) {
        // While the background start is still running (the first moves are Stockfish's, so they come back
        // quickly), the starting thread owns the workers, and a worker it hasn't started yet isn't dead.
        if (!this->isStartFinished) {
            return 0;
        }
        vector<Worker*> deadWorkers;
        {
            lock_guard<mutex> lock(this->poolMutex);
            for (unique_ptr<Worker>& worker : this->workers) {
                // needsRespawn: it timed out or died during a move. isReaderFinished: it died while waiting.
                if (worker->needsRespawn || !worker->process || worker->isReaderFinished) {
                    deadWorkers.push_back(worker.get());
                }
            }
        }
        if (deadWorkers.empty()) {
            return 0;
        }
        for (Worker* deadWorker : deadWorkers) {
            this->retireWorker(*deadWorker);
            this->startWorker(*deadWorker, error);
        }
        this->waitUntilAllReady(chrono::steady_clock::now() + chrono::milliseconds(3000), error);
        return (int)deadWorkers.size();
    }

    // "quit" + the end of their input, half a second to exit by themselves, then kill whatever is left.
    void shutdown() {
        {
            lock_guard<mutex> lock(this->startMutex);
            this->isShutdownRequested = true;
            if (this->startingThread.joinable()) {
                this->startingThread.join();
            }
        }
        for (unique_ptr<Worker>& worker : this->workers) {
            if (worker->process) {
                worker->process->writeLine("{\"type\":\"quit\"}");
                worker->process->closeInput();
            }
        }
        chrono::steady_clock::time_point graceEnd = chrono::steady_clock::now() + chrono::milliseconds(500);
        for (unique_ptr<Worker>& worker : this->workers) {
            if (worker->process) {
                long long millisecondsLeft = chrono::duration_cast<chrono::milliseconds>(
                                                 graceEnd - chrono::steady_clock::now()).count();
                worker->process->waitForExit(millisecondsLeft > 0 ? (DWORD)millisecondsLeft : 0);
            }
        }
        for (unique_ptr<Worker>& worker : this->workers) {
            this->retireWorker(*worker);
        }
        {
            lock_guard<mutex> lock(this->poolMutex);
            this->workers.clear();
        }
        if (this->jobHandle) {
            // Closing the job kills anything that is somehow still in it.
            CloseHandle(this->jobHandle);
            this->jobHandle = NULL;
        }
    }

  private:
    struct Worker {
        int number = 0;                                     // 1..N
        unique_ptr<KernelWorkerProcess> process;
        thread readerThread;
        // Everything below is guarded by poolMutex.
        HANDLE readerThreadHandle = NULL;                   // a real Win32 handle, for CancelSynchronousIo
        deque<pair<nlohmann::json, chrono::steady_clock::time_point>> inbox;
        bool isReaderFinished = false;
        bool isReady = false;
        bool needsRespawn = false;
    };

    string kernelExecutableFilePath;
    string errorLogFilePath;
    int numberOfWorkers = 0;
    HANDLE jobHandle = NULL;
    vector<unique_ptr<Worker>> workers;
    mutex poolMutex;
    condition_variable poolConditionVariable;
    atomic<long long> lastRequestId{0};
    mutex startMutex;
    thread startingThread;
    bool isStartRequested = false;
    atomic<bool> isStartFinished{false};                    // set by the starting thread as its very last step
    atomic<bool> isShutdownRequested{false};
    string startError;                                      // guarded by poolMutex

    void startAllWorkers() {
        // A Job Object with "kill on close" (and "die on a crash", so a crashing worker exits at once instead of
        // waiting for Windows Error Reporting): when Engine UCI ends, Windows kills every worker in it.
        this->jobHandle = CreateJobObjectA(NULL, NULL);
        if (this->jobHandle) {
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION jobLimits;
            ZeroMemory(&jobLimits, sizeof(jobLimits));
            jobLimits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
                                                         JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION;
            SetInformationJobObject(this->jobHandle, JobObjectExtendedLimitInformation, &jobLimits, sizeof(jobLimits));
        }
        {
            lock_guard<mutex> lock(this->poolMutex);
            for (int workerNumber = 1; workerNumber <= this->numberOfWorkers; workerNumber++) {
                this->workers.push_back(unique_ptr<Worker>(new Worker()));
                this->workers.back()->number = workerNumber;
            }
        }
        string error;
        for (unique_ptr<Worker>& worker : this->workers) {
            if (this->isShutdownRequested) {
                break;
            }
            this->startWorker(*worker, error);
        }
        this->waitUntilAllReady(chrono::steady_clock::now() + chrono::milliseconds(10000), error);
        {
            lock_guard<mutex> lock(this->poolMutex);
            this->startError = error;
        }
        this->isStartFinished = true;
    }

    void startWorker(Worker& worker, string& error) {
        unique_ptr<KernelWorkerProcess> process(new KernelWorkerProcess());
        string startError;
        bool isStarted = process->start(this->kernelExecutableFilePath, this->jobHandle, this->errorLogFilePath,
                                        startError);
        if (!startError.empty() && error.empty()) {
            error = "Kernel worker " + to_string(worker.number) + ": " + startError;
        }
        if (!isStarted) {
            lock_guard<mutex> lock(this->poolMutex);
            worker.needsRespawn = true;
            return;
        }
        {
            lock_guard<mutex> lock(this->poolMutex);
            worker.process = move(process);
            worker.inbox.clear();
            worker.isReaderFinished = false;
            worker.isReady = false;
            worker.needsRespawn = false;
        }
        worker.readerThread = thread([this, &worker]() { this->readAnswersOf(worker); });
        worker.process->writeLine("{\"type\":\"hello\"}");
    }

    void readAnswersOf(Worker& worker) {
        HANDLE myThreadHandle = NULL;
        DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &myThreadHandle, 0, FALSE,
                        DUPLICATE_SAME_ACCESS);
        {
            lock_guard<mutex> lock(this->poolMutex);
            worker.readerThreadHandle = myThreadHandle;
        }
        string line;
        while (worker.process->readLine(line)) {
            chrono::steady_clock::time_point receivedTime = chrono::steady_clock::now();
            nlohmann::json message = nlohmann::json::parse(line, nullptr, false);
            if (message.is_discarded() || !message.is_object()) {
                message = nlohmann::json{{"type", "not_json"}, {"line", line.substr(0, 200)}};
            }
            {
                lock_guard<mutex> lock(this->poolMutex);
                worker.inbox.push_back({message, receivedTime});
            }
            this->poolConditionVariable.notify_all();
        }
        {
            lock_guard<mutex> lock(this->poolMutex);
            worker.isReaderFinished = true;
        }
        this->poolConditionVariable.notify_all();
    }

    // Every started worker answers "hello" with {"type":"ready"}.
    void waitUntilAllReady(chrono::steady_clock::time_point deadline, string& error) {
        unique_lock<mutex> lock(this->poolMutex);
        while (true) {
            int numberOfNotReadyWorkers = 0;
            for (unique_ptr<Worker>& worker : this->workers) {
                if (worker->isReady || worker->needsRespawn || !worker->process) {
                    continue;
                }
                while (!worker->inbox.empty()) {
                    nlohmann::json message = worker->inbox.front().first;
                    worker->inbox.pop_front();
                    if (message.value("type", "") == "ready") {
                        worker->isReady = true;
                        break;
                    }
                }
                if (!worker->isReady && worker->isReaderFinished) {
                    worker->needsRespawn = true;
                    if (error.empty()) {
                        error = "Kernel worker " + to_string(worker->number) + " exited before it was ready";
                    }
                }
                if (!worker->isReady && !worker->needsRespawn) {
                    numberOfNotReadyWorkers++;
                }
            }
            if (numberOfNotReadyWorkers == 0) {
                return;
            }
            if (chrono::steady_clock::now() >= deadline) {
                if (error.empty()) {
                    error = to_string(numberOfNotReadyWorkers) + " Kernel worker(s) not ready before the deadline";
                }
                for (unique_ptr<Worker>& worker : this->workers) {
                    if (!worker->isReady && worker->process) {
                        worker->needsRespawn = true;
                    }
                }
                return;
            }
            this->poolConditionVariable.wait_until(lock, deadline);
        }
    }

    // Kills the worker, waits for its reader thread to see the end of the output, and frees everything.
    void retireWorker(Worker& worker) {
        if (worker.process) {
            worker.process->kill(5000);
        }
        bool isReaderFinished = true;
        if (worker.readerThread.joinable()) {
            unique_lock<mutex> lock(this->poolMutex);
            isReaderFinished = this->poolConditionVariable.wait_for(lock, chrono::milliseconds(2000),
                                                                    [&worker]() { return worker.isReaderFinished; });
            // Only possible if another process still holds a write end of this worker's stdout: then I cancel
            // the blocked read by hand, so the engine can never hang here.
            for (int attempt = 0; !isReaderFinished && attempt < 50; attempt++) {
                HANDLE readerThreadHandle = worker.readerThreadHandle;
                lock.unlock();
                if (readerThreadHandle) {
                    CancelSynchronousIo(readerThreadHandle);
                }
                lock.lock();
                isReaderFinished = this->poolConditionVariable.wait_for(lock, chrono::milliseconds(20),
                                                                        [&worker]() { return worker.isReaderFinished; });
            }
        }
        if (worker.readerThread.joinable()) {
            if (isReaderFinished) {
                worker.readerThread.join();
            }
            else {
                worker.readerThread.detach();
            }
        }
        lock_guard<mutex> lock(this->poolMutex);
        if (worker.readerThreadHandle) {
            CloseHandle(worker.readerThreadHandle);
            worker.readerThreadHandle = NULL;
        }
        if (isReaderFinished) {
            worker.process.reset();
        }
        else {
            // A detached reader may still use it, so it's never freed (it can't happen with the handle lists).
            (void)worker.process.release();
        }
        worker.inbox.clear();
        worker.isReaderFinished = false;
        worker.isReady = false;
    }
};

// ############################################################ \\

// THE Kernel worker pool of Engine UCI. Kernel.exe includes this file too (through "Chess State.hpp"),
// but never uses it, so it never starts a worker.
inline KernelWorkerPool& GetTheKernelWorkerPool() {
    static KernelWorkerPool theKernelWorkerPool;
    return theKernelWorkerPool;
}

#endif // KERNEL_WORKERS_H_INCLUDED
