// The eye log ("Eye log" on the Advanced tab): the panel runs `frameeyeosc --record FILE` as its child, which only
// reads the eye server's shared memory and writes every raw sample to a CSV file; nothing is sent. Stopping sends it
// SIGINT (it then writes out everything so far), and it stops by itself after kMaxSec. The child never outlives the
// panel: it is stopped when the panel exits, and gets SIGINT from the kernel if the panel dies. With the eye cameras in
// use, eyecam's drift log runs alongside it (DriftLink). Nothing here talks to OpenVR, so it can be tested on its own
// (recorder_test.cpp).
#pragma once

#include <sys/types.h>

#include <ctime>
#include <string>

namespace recorder {

/**
 * In a child between fork and exec: mark every descriptor from 3 up close-on-exec, however high, so nothing of the
 * panel's (its lock file, sockets, the GPU) reaches the program it starts. Marked rather than closed, so a pipe that
 * reports a failed exec stays open until the exec. close_range (Linux 5.11+); otherwise the descriptors listed in
 * /proc/self/fd, read with getdents64 (only async-signal-safe calls).
 */
void cloexecFrom3();

/** A recording stops by itself after this long (about 140 MB at 2.3 MB a minute). */
constexpr double kMaxSec = 60 * 60;
/** After SIGINT, the child gets this long to write out and exit before it is killed. */
constexpr double kStopWaitSec = 3.0;

/**
 * Where recordings go: $XDG_DATA_HOME/frameeyeosc/recordings, or ~/.local/share/frameeyeosc/recordings.
 * @return the folder
 */
std::string defaultDir();

/**
 * A path as shown: the home folder written as "~".
 * @param path the path
 * @return the shorter path
 */
std::string shortPath(const std::string& path);

/**
 * The local time for a file name.
 * @param when the time
 * @return "2026-09-30_01-02-03"
 */
std::string fileStamp(std::time_t when);

/**
 * The path of a new recording without its extension: dir/eyes_<stamp>, or with _2, _3... added when any of its three
 * files (.csv, .log, .config.json) is there already (a stop and a start within the same second), so nothing is
 * overwritten.
 * @param dir the folder
 * @param stamp fileStamp of now
 * @return the base path
 */
std::string uniqueBase(const std::string& dir, const std::string& stamp);

/**
 * How long a recording has run, as shown.
 * @param seconds the time
 * @return "1:23" (minutes and seconds; "60:00" at the limit)
 */
std::string elapsedText(double seconds);

/**
 * The frameeyeosc program: next to the panel's own binary, else on the PATH.
 * @return its path, or "" if there is none
 */
std::string findFrameeyeosc();

/** What the panel shows about the eye log. */
struct View {
    bool recording = false;  ///< a recording runs (not stopping)
    double elapsedSec = 0.0;  ///< how long it has run
    std::string path;        ///< the CSV file of the current or last recording
    std::string error;       ///< why the last one could not start or ended by itself (English, one line); empty if not
    bool autoStopped = false;  ///< the last one was stopped by the 60-minute limit (and none runs now)
};

/** Runs and stops the recording child. */
class Recorder {
public:
    Recorder() = default;
    ~Recorder();
    Recorder(const Recorder&) = delete;
    Recorder& operator=(const Recorder&) = delete;

    /**
     * Start recording: create the folder, copy config.json next to the CSV, and start `program --record CSV`
     * (its messages go to a .log file next to it).
     * @param program the frameeyeosc binary
     * @param dir the folder
     * @param configPath config.json, copied as eyes_….config.json (skipped if it can't be read)
     * @param now monotonic seconds
     * @return false if it could not start (see view().error)
     */
    bool start(const std::string& program, const std::string& dir, const std::string& configPath, double now);

    /**
     * Ask the recording to stop (SIGINT). It is reaped by poll.
     * @param now monotonic seconds
     */
    void stop(double now);

    /**
     * Reap the child when it has exited, notice it ending by itself, stop it at kMaxSec, and kill it if it does not
     * exit within kStopWaitSec of being asked. Call every loop.
     * @param now monotonic seconds
     * @return true if what view() shows changed
     */
    bool poll(double now);

    /** Stop and wait for the child (the panel is exiting). */
    void shutdown();

    /**
     * Add a line of the panel's own to the current or last recording's .log (the child appends after it). Marked
     * "[panel] ", so it is never taken for the child's last words.
     * @param line the line, without the newline
     */
    void note(const std::string& line);

    /** @return true while a recording runs (not stopping) */
    bool recording() const { return pid_ > 0 && !stopping_; }

    /** @return true while the child has not been reaped */
    bool busy() const { return pid_ > 0; }

    /**
     * What to show.
     * @param now monotonic seconds
     * @return the view
     */
    View view(double now) const;

private:
    pid_t pid_ = -1;
    bool stopping_ = false;     ///< SIGINT was sent
    bool autoStopped_ = false;  ///< ...because of kMaxSec
    double startedAt_ = 0.0;
    double stopAt_ = 0.0;       ///< when SIGINT was sent
    std::string csv_;
    std::string log_;
    std::string error_;

    /**
     * The child has exited: log it and, if nobody asked it to stop, say why.
     * @param status its wait status
     * @param now monotonic seconds
     */
    void finished(int status, double now);
};

/** What the panel's own lines in a recording's .log start with (Recorder::note). */
constexpr const char* kNotePrefix = "[panel] ";

/**
 * The name eyecam's drift log takes for a recording (`driftlog on <stem>`): its CSV's name without ".csv", and without
 * the _2, _3... of a second recording within the same second (eyecam takes only eyes_YYYY-MM-DD_HH-MM-SS, and adds its
 * own _2 when that file is there; the .log says which file it was).
 * @param csvPath the recording's CSV
 * @return "eyes_2026-10-12_14-03-09", or "" if it isn't named so
 */
std::string driftStem(const std::string& csvPath);

/**
 * Whether a drift log file is one the panel started for a recording (eyes_….eyecam.csv), not one started by hand
 * (drift_….csv).
 * @param path the file (status.json's driftlog.path)
 * @return true if the panel's
 */
bool panelDriftFile(const std::string& path);

/** What the drift link looks at, each loop. */
struct DriftInputs {
    bool recording = false;      ///< the eye log runs (not stopping)
    std::string stem;            ///< ...its driftStem ("" = none)
    bool eyecamRunning = false;  ///< eyecam-rec runs (its status.json is fresh)
    bool camerasInUse = false;   ///< the eye cameras are in use (eyecam::inUse)
    bool hasDriftlog = false;    ///< its status.json has "driftlog" (an older eyecam-rec doesn't: nothing is sent)
    bool driftlogOn = false;     ///< ...it is on
    std::string driftlogPath;    ///< ...its file (or the last one)
    double now = 0.0;            ///< monotonic seconds
};

/** A "driftlog on" that never showed in eyecam-rec's status (refused, or not answered) is sent again this often (s). */
constexpr double kDriftRetrySec = 30.0;

/**
 * eyecam's drift log (numbers only, one row per eye per second, in ~/eyecam/drift) alongside the eye log while the eye
 * cameras are in use, so the two can be laid side by side: "driftlog on <stem>" once a recording runs (also when
 * eyecam-rec comes up during it), "driftlog off" once it ends, however it ends (stopped, failed, at its limit, the panel
 * exiting). A drift log started by hand (drift_….csv) is left alone: no "on" over it, no "off" for it. The first time
 * eyecam-rec is seen with no recording running, a panel's drift log still on (left by a panel that crashed during a
 * recording) is turned off. Once eyecam-rec showed the recording's drift log on, the log going off (or to another file
 * that isn't one started by hand) during the recording, as when eyecam-rec restarts, sends "driftlog on" again at once;
 * one that never showed is asked for again every kDriftRetrySec. One command at a time: it waits while another is out.
 */
class DriftLink {
public:
    /**
     * The command to send now, if any.
     * @param in the eye log and eyecam-rec now
     * @param busy a command is still out
     * @param command where to write it
     * @return true if there is one (it counts as sent)
     */
    bool next(const DriftInputs& in, bool busy, std::string& command);

    /** @return the stem "driftlog on" went out for (no "off" since), "" if none */
    const std::string& on() const { return on_; }

private:
    std::string on_;
    bool checked_ = false;  ///< eyecam-rec was seen with no recording (or the panel turned its log on)
    bool shown_ = false;    ///< eyecam-rec's status showed on_'s drift log on since "driftlog on" last went out
    double sentAt_ = 0.0;   ///< ...which was then
};

}  // namespace recorder
