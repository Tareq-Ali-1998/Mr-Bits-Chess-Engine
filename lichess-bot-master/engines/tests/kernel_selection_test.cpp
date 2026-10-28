#include "../Kernel Selection.hpp"
#include <iostream>

using namespace mrbits::kernel_selection;
namespace fs = std::filesystem;

void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
void config(const fs::path& root, const std::string& text) {
    std::ofstream(root / "kernel-selection.json") << text;
}
template<class F> void rejected(F action) {
    bool threw = false;
    try { action(); } catch (const std::exception&) { threw = true; }
    require(threw, "Invalid selection was accepted");
}
int main(int argc, char** argv) {
    try {
        require(argc==2, "Pass a disposable test directory");
        const fs::path root=argv[1]; fs::create_directories(root);
        std::ofstream(root/"Kernel.exe") << "test placeholder; never executed";
        require(Read(root).version=="original", "Missing config did not default to original");
        for(const std::string version : {"v1","v2","v3","v4","v12"}) {
            const auto folder=root/"Kernels"/version; fs::create_directories(folder);
            const auto executable=folder/("Kernel-"+version+".exe");
            std::ofstream(executable) << "test placeholder; never executed";
            config(root,"{\"version\":\""+version+"\"}");
            const auto selected=Read(root);
            require(selected.version==version && selected.executable==executable,"Wrong variant path");
        }
        for(const auto text : {"{", "[]", "{}", "{\"version\":2}",
                              "{\"version\":\"v5\"}", "{\"version\":\"v0\"}",
                              "{\"version\":\"v01\"}", "{\"version\":\"../../escape\"}"}) {
            config(root,text); rejected([&]{Read(root);});
        }
        config(root,"{\"version\":\"v3\"}");
        fs::remove(root/"Kernels/v3/Kernel-v3.exe"); rejected([&]{Read(root);});
        config(root,"{\"version\":\"original\"}");
        const auto selected=Read(root);
        const auto label=TelemetryLabel(selected,"stamp",nlohmann::json{
            {"kernelWorkers",nlohmann::json::array({
                {{"answer",{{"engineVersion","kernel-v3-A"}}}},
                {{"answer",{{"engineVersion","kernel-v3-A"}}}},
                {{"answer",{{"engineVersion","kernel-v2-B"}}}},
                {{"status","timeout"}}
            })}});
        require(label=="uci=stamp;kernel=original;worker=kernel-v2-B;worker=kernel-v3-A", "Telemetry label incorrect");
        require(TelemetryLabel(selected,"stamp",nlohmann::json::object())=="uci=stamp;kernel=original","Empty-worker label incorrect");
        std::cout<<"PASS: selection defaults, version folders, invalid config, missing executable and version telemetry\n";
    } catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
}
