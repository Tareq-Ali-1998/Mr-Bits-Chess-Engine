#pragma once

// board782_v1 inference support. This header performs no engine-state mutation.
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#if defined(__AVX2__)
#include <immintrin.h>
#endif

namespace mrbits::nn {

inline constexpr std::size_t feature_dimension = 782;
inline constexpr std::size_t packed_size = 78;
inline constexpr std::size_t maximum_active_features = 78;

struct State {
    bool white_to_move = true;
    // Bits 0,1,2,3: retained White K,Q and Black k,q castling rights.
    std::uint8_t castling = 0;
    // Preserve the recorded EP target file, even without a legal EP capture.
    std::int8_t ep_file = -1;
};

struct ActiveFeatures {
    std::uint16_t indices[maximum_active_features]{};
    std::size_t size = 0;
};

namespace detail {

inline void validate_active_features(const ActiveFeatures& features) {
    if (features.size > maximum_active_features) {
        throw std::invalid_argument("Too many active board782_v1 features");
    }
    for (std::size_t i = 0; i < features.size; ++i) {
        if (features.indices[i] >= feature_dimension ||
            (i != 0 && features.indices[i - 1] >= features.indices[i])) {
            throw std::invalid_argument("Active features must be unique, sorted and below 782");
        }
    }
}

inline void append_state(ActiveFeatures& result, const State& state) {
    if ((state.castling & 0xf0u) != 0 || state.ep_file < -1 || state.ep_file > 7) {
        throw std::invalid_argument("Invalid castling mask or en-passant file");
    }
    if (state.white_to_move) {
        result.indices[result.size++] = 768;
    }
    for (unsigned bit = 0; bit < 4; ++bit) {
        if ((state.castling & (1u << bit)) != 0) {
            result.indices[result.size++] = static_cast<std::uint16_t>(769 + bit);
        }
    }
    result.indices[result.size++] = static_cast<std::uint16_t>(773 + state.ep_file + 1);
}

inline std::uint32_t read_u32_le(const std::uint8_t* bytes) noexcept {
    return static_cast<std::uint32_t>(bytes[0]) |
           (static_cast<std::uint32_t>(bytes[1]) << 8) |
           (static_cast<std::uint32_t>(bytes[2]) << 16) |
           (static_cast<std::uint32_t>(bytes[3]) << 24);
}

constexpr std::array<std::uint32_t, 256> make_crc32_table() noexcept {
    std::array<std::uint32_t, 256> result{};
    for (std::size_t i = 0; i < result.size(); ++i) {
        std::uint32_t value = static_cast<std::uint32_t>(i);
        for (unsigned bit = 0; bit < 8; ++bit) {
            value = (value >> 1) ^ ((value & 1u) ? 0xedb88320u : 0u);
        }
        result[i] = value;
    }
    return result;
}

inline constexpr auto crc32_table = make_crc32_table();

inline std::uint32_t crc32(const std::uint8_t* bytes, std::size_t count) noexcept {
    std::uint32_t value = 0xffffffffu;
    for (std::size_t i = 0; i < count; ++i) {
        value = crc32_table[(value ^ bytes[i]) & 0xffu] ^ (value >> 8);
    }
    return value ^ 0xffffffffu;
}

struct ModelContract {
    std::uint32_t model_id;
    std::uint32_t parameter_count;
    std::uint32_t layer_count;
    std::uint32_t projection_width;
    std::uint32_t block_count;
    std::uint32_t head_width;
};

inline std::vector<float> load_weights(const std::string& path, ModelContract expected) {
    static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
                  "MRBNN001 requires IEEE-754 binary32 floats");
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) {
        throw std::runtime_error("Cannot open neural weight file: " + path);
    }
    const auto length = stream.tellg();
    const std::uint64_t expected_length = 64ull + 4ull * expected.parameter_count;
    if (length < 0 || static_cast<std::uint64_t>(length) != expected_length) {
        throw std::runtime_error("Neural weight file has an incorrect length");
    }
    stream.seekg(0);
    std::array<std::uint8_t, 64> header{};
    stream.read(reinterpret_cast<char*>(header.data()), header.size());
    if (!stream || std::memcmp(header.data(), "MRBNN001", 8) != 0) {
        throw std::runtime_error("Unsupported neural weight file magic");
    }
    if (read_u32_le(header.data() + 8) != expected.model_id ||
        read_u32_le(header.data() + 12) != feature_dimension ||
        read_u32_le(header.data() + 16) != expected.parameter_count ||
        read_u32_le(header.data() + 20) != expected.layer_count ||
        read_u32_le(header.data() + 24) != expected.projection_width ||
        read_u32_le(header.data() + 28) != expected.block_count ||
        read_u32_le(header.data() + 32) != expected.head_width) {
        throw std::runtime_error("Neural weight architecture does not match this model");
    }
    for (std::size_t i = 40; i < header.size(); ++i) {
        if (header[i] != 0) {
            throw std::runtime_error("Neural weight header reserved bytes must be zero");
        }
    }
    std::vector<float> weights(expected.parameter_count);
    const auto payload_size = static_cast<std::size_t>(expected.parameter_count) * 4;
    stream.read(reinterpret_cast<char*>(weights.data()), static_cast<std::streamsize>(payload_size));
    if (!stream) {
        throw std::runtime_error("Could not read the complete neural weight payload");
    }
    auto* bytes = reinterpret_cast<std::uint8_t*>(weights.data());
    if (crc32(bytes, payload_size) != read_u32_le(header.data() + 36)) {
        throw std::runtime_error("Neural weight payload CRC32 mismatch");
    }
    const std::uint32_t endian_probe = 1;
    const bool little_endian = *reinterpret_cast<const std::uint8_t*>(&endian_probe) == 1;
    for (std::size_t i = 0; i < weights.size(); ++i) {
        if (!little_endian) {
            const std::uint32_t bits = read_u32_le(bytes + i * 4);
            std::memcpy(&weights[i], &bits, 4);
        }
        std::uint32_t bits;
        std::memcpy(&bits, &weights[i], 4);
        // Inspect IEEE bits so validation also survives a caller's fast-math flags.
        if ((bits & 0x7f800000u) == 0x7f800000u) {
            throw std::runtime_error("Neural weight payload contains a non-finite value");
        }
    }
    return weights;
}

#if defined(__AVX2__)
inline __m256 multiply_add(__m256 a, __m256 b, __m256 sum) noexcept {
#if defined(__FMA__)
    return _mm256_fmadd_ps(a, b, sum);
#else
    return _mm256_add_ps(_mm256_mul_ps(a, b), sum);
#endif
}
#endif

inline float dot(const float* a, const float* b, std::size_t count) noexcept {
    std::size_t i = 0;
#if defined(__AVX2__)
    __m256 sum0 = _mm256_setzero_ps();
    __m256 sum1 = _mm256_setzero_ps();
    __m256 sum2 = _mm256_setzero_ps();
    __m256 sum3 = _mm256_setzero_ps();
    for (; i + 32 <= count; i += 32) {
        sum0 = multiply_add(_mm256_loadu_ps(a + i), _mm256_loadu_ps(b + i), sum0);
        sum1 = multiply_add(_mm256_loadu_ps(a + i + 8), _mm256_loadu_ps(b + i + 8), sum1);
        sum2 = multiply_add(_mm256_loadu_ps(a + i + 16), _mm256_loadu_ps(b + i + 16), sum2);
        sum3 = multiply_add(_mm256_loadu_ps(a + i + 24), _mm256_loadu_ps(b + i + 24), sum3);
    }
    __m256 sum = _mm256_add_ps(_mm256_add_ps(sum0, sum1), _mm256_add_ps(sum2, sum3));
    for (; i + 8 <= count; i += 8) {
        sum = multiply_add(_mm256_loadu_ps(a + i), _mm256_loadu_ps(b + i), sum);
    }
    alignas(32) float lanes[8];
    _mm256_store_ps(lanes, sum);
    float result = ((lanes[0] + lanes[1]) + (lanes[2] + lanes[3])) +
                   ((lanes[4] + lanes[5]) + (lanes[6] + lanes[7]));
#else
    float sum0 = 0, sum1 = 0, sum2 = 0, sum3 = 0;
    for (; i + 4 <= count; i += 4) {
        sum0 += a[i] * b[i];
        sum1 += a[i + 1] * b[i + 1];
        sum2 += a[i + 2] * b[i + 2];
        sum3 += a[i + 3] * b[i + 3];
    }
    float result = (sum0 + sum1) + (sum2 + sum3);
#endif
    for (; i < count; ++i) {
        result += a[i] * b[i];
    }
    return result;
}

template <bool Subtract = false>
inline void add_column(float* accumulator, const float* column, std::size_t width) noexcept {
    std::size_t i = 0;
#if defined(__AVX2__)
    for (; i + 8 <= width; i += 8) {
        const __m256 current = _mm256_loadu_ps(accumulator + i);
        const __m256 value = _mm256_loadu_ps(column + i);
        if constexpr (Subtract) {
            _mm256_storeu_ps(accumulator + i, _mm256_sub_ps(current, value));
        } else {
            _mm256_storeu_ps(accumulator + i, _mm256_add_ps(current, value));
        }
    }
#endif
    for (; i < width; ++i) {
        if constexpr (Subtract) {
            accumulator[i] -= column[i];
        } else {
            accumulator[i] += column[i];
        }
    }
}

inline void relu_copy(const float* input, float* output, std::size_t count) noexcept {
    std::size_t i = 0;
#if defined(__AVX2__)
    const __m256 zero = _mm256_setzero_ps();
    for (; i + 8 <= count; i += 8) {
        _mm256_storeu_ps(output + i, _mm256_max_ps(_mm256_loadu_ps(input + i), zero));
    }
#endif
    for (; i < count; ++i) {
        output[i] = input[i] > 0 ? input[i] : 0.0f;
    }
}

template <bool Relu>
inline void dense(const float* input, const float* weights, const float* bias,
                  float* output, std::size_t input_width, std::size_t output_width) noexcept {
    for (std::size_t row = 0; row < output_width; ++row) {
        const float value = dot(input, weights + row * input_width, input_width) + bias[row];
        if constexpr (Relu) {
            output[row] = value > 0 ? value : 0.0f;
        } else {
            output[row] = value;
        }
    }
}

inline void dense_residual_relu(const float* input, const float* weights, const float* bias,
                                float* hidden, std::size_t width) noexcept {
    // All rows read the separate input array, so hidden can be updated in place.
    for (std::size_t row = 0; row < width; ++row) {
        const float residual = dot(input, weights + row * width, width) + bias[row];
        const float value = hidden[row] + residual;
        hidden[row] = value > 0 ? value : 0.0f;
    }
}

inline void validate_feature_index(std::uint16_t index) {
    if (index >= feature_dimension) {
        throw std::invalid_argument("Feature index must be below 782");
    }
}

} // namespace detail

inline ActiveFeatures from_packed(const std::uint8_t* packed, std::size_t count) {
    if (packed == nullptr || count != packed_size) {
        throw std::invalid_argument("Expected 78 packed board782_v1 bytes");
    }
    ActiveFeatures result;
    for (std::size_t square = 0; square < 64; ++square) {
        const unsigned code = packed[square];
        if (code > 12) {
            throw std::invalid_argument("Invalid packed piece code");
        }
        if (code != 0) {
            result.indices[result.size++] = static_cast<std::uint16_t>((code - 1) * 64 + square);
        }
    }
    std::sort(result.indices, result.indices + result.size);
    unsigned ep_options = 0;
    for (std::size_t i = 64; i < packed_size; ++i) {
        if (packed[i] > 1) {
            throw std::invalid_argument("Packed state flags must be binary");
        }
        if (packed[i] != 0) {
            result.indices[result.size++] = static_cast<std::uint16_t>(768 + i - 64);
        }
        if (i >= 69) {
            ep_options += packed[i];
        }
    }
    if (ep_options != 1) {
        throw std::invalid_argument("Exactly one packed en-passant option must be active");
    }
    return result;
}

inline ActiveFeatures from_packed(const std::uint8_t (&packed)[packed_size]) {
    return from_packed(packed, packed_size);
}

inline ActiveFeatures from_packed(const std::array<std::uint8_t, packed_size>& packed) {
    return from_packed(packed.data(), packed.size());
}

inline ActiveFeatures from_kernel(const std::int8_t (&board)[8][8], const State& state) {
    ActiveFeatures result;
    // Kernel types 1=P, 3=N, 4=B, 5=R, 6=Q, 7=K; bit 3 means White.
    constexpr std::uint8_t type_map[8] = {0, 1, 0, 2, 3, 4, 5, 6};
    for (std::size_t row = 0; row < 8; ++row) {
        for (std::size_t column = 0; column < 8; ++column) {
            const unsigned code = static_cast<std::uint8_t>(board[row][column]) & 15u;
            const unsigned type = code & 7u;
            if (type == 0) {
                if ((code & 8u) != 0) {
                    throw std::invalid_argument("Kernel color bit is set on an empty square");
                }
                continue;
            }
            if (type == 2) {
                throw std::invalid_argument("Unsupported Kernel piece type 2");
            }
            const unsigned packed_code = type_map[type] + ((code & 8u) ? 0u : 6u);
            result.indices[result.size++] = static_cast<std::uint16_t>((packed_code - 1) * 64 + row * 8 + column);
        }
    }
    std::sort(result.indices, result.indices + result.size);
    detail::append_state(result, state);
    return result;
}

} // namespace mrbits::nn
