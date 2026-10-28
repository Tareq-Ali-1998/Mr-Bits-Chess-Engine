#pragma once
#include "../common.hpp"

namespace mrbits::nn {

// Fixed trained architecture: 782 -> 256 ReLU -> 64 ReLU -> 1 White-pawn score.
class Small {
public:
    static constexpr std::size_t projection_width = 256;
    static constexpr std::size_t head_width = 64;
    static constexpr std::size_t parameter_count = 216961;

    struct Workspace {
        // Raw, pre-ReLU projection. Preserved by evaluate_accumulator().
        alignas(64) std::array<float, projection_width> accumulator{};
        alignas(64) std::array<float, projection_width> projection{};
        alignas(64) std::array<float, head_width> hidden{};
    };

    static Small load(const std::string& path) {
        return Small(detail::load_weights(path, {1, parameter_count, 3, projection_width, 0, head_width}));
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
        detail::relu_copy(workspace.accumulator.data(), workspace.projection.data(), projection_width);
        const float* head_weights = weights_.data() + head_weights_offset;
        detail::dense<true>(workspace.projection.data(), head_weights,
                            head_weights + projection_width * head_width,
                            workspace.hidden.data(), projection_width, head_width);
        const float* output_weights = weights_.data() + output_weights_offset;
        return detail::dot(workspace.hidden.data(), output_weights, head_width) + output_weights[head_width];
    }

    float evaluate(const ActiveFeatures& features, Workspace& workspace) const {
        detail::validate_active_features(features);
        reset_accumulator(workspace);
        for (std::size_t i = 0; i < features.size; ++i) {
            // Already validated, so the hot projection loop has no redundant checks.
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
    static constexpr std::size_t head_weights_offset = projection_bias_offset + projection_width;
    static constexpr std::size_t output_weights_offset = head_weights_offset + projection_width * head_width + head_width;

    explicit Small(std::vector<float>&& weights) : weights_(std::move(weights)) {}
    // No public mutation and no lazy state: a const model can be shared by threads.
    std::vector<float> weights_;
};

} // namespace mrbits::nn
