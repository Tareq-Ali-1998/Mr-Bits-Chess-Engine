#include "../Kernel Workers.hpp"
#include <iostream>

int main(int argc,char** argv) {
    if(argc!=3) return 2;
    KernelWorkerPool pool;
    pool.configure(argv[1],argv[2],1);
    pool.startInTheBackground();
    std::string error;
    if(!pool.waitUntilStarted(error)) { std::cerr<<error<<'\n'; return 1; }
    auto slots=pool.getUsableWorkerSlots();
    if(slots.size()!=1) return 1;
    const auto id=pool.getNewRequestId();
    // Invalid request returns an error without searching or constructing a game.
    const auto request=nlohmann::json{{"type","metadata-probe"},{"id",id}}.dump();
    auto answers=pool.askAllWorkers(slots,{request},{id},2000);
    pool.shutdown();
    if(answers.size()!=1 || answers[0].status!="answered" ||
       !answers[0].message.contains("engineVersion") ||
       answers[0].message["engineVersion"].get<std::string>().find("kernel-v2-")!=0) {
        std::cerr<<"Actual hello build metadata was not retained\n"; return 1;
    }
    std::cout<<"PASS: actual worker hello build survives the pool response: "
             <<answers[0].message["engineVersion"].get<std::string>()<<'\n';
}
