#ifndef ENGINE_LOG_H_INCLUDED
#define ENGINE_LOG_H_INCLUDED

#include <bits/stdc++.h>
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>    // GetLocalTime, CreateDirectoryA, GetCurrentProcessId

using namespace std;

// ############################################################ \\
//                            Notes                             \\
// Engine UCI's own text log: every line lichess-bot sends me   \\
// (">>"), every line I answer ("<<") and every problem ("!!"), \\
// with the time, in engines\logs\uci_<date>_pid<pid>.log.      \\
// stdout is the UCI channel, so nothing else may ever be       \\
// printed there, and lichess-bot throws the engine's stderr    \\
// away. The games themselves are stored in the database; this  \\
// file is only for debugging.                                  \\
// ############################################################ \\

inline ofstream UCI_LOG_FILE;
inline mutex UCI_LOG_MUTEX;
inline const chrono::steady_clock::time_point PROCESS_START_TIME = chrono::steady_clock::now();

inline void OpenUciLogFile(const string& logsDirectory) {
    // It fails harmlessly when the folder already exists.
    CreateDirectoryA(logsDirectory.c_str(), NULL);
    SYSTEMTIME now;
    GetLocalTime(&now);
    char fileName[96];
    snprintf(fileName, sizeof(fileName), "\\uci_%04d%02d%02d-%02d%02d%02d_pid%lu.log", now.wYear, now.wMonth,
             now.wDay, now.wHour, now.wMinute, now.wSecond, (unsigned long)GetCurrentProcessId());
    UCI_LOG_FILE.open(logsDirectory + fileName, ios::app);
}

// It can be called from several threads at the same time (the Kernel workers' readers, the database
// writer), hence the mutex. Kernel.exe never opens the log, so there it does nothing.
inline void WriteToUciLog(const string& text) {
    lock_guard<mutex> lock(UCI_LOG_MUTEX);
    if (!UCI_LOG_FILE.is_open()) {
        return;
    }
    SYSTEMTIME now;
    GetLocalTime(&now);
    long long millisecondsSinceStart = chrono::duration_cast<chrono::milliseconds>(
                                           chrono::steady_clock::now() - PROCESS_START_TIME).count();
    char timeStamp[64];
    snprintf(timeStamp, sizeof(timeStamp), "%02d:%02d:%02d.%03d +%6lldms ", now.wHour, now.wMinute, now.wSecond,
             now.wMilliseconds, millisecondsSinceStart);
    UCI_LOG_FILE << timeStamp << text << '\n';
    UCI_LOG_FILE.flush();
}

#endif // ENGINE_LOG_H_INCLUDED
