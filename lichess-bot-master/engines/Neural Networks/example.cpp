// Standalone demonstration. Kernel.cpp is intentionally not modified.
#include "Small/Small.hpp"
#include "Large/Large.hpp"
#include <iomanip>
#include <iostream>

template <class Model>
void show_score(const std::string& weight_file) {
    const auto model = Model::load(weight_file); // Once at engine startup.
    typename Model::Workspace workspace;         // One separate workspace per thread.
    const std::int8_t board[8][8] = {
        {5, 3, 4, 6, 7, 4, 3, 5},
        {1, 1, 1, 1, 1, 1, 1, 1},
        {0, 0, 0, 0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0, 0, 0, 0},
        {9, 9, 9, 9, 9, 9, 9, 9},
        {13, 11, 12, 14, 15, 12, 11, 13}
    };
    // Starting position: White to move; KQkq rights; no EP target.
    const mrbits::nn::State state{true, 15, -1};
    const float white_pawns = model.evaluate(board, state, workspace);
    std::cout << std::fixed << std::setprecision(6)
              << "Starting-position score (White pawns): " << white_pawns
              << "\nEquivalent centipawns: " << white_pawns * 100.0f << '\n';
}

int main(int argc, char** argv) {
    try {
        if (argc != 3) {
            std::cerr << "Usage: example small|large path/to/weights.bin\n";
            return 2;
        }
        const std::string kind = argv[1];
        if (kind == "small") show_score<mrbits::nn::Small>(argv[2]);
        else if (kind == "large") show_score<mrbits::nn::Large>(argv[2]);
        else throw std::invalid_argument("Expected small or large");
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
