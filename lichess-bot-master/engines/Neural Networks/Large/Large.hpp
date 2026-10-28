#pragma once
#include "../common.hpp"

namespace mrbits::nn {

// 782 -> 1024 ReLU -> 8 residual blocks -> 256 ReLU -> 1 White-pawn score.
class Large {
public:
    static constexpr std::size_t projection_width = 1024;
    static constexpr std::size_t block_count = 8;
    static constexpr std::size_t head_width = 256;
    static constexpr std::size_t parameter_count = 17858049;

    struct Workspace {
        // Raw, pre-ReLU projection. Preserved by evaluate_accumulator().
        alignas(64) std::array<float, projection_width> accumulator{};
        alignas(64) std::array<float, projection_width> hidden{};
        alignas(64) std::array<float, projection_width> inner{};
        alignas(64) std::array<float, head_width> head{};
    };

    static Large load(const std::string& path) {
        return Large(detail::load_weights(path, {2, parameter_count, 19, projection_width, block_count, head_width}));
    }

    void reset_accumulator(Workspace& workspace) const noexcept {
        std::copy_n(weights_.data() + projection_bias_offset, projection_width, workspace.accumulator.data());
    }

    void add_feature(std::uint16_t feature, Workspace& workspace) const {
        detail::validate_feature_index(feature);
        detail::add_column(workspace.accumulator.data(), weights_.data() + feature * projection_width,
                           projection_width);
    }

    void remove_feature(std::uint16_t feature, Workspace& workspace) const {
        detail::validate_feature_index(feature);
        detail::add_column<true>(workspace.accumulator.data(), weights_.data() + feature * projection_width,
                                 projection_width);
    }

    float evaluate_accumulator(Workspace& workspace) const noexcept {
        detail::relu_copy(workspace.accumulator.data(), workspace.hidden.data(), projection_width);
        const float* cursor = weights_.data() + block_weights_offset;
        for (std::size_t block = 0; block < block_count; ++block) {
            detail::dense<true>(workspace.hidden.data(), cursor, cursor + projection_width * projection_width,
                                workspace.inner.data(), projection_width, projection_width);
            cursor += projection_width * projection_width + projection_width;
            // Exact block contract: ReLU(h + second(ReLU(first(h)))).
            // Fusing the second output with its skip add avoids a 1024-float scratch/pass.
            detail::dense_residual_relu(workspace.inner.data(), cursor, cursor + projection_width * projection_width,
                                        workspace.hidden.data(), projection_width);
            cursor += projection_width * projection_width + projection_width;
        }
        detail::dense<true>(workspace.hidden.data(), cursor, cursor + projection_width * head_width,
                            workspace.head.data(), projection_width, head_width);
        cursor += projection_width * head_width + head_width;
        return detail::dot(workspace.head.data(), cursor, head_width) + cursor[head_width];
    }

    float evaluate(const ActiveFeatures& features, Workspace& workspace) const {
        detail::validate_active_features(features);
        reset_accumulator(workspace);
        for (std::size_t i = 0; i < features.size; ++i) {
            detail::add_column(workspace.accumulator.data(),
                               weights_.data() + features.indices[i] * projection_width,
                               projection_width);
        }
        return evaluate_accumulator(workspace);
    }

    float evaluate(const std::int8_t (&board)[8][8], const State& state, Workspace& workspace) const {
        return evaluate(from_kernel(board, state), workspace);
    }

private:
    static constexpr std::size_t projection_bias_offset = feature_dimension * projection_width;
    static constexpr std::size_t block_weights_offset = projection_bias_offset + projection_width;

    explicit Large(std::vector<float>&& weights) : weights_(std::move(weights)) {}
    std::vector<float> weights_;
};

} // namespace mrbits::nn
