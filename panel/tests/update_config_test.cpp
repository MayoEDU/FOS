// Exercise the production fork configuration through the vendored updater, without GitHub or systemd.
#include "update_config.h"

#include <unistd.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

namespace {

int failures = 0;

void check(bool ok, const char* what, int line) {
    if (ok) return;
    ++failures;
    std::fprintf(stderr, "FAILED line %d: %s\n", line, what);
}

#define CHECK(condition) check((condition), #condition, __LINE__)

std::vector<std::string> lines(const std::string& path) {
    std::ifstream in(path);
    std::vector<std::string> result;
    for (std::string line; std::getline(in, line);) result.push_back(line);
    return result;
}

bool waitFor(frame_updater::UpdateChecker& updater, frame_updater::UpdateState expected) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (std::chrono::steady_clock::now() < deadline) {
        updater.tick(false);
        if (updater.status().state == expected && !updater.status().checking) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    return false;
}

}  // namespace

int main() {
    char pattern[] = "/tmp/fos-update-test-XXXXXX";
    const char* dir = ::mkdtemp(pattern);
    if (dir == nullptr) return 1;
    const std::string scratch(dir);
    const char* oldCache = std::getenv("XDG_CACHE_HOME");
    const bool hadCache = oldCache != nullptr;
    const std::string savedCache = oldCache != nullptr ? oldCache : "";
    ::setenv("XDG_CACHE_HOME", scratch.c_str(), 1);

    const std::string trace = scratch + "/args";
    const std::string script = scratch + "/updater.sh";
    {
        std::ofstream out(script);
        out << "#!/bin/sh\n"
            << "printf '%s\\n' \"$@\" >>'" << trace << "'\n"
            << "for arg do action=$arg; done\n"
            << "if [ \"$action\" = check ]; then\n"
            << "printf '%s\\n' '{\"status\":\"update-available\",\"latest\":\"0.8.1\",\"installable\":true}'\n"
            << "else\n"
            << "printf '%s\\n' '{\"state\":\"failed\",\"error\":\"test-only\",\"message\":\"no installer ran\"}'\n"
            << "fi\n";
    }
    {
        auto config = fos::updaterConfig(script, "0.8.0");
        CHECK(config.app == "frameeyeosc");
        CHECK(config.repo == "MayoEDU/FOS");
        CHECK(std::string(fos::kReleasePage) == "https://github.com/MayoEDU/FOS/releases/latest");
        CHECK(fos::canInstallCompanion("perf"));
        CHECK(!fos::canInstallCompanion(""));
        CHECK(!fos::canInstallCompanion("eye"));
        CHECK(!fos::canInstallCompanion("frameeyeosc"));
        CHECK(frame_updater::compareVersions(config.currentVersion, "0.7.8") > 0);
        frame_updater::UpdateChecker updater(config);
        updater.checkNow();
        CHECK(waitFor(updater, frame_updater::UpdateState::Available));
        CHECK(updater.install());
        CHECK(waitFor(updater, frame_updater::UpdateState::InstallFailed));
        const std::vector<std::string> base = {
            "--app", "frameeyeosc", "--repo", "MayoEDU/FOS", "--current", "0.8.0",
            "--asset", "frameeyeosc-{version}-steamframe-aarch64.tar.gz"};
        auto expected = base;
        expected.insert(expected.end(), {"--force", "check"});
        expected.insert(expected.end(), base.begin(), base.end());
        expected.insert(expected.end(), {"--install-arg", "--with-panel", "--detach", "install"});
        CHECK(lines(trace) == expected);
    }
    if (hadCache) ::setenv("XDG_CACHE_HOME", savedCache.c_str(), 1);
    else ::unsetenv("XDG_CACHE_HOME");
    std::filesystem::remove_all(scratch);
    if (failures == 0) std::puts("FOS update routing passed (check and install, no network).");
    return failures == 0 ? 0 : 1;
}
