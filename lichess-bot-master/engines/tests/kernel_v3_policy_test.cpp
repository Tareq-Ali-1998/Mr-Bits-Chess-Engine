// Persistent reconstruction of the earlier temporary v3 diagnostic harness.
// Reads focused fixtures from run_kernel_policy_tests.py. Never calls worker main.
#ifdef NDEBUG
#error These diagnostic tests require assertions; compile without -DNDEBUG.
#endif
#define main mrbits_v3_worker_main_not_called_by_this_test
#include "../Kernels/v3/Kernel-v3.cpp"
#undef main

int main() {
    char kind;
    int color;
    while (std::cin >> kind >> color) {
        for (int row = 0; row < 8; ++row) for (int col = 0; col < 8; ++col) {
            int code;
            std::cin >> code;
            board[row][col] = static_cast<int8_t>(code);
            numberOfMovesOfThePieceOnThisSquare[row][col] = static_cast<int16_t>(row * 8 + col + 17);
        }
        engineScore = 1234; opponentScore = -4321; whitePieces = 0x55; blackPieces = 0xaa;
        previousMoves = {123, 456};
        int8_t saved[8][8];
        std::memcpy(saved, board, sizeof(saved));
        if (kind == 'A') {
            std::cout << v3_ordering::RootKingNeedsAllMoves(color != 0);
        } else {
            assert(kind == 'R');
            size_t count;
            std::cin >> count;
            std::vector<int16_t> moves;
            for (size_t i = 0; i < count; ++i) {
                int value;
                std::cin >> value;
                moves.push_back(static_cast<int16_t>(value));
            }
            v3_ordering::KeepRootCandidates(moves);
            std::cout << moves.size();
            for (const auto move : moves) std::cout << ' ' << move;
        }
        assert(std::cin);
        assert(std::memcmp(saved, board, sizeof(saved)) == 0);
        assert(engineScore == 1234 && opponentScore == -4321 && whitePieces == 0x55 && blackPieces == 0xaa);
        assert((previousMoves == std::vector<int16_t>{123, 456}));
        for (int row = 0; row < 8; ++row) for (int col = 0; col < 8; ++col) {
            assert(numberOfMovesOfThePieceOnThisSquare[row][col] == row * 8 + col + 17);
        }
        std::cout << '\n';
    }
    return 0;
}
