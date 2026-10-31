#pragma once

// V7 only. Include after the original Kernel globals, lookup tables,
// MakeChanges(), and the shared neural helpers. Positions use the original
// a8-first board and encoded moves; this does not modify the older Kernels.
#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace mrbits::v7_position {

inline int16_t Encode(const int sr, const int sc, const int dr, const int dc,
                      const int tag = 0) noexcept {
    return static_cast<int16_t>(sr | (sc << 3) | (dr << 6) | (dc << 9) | (tag << 12));
}

inline bool Inside(const int row, const int column) noexcept {
    return row >= 0 && row < 8 && column >= 0 && column < 8;
}

// Geometric attacks include pinned pieces: a king cannot enter their attacks.
// Pawn attacks do not depend on whether the target square is occupied.
inline bool IsSquareAttacked(const int row, const int column, const bool byWhite) noexcept {
    const int color = byWhite ? 8 : 0;
    auto pieceAt = [&](const int r, const int c, const int type) {
        return Inside(r, c) && (board[r][c] & 15) == (type | color);
    };
    const int pawnRow = row + (byWhite ? 1 : -1);
    if (pieceAt(pawnRow, column - 1, 1) || pieceAt(pawnRow, column + 1, 1)) return true;

    constexpr int knightSteps[8][2] = {
        {-2,-1}, {-2,1}, {-1,-2}, {-1,2}, {1,-2}, {1,2}, {2,-1}, {2,1}
    };
    for (const auto& step : knightSteps) {
        if (pieceAt(row + step[0], column + step[1], 3)) return true;
    }
    for (int dr = -1; dr <= 1; ++dr) for (int dc = -1; dc <= 1; ++dc) {
        if (dr == 0 && dc == 0) continue;
        if (pieceAt(row + dr, column + dc, 7)) return true;
        const int slider = dr != 0 && dc != 0 ? 4 : 5;
        for (int r = row + dr, c = column + dc; Inside(r, c); r += dr, c += dc) {
            const int piece = board[r][c] & 15;
            if (!piece) continue;
            if ((piece & 8) == color && ((piece & 7) == slider || (piece & 7) == 6)) return true;
            break;
        }
    }
    return false;
}

// Return the unique king's a8-first square (row*8+column). Occupancy masks
// are already maintained by the engine; do not scan 64 squares to find pieces.
inline int FindKing(const bool white) {
    uint64_t pieces = static_cast<uint64_t>(white ? whitePieces : blackPieces);
    const int king = 7 | (white ? 8 : 0);
    int square = -1;
    while (pieces) {
        const int bit = 63 - __builtin_clzll(pieces);
        pieces ^= (uint64_t{1} << bit);
        const int row = getPieceRowFromBit[bit], column = getPieceColumnFromBit[bit];
        if ((board[row][column] & 15) != king) continue;
        if (square != -1) throw std::invalid_argument("V7 position has more than one king of one color");
        square = row * 8 + column;
    }
    if (square == -1) throw std::invalid_argument("V7 position is missing a king");
    return square;
}

inline bool InCheck(const bool white) {
    const int square = FindKing(white);
    return IsSquareAttacked(square / 8, square % 8, !white);
}

// Exact incremental rollback. The constructor requires a pseudo-legal move
// produced by this generator or an already validated root/history move.
// Castle: four cells; EP: three; ordinary/promotion: two. No full-board copy
// and no assumptions about the original undo function's counter values.
class UndoMove {
    struct Cell {
        uint8_t square;
        int8_t piece;
        int16_t count;
    };
    std::array<Cell, 4> cells_{};
    long long white_, black_;
    int engine_score_, opponent_score_;
    unsigned count_ = 0;

    void Save(const int row, const int column) noexcept {
        const auto square = static_cast<uint8_t>(row * 8 + column);
        for (unsigned i = 0; i < count_; ++i) if (cells_[i].square == square) return;
        cells_[count_++] = {square, board[row][column], numberOfMovesOfThePieceOnThisSquare[row][column]};
    }

public:
    explicit UndoMove(const int16_t encodedMove) noexcept
        : white_(whitePieces), black_(blackPieces),
          engine_score_(engineScore), opponent_score_(opponentScore) {
        const auto move = static_cast<uint16_t>(encodedMove);
        const int sr = move & 7, sc = (move >> 3) & 7;
        const int dr = (move >> 6) & 7, dc = (move >> 9) & 7;
        const int tag = (move >> 12) & 15;
        Save(sr, sc); Save(dr, dc);
        if (tag == 3) Save(sr, dc);
        if (tag == 4 || tag == 5) {
            Save(sr, tag == 4 ? 7 : 0);
            Save(sr, tag == 4 ? 5 : 3);
        }
        MakeChanges(encodedMove);
    }
    UndoMove(const UndoMove&) = delete;
    UndoMove& operator=(const UndoMove&) = delete;
    ~UndoMove() noexcept {
        for (unsigned i = 0; i < count_; ++i) {
            const auto& cell = cells_[i];
            board[cell.square / 8][cell.square % 8] = cell.piece;
            numberOfMovesOfThePieceOnThisSquare[cell.square / 8][cell.square % 8] = cell.count;
        }
        whitePieces = white_; blackPieces = black_;
        engineScore = engine_score_; opponentScore = opponent_score_;
    }
};

// Raw target is retained after a valid double push even if no legal EP capture
// exists. This is also the flag used by the trained neural input contract.
inline int8_t RawEnPassantFile(const bool whiteToMove, const int16_t encodedPreviousMove) noexcept {
    const auto previous = static_cast<uint16_t>(encodedPreviousMove);
    if (((previous >> 12) & 15) != 0) return -1;
    const int sr = previous & 7, sc = (previous >> 3) & 7;
    const int dr = (previous >> 6) & 7, dc = (previous >> 9) & 7;
    const bool previousWhite = !whiteToMove;
    if (sc != dc || !((previousWhite && sr == 6 && dr == 4) ||
                     (!previousWhite && sr == 1 && dr == 3))) return -1;
    if ((board[dr][dc] & 15) != (1 | (previousWhite ? 8 : 0)) ||
        board[sr][sc] != 0 || board[(sr + dr) / 2][sc] != 0) return -1;
    return static_cast<int8_t>(dc);
}

inline nn::State NeuralState(const bool whiteToMove, const int16_t previousMove) noexcept {
    return {whiteToMove, kernel_neural::CastlingRights(), RawEnPassantFile(whiteToMove, previousMove)};
}

inline bool IsTactical(const int16_t encodedMove) noexcept {
    const auto move = static_cast<uint16_t>(encodedMove);
    const int tag = (move >> 12) & 15;
    return (board[(move >> 6) & 7][(move >> 9) & 7] & 7) != 0 ||
        tag == 1 || tag == 2 || tag == 3 || tag == 6 || tag == 7;
}

inline std::vector<int16_t> LegalMoves(const bool white, const int16_t previousMove) {
    const int kingSquare = FindKing(white);
    (void)FindKing(!white); // Capturing/losing a king is not a legal v7 position.
    const int color = white ? 8 : 0;
    const int direction = white ? -1 : 1;
    const int8_t epFile = RawEnPassantFile(white, previousMove);
    std::vector<int16_t> pseudo;
    pseudo.reserve(64);
    auto addPawn = [&](const int sr, const int sc, const int dr, const int dc) {
        if (dr == 0 || dr == 7) {
            for (const int tag : {1, 2, 6, 7}) pseudo.push_back(Encode(sr, sc, dr, dc, tag));
        } else pseudo.push_back(Encode(sr, sc, dr, dc));
    };
    auto addStep = [&](const int sr, const int sc, const int dr, const int dc) {
        if (!Inside(dr, dc)) return;
        const int target = board[dr][dc] & 15;
        if (!target || ((target & 8) != color && (target & 7) != 7)) {
            pseudo.push_back(Encode(sr, sc, dr, dc));
        }
    };
    uint64_t pieces = static_cast<uint64_t>(white ? whitePieces : blackPieces);
    while (pieces) {
        const int bit = 63 - __builtin_clzll(pieces);
        pieces ^= (uint64_t{1} << bit);
        const int row = getPieceRowFromBit[bit], column = getPieceColumnFromBit[bit];
        const int piece = board[row][column] & 15, type = piece & 7;
        if (!piece || (piece & 8) != color || type == 2) {
            throw std::invalid_argument("V7 piece occupancy masks disagree with the board");
        }
        if (type == 1) {
            const int nextRow = row + direction;
            if (!Inside(nextRow, column)) continue;
            if (board[nextRow][column] == 0) {
                addPawn(row, column, nextRow, column);
                const int doubleRow = row + 2 * direction;
                if (row == (white ? 6 : 1) && board[doubleRow][column] == 0) {
                    pseudo.push_back(Encode(row, column, doubleRow, column));
                }
            }
            for (const int dc : {-1, 1}) {
                const int nextColumn = column + dc;
                if (!Inside(nextRow, nextColumn)) continue;
                const int target = board[nextRow][nextColumn] & 15;
                if (target && (target & 8) != color && (target & 7) != 7) {
                    addPawn(row, column, nextRow, nextColumn);
                } else if (!target && row == (white ? 3 : 4) && nextColumn == epFile &&
                           (board[row][nextColumn] & 15) == (1 | (white ? 0 : 8))) {
                    pseudo.push_back(Encode(row, column, nextRow, nextColumn, 3));
                }
            }
        } else if (type == 3) {
            constexpr int steps[8][2] = {
                {-2,-1}, {-2,1}, {-1,-2}, {-1,2}, {1,-2}, {1,2}, {2,-1}, {2,1}
            };
            for (const auto& step : steps) addStep(row, column, row + step[0], column + step[1]);
        } else if (type == 4 || type == 5 || type == 6) {
            for (int dr = -1; dr <= 1; ++dr) for (int dc = -1; dc <= 1; ++dc) {
                if (dr == 0 && dc == 0) continue;
                const bool diagonal = dr != 0 && dc != 0;
                if ((type == 4 && !diagonal) || (type == 5 && diagonal)) continue;
                for (int r = row + dr, c = column + dc; Inside(r, c); r += dr, c += dc) {
                    const int target = board[r][c] & 15;
                    if (!target) pseudo.push_back(Encode(row, column, r, c));
                    else {
                        if ((target & 8) != color && (target & 7) != 7) pseudo.push_back(Encode(row, column, r, c));
                        break;
                    }
                }
            }
        } else if (type == 7) {
            for (int dr = -1; dr <= 1; ++dr) for (int dc = -1; dc <= 1; ++dc) {
                if (dr != 0 || dc != 0) addStep(row, column, row + dr, column + dc);
            }
            const int homeRow = white ? 7 : 0;
            if (row == homeRow && column == 4 && numberOfMovesOfThePieceOnThisSquare[row][column] == 0 &&
                !IsSquareAttacked(row, column, !white)) {
                for (const bool shortCastle : {true, false}) {
                    const int rookColumn = shortCastle ? 7 : 0;
                    const int transitColumn = shortCastle ? 5 : 3;
                    const int destinationColumn = shortCastle ? 6 : 2;
                    if ((board[homeRow][rookColumn] & 15) != (5 | color) ||
                        numberOfMovesOfThePieceOnThisSquare[homeRow][rookColumn] != 0) continue;
                    bool clear = true;
                    for (int c = shortCastle ? 5 : 1; c <= (shortCastle ? 6 : 3); ++c) {
                        if (board[homeRow][c] != 0) { clear = false; break; }
                    }
                    if (!clear) continue;
                    bool transitSafe;
                    {
                        const UndoMove transit(Encode(homeRow, 4, homeRow, transitColumn));
                        transitSafe = !IsSquareAttacked(homeRow, transitColumn, !white);
                    }
                    if (transitSafe) pseudo.push_back(Encode(homeRow, 4, homeRow, destinationColumn,
                                                             shortCastle ? 4 : 5));
                }
            }
        } else {
            throw std::invalid_argument("V7 position contains an unsupported piece type");
        }
    }

    std::vector<int16_t> legal;
    legal.reserve(pseudo.size());
    for (const int16_t encodedMove : pseudo) {
        const auto move = static_cast<uint16_t>(encodedMove);
        const int sr = move & 7, sc = (move >> 3) & 7;
        const int dr = (move >> 6) & 7, dc = (move >> 9) & 7;
        const bool kingMoves = (board[sr][sc] & 7) == 7;
        const int kingRow = kingMoves ? dr : kingSquare / 8;
        const int kingColumn = kingMoves ? dc : kingSquare % 8;
        const UndoMove undo(encodedMove);
        if (!IsSquareAttacked(kingRow, kingColumn, !white)) legal.push_back(encodedMove);
    }
    return legal;
}

} // namespace mrbits::v7_position
