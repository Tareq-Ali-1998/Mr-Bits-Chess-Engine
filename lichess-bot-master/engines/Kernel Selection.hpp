#pragma once
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "json.hpp"

namespace mrbits::kernel_selection {

struct Selection {
    std::string version;
    std::filesystem::path executable;
};

inline bool VersionFolderName(const std::string& version) {
    return version.size() >= 2 && version[0] == 'v' && version[1] >= '1' && version[1] <= '9' &&
        std::all_of(version.begin() + 2, version.end(), [](char ch) { return ch >= '0' && ch <= '9'; });
}

inline Selection Read(const std::filesystem::path& engines_directory) {
    const auto config = engines_directory / "kernel-selection.json";
    std::string version = "original";
    std::error_code error;
    const bool present = std::filesystem::exists(config, error);
    if (error) throw std::runtime_error("Cannot inspect kernel-selection.json: " + error.message());
    if (present) {
        std::ifstream stream(config);
        if (!stream) throw std::runtime_error("Cannot read kernel-selection.json");
        const auto document = nlohmann::json::parse(stream);
        if (!document.is_object() || !document.contains("version") || !document["version"].is_string()) {
            throw std::runtime_error("kernel-selection.json requires a string 'version'");
        }
        version = document["version"].get<std::string>();
    }
    std::filesystem::path executable;
    if (version == "original") executable = engines_directory / "Kernel.exe";
    else if (VersionFolderName(version)) {
        executable = engines_directory / "Kernels" / version / ("Kernel-" + version + ".exe");
    } else {
        throw std::runtime_error("Unknown Kernel version '" + version + "'; choose original or a folder named v1, v2, ...");
    }
    if (!std::filesystem::is_regular_file(executable)) {
        throw std::runtime_error("Selected Kernel executable is missing: " + executable.string() +
                                 "; build that version before starting the application");
    }
    return {version, executable};
}

// Record the configured variant, UCI build, and available actual worker builds.
// Stockfish-only paths still carry the configured variant, not proof of NN use.
inline std::string TelemetryLabel(const Selection& selection, const std::string& uci_build,
                                  const nlohmann::json& move_record) {
    std::string label = "uci=" + uci_build + ";kernel=" + selection.version;
    std::vector<std::string> builds;
    auto workers = move_record.find("kernelWorkers");
    if (workers != move_record.end() && workers->is_array()) {
        for (const auto& worker : *workers) {
            if (!worker.is_object()) continue;
            auto answer = worker.find("answer");
            if (answer == worker.end() || !answer->is_object()) continue;
            auto build = answer->find("engineVersion");
            if (build != answer->end() && build->is_string()) builds.push_back(build->get<std::string>());
        }
    }
    std::sort(builds.begin(), builds.end());
    builds.erase(std::unique(builds.begin(), builds.end()), builds.end());
    for (const auto& build : builds) label += ";worker=" + build;
    return label;
}

} // namespace mrbits::kernel_selection
