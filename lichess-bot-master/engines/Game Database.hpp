#ifndef GAME_DATABASE_H_INCLUDED
#define GAME_DATABASE_H_INCLUDED

#include <bits/stdc++.h>

#include "sqlite/sqlite3.h"
#include "json.hpp"
#include "Engine Log.hpp"

using namespace std;

// ############################################################ \\
//                            Notes                             \\
// Every move Mr. Bits plays goes into the game database        \\
// (lichess-bot-master\database\mrbits.sqlite): the move, the   \\
// time, the path that decided it, and every Kernel worker with \\
// its depths and candidate moves. The writer has its own       \\
// thread and gets the move only after "bestmove" is sent, so a \\
// slow disk or a locked database never costs the clock. If the \\
// database can't be opened, the engine keeps playing and only  \\
// the log says so.                                             \\
// ############################################################ \\

class GameDatabase {
  public:
    ~GameDatabase() {
        this->close(3000);
    }

    // Starts the writer thread, which opens the file and applies schema.sql (it's safe to run again).
    void open(const string& databaseFilePath, const string& schemaFilePath) {
        lock_guard<mutex> lock(this->queueMutex);
        if (this->writerThread.joinable()) {
            return;
        }
        this->databaseFilePath = databaseFilePath;
        this->schemaFilePath = schemaFilePath;
        this->writerThread = thread([this]() { this->writeEverythingInTheQueue(); });
    }

    void recordMove(const nlohmann::json& moveRecord) {
        this->addToTheQueue("move", moveRecord);
    }

    // An empty gameId or a ply of 0 means the event isn't about one game or one move (NULL in the database).
    void recordEvent(const string& gameId, const int& ply, const string& level, const string& source,
                     const string& message) {
        nlohmann::json eventRecord;
        eventRecord["at"] = (long long)chrono::duration_cast<chrono::milliseconds>(
                                chrono::system_clock::now().time_since_epoch()).count();
        eventRecord["gameId"] = gameId.empty() ? nlohmann::json(nullptr) : nlohmann::json(gameId);
        eventRecord["ply"] = (ply > 0) ? nlohmann::json(ply) : nlohmann::json(nullptr);
        eventRecord["level"] = level;
        eventRecord["source"] = source;
        eventRecord["message"] = message;
        this->addToTheQueue("event", eventRecord);
    }

    // Writes what is still in the queue (for at most maximumWaitInMilliseconds), then closes the file.
    void close(const int& maximumWaitInMilliseconds) {
        bool isFinishedInTime;
        {
            unique_lock<mutex> lock(this->queueMutex);
            if (!this->writerThread.joinable()) {
                return;
            }
            this->isClosing = true;
            this->queueConditionVariable.notify_all();
            isFinishedInTime = this->queueConditionVariable.wait_for(lock, chrono::milliseconds(maximumWaitInMilliseconds),
                                                                     [this]() { return this->isWriterFinished; });
        }
        if (isFinishedInTime) {
            this->writerThread.join();
        }
        else {
            WriteToUciLog("!! database: the writer didn't finish in time, the last moves may be missing");
            this->writerThread.detach();
        }
    }

  private:
    string databaseFilePath;
    string schemaFilePath;
    thread writerThread;
    mutex queueMutex;
    condition_variable queueConditionVariable;
    deque<pair<string, nlohmann::json>> queue;      // ("move" or "event", the record)
    bool isClosing = false;
    bool isWriterFinished = false;
    sqlite3* database = NULL;

    void addToTheQueue(const string& recordType, const nlohmann::json& record) {
        {
            lock_guard<mutex> lock(this->queueMutex);
            if (!this->writerThread.joinable() || this->isClosing) {
                return;
            }
            this->queue.push_back({recordType, record});
        }
        this->queueConditionVariable.notify_all();
    }

    void writeEverythingInTheQueue() {
        bool isDatabaseReady = this->openTheDatabase();
        while (true) {
            pair<string, nlohmann::json> nextRecord;
            {
                unique_lock<mutex> lock(this->queueMutex);
                this->queueConditionVariable.wait(lock, [this]() { return !this->queue.empty() || this->isClosing; });
                if (this->queue.empty()) {
                    break;
                }
                nextRecord = this->queue.front();
                this->queue.pop_front();
            }
            // Another program may have held the database when I started (DB Browser with unsaved changes, for
            // example), so I try again before every record instead of giving up on the whole game.
            if (!isDatabaseReady) {
                isDatabaseReady = this->openTheDatabase();
            }
            if (!isDatabaseReady) {
                continue;
            }
            try {
                if (nextRecord.first == "move") {
                    this->writeMove(nextRecord.second);
                }
                else {
                    this->writeEvent(nextRecord.second);
                }
            } catch (const exception& error) {
                this->execute("ROLLBACK");
                WriteToUciLog(string("!! database: a ") + nextRecord.first + " was not stored (" + error.what() + ")");
            }
        }
        this->closeTheDatabase();
        lock_guard<mutex> lock(this->queueMutex);
        this->isWriterFinished = true;
        this->queueConditionVariable.notify_all();
    }

    bool openTheDatabase() {
        ifstream schemaFile(this->schemaFilePath);
        if (!schemaFile) {
            WriteToUciLog("!! database not ready: " + this->schemaFilePath + " not found");
            return false;
        }
        stringstream schemaText;
        schemaText << schemaFile.rdbuf();

        if (sqlite3_open_v2(this->databaseFilePath.c_str(), &this->database,
                            SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE, NULL) != SQLITE_OK) {
            WriteToUciLog("!! database not ready: can't open " + this->databaseFilePath + " (" +
                          (this->database ? sqlite3_errmsg(this->database) : "out of memory") + ")");
            this->closeTheDatabase();
            return false;
        }
        // Wait up to 5 s when another program (the lichess sync) is writing at the same moment.
        sqlite3_busy_timeout(this->database, 5000);
        // schema.sql does all its work in one transaction, so a second engine starting at the same moment
        // simply waits for the first one, and a reader never sees a view missing.
        if (!this->execute(schemaText.str()) || !this->execute("PRAGMA foreign_keys = ON")) {
            WriteToUciLog("!! database not ready: schema.sql failed (" + string(sqlite3_errmsg(this->database)) +
                          "), I'll try again before the next record");
            this->execute("ROLLBACK");
            this->closeTheDatabase();
            return false;
        }
        WriteToUciLog("   database  : " + this->databaseFilePath);
        return true;
    }

    void closeTheDatabase() {
        if (this->database) {
            sqlite3_close(this->database);
            this->database = NULL;
        }
    }

    bool execute(const string& sql) {
        if (!this->database) {
            return false;
        }
        char* errorMessage = NULL;
        int result = sqlite3_exec(this->database, sql.c_str(), NULL, NULL, &errorMessage);
        if (errorMessage) {
            sqlite3_free(errorMessage);
        }
        return result == SQLITE_OK;
    }

    // One prepared statement, used once and freed at the end of the scope.
    class Statement {
      public:
        Statement(sqlite3* database, const string& sql) {
            this->database = database;
            if (sqlite3_prepare_v2(database, sql.c_str(), -1, &this->statement, NULL) != SQLITE_OK) {
                throw runtime_error(string("prepare failed: ") + sqlite3_errmsg(database));
            }
        }

        ~Statement() {
            sqlite3_finalize(this->statement);
        }

        Statement(const Statement&) = delete;
        Statement& operator=(const Statement&) = delete;

        // A JSON value becomes the matching SQL value (null, an integer, a real, a text).
        Statement& bind(const int& index, const nlohmann::json& value) {
            int result;
            if (value.is_null()) {
                result = sqlite3_bind_null(this->statement, index);
            }
            else if (value.is_boolean()) {
                result = sqlite3_bind_int(this->statement, index, value.get<bool>() ? 1 : 0);
            }
            else if (value.is_number_integer()) {
                result = sqlite3_bind_int64(this->statement, index, value.get<long long>());
            }
            else if (value.is_number()) {
                result = sqlite3_bind_double(this->statement, index, value.get<double>());
            }
            else if (value.is_string()) {
                string text = value.get<string>();
                result = sqlite3_bind_text(this->statement, index, text.c_str(), (int)text.size(), SQLITE_TRANSIENT);
            }
            else {
                // An array or an object is stored as its JSON text (the root moves, for example).
                string text = value.dump();
                result = sqlite3_bind_text(this->statement, index, text.c_str(), (int)text.size(), SQLITE_TRANSIENT);
            }
            if (result != SQLITE_OK) {
                throw runtime_error(string("bind failed: ") + sqlite3_errmsg(this->database));
            }
            return *this;
        }

        void run() {
            if (sqlite3_step(this->statement) != SQLITE_DONE) {
                throw runtime_error(string("step failed: ") + sqlite3_errmsg(this->database));
            }
        }

      private:
        sqlite3* database = NULL;
        sqlite3_stmt* statement = NULL;
    };

    // The value of a key, or SQL NULL when it's missing.
    static nlohmann::json valueOf(const nlohmann::json& object, const string& key) {
        if (object.is_object() && object.contains(key)) {
            return object[key];
        }
        return nullptr;
    }

    // One move in one transaction: its old rows (if this ply was played before, after an engine restart) are
    // deleted first, and the foreign keys delete its workers, depths and candidates with it.
    void writeMove(const nlohmann::json& moveRecord) {

        const nlohmann::json gameId = moveRecord.at("gameId");
        const nlohmann::json ply = moveRecord.at("ply");
        const nlohmann::json go = valueOf(moveRecord, "go");
        const nlohmann::json opponent = valueOf(moveRecord, "opponent");

        if (!this->execute("BEGIN IMMEDIATE")) {
            throw runtime_error(string("BEGIN failed: ") + sqlite3_errmsg(this->database));
        }

        Statement(this->database,
                  "INSERT INTO engine_games(game_id, our_color, opponent_title, opponent_rating, opponent_is_bot, "
                  "opponent_name, first_move_at, last_move_at, engine_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                  "ON CONFLICT(game_id) DO UPDATE SET "
                  "our_color = COALESCE(engine_games.our_color, excluded.our_color), "
                  "opponent_title = COALESCE(excluded.opponent_title, engine_games.opponent_title), "
                  "opponent_rating = COALESCE(excluded.opponent_rating, engine_games.opponent_rating), "
                  "opponent_is_bot = COALESCE(excluded.opponent_is_bot, engine_games.opponent_is_bot), "
                  "opponent_name = COALESCE(excluded.opponent_name, engine_games.opponent_name), "
                  "first_move_at = MIN(engine_games.first_move_at, excluded.first_move_at), "
                  "last_move_at = MAX(COALESCE(engine_games.last_move_at, 0), excluded.last_move_at), "
                  "engine_version = excluded.engine_version")
            .bind(1, gameId).bind(2, valueOf(moveRecord, "ourColor"))
            .bind(3, valueOf(opponent, "title")).bind(4, valueOf(opponent, "rating"))
            .bind(5, valueOf(opponent, "isBot")).bind(6, valueOf(opponent, "name"))
            .bind(7, moveRecord.at("receivedAt")).bind(8, moveRecord.at("receivedAt"))
            .bind(9, valueOf(moveRecord, "engineVersion"))
            .run();

        Statement(this->database, "DELETE FROM engine_moves WHERE game_id = ? AND ply = ?")
            .bind(1, gameId).bind(2, ply).run();

        Statement(this->database,
                  "INSERT INTO engine_moves(game_id, ply, received_at, wtime_ms, btime_ms, winc_ms, binc_ms, "
                  "movetime_ms, allowed_seconds, path, legal_moves, workers, best_move, best_score, stockfish_depth, "
                  "t_legal_ms, t_kernel_ms, t_tie_check_ms, t_total_ms, engine_version) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(1, gameId).bind(2, ply).bind(3, moveRecord.at("receivedAt"))
            .bind(4, valueOf(go, "wtime")).bind(5, valueOf(go, "btime"))
            .bind(6, valueOf(go, "winc")).bind(7, valueOf(go, "binc")).bind(8, valueOf(go, "movetime"))
            .bind(9, valueOf(moveRecord, "allowedSeconds")).bind(10, moveRecord.at("path"))
            .bind(11, valueOf(moveRecord, "legalMoves")).bind(12, valueOf(moveRecord, "workers"))
            .bind(13, valueOf(moveRecord, "bestMove")).bind(14, valueOf(moveRecord, "bestScore"))
            .bind(15, valueOf(moveRecord, "stockfishDepth"))
            .bind(16, valueOf(moveRecord, "legalMovesMs")).bind(17, valueOf(moveRecord, "kernelMs"))
            .bind(18, valueOf(moveRecord, "tieCheckMs")).bind(19, valueOf(moveRecord, "totalMs"))
            .bind(20, valueOf(moveRecord, "engineVersion"))
            .run();

        const nlohmann::json kernelWorkers = valueOf(moveRecord, "kernelWorkers");
        if (kernelWorkers.is_array()) {
            for (const nlohmann::json& workerRecord : kernelWorkers) {
                this->writeWorker(gameId, ply, workerRecord);
            }
        }

        if (!this->execute("COMMIT")) {
            throw runtime_error(string("COMMIT failed: ") + sqlite3_errmsg(this->database));
        }

    }

    void writeWorker(const nlohmann::json& gameId, const nlohmann::json& ply, const nlohmann::json& workerRecord) {

        const nlohmann::json worker = workerRecord.at("worker");
        const nlohmann::json answer = valueOf(workerRecord, "answer");

        Statement(this->database,
                  "INSERT INTO worker_runs(game_id, ply, worker, root_moves, status, depth, best_move, best_score, "
                  "setup_ms, search_ms, nodes, leaf_nodes, pruned, total_nodes, unsearched_root_moves, error) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(1, gameId).bind(2, ply).bind(3, worker)
            .bind(4, valueOf(workerRecord, "rootMoves")).bind(5, workerRecord.at("status"))
            .bind(6, valueOf(answer, "depth")).bind(7, valueOf(answer, "bestMove")).bind(8, valueOf(answer, "score"))
            .bind(9, valueOf(answer, "setupMs")).bind(10, valueOf(answer, "searchMs"))
            .bind(11, valueOf(answer, "nodes")).bind(12, valueOf(answer, "leafNodes"))
            .bind(13, valueOf(answer, "pruned")).bind(14, valueOf(answer, "totalNodes"))
            .bind(15, valueOf(answer, "unsearchedRootMoves")).bind(16, valueOf(workerRecord, "error"))
            .run();

        const nlohmann::json perDepth = valueOf(answer, "perDepth");
        if (perDepth.is_array()) {
            for (const nlohmann::json& depthRecord : perDepth) {
                Statement(this->database,
                          "INSERT INTO worker_depths(game_id, ply, worker, depth, completed, ms, nodes, leaf_nodes, "
                          "pruned, best_move, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
                    .bind(1, gameId).bind(2, ply).bind(3, worker)
                    .bind(4, depthRecord.at("depth")).bind(5, valueOf(depthRecord, "completed"))
                    .bind(6, valueOf(depthRecord, "ms")).bind(7, valueOf(depthRecord, "nodes"))
                    .bind(8, valueOf(depthRecord, "leafNodes")).bind(9, valueOf(depthRecord, "pruned"))
                    .bind(10, valueOf(depthRecord, "bestMove")).bind(11, valueOf(depthRecord, "score"))
                    .run();
            }
        }

        const nlohmann::json rootScores = valueOf(answer, "rootScores");
        if (rootScores.is_array()) {
            for (const nlohmann::json& rootScore : rootScores) {
                Statement(this->database,
                          "INSERT INTO root_candidates(game_id, ply, worker, move, score, exact, depth) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)")
                    .bind(1, gameId).bind(2, ply).bind(3, worker)
                    .bind(4, rootScore.at("move")).bind(5, valueOf(rootScore, "score"))
                    .bind(6, valueOf(rootScore, "exact")).bind(7, valueOf(answer, "depth"))
                    .run();
            }
        }

    }

    void writeEvent(const nlohmann::json& eventRecord) {
        Statement(this->database, "INSERT INTO events(at, game_id, ply, level, source, message) VALUES (?, ?, ?, ?, ?, ?)")
            .bind(1, eventRecord.at("at")).bind(2, valueOf(eventRecord, "gameId")).bind(3, valueOf(eventRecord, "ply"))
            .bind(4, eventRecord.at("level")).bind(5, eventRecord.at("source")).bind(6, eventRecord.at("message"))
            .run();
    }
};

// ############################################################ \\

// THE game database of Engine UCI. It's never destroyed, on purpose: when close() stops waiting (another
// program held the database at the very end of a game), the writer thread can still be running until the
// process ends, so the object it uses must still be there.
inline GameDatabase& GetTheGameDatabase() {
    static GameDatabase* theGameDatabase = new GameDatabase();
    return *theGameDatabase;
}

#endif // GAME_DATABASE_H_INCLUDED
