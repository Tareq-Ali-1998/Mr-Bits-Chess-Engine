// Independent C++ parity/benchmark driver. Does not alter or invoke the engine.
#include "Small/Small.hpp"
#include "Large/Large.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace nn = mrbits::nn;
using Clock = std::chrono::steady_clock;
volatile double benchmark_sink = 0.0;

struct Sample { std::array<std::uint8_t, 78> packed{}; float reference = 0; };
struct Timing { std::vector<double> ns; std::size_t iterations = 0; double checksum = 0; };

std::uint32_t read_u32(std::istream& in) {
    unsigned char bytes[4];
    if (!in.read(reinterpret_cast<char*>(bytes), 4)) throw std::runtime_error("Truncated corpus integer");
    return std::uint32_t(bytes[0]) | (std::uint32_t(bytes[1]) << 8) |
           (std::uint32_t(bytes[2]) << 16) | (std::uint32_t(bytes[3]) << 24);
}

std::vector<Sample> read_samples(const std::string& path) {
    static_assert(sizeof(float) == 4, "Corpus requires float32");
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open corpus");
    char magic[8];
    if (!in.read(magic, 8) || std::memcmp(magic, "MRBTST01", 8)) throw std::runtime_error("Wrong corpus magic");
    const auto count = read_u32(in);
    if (!count || count > 100000) throw std::runtime_error("Unreasonable corpus size");
    std::vector<Sample> samples(count);
    for (auto& sample : samples) {
        if (!in.read(reinterpret_cast<char*>(sample.packed.data()), 78)) throw std::runtime_error("Truncated packed position");
        const auto bits = read_u32(in);
        std::memcpy(&sample.reference, &bits, 4);
        if (!std::isfinite(sample.reference)) throw std::runtime_error("Nonfinite reference");
    }
    if (in.peek() != std::char_traits<char>::eof()) throw std::runtime_error("Trailing corpus bytes");
    return samples;
}

bool same_features(const nn::ActiveFeatures& a, const nn::ActiveFeatures& b) {
    if (a.size != b.size) return false;
    for (std::size_t i = 0; i < a.size; ++i) if (a.indices[i] != b.indices[i]) return false;
    return true;
}

double difference(float a, float b) {
    if (!std::isfinite(a) || !std::isfinite(b)) throw std::runtime_error("Nonfinite adapter/accumulator result");
    return std::abs(double(a) - b);
}

void kernel_position(const Sample& sample, std::int8_t (&board)[8][8], nn::State& state, bool high_flags = false) {
    // Kernel.cpp's low nibble: P=1,N=3,B=4,R=5,Q=6,K=7; bit3 means White.
    const std::uint8_t types[] = {0, 1, 3, 4, 5, 6, 7};
    for (std::size_t square = 0; square < 64; ++square) {
        const auto code = sample.packed[square];
        auto value = std::uint8_t(code ? types[(code - 1) % 6 + 1] | (code <= 6 ? 8 : 0) : 0);
        if (high_flags) value |= (square % 2 ? 0x40 : 0x80);
        board[square / 8][square % 8] = static_cast<std::int8_t>(value);
    }
    state.white_to_move = sample.packed[64] != 0;
    state.castling = 0;
    for (unsigned i = 0; i < 4; ++i) state.castling |= sample.packed[65 + i] << i;
    state.ep_file = -1;
    for (unsigned i = 1; i <= 8; ++i) if (sample.packed[69 + i]) state.ep_file = static_cast<std::int8_t>(i - 1);
}

template<class Function> void must_reject(Function operation, const char* name, unsigned& count) {
    bool rejected = false;
    try { operation(); } catch (const std::invalid_argument&) { rejected = true; }
    if (!rejected) throw std::runtime_error(std::string("Invalid adapter input was accepted: ") + name);
    ++count;
}

unsigned check_bad_inputs(const Sample& sample) {
    unsigned checks = 0;
    for (unsigned mode = 0; mode < 5; ++mode) {
        auto bad = sample.packed;
        if (mode == 0) bad[0] = 13;
        if (mode == 1) bad[64] = 2;
        if (mode == 2) bad[65] = 2;
        if (mode >= 3) { std::fill(bad.begin() + 69, bad.end(), 0); if (mode == 4) bad[69] = bad[70] = 1; }
        must_reject([&] { nn::from_packed(bad); }, "packed piece/flag/EP", checks);
    }
    must_reject([&] { nn::from_packed(sample.packed.data(), 77); }, "packed length", checks);
    for (unsigned mode = 0; mode < 4; ++mode) {
        std::int8_t board[8][8]; nn::State state;
        kernel_position(sample, board, state);
        if (mode == 0) board[0][0] = 2;
        if (mode == 1) board[0][0] = 8;
        if (mode == 2) state.castling = 16;
        if (mode == 3) state.ep_file = 8;
        must_reject([&] { nn::from_kernel(board, state); }, "kernel piece/state", checks);
    }
    return checks;
}

bool runtime_avx2() {
#if (defined(__GNUC__) || defined(__clang__)) && (defined(__i386__) || defined(__x86_64__))
    __builtin_cpu_init();
    return __builtin_cpu_supports("avx2");
#else
    return false;
#endif
}

bool runtime_fma() {
#if (defined(__GNUC__) || defined(__clang__)) && (defined(__i386__) || defined(__x86_64__))
    __builtin_cpu_init();
    return __builtin_cpu_supports("fma");
#else
    return false;
#endif
}

template<class Function> Timing time_calls(Function evaluate, std::size_t size, unsigned rounds, double minimum_seconds) {
    for (std::size_t i = 0; i < std::min<std::size_t>(size, 16); ++i) benchmark_sink += evaluate(i);
    auto run = [&](std::size_t count, std::size_t offset) {
        double checksum = 0;
        const auto start = Clock::now();
        for (std::size_t i = 0; i < count; ++i) checksum += evaluate((i + offset) % size);
        const double seconds = std::chrono::duration<double>(Clock::now() - start).count();
        benchmark_sink += checksum;
        return std::make_pair(seconds, checksum);
    };
    Timing timing;
    timing.iterations = 32;
    while (timing.iterations < 1048576) {
        const auto probe = run(timing.iterations, 0);
        if (probe.first >= minimum_seconds) break;
        timing.iterations *= 2;
    }
    for (unsigned round = 0; round < rounds; ++round) {
        const auto result = run(timing.iterations, round * 31);
        timing.ns.push_back(result.first * 1e9 / timing.iterations);
        timing.checksum += result.second;
    }
    return timing;
}

void write_timing(std::ostream& out, const Timing& timing) {
    auto sorted = timing.ns;
    std::sort(sorted.begin(), sorted.end());
    const auto count = sorted.size();
    const double median = count % 2 ? sorted[count / 2] : (sorted[count / 2 - 1] + sorted[count / 2]) / 2;
    out << "{\"iterations_per_round\":" << timing.iterations << ",\"rounds\":" << count
        << ",\"median_ns_per_position\":" << median << ",\"positions_per_second\":" << 1e9 / median
        << ",\"min_ns_per_position\":" << sorted.front() << ",\"max_ns_per_position\":" << sorted.back()
        << ",\"checksum\":" << timing.checksum << ",\"round_ns_per_position\":[";
    for (std::size_t i = 0; i < count; ++i) { if (i) out << ','; out << timing.ns[i]; }
    out << "]}";
}

template<class Model> int verify_model(const std::string& weights, const std::string& corpus,
                                     const std::string& output, unsigned rounds, double minimum_seconds,
                                     bool benchmark) {
    auto model = Model::load(weights);
    auto samples = read_samples(corpus);
    typename Model::Workspace workspace;
    typename Model::Workspace accumulator;
    std::vector<nn::ActiveFeatures> features;
    std::vector<float> scores;
    double adapter_max = 0, reset_max = 0, delta_max = 0, roundtrip_max = 0;
    const auto rejected = check_bad_inputs(samples.front());
    nn::ActiveFeatures previous{};
    for (std::size_t index = 0; index < samples.size(); ++index) {
        auto active = nn::from_packed(samples[index].packed);
        for (std::size_t i = 1; i < active.size; ++i)
            if (active.indices[i - 1] >= active.indices[i]) throw std::runtime_error("Features not strictly ascending");
        features.push_back(active);
        const float packed_score = model.evaluate(active, workspace);
        if (!std::isfinite(packed_score)) throw std::runtime_error("Nonfinite C++ output");
        scores.push_back(packed_score);
        for (bool flags : {false, true}) {
            std::int8_t board[8][8]; nn::State state;
            kernel_position(samples[index], board, state, flags);
            if (!same_features(active, nn::from_kernel(board, state))) throw std::runtime_error("Kernel adapter feature mismatch");
            adapter_max = std::max(adapter_max, difference(model.evaluate(board, state, workspace), packed_score));
        }
        model.reset_accumulator(accumulator);
        for (std::size_t i = 0; i < active.size; ++i) model.add_feature(active.indices[i], accumulator);
        const auto saved = accumulator.accumulator;
        reset_max = std::max(reset_max, difference(model.evaluate_accumulator(accumulator), packed_score));
        if (saved != accumulator.accumulator) throw std::runtime_error("Evaluation modified the raw accumulator");
    }
    model.reset_accumulator(accumulator);
    auto change = [&](const nn::ActiveFeatures& from, const nn::ActiveFeatures& to) {
        std::size_t a = 0, b = 0;
        while (a < from.size || b < to.size) {
            if (b == to.size || (a < from.size && from.indices[a] < to.indices[b])) model.remove_feature(from.indices[a++], accumulator);
            else if (a == from.size || to.indices[b] < from.indices[a]) model.add_feature(to.indices[b++], accumulator);
            else { ++a; ++b; }
        }
    };
    for (std::size_t index = 0; index < features.size(); ++index) {
        const auto& active = features[index];
        if (index % 32 == 0) { model.reset_accumulator(accumulator); previous = nn::ActiveFeatures{}; }
        change(previous, active);
        delta_max = std::max(delta_max, difference(model.evaluate_accumulator(accumulator), scores[index]));
        previous = active;
    }
    unsigned roundtrips = 0;
    for (std::size_t i = 0; i + 1 < std::min<std::size_t>(features.size(), 16); i += 2) {
        model.reset_accumulator(accumulator);
        for (std::size_t j = 0; j < features[i].size; ++j) model.add_feature(features[i].indices[j], accumulator);
        for (unsigned repeat = 0; repeat < 8; ++repeat) {
            change(features[i], features[i + 1]);
            roundtrip_max = std::max(roundtrip_max, difference(model.evaluate_accumulator(accumulator), scores[i + 1]));
            change(features[i + 1], features[i]);
            roundtrip_max = std::max(roundtrip_max, difference(model.evaluate_accumulator(accumulator), scores[i]));
            ++roundtrips;
        }
    }
    // Correctness only: immutable model shared across four private Workspaces.
    // The latency measurements below remain strictly serial/single-threaded.
    std::array<double, 4> thread_errors{};
    std::array<std::exception_ptr, 4> thread_exceptions{};
    std::vector<std::thread> workers;
    for (std::size_t thread = 0; thread < 4; ++thread) workers.emplace_back([&, thread] {
        try {
            typename Model::Workspace local;
            for (std::size_t i = thread; i < std::min<std::size_t>(features.size(), 64); i += 4)
                thread_errors[thread] = std::max(thread_errors[thread], difference(model.evaluate(features[i], local), scores[i]));
        } catch (...) { thread_exceptions[thread] = std::current_exception(); }
    });
    for (auto& worker : workers) worker.join();
    for (auto exception : thread_exceptions) if (exception) std::rethrow_exception(exception);
    const auto thread_max = *std::max_element(thread_errors.begin(), thread_errors.end());
    std::ofstream out(output);
    if (!out) throw std::runtime_error("Cannot write result JSON");
    out << std::setprecision(12);
    out << "{\"schema\":\"chesslab.cpp-driver.v1\",\"positions\":" << samples.size()
        << ",\"adapter_checks\":" << samples.size() * 2 << ",\"invalid_input_checks\":" << rejected
        << ",\"adapter_max_abs_pawns\":" << adapter_max << ",\"accumulator_reset_max_abs_pawns\":" << reset_max
        << ",\"delta_rebase_every_positions\":32,\"delta_max_abs_pawns\":" << delta_max
        << ",\"feature_delta_roundtrips\":" << roundtrips << ",\"roundtrip_max_abs_pawns\":" << roundtrip_max
        << ",\"private_workspace_test_threads\":4,\"private_workspace_max_abs_pawns\":" << thread_max
        << ",\"compiled_avx2\":"
#ifdef __AVX2__
        << "true"
#else
        << "false"
#endif
        << ",\"compiled_fma\":"
#ifdef __FMA__
        << "true"
#else
        << "false"
#endif
        << ",\"scores\":[";
    for (std::size_t i = 0; i < scores.size(); ++i) { if (i) out << ','; out << scores[i]; }
    out << ']';
    if (benchmark) {
        const auto inference = time_calls([&](std::size_t i) { return model.evaluate(features[i], workspace); }, samples.size(), rounds, minimum_seconds);
        const auto packed = time_calls([&](std::size_t i) { return model.evaluate(nn::from_packed(samples[i].packed), workspace); }, samples.size(), rounds, minimum_seconds);
        out << ",\"benchmark_prebuilt_features\":"; write_timing(out, inference);
        out << ",\"benchmark_packed_adapter_and_evaluate\":"; write_timing(out, packed);
    }
    out << "}\n";
    return 0;
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--cpu-info") {
            std::cout << "{\"runtime_avx2\":" << (runtime_avx2() ? "true" : "false")
                      << ",\"runtime_fma\":" << (runtime_fma() ? "true" : "false") << "}\n"; return 0;
        }
        if (argc == 4 && std::string(argv[1]) == "--check-load") {
            const std::string model = argv[2];
            if (model == "small") nn::Small::load(argv[3]);
            else if (model == "large") nn::Large::load(argv[3]);
            else throw std::runtime_error("Unknown model");
            std::cout << "{\"loaded\":true}\n"; return 0;
        }
        if (argc < 5) throw std::runtime_error("Usage: verify_cpp MODEL WEIGHTS CORPUS OUTPUT [--rounds N] [--min-seconds S] [--skip-benchmark]");
        unsigned rounds = 5; double minimum_seconds = 0.1; bool benchmark = true;
        for (int i = 5; i < argc; ++i) {
            const std::string flag = argv[i];
            if (flag == "--skip-benchmark") benchmark = false;
            else if (flag == "--rounds" && i + 1 < argc) rounds = static_cast<unsigned>(std::stoul(argv[++i]));
            else if (flag == "--min-seconds" && i + 1 < argc) minimum_seconds = std::stod(argv[++i]);
            else throw std::runtime_error("Unknown/missing argument");
        }
        if (!rounds || rounds > 31 || !std::isfinite(minimum_seconds) || minimum_seconds < 0.01 || minimum_seconds > 5)
            throw std::runtime_error("Invalid benchmark limits");
        const std::string model = argv[1];
        if (model == "small") return verify_model<nn::Small>(argv[2], argv[3], argv[4], rounds, minimum_seconds, benchmark);
        if (model == "large") return verify_model<nn::Large>(argv[2], argv[3], argv[4], rounds, minimum_seconds, benchmark);
        throw std::runtime_error("Unknown model");
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n'; return 1;
    }
}
