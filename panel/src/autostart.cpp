// The autostart worker.
#include "autostart.h"

#include "command.h"

#include <signal.h>

#include <chrono>
#include <cstdio>
#include <vector>

namespace {

/**
 * Enable or disable the unit (never starts or stops it, so the running panel is not touched).
 * @param enable true = enable
 * @return true on success
 */
bool writeAutostart(bool enable) {
    const std::vector<std::string> argv = {"systemctl", "--user", enable ? "enable" : "disable", kServiceName};
    const CommandResult result = runCommand(argv, 5000);
    std::fprintf(stderr, "[autostart] %s\n", describeCommand(argv, result).c_str());
    return result.ok();
}

}  // namespace

Autostart parseAutostart(const std::string& text) {
    const size_t end = text.find_first_of(" \t\r\n");
    const std::string first = text.substr(0, end);
    if (first == "not-found") return Autostart::Missing;
    if (first == "disabled") return Autostart::Disabled;
    if (first.rfind("enabled", 0) == 0) return Autostart::Enabled;  // enabled / enabled-runtime
    return Autostart::Unknown;  // masked, static, ... (not used by this unit)
}

Autostart readAutostart() {
    const std::vector<std::string> argv = {"systemctl", "--user", "is-enabled", kServiceName};
    const CommandResult result = runCommand(argv);
    // is-enabled exits with 1 for disabled / not-found, so read the text whatever the exit code
    Autostart state = parseAutostart(result.out);
    if (state == Autostart::Unknown) state = parseAutostart(result.err);
    if (state == Autostart::Unknown) std::fprintf(stderr, "[autostart] %s\n", describeCommand(argv, result).c_str());
    return state;
}

AutostartWorker::~AutostartWorker() {
    stop();
}

void AutostartWorker::start() {
    if (thread_.joinable()) return;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        stop_ = false;
    }
    thread_ = std::thread([this] { run(); });
}

void AutostartWorker::stop() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        stop_ = true;
    }
    wake_.notify_all();
    if (thread_.joinable()) thread_.join();
}

void AutostartWorker::setActive(bool active) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (active == active_) return;
        active_ = active;
        if (active) refreshNow_ = true;
    }
    wake_.notify_all();
}

void AutostartWorker::request(bool enable) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        queue_.push_back(enable);
    }
    wake_.notify_all();
}

uint64_t AutostartWorker::snapshot(AutostartState& state) const {
    std::lock_guard<std::mutex> lock(mutex_);
    state = state_;
    return version_;
}

void AutostartWorker::run() {
    // SIGTERM, SIGINT and SIGUSR1 are handled on the main thread (command.cpp clears the mask for children)
    sigset_t blocked;
    sigemptyset(&blocked);
    sigaddset(&blocked, SIGTERM);
    sigaddset(&blocked, SIGINT);
    sigaddset(&blocked, SIGUSR1);
    pthread_sigmask(SIG_BLOCK, &blocked, nullptr);

    using Clock = std::chrono::steady_clock;
    const auto refreshInterval =
        std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(kRefreshSec));
    /**
     * Store a new state (call with the mutex held); the version only moves when something visible changed.
     */
    const auto store = [this](const AutostartState& fresh) {
        if (fresh.autostart != state_.autostart || fresh.writeFailed != state_.writeFailed) ++version_;
        state_ = fresh;
    };

    Clock::time_point nextRefresh = Clock::now();
    std::unique_lock<std::mutex> lock(mutex_);
    while (!stop_) {
        if (!queue_.empty()) {
            const bool enable = queue_.front();
            queue_.pop_front();
            lock.unlock();
            const bool ok = writeAutostart(enable);
            AutostartState fresh;
            fresh.autostart = readAutostart();
            fresh.writeFailed = !ok;
            lock.lock();
            store(fresh);
            nextRefresh = Clock::now() + refreshInterval;
            continue;
        }
        if (refreshNow_ || (active_ && Clock::now() >= nextRefresh)) {
            refreshNow_ = false;
            lock.unlock();
            AutostartState fresh;
            fresh.autostart = readAutostart();
            lock.lock();
            fresh.writeFailed = state_.writeFailed;
            store(fresh);
            nextRefresh = Clock::now() + refreshInterval;
            continue;
        }
        // While the panel is closed, wait until asked
        if (active_) {
            wake_.wait_until(lock, nextRefresh);
        } else {
            wake_.wait(lock);
        }
    }
}
