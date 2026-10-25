// ChildProcess.hpp -- start a child .exe with its stdin/stdout connected to anonymous pipes (Windows only).
//
// Prototype for Mr. Bits, plan 02 Phase 3. Header-only: <windows.h> + the standard library.
// Built and tested with MinGW-w64 UCRT g++ 14.2 (-std=c++17, default _WIN32_WINNT=0x0601) on Windows 11.
//
// Guarantees
//  * The child inherits EXACTLY three handles: its stdin pipe end, its stdout pipe end and its stderr log file
//    (STARTUPINFOEX + PROC_THREAD_ATTRIBUTE_HANDLE_LIST). It never inherits the parent's pipe ends, another
//    worker's pipe ends, or Engine UCI's own stdin/stdout (python-chess hands those to Engine UCI as
//    inheritable handles, so without the list every worker would get a copy).
//  * The parent's two ends are created non-inheritable and stay that way. The child's three ends are made
//    inheritable only inside the spawn mutex, and are closed in the parent right after CreateProcess, so a
//    dead child always means ERROR_BROKEN_PIPE for the parent's ReadFile and ERROR_NO_DATA for its WriteFile.
//  * The child is created SUSPENDED, put in the Job Object, then resumed: it never runs outside the job.
//    A parent that is already inside a job needs nothing special on Windows 8+: our job simply nests under it
//    (verified on Windows 11 with plain, BREAKAWAY_OK and SILENT_BREAKAWAY_OK outer jobs). If the assignment
//    still fails (ERROR_ACCESS_DENIED: a job-hierarchy conflict, or Windows 7), the suspended child is
//    discarded and re-created with CREATE_BREAKAWAY_FROM_JOB (works only if the outer job allows breakaway),
//    and as a last resort without our job (jobState() tells you which; log it -- that worker is no longer
//    killed automatically if Engine UCI dies mid-search).
//  * No cmd.exe: CreateProcessW runs the .exe directly, with a quoted, writable command line.
//
// Threading contract
//  * One thread may be blocked in readLine() while ANOTHER thread calls writeLine() or kill().
//  * Never call readLine() from two threads at once, and never close/destroy a ChildProcess while a thread is
//    blocked in readLine(): kill() first (that unblocks the reader with ERROR_BROKEN_PIPE), join the reader,
//    then destroy.
//  * Any other code in the same process that starts programs with bInheritHandles=TRUE and no handle list
//    (system(), _popen(), _spawn*, std::system) must hold ChildProcess::spawnMutex() while doing so, or it can
//    inherit a child's pipe ends during the few microseconds they are inheritable.
#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

#if !defined(PROC_THREAD_ATTRIBUTE_HANDLE_LIST)
#error "ChildProcess.hpp needs PROC_THREAD_ATTRIBUTE_HANDLE_LIST (_WIN32_WINNT >= 0x0600)"
#endif

namespace mrbits {

// ---------------------------------------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------------------------------------

// UTF-8 first (what the rest of the code base uses); falls back to the ANSI code page, which is what
// GetModuleFileNameA() returns if a path ever contains non-ASCII characters.
inline std::wstring toWide(const std::string& s) {
    if (s.empty()) return std::wstring();
    UINT cp = CP_UTF8;
    DWORD flags = MB_ERR_INVALID_CHARS;
    int n = MultiByteToWideChar(cp, flags, s.data(), (int)s.size(), nullptr, 0);
    if (n <= 0) { cp = CP_ACP; flags = 0; n = MultiByteToWideChar(cp, flags, s.data(), (int)s.size(), nullptr, 0); }
    std::wstring w((size_t)(n > 0 ? n : 0), L'\0');
    if (n > 0) MultiByteToWideChar(cp, flags, s.data(), (int)s.size(), &w[0], n);
    return w;
}

inline std::string win32ErrorText(DWORD err) {
    char* msg = nullptr;
    DWORD n = FormatMessageA(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                             FORMAT_MESSAGE_IGNORE_INSERTS, nullptr, err, 0, (LPSTR)&msg, 0, nullptr);
    std::string s = n ? std::string(msg, n) : std::string("unknown error");
    if (msg) LocalFree(msg);
    while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' ' || s.back() == '.')) s.pop_back();
    return std::to_string(err) + " (" + s + ")";
}

// Appends one argument using the rules of CommandLineToArgvW and of the MSVC/UCRT startup code:
// backslashes are literal unless they precede a double quote. (argv[0] is quoted separately, see below.)
inline void appendQuotedArg(std::wstring& cmd, const std::wstring& arg) {
    if (!arg.empty() && arg.find_first_of(L" \t\n\v\"") == std::wstring::npos) { cmd += arg; return; }
    cmd += L'"';
    for (size_t i = 0;; ++i) {
        size_t backslashes = 0;
        while (i < arg.size() && arg[i] == L'\\') { ++i; ++backslashes; }
        if (i == arg.size()) { cmd.append(backslashes * 2, L'\\'); break; }
        if (arg[i] == L'"') { cmd.append(backslashes * 2 + 1, L'\\'); cmd += L'"'; }
        else                { cmd.append(backslashes, L'\\');         cmd += arg[i]; }
    }
    cmd += L'"';
}

// ---------------------------------------------------------------------------------------------------------
// JobObject: when its last handle closes (Engine UCI returns, crashes, or is killed with taskkill /F),
// Windows terminates every process still in the job. Keep ONE alive for the whole life of Engine UCI.
// ---------------------------------------------------------------------------------------------------------
class JobObject {
public:
    // extraLimitFlags: for tests only (e.g. JOB_OBJECT_LIMIT_BREAKAWAY_OK to build an "outer" job).
    explicit JobObject(bool dieOnUnhandledException = true, DWORD extraLimitFlags = 0) {
        handle_ = CreateJobObjectW(nullptr, nullptr);   // unnamed; lpJobAttributes = NULL => NOT inheritable
        if (!handle_) { error_ = GetLastError(); return; }
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info;
        std::memset(&info, 0, sizeof info);
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | extraLimitFlags;
        // A crashing worker exits at once instead of waiting for Windows Error Reporting (a hidden WerFault
        // dialog would keep the crashed process -- and its pipe -- alive until the move times out).
        if (dieOnUnhandledException) info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION;
        if (!SetInformationJobObject(handle_, JobObjectExtendedLimitInformation, &info, sizeof info)) {
            error_ = GetLastError();
            CloseHandle(handle_);
            handle_ = nullptr;
        }
    }
    ~JobObject() { if (handle_) CloseHandle(handle_); }
    JobObject(const JobObject&) = delete;
    JobObject& operator=(const JobObject&) = delete;

    bool ok() const { return handle_ != nullptr; }
    HANDLE handle() const { return handle_; }
    DWORD error() const { return error_; }

    // Accounting for every process that ever ran in the job.
    bool accounting(double& cpuMs, DWORD& activeProcesses, DWORD& totalProcesses) const {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION a;
        std::memset(&a, 0, sizeof a);
        if (!QueryInformationJobObject(handle_, JobObjectBasicAccountingInformation, &a, sizeof a, nullptr)) return false;
        cpuMs = (double)(a.TotalUserTime.QuadPart + a.TotalKernelTime.QuadPart) / 10000.0;
        activeProcesses = a.ActiveProcesses;
        totalProcesses = a.TotalProcesses;
        return true;
    }

    // TEST HOOK ONLY. The docs say a job with UI limits cannot be nested; on Windows 11 (tested) the nested
    // assignment still succeeded, so the fallback test uses a job-hierarchy conflict instead (pool_test nestedjob).
    bool setUiLimitsForTest() {
        JOBOBJECT_BASIC_UI_RESTRICTIONS ui;
        ui.UIRestrictionsClass = JOB_OBJECT_UILIMIT_HANDLES;
        return SetInformationJobObject(handle_, JobObjectBasicUIRestrictions, &ui, sizeof ui) != 0;
    }

private:
    HANDLE handle_ = nullptr;
    DWORD error_ = 0;
};

// ---------------------------------------------------------------------------------------------------------
// ChildProcess
// ---------------------------------------------------------------------------------------------------------
struct SpawnOptions {
    std::string exePath;                    // FULL path; build it from the executable's own folder (plan 02 Phase 1a)
    std::vector<std::string> args;          // quoted automatically
    std::string stderrPath;                 // "" => NUL. Opened for append and shared, so you can tail it live.
    std::string workingDir;                 // "" => the parent's current directory
    JobObject* job = nullptr;               // nullptr => no job (not recommended)
    // DETACHED_PROCESS: no console at all (no window even if Engine UCI has no console, no conhost.exe per
    // worker, no console Ctrl+C/Ctrl+Break; CREATE_NO_WINDOW would add one conhost.exe per worker). No priority
    // flag => the child starts at NORMAL_PRIORITY_CLASS although Engine UCI is HIGH, exactly like today's
    // system() -> cmd.exe path; Kernel.exe's main() then raises itself to HIGH, today and in worker mode.
    DWORD creationFlags = DETACHED_PROCESS;
    bool restrictInheritance = true;        // PROC_THREAD_ATTRIBUTE_HANDLE_LIST. false ONLY for the leak experiment.
    bool serializeSpawn = true;             // hold spawnMutex(). false is safe ONLY with restrictInheritance=true and
                                            // when nothing else in the process spawns with inheritance meanwhile.
    bool tryBreakawayIfAssignFails = true;
    DWORD pipeBufferSize = 0;               // 0 = the default 4 KB (measured); e.g. 65536 for big answers
};

enum class JobState { NoJobRequested, Assigned, AssignedAfterBreakaway, AssignFailedRunningWithoutJob };

inline const char* jobStateName(JobState s) {
    switch (s) {
        case JobState::NoJobRequested: return "no-job-requested";
        case JobState::Assigned: return "assigned";
        case JobState::AssignedAfterBreakaway: return "assigned-after-breakaway";
        case JobState::AssignFailedRunningWithoutJob: return "assign-failed-running-without-job";
    }
    return "?";
}

class ChildProcess {
public:
    ChildProcess() = default;
    ~ChildProcess() { kill(1, 2000); closeHandles(); }
    ChildProcess(const ChildProcess&) = delete;
    ChildProcess& operator=(const ChildProcess&) = delete;

    // Serializes every handle-inheriting CreateProcess in this process (see the threading contract).
    static std::mutex& spawnMutex() { static std::mutex m; return m; }

    bool start(const SpawnOptions& o) {
        if (process_) return fail("start: already started", ERROR_ALREADY_EXISTS);
        HANDLE childIn = nullptr, childOut = nullptr, childErr = INVALID_HANDLE_VALUE;
        auto closeChildEnds = [&]() {
            if (childIn) CloseHandle(childIn);
            if (childOut) CloseHandle(childOut);
            if (childErr != INVALID_HANDLE_VALUE) CloseHandle(childErr);
            childIn = childOut = nullptr; childErr = INVALID_HANDLE_VALUE;
        };

        // 1. Two anonymous pipes, both ends NON-inheritable (lpPipeAttributes = NULL).
        if (!CreatePipe(&childIn, &stdinWrite_, nullptr, o.pipeBufferSize)) return fail("CreatePipe(stdin)", GetLastError());
        if (!CreatePipe(&stdoutRead_, &childOut, nullptr, o.pipeBufferSize)) {
            DWORD e = GetLastError(); closeChildEnds(); closeHandles(); return fail("CreatePipe(stdout)", e);
        }
        // 2. stderr -> a log file (append-only access: concurrent writers can't overwrite each other).
        std::wstring errPath = o.stderrPath.empty() ? std::wstring(L"NUL") : toWide(o.stderrPath);
        childErr = CreateFileW(errPath.c_str(), FILE_APPEND_DATA | SYNCHRONIZE,
                               FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_ALWAYS,
                               FILE_ATTRIBUTE_NORMAL, nullptr);
        if (childErr == INVALID_HANDLE_VALUE) {
            DWORD e = GetLastError(); closeChildEnds(); closeHandles(); return fail("CreateFileW(stderr log)", e);
        }
        // 3. Command line: quoted program path + quoted arguments, in a WRITABLE buffer (CreateProcessW may
        //    modify it). lpApplicationName is also given, so nothing is searched on PATH and a path with
        //    spaces ("Engine UCI.exe") can never be mis-split into "C:\...\Engine" + "UCI.exe".
        std::wstring app = toWide(o.exePath);
        std::wstring cmd = L"\"" + app + L"\"";
        for (const std::string& a : o.args) { cmd += L' '; appendQuotedArg(cmd, toWide(a)); }
        std::wstring cwd = toWide(o.workingDir);

        std::unique_lock<std::mutex> lock(spawnMutex(), std::defer_lock);
        if (o.serializeSpawn) lock.lock();

        // 4. Only now, inside the mutex, make the child's three ends inheritable.
        SetHandleInformation(childIn, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(childOut, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(childErr, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);

        // 5. The list of handles the child may inherit. The array must stay alive until CreateProcess returns
        //    (UpdateProcThreadAttribute stores the pointer, not a copy), and must not contain duplicates.
        HANDLE inheritList[3] = { childIn, childOut, childErr };
        SIZE_T attrSize = 0;
        InitializeProcThreadAttributeList(nullptr, 1, 0, &attrSize);
        std::vector<unsigned char> attrBuf(attrSize ? attrSize : 64);
        LPPROC_THREAD_ATTRIBUTE_LIST attrs = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attrBuf.data());
        bool attrsReady = false;
        if (o.restrictInheritance) {
            if (!InitializeProcThreadAttributeList(attrs, 1, 0, &attrSize)) {
                DWORD e = GetLastError(); closeChildEnds(); closeHandles(); return fail("InitializeProcThreadAttributeList", e);
            }
            attrsReady = true;
            if (!UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inheritList,
                                           sizeof inheritList, nullptr, nullptr)) {
                DWORD e = GetLastError(); DeleteProcThreadAttributeList(attrs); closeChildEnds(); closeHandles();
                return fail("UpdateProcThreadAttribute(HANDLE_LIST)", e);
            }
        }

        auto create = [&](DWORD extraFlags, PROCESS_INFORMATION& pi) -> bool {
            STARTUPINFOEXW si;
            std::memset(&si, 0, sizeof si);
            si.StartupInfo.cb = o.restrictInheritance ? sizeof(STARTUPINFOEXW) : sizeof(STARTUPINFOW);
            si.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
            si.StartupInfo.hStdInput = childIn;
            si.StartupInfo.hStdOutput = childOut;
            si.StartupInfo.hStdError = childErr;
            si.lpAttributeList = o.restrictInheritance ? attrs : nullptr;
            DWORD flags = o.creationFlags | CREATE_SUSPENDED | extraFlags |
                          (o.restrictInheritance ? EXTENDED_STARTUPINFO_PRESENT : 0);
            std::vector<wchar_t> cmdBuf(cmd.begin(), cmd.end());
            cmdBuf.push_back(L'\0');
            std::memset(&pi, 0, sizeof pi);
            return CreateProcessW(app.c_str(), cmdBuf.data(), nullptr, nullptr, TRUE /* inherit: only the list */,
                                  flags, nullptr, cwd.empty() ? nullptr : cwd.c_str(), &si.StartupInfo, &pi) != 0;
        };
        auto discard = [](PROCESS_INFORMATION& pi) {     // a suspended child that never ran
            TerminateProcess(pi.hProcess, 1);
            WaitForSingleObject(pi.hProcess, 5000);
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            std::memset(&pi, 0, sizeof pi);
        };

        PROCESS_INFORMATION pi;
        DWORD err = 0;
        bool ok = create(0, pi);
        if (!ok) err = GetLastError();
        jobState_ = JobState::NoJobRequested;
        jobError_ = 0;
        if (ok && o.job && o.job->ok()) {
            if (AssignProcessToJobObject(o.job->handle(), pi.hProcess)) {
                jobState_ = JobState::Assigned;
            } else {
                jobError_ = GetLastError();
                discard(pi);
                bool done = false;
                // Retry outside the parent's job; CreateProcess fails with ERROR_ACCESS_DENIED unless that job
                // has JOB_OBJECT_LIMIT_BREAKAWAY_OK.
                if (o.tryBreakawayIfAssignFails && create(CREATE_BREAKAWAY_FROM_JOB, pi)) {
                    if (AssignProcessToJobObject(o.job->handle(), pi.hProcess)) { jobState_ = JobState::AssignedAfterBreakaway; done = true; }
                    else discard(pi);
                }
                if (!done) {
                    ok = create(0, pi);
                    if (!ok) err = GetLastError();
                    else jobState_ = JobState::AssignFailedRunningWithoutJob;   // still exits on stdin EOF when idle
                }
            }
        }
        if (ok && ResumeThread(pi.hThread) == (DWORD)-1) { err = GetLastError(); discard(pi); ok = false; }

        // 6. Close the child's ends in the parent NOW: before the next spawn and before releasing the mutex.
        closeChildEnds();
        if (attrsReady) DeleteProcThreadAttributeList(attrs);
        if (lock.owns_lock()) lock.unlock();

        if (!ok) { closeHandles(); return fail("CreateProcessW(" + o.exePath + ")", err); }
        CloseHandle(pi.hThread);
        process_ = pi.hProcess;
        pid_ = pi.dwProcessId;
        rbuf_.clear(); rpos_ = 0; crStripped_ = 0;
        return true;
    }

    // Writes line + '\n' with a full WriteFile loop. Fails (ERROR_NO_DATA / ERROR_BROKEN_PIPE) when the child
    // is gone. Blocks while the pipe buffer is full, i.e. while the child is busy and not reading.
    bool writeLine(const std::string& line) {
        if (!stdinWrite_) return fail("writeLine: stdin closed", ERROR_INVALID_HANDLE);
        size_t body = line.size();
        if (body && line[body - 1] == '\n') --body;
        if (std::memchr(line.data(), '\n', body)) return fail("writeLine: embedded newline", ERROR_INVALID_DATA);
        std::string buf(line.data(), body);
        buf.push_back('\n');
        const char* p = buf.data();
        size_t left = buf.size();
        while (left > 0) {
            DWORD chunk = (DWORD)(left > (1u << 30) ? (1u << 30) : left), written = 0;
            if (!WriteFile(stdinWrite_, p, chunk, &written, nullptr)) return fail("WriteFile", GetLastError());
            p += written;
            left -= written;
        }
        return true;
    }

    // Reads one '\n'-terminated line (without the '\n' and without one trailing '\r': a child whose stdout is
    // in text mode -- the C/C++ default on Windows -- turns every "\n" into "\r\n").
    // Returns false at EOF (ReadFile fails with ERROR_BROKEN_PIPE once every write end is closed) or on error;
    // an unterminated tail is left in the buffer (bufferedBytes()) and is NOT returned as a line.
    bool readLine(std::string& line) {
        for (;;) {
            size_t nl = rbuf_.find('\n', rpos_);
            if (nl != std::string::npos) {
                size_t end = nl;
                if (end > rpos_ && rbuf_[end - 1] == '\r') { --end; ++crStripped_; }
                line.assign(rbuf_, rpos_, end - rpos_);
                rpos_ = nl + 1;
                if (rpos_ == rbuf_.size()) { rbuf_.clear(); rpos_ = 0; }
                else if (rpos_ > 65536) { rbuf_.erase(0, rpos_); rpos_ = 0; }
                return true;
            }
            if (!stdoutRead_) return fail("readLine: stdout closed", ERROR_INVALID_HANDLE);
            char tmp[65536];
            DWORD got = 0;
            if (!ReadFile(stdoutRead_, tmp, sizeof tmp, &got, nullptr)) {
                DWORD e = GetLastError();
                eof_ = true;
                return fail(e == ERROR_BROKEN_PIPE ? "EOF" : "ReadFile", e);
            }
            if (got) rbuf_.append(tmp, got);          // got == 0 only after a zero-length WriteFile: not EOF
        }
    }

    // Graceful shutdown: the child's getline() sees EOF.
    void closeStdin() { if (stdinWrite_) { CloseHandle(stdinWrite_); stdinWrite_ = nullptr; } }

    // TerminateProcess + wait. Unblocks a thread stuck in readLine() (ERROR_BROKEN_PIPE) -- reliable only
    // because nobody else holds a write end of the child's stdout pipe (the handle list).
    bool kill(UINT exitCode = 1, DWORD waitMs = 5000) {
        if (!process_) return true;
        if (WaitForSingleObject(process_, 0) == WAIT_OBJECT_0) return true;
        TerminateProcess(process_, exitCode);
        return WaitForSingleObject(process_, waitMs) == WAIT_OBJECT_0;
    }
    bool waitExit(DWORD ms) { return !process_ || WaitForSingleObject(process_, ms) == WAIT_OBJECT_0; }
    bool running() const { return process_ && WaitForSingleObject(process_, 0) == WAIT_TIMEOUT; }
    DWORD exitCode() const { DWORD c = STILL_ACTIVE; if (process_) GetExitCodeProcess(process_, &c); return c; }

    // Releases every handle. Only call when no thread is inside readLine()/writeLine().
    void closeHandles() {
        if (stdinWrite_) { CloseHandle(stdinWrite_); stdinWrite_ = nullptr; }
        if (stdoutRead_) { CloseHandle(stdoutRead_); stdoutRead_ = nullptr; }
        if (process_) { CloseHandle(process_); process_ = nullptr; }
    }

    DWORD pid() const { return pid_; }
    HANDLE processHandle() const { return process_; }
    HANDLE stdoutReadHandle() const { return stdoutRead_; }   // for PeekNamedPipe experiments
    HANDLE stdinWriteHandle() const { return stdinWrite_; }
    JobState jobState() const { return jobState_; }
    DWORD jobError() const { return jobError_; }
    DWORD lastError() const { return lastError_; }
    const std::string& lastErrorText() const { return lastErrorText_; }
    size_t crStripped() const { return crStripped_; }
    size_t bufferedBytes() const { return rbuf_.size() - rpos_; }
    bool sawEof() const { return eof_; }

private:
    bool fail(const std::string& what, DWORD err) {
        lastError_ = err;
        lastErrorText_ = what + ": " + win32ErrorText(err);
        return false;
    }

    HANDLE process_ = nullptr;
    HANDLE stdinWrite_ = nullptr;     // parent's end of the child's stdin  (never inheritable)
    HANDLE stdoutRead_ = nullptr;     // parent's end of the child's stdout (never inheritable)
    DWORD pid_ = 0;
    JobState jobState_ = JobState::NoJobRequested;
    DWORD jobError_ = 0;
    DWORD lastError_ = 0;
    std::string lastErrorText_;
    std::string rbuf_;
    size_t rpos_ = 0;
    size_t crStripped_ = 0;
    bool eof_ = false;
};

}  // namespace mrbits
