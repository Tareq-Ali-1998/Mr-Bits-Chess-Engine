#include "Small/Small.hpp"
#include "Large/Large.hpp"
#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <iostream>
using namespace mrbits::nn;
template<class Model> void stress(const char* name, const char* path, const ActiveFeatures& root, const ActiveFeatures& child) {
    const auto model = Model::load(path);
    typename Model::Workspace incremental, reference;
    const float root_score = model.evaluate(root, incremental);
    const float child_score = model.evaluate(child, reference);
    const auto root_accumulator = incremental.accumulator;
    auto delta = [&](const ActiveFeatures& old, const ActiveFeatures& next) {
        std::size_t a = 0, b = 0;
        while (a < old.size || b < next.size) {
            if (b == next.size || (a < old.size && old.indices[a] < next.indices[b])) model.remove_feature(old.indices[a++], incremental);
            else if (a == old.size || next.indices[b] < old.indices[a]) model.add_feature(next.indices[b++], incremental);
            else { ++a; ++b; }
        }
    };
    float max_score_error = 0, max_accumulator_error = 0;
    for (int cycle = 0; cycle < 256; ++cycle) {
        delta(root, child);
        max_score_error = std::max(max_score_error, std::abs(model.evaluate_accumulator(incremental) - child_score));
        delta(child, root);
        max_score_error = std::max(max_score_error, std::abs(model.evaluate_accumulator(incremental) - root_score));
        for (std::size_t i = 0; i < root_accumulator.size(); ++i) max_accumulator_error = std::max(max_accumulator_error, std::abs(incremental.accumulator[i] - root_accumulator[i]));
        if (cycle % 16 == 15) {
            model.reset_accumulator(incremental);
            for (std::size_t i = 0; i < root.size; ++i) model.add_feature(root.indices[i], incremental);
            if (incremental.accumulator != root_accumulator) throw std::runtime_error("Full rebuild did not restore the accumulator");
        }
    }
    if (!(max_score_error < 0.001f)) throw std::runtime_error("Incremental score drift exceeds 0.001 pawn diagnostic threshold");
    std::cout << name << " root=" << root_score << " child=" << child_score
              << " max_score_error_pawns=" << max_score_error
              << " max_accumulator_error=" << max_accumulator_error << '\n';
}
int main(int argc, char** argv) {
    if (argc != 3) throw std::runtime_error("Usage: incremental_stress SMALL_WEIGHTS LARGE_WEIGHTS");
    std::uint8_t packed[78]{};
    const std::uint8_t black[] = {10,8,9,11,12,9,8,10}, white[] = {4,2,3,5,6,3,2,4};
    for (int c = 0; c < 8; ++c) { packed[c]=black[c]; packed[8+c]=7; packed[48+c]=1; packed[56+c]=white[c]; }
    for (int i = 64; i <= 69; ++i) packed[i]=1;
    const auto root = from_packed(packed);
    packed[52]=0; packed[36]=1; packed[64]=0; packed[69]=0; packed[74]=1;
    const auto child = from_packed(packed);
    std::cout << std::setprecision(10);
    stress<Small>("small", argv[1], root, child);
    stress<Large>("large", argv[2], root, child);
    std::int8_t board[8][8]{};
    constexpr std::uint8_t types[7] = {0,1,3,4,5,6,7};
    packed[52]=1; packed[36]=0; packed[64]=1; packed[69]=1; packed[74]=0;
    for(int i=0;i<64;++i) if(packed[i]) board[i/8][i%8]=static_cast<std::int8_t>(types[(packed[i]-1)%6+1] | (packed[i] <= 6 ? 8 : 0));
    volatile std::uint64_t checksum=0;
    constexpr int repetitions=200000;
    auto start=std::chrono::steady_clock::now();
    for (int i=0;i<repetitions;++i) { auto f=from_kernel(board, State{(i&1)!=0,15,-1}); checksum += f.indices[static_cast<std::size_t>(i)%f.size]; }
    double ns=std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/repetitions;
    std::cout << "kernel_encoding_ns=" << ns << " checksum=" << checksum << '\n';
}
