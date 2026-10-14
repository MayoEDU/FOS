// "Start with SteamVR": enables or disables the systemd user unit frameeyeosc-panel.service. systemctl runs on a
// worker thread so the main thread keeps answering the laser pointer.
#pragma once

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <thread>

/** The unit that "Start with SteamVR" switches (installed by contrib/install-panel.sh). */
constexpr const char* kServiceName = "frameeyeosc-panel.service";

/** The state of the unit as `systemctl --user is-enabled` reports it. */
enum class Autostart {
    Unknown,   ///< not read yet, or unreadable
    Enabled,
    Disabled,
    Missing,   ///< the unit file is not installed (not-found)
};

/** What the worker knows. */
struct AutostartState {
    Autostart autostart = Autostart::Unknown;
    bool writeFailed = false;  ///< the last enable / disable failed (shown until one succeeds)
};

/**
 * Parse the output of `systemctl --user is-enabled`.
 * @param text the output
 * @return the state
 */
Autostart parseAutostart(const std::string& text);

/**
 * Read the unit state now with `systemctl --user is-enabled` (blocks up to 2 s; the overlay uses the worker).
 * @return the state
 */
Autostart readAutostart();

/**
 * A worker thread that reads the unit state while the panel is open (right after it opens, then every 5 s)
 * and runs enable / disable when asked. It does nothing while the panel is closed.
 */
class AutostartWorker {
public:
    /** How often the state is read again while the panel is open (seconds). */
    static constexpr double kRefreshSec = 5.0;

    AutostartWorker() = default;
    ~AutostartWorker();
    AutostartWorker(const AutostartWorker&) = delete;
    AutostartWorker& operator=(const AutostartWorker&) = delete;

    /** Start the thread (it waits until there is something to do). */
    void start();

    /** Stop the thread and wait for it (and for a running systemctl, up to its timeout). */
    void stop();

    /**
     * Tell whether the panel is open. Opening triggers an immediate read.
     * @param active true while the panel is visible
     */
    void setActive(bool active);

    /**
     * Ask to enable or disable the unit (the state is read again right after).
     * @param enable true = enable
     */
    void request(bool enable);

    /**
     * Copy the current state.
     * @param state where to copy it
     * @return a number that grows whenever the state changes (to decide on redraws)
     */
    uint64_t snapshot(AutostartState& state) const;

private:
    mutable std::mutex mutex_;
    std::condition_variable wake_;
    std::thread thread_;
    std::deque<bool> queue_;
    bool active_ = false;
    bool refreshNow_ = false;
    bool stop_ = false;
    AutostartState state_;
    uint64_t version_ = 0;

    /** The thread body. */
    void run();
};
