// WorkerPool.hpp -- N long-lived JSON Lines workers behind ChildProcess (prototype for Mr. Bits plan 02 Phase 3).
//
// Timeout design ("read a line with a timeout" on anonymous pipes, which have no overlapped I/O):
//   * every worker has ONE reader thread that does nothing but readLine() -> parse -> push into the worker's
//     inbox -> notify one pool-wide condition variable;
//   * the caller writes the requests, then waits on the condition variable with wait_until(deadline), so the
//     caller's wait is bounded no matter what a worker does;
//   * a worker still silent at the deadline is TerminateProcess'ed. That closes the only write end of its
//     stdout pipe, so its reader thread's blocked ReadFile fails with ERROR_BROKEN_PIPE and the thread ends;
//   * respawnDead() (call it after "bestmove" is printed) joins that reader -- with a CancelSynchronousIo
//     fallback in case some stray process still holds the pipe -- and starts a fresh worker.
//   Late answers can never be mistaken for current ones: every reply must carry the request's id.
#pragma once

#include "ChildProcess.hpp"
#include "json.hpp"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <memory>
#include <thread>
#include <utility>

namespace mrbits {

using Clock = std::chrono::steady_clock;
using Json = nlohmann::json;

struct PoolConfig {
    std::string exePath;               // full path, e.g. ExecutableDirectory() + "\\Kernel.exe"
    std::vector<std::string> args;     // e.g. {"--worker"}
    std::string logDir;                // worker i's stderr -> logDir\worker_<i>.stderr.log ("" => NUL)
    int count = 28;
    DWORD creationFlags = DETACHED_PROCESS;
    bool dieOnUnhandledException = true;
    bool useJob = true;                // false ONLY for the "what if there is no job" experiment
    int readyTimeoutMs = 10000;        // hello -> ready, for the whole pool
    bool restrictInheritance = true;   // experiment switches; keep true in Engine UCI
    bool serializeSpawn = true;
    // 64 KB instead of the 4 KB default: a request up to 64 KB (a 300-move game is ~5 KB) never blocks the
    // coordinator's WriteFile even if a worker is slow to read, and ~100 KB answers are 4.5x faster (RESULTS T13).
    DWORD pipeBufferSize = 65536;
};

struct Reply {
    enum Status { Ok, Error, Timeout, Dead, WriteFailed, Skipped };
    Status status = Skipped;
    Json msg;                          // the worker's parsed reply
    double ms = 0;                     // request written -> reply parsed by the reader thread
};

inline const char* replyStatusName(Reply::Status s) {
    switch (s) {
        case Reply::Ok: return "ok";
        case Reply::Error: return "error";
        case Reply::Timeout: return "timeout";
        case Reply::Dead: return "dead";
        case Reply::WriteFailed: return "write-failed";
        case Reply::Skipped: return "skipped";
    }
    return "?";
}

class WorkerPool {
public:
    struct Stats {
        long long spawned = 0, killedOnTimeout = 0, diedUnexpectedly = 0, staleDropped = 0, cancelFallbacks = 0,
                  readersLeaked = 0;
        double lastWakeLateMs = 0;   // how late wait_until woke up after the deadline, last timed-out round
    };

    WorkerPool() = default;
    ~WorkerPool() { shutdown(); }
    WorkerPool(const WorkerPool&) = delete;
    WorkerPool& operator=(const WorkerPool&) = delete;

    // Spawns cfg.count workers (sequentially: CreateProcess is the cheap part), sends each a hello, and waits
    // until every one has answered {"type":"ready"}.
    bool start(const PoolConfig& cfg, std::string* error = nullptr) {
        shutdown();
        cfg_ = cfg;
        if (cfg.useJob) {
            job_.reset(new JobObject(cfg.dieOnUnhandledException));
            if (!job_->ok() && error) *error = "CreateJobObject failed: " + win32ErrorText(job_->error()) + " (continuing without a job)";
        }
        for (int i = 0; i < cfg.count; ++i) {
            workers_.emplace_back(new Worker());
            workers_.back()->index = i;
        }
        for (auto& w : workers_)
            if (!spawn(*w, error)) return false;
        return waitReady(Clock::now() + std::chrono::milliseconds(cfg.readyTimeoutMs), error);
    }

    int size() const { return (int)workers_.size(); }

    // lines[i] goes to worker i ("" = skip worker i); ids[i] is the id that lines[i] carries.
    // Returns when every addressed worker has answered, died, or the deadline has passed. Workers that miss
    // the deadline are killed at once (so they stop using CPU) and marked for respawnDead().
    std::vector<Reply> roundTrip(const std::vector<std::string>& lines, const std::vector<long long>& ids,
                                 std::chrono::milliseconds timeout) {
        const int n = size();
        std::vector<Reply> out((size_t)n);
        std::vector<char> pending((size_t)n, 0);
        std::vector<Clock::time_point> sent((size_t)n);
        const Clock::time_point deadline = Clock::now() + timeout;
        int left = 0;
        for (int i = 0; i < n; ++i) {
            Worker& w = *workers_[i];
            if (i >= (int)lines.size() || lines[i].empty()) { out[i].status = Reply::Skipped; continue; }
            bool unusable;
            { std::lock_guard<std::mutex> lk(m_); unusable = !w.proc || w.needsRespawn; }
            if (unusable) { out[i].status = Reply::Dead; continue; }
            sent[i] = Clock::now();
            if (!w.proc->writeLine(lines[i])) {        // ERROR_NO_DATA / ERROR_BROKEN_PIPE: the worker is gone
                out[i].status = Reply::WriteFailed;
                std::lock_guard<std::mutex> lk(m_);
                w.needsRespawn = true;
                ++stats_.diedUnexpectedly;
                continue;
            }
            pending[i] = 1;
            ++left;
        }
        std::unique_lock<std::mutex> lk(m_);
        for (;;) {
            for (int i = 0; i < n && left > 0; ++i) {
                if (!pending[i]) continue;
                Worker& w = *workers_[i];
                while (!w.inbox.empty()) {
                    std::pair<Json, Clock::time_point> msg = std::move(w.inbox.front());
                    w.inbox.pop_front();
                    const Json& j = msg.first;
                    auto idIt = j.find("id");
                    auto typeIt = j.find("type");
                    bool idMatches = idIt != j.end() && idIt->is_number_integer() && idIt->get<long long>() == ids[i];
                    bool isReply = typeIt != j.end() && typeIt->is_string() &&
                                   (*typeIt == "result" || *typeIt == "error");
                    if (idMatches && isReply) {
                        out[i].status = (*typeIt == "result") ? Reply::Ok : Reply::Error;
                        out[i].ms = std::chrono::duration<double, std::milli>(msg.second - sent[i]).count();
                        out[i].msg = std::move(msg.first);
                        pending[i] = 0;
                        --left;
                        break;
                    }
                    ++stats_.staleDropped;             // an old id, or a stray line: never the current answer
                }
                if (pending[i] && w.readerDone) {      // EOF: the worker exited or crashed
                    out[i].status = Reply::Dead;
                    pending[i] = 0;
                    --left;
                    w.needsRespawn = true;
                    ++stats_.diedUnexpectedly;
                }
            }
            if (left == 0 || Clock::now() >= deadline) break;
            cv_.wait_until(lk, deadline);
        }
        std::vector<int> late;
        for (int i = 0; i < n; ++i)
            if (pending[i]) { out[i].status = Reply::Timeout; workers_[i]->needsRespawn = true; ++stats_.killedOnTimeout; late.push_back(i); }
        if (!late.empty()) stats_.lastWakeLateMs = std::chrono::duration<double, std::milli>(Clock::now() - deadline).count();
        lk.unlock();
        // TerminateProcess is asynchronous: don't wait for the exit here (that cost ~10 ms per kill in tests);
        // retire() waits before the reader is joined. The kill unblocks that worker's reader thread.
        for (int i : late) workers_[i]->proc->kill(1, 0);
        return out;
    }

    // Replaces every worker that timed out or died. Returns how many are ready again.
    int respawnDead(std::string* error = nullptr) {
        std::vector<Worker*> todo;
        {
            std::lock_guard<std::mutex> lk(m_);
            for (auto& w : workers_) if (w->needsRespawn || !w->proc) todo.push_back(w.get());
        }
        for (Worker* w : todo) { retire(*w); spawn(*w, error); }
        if (todo.empty()) return 0;
        waitReady(Clock::now() + std::chrono::milliseconds(cfg_.readyTimeoutMs), error);
        int ok = 0;
        std::lock_guard<std::mutex> lk(m_);
        for (Worker* w : todo) if (w->ready && !w->needsRespawn) ++ok;
        return ok;
    }

    // quit + close stdin, give the workers graceMs to exit on their own, then kill the rest and join readers.
    void shutdown(DWORD graceMs = 500) {
        if (workers_.empty()) { job_.reset(); return; }
        for (auto& w : workers_)
            if (w->proc) { w->proc->writeLine("{\"type\":\"quit\"}"); w->proc->closeStdin(); }
        const Clock::time_point until = Clock::now() + std::chrono::milliseconds(graceMs);
        for (auto& w : workers_) {
            if (!w->proc) continue;
            auto leftMs = std::chrono::duration_cast<std::chrono::milliseconds>(until - Clock::now()).count();
            w->proc->waitExit((DWORD)std::max<long long>(0, leftMs));
        }
        for (auto& w : workers_) retire(*w);
        workers_.clear();
        job_.reset();                                   // closing the job kills anything that is somehow left
    }

    JobObject* job() { return job_.get(); }
    ChildProcess* process(int i) { return workers_[i]->proc.get(); }
    DWORD pidOf(int i) const { return workers_[i]->proc ? workers_[i]->proc->pid() : 0; }
    const Stats& stats() const { return stats_; }

private:
    struct Worker {
        int index = 0;
        std::unique_ptr<ChildProcess> proc;
        std::thread reader;
        // everything below is guarded by WorkerPool::m_
        HANDLE readerThread = nullptr;     // real Win32 handle of the reader thread, for CancelSynchronousIo
        std::deque<std::pair<Json, Clock::time_point>> inbox;
        bool readerDone = false;
        bool ready = false;
        bool needsRespawn = false;
        DWORD readerError = 0;
    };

    bool spawn(Worker& w, std::string* error) {
        std::unique_ptr<ChildProcess> p(new ChildProcess());
        SpawnOptions o;
        o.exePath = cfg_.exePath;
        o.args = cfg_.args;
        if (!cfg_.logDir.empty()) o.stderrPath = cfg_.logDir + "\\worker_" + std::to_string(w.index + 1) + ".stderr.log";
        o.job = (job_ && job_->ok()) ? job_.get() : nullptr;
        o.creationFlags = cfg_.creationFlags;
        o.restrictInheritance = cfg_.restrictInheritance;
        o.serializeSpawn = cfg_.serializeSpawn;
        o.pipeBufferSize = cfg_.pipeBufferSize;
        if (!p->start(o)) {
            if (error) *error = "worker " + std::to_string(w.index + 1) + ": " + p->lastErrorText();
            std::lock_guard<std::mutex> lk(m_);
            w.needsRespawn = true;
            return false;
        }
        {
            std::lock_guard<std::mutex> lk(m_);
            w.proc = std::move(p);
            w.inbox.clear();
            w.readerDone = false;
            w.ready = false;
            w.needsRespawn = false;
            w.readerError = 0;
        }
        ++stats_.spawned;
        w.reader = std::thread(&WorkerPool::readerLoop, this, &w);
        return w.proc->writeLine("{\"type\":\"hello\",\"protocol\":1}");
    }

    void readerLoop(Worker* w) {
        HANDLE self = nullptr;
        DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &self, 0, FALSE, DUPLICATE_SAME_ACCESS);
        { std::lock_guard<std::mutex> lk(m_); w->readerThread = self; }
        std::string line;
        while (w->proc->readLine(line)) {
            const Clock::time_point t = Clock::now();
            Json j = Json::parse(line, nullptr, false);
            if (j.is_discarded() || !j.is_object()) j = Json{{"type", "badline"}, {"raw", line.substr(0, 200)}};
            { std::lock_guard<std::mutex> lk(m_); w->inbox.emplace_back(std::move(j), t); }
            cv_.notify_all();
        }
        { std::lock_guard<std::mutex> lk(m_); w->readerDone = true; w->readerError = w->proc->lastError(); }
        cv_.notify_all();
    }

    bool waitReady(Clock::time_point deadline, std::string* error) {
        std::unique_lock<std::mutex> lk(m_);
        for (;;) {
            int notReady = 0;
            for (auto& w : workers_) {
                if (w->ready || w->needsRespawn || !w->proc) continue;
                while (!w->inbox.empty()) {
                    const Json& j = w->inbox.front().first;
                    auto t = j.find("type");
                    bool isReady = t != j.end() && t->is_string() && *t == "ready";
                    w->inbox.pop_front();
                    if (isReady) { w->ready = true; break; }
                }
                if (!w->ready && w->readerDone) { w->needsRespawn = true; ++stats_.diedUnexpectedly; }
                if (!w->ready && !w->needsRespawn) ++notReady;
            }
            if (notReady == 0) break;
            if (Clock::now() >= deadline) {
                if (error) *error = std::to_string(notReady) + " worker(s) not ready before the deadline";
                for (auto& w : workers_) if (!w->ready && w->proc) w->needsRespawn = true;
                return false;
            }
            cv_.wait_until(lk, deadline);
        }
        for (auto& w : workers_) if (!w->ready) return false;
        return true;
    }

    // Kills the worker, waits (bounded) for its reader thread to see EOF, joins it, releases everything.
    void retire(Worker& w) {
        if (w.proc) w.proc->kill(1, 5000);
        std::unique_lock<std::mutex> lk(m_);
        bool done = !w.reader.joinable() ||
                    cv_.wait_for(lk, std::chrono::milliseconds(2000), [&] { return w.readerDone; });
        for (int tries = 0; !done && tries < 100; ++tries) {
            // Only reachable if another process still holds a write end of this worker's stdout pipe.
            HANDLE h = w.readerThread;
            lk.unlock();
            if (h) CancelSynchronousIo(h);              // ERROR_NOT_FOUND if not inside ReadFile right now
            lk.lock();
            ++stats_.cancelFallbacks;
            done = cv_.wait_for(lk, std::chrono::milliseconds(20), [&] { return w.readerDone; });
        }
        HANDLE h = w.readerThread;
        w.readerThread = nullptr;
        w.inbox.clear();
        lk.unlock();
        if (w.reader.joinable()) {
            if (done) w.reader.join();
            else { w.reader.detach(); ++stats_.readersLeaked; }
        }
        if (h) CloseHandle(h);
        if (done) w.proc.reset();
        else (void)w.proc.release();                   // a detached reader may still touch it: leak, never free
        std::lock_guard<std::mutex> lk2(m_);
        w.readerDone = false;
        w.ready = false;
    }

    PoolConfig cfg_;
    std::unique_ptr<JobObject> job_;
    std::vector<std::unique_ptr<Worker>> workers_;
    std::mutex m_;
    std::condition_variable cv_;
    Stats stats_;
};

}  // namespace mrbits
