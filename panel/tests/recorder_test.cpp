// Tests for the eye log (recorder.cpp): names, starting, stopping and reaping a child that stands in for
// `frameeyeosc --record`, the panel's own lines in its .log, and the commands that keep eyecam's drift log alongside it. Built with the panel as recorder-test; exits non-zero on failure. Given the path of a real
// frameeyeosc, it also records a few seconds with it (reads the eye server read-only) and checks the CSV:
//   panel/build/recorder-test target/release/frameeyeosc
// Files go to a folder made under the current one, removed at the end.
#include "recorder.h"

#include <signal.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <thread>

namespace {

int gFailures = 0;

/**
 * Record a failed check.
 * @param ok the check
 * @param what what was checked
 * @param line where
 */
void check(bool ok, const char* what, int line) {
    if (ok) return;
    ++gFailures;
    std::fprintf(stderr, "FAILED line %d: %s\n", line, what);
}

#define CHECK(condition) check((condition), #condition, __LINE__)

using recorder::Recorder;

/**
 * Monotonic seconds, as the panel's loop passes them.
 * @return seconds
 */
double now() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

/**
 * Write an executable shell script.
 * @param path where
 * @param body the script after the #! line
 */
void script(const std::string& path, const std::string& body) {
    std::ofstream(path) << "#!/bin/sh\n" << body;
    ::chmod(path.c_str(), 0755);
}

/**
 * Poll until the child is reaped, at most a few seconds.
 * @param r the recorder
 * @param offset added to the time passed (to get past the recorder's own limits)
 * @return true if it was reaped
 */
bool waitReaped(Recorder& r, double offset = 0.0) {
    const double end = now() + 5.0;
    while (r.busy() && now() < end) {
        r.poll(now() + offset);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    return !r.busy();
}

/**
 * Whether a file exists.
 * @param path the file
 * @return true if it does
 */
bool exists(const std::string& path) {
    struct stat info {};
    return ::stat(path.c_str(), &info) == 0;
}

/**
 * A file's text.
 * @param path the file
 * @return its contents
 */
std::string read(const std::string& path) {
    std::ifstream file(path);
    return std::string(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
}

void testNames() {
    ::setenv("TZ", "UTC", 1);
    ::tzset();
    CHECK(recorder::fileStamp(0) == "1970-01-01_00-00-00");
    CHECK(recorder::fileStamp(1790000000) == "2026-09-21_14-13-20");
    CHECK(recorder::elapsedText(0) == "0:00" && recorder::elapsedText(83.9) == "1:23");
    CHECK(recorder::elapsedText(recorder::kMaxSec) == "60:00");
    ::setenv("HOME", "/home/steamos", 1);
    CHECK(recorder::shortPath("/home/steamos/.local/share/frameeyeosc/recordings") ==
          "~/.local/share/frameeyeosc/recordings");
    CHECK(recorder::shortPath("/tmp/x") == "/tmp/x");
    ::unsetenv("XDG_DATA_HOME");
    CHECK(recorder::defaultDir() == "/home/steamos/.local/share/frameeyeosc/recordings");
    ::setenv("XDG_DATA_HOME", "/data", 1);
    CHECK(recorder::defaultDir() == "/data/frameeyeosc/recordings");
}

void testUniqueNames(const std::string& dir) {
    // A stop and a start within the same second: never over an earlier recording's files
    const std::string names = dir + "/names";
    ::mkdir(names.c_str(), 0755);
    const std::string stamp = "2026-10-01_12-00-00";
    CHECK(recorder::uniqueBase(names, stamp) == names + "/eyes_" + stamp);
    std::ofstream(names + "/eyes_" + stamp + ".csv") << "x";
    CHECK(recorder::uniqueBase(names, stamp) == names + "/eyes_" + stamp + "_2");
    // Any of the three files counts
    std::ofstream(names + "/eyes_" + stamp + "_2.config.json") << "{}";
    CHECK(recorder::uniqueBase(names, stamp) == names + "/eyes_" + stamp + "_3");
}

void testChild(const std::string& dir) {
    const std::string config = dir + "/config.json";
    std::ofstream(config) << "{\"gaze_roll_deg\": 2.0}\n";
    // Stops on SIGINT like frameeyeosc --record, saying how many samples it wrote
    const std::string good = dir + "/good.sh";
    script(good, "trap 'echo \"Stopped: 3 samples in $2\" >&2; exit 0' INT\n"
                 "echo sample_time > \"$2\"\necho \"Recording to $2\" >&2\n"
                 "while :; do sleep 0.05; done\n");
    {
        Recorder r;
        const double start = now();
        CHECK(r.start(good, dir + "/out", config, start));
        CHECK(r.recording() && r.busy());
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        CHECK(!r.poll(now()) && r.recording());
        const recorder::View v = r.view(start + 83.5);
        CHECK(v.recording && v.elapsedSec > 83 && v.error.empty());
        // eyes_<local time>.csv, the settings copied next to it, and the child's messages in a .log
        const std::string base = v.path.substr(0, v.path.size() - 4);
        CHECK(v.path.rfind(dir + "/out/eyes_", 0) == 0 && v.path.size() == dir.size() + 33);
        CHECK(read(base + ".config.json") == "{\"gaze_roll_deg\": 2.0}\n");
        // A second start while one runs is refused
        CHECK(!r.start(good, dir + "/out", config, now()));
        r.stop(now());
        CHECK(!r.recording() && r.busy());
        CHECK(waitReaped(r));
        CHECK(r.view(now()).error.empty() && !r.view(now()).recording);
        CHECK(read(v.path) == "sample_time\n");
        CHECK(read(base + ".log").find("Stopped: 3 samples") != std::string::npos);
    }
    {
        // The panel's own line in the .log (the drift log's file), kept between the child's lines before and after it
        Recorder r;
        CHECK(r.start(good, dir + "/out8", config, now()));
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        r.note("eyecam drift log: /home/steamos/eyecam/drift/eyes_x.eyecam.csv");
        r.stop(now());
        CHECK(waitReaped(r));
        const std::string log = read(r.view(now()).path.substr(0, r.view(now()).path.size() - 4) + ".log");
        const size_t recording = log.find("Recording to ");
        const size_t note = log.find("[panel] eyecam drift log: /home/steamos/eyecam/drift/eyes_x.eyecam.csv\n");
        const size_t stopped = log.find("Stopped: 3 samples");
        CHECK(recording != std::string::npos && note != std::string::npos && stopped != std::string::npos);
        CHECK(recording < note && note < stopped);
    }
    {
        // Ends by itself (no eye server): its last words are the error
        const std::string failing = dir + "/failing.sh";
        script(failing, "echo \"Recording to $2\" >&2\necho 'Error: the eye server is not running' >&2\nexit 1\n");
        Recorder r;
        CHECK(r.start(failing, dir + "/out2", config, now()));
        CHECK(waitReaped(r));
        CHECK(r.view(now()).error == "the eye server is not running");
        // ...the panel's own line after them is not
        const std::string quiet = dir + "/quiet.sh";
        script(quiet, "echo 'Error: the eye server is not running' >&2\nsleep 0.3\nexit 1\n");
        CHECK(r.start(quiet, dir + "/out2", config, now()));
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        r.note("eyecam drift log: /home/steamos/eyecam/drift/eyes_x.eyecam.csv");
        CHECK(waitReaped(r));
        CHECK(r.view(now()).error == "the eye server is not running");
        // Silent: the exit code
        const std::string silent = dir + "/silent.sh";
        script(silent, "exit 3\n");
        CHECK(r.start(silent, dir + "/out2", config, now() + 1));
        CHECK(waitReaped(r));
        CHECK(r.view(now()).error == "frameeyeosc stopped (exit code 3)");
    }
    {
        // Can't be run at all, or not found
        Recorder r;
        CHECK(!r.start(dir + "/missing", dir + "/out3", config, now()) && !r.busy());
        CHECK(r.view(now()).error.find("can't run " + dir + "/missing: ") == 0);
        CHECK(!r.start("", dir + "/out3", config, now()));
        CHECK(r.view(now()).error.find("not found") != std::string::npos);
    }
    {
        // Stops by itself after an hour, and a child that ignores SIGINT is killed after kStopWaitSec
        const std::string stubborn = dir + "/stubborn.sh";
        script(stubborn, "trap '' INT\nexec sleep 30\n");
        Recorder r;
        const double start = now();
        CHECK(r.start(stubborn, dir + "/out4", config, start));
        CHECK(r.poll(start + recorder::kMaxSec + 0.01) && !r.recording() && r.busy());
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        CHECK(r.busy());
        CHECK(waitReaped(r, recorder::kMaxSec + recorder::kStopWaitSec + 1));
        CHECK(r.view(now()).error.empty());
        // The row then says it stopped at the limit, until the next start
        CHECK(r.view(now()).autoStopped);
        CHECK(r.start(good, dir + "/out4", config, now()) && !r.view(now()).autoStopped);
        r.stop(now());
        CHECK(waitReaped(r) && !r.view(now()).autoStopped);
    }
    {
        // Two recordings started within the same second keep their own files
        Recorder r;
        CHECK(r.start(good, dir + "/out6", config, now()));
        const std::string first = r.view(now()).path;
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        r.stop(now());
        CHECK(waitReaped(r));
        CHECK(r.start(good, dir + "/out6", config, now()));
        const std::string second = r.view(now()).path;
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        r.stop(now());
        CHECK(waitReaped(r));
        CHECK(first != second && read(first) == "sample_time\n" && read(second) == "sample_time\n");
    }
    {
        // A descriptor of the panel's above 1024 does not reach the recorder
        const std::string leak = dir + "/leak";
        const std::string peek = dir + "/peek.sh";
        script(peek, "if [ -e /proc/$$/fd/2000 ]; then echo leaked > " + leak + "; else echo closed > " + leak +
                         "; fi\ntrap 'exit 0' INT\nwhile :; do sleep 0.05; done\n");
        // Past the usual soft limit of 1024 (the hard limit is far higher; SteamVR's libraries may raise it)
        rlimit limit {};
        ::getrlimit(RLIMIT_NOFILE, &limit);
        if (limit.rlim_cur < 4096 && limit.rlim_max >= 4096) {
            limit.rlim_cur = 4096;
            ::setrlimit(RLIMIT_NOFILE, &limit);
        }
        const int high = ::dup2(1, 2000);
        CHECK(high == 2000);
        Recorder r;
        CHECK(r.start(peek, dir + "/out7", config, now()));
        for (int i = 0; i < 100 && !exists(leak); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(10));
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        CHECK(read(leak) == "closed\n");
        r.stop(now());
        CHECK(waitReaped(r));
        ::close(2000);
    }
    {
        // Exiting the panel stops and reaps it: nothing is left running
        const std::string pidFile = dir + "/pid";
        const std::string waiting = dir + "/waiting.sh";
        script(waiting, "echo $$ > " + pidFile + "\ntrap 'exit 0' INT\nwhile :; do sleep 0.05; done\n");
        pid_t child = 0;
        {
            Recorder r;
            CHECK(r.start(waiting, dir + "/out5", config, now()));
            for (int i = 0; i < 100 && !exists(pidFile); ++i) std::this_thread::sleep_for(std::chrono::milliseconds(10));
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            child = std::atoi(read(pidFile).c_str());
        }
        CHECK(child > 0 && ::kill(child, 0) != 0);
    }
}

void testDriftNames() {
    CHECK(recorder::driftStem("/x/recordings/eyes_2026-10-12_14-03-09.csv") == "eyes_2026-10-12_14-03-09");
    // A second recording in the same second: eyecam adds its own _2
    CHECK(recorder::driftStem("/x/eyes_2026-10-12_14-03-09_2.csv") == "eyes_2026-10-12_14-03-09");
    for (const char* odd : {"", "/x/eyes_2026-10-12_14-03-09.log", "/x/eyes_2026-10-12_14-03.csv",
                            "/x/eyes_2026-10-12_14-03-09_.csv", "/x/eyes_2026-10-12_14-03-09_a.csv",
                            "/x/drift_2026-10-12_14-03-09.csv", "/x/eyes_2026-10-12_14-03-09x.csv"}) {
        CHECK(recorder::driftStem(odd).empty());
    }
    CHECK(recorder::panelDriftFile("/home/steamos/eyecam/drift/eyes_2026-10-12_14-03-09.eyecam.csv"));
    CHECK(recorder::panelDriftFile("/home/steamos/eyecam/drift/eyes_2026-10-12_14-03-09_2.eyecam.csv"));
    CHECK(!recorder::panelDriftFile("/home/steamos/eyecam/drift/drift_2026-10-12_14-03-09.csv"));
    CHECK(!recorder::panelDriftFile("/home/steamos/eyecam/drift/eyes_2026-10-12_14-03-09.csv"));
    CHECK(!recorder::panelDriftFile(""));
}

/**
 * The commands a drift link sends over a sequence of loops.
 */
struct DriftRun {
    recorder::DriftLink link;
    recorder::DriftInputs in;

    /**
     * One loop.
     * @param busy a command is still out
     * @return the command sent, "" for none
     */
    std::string step(bool busy = false) {
        std::string command;
        return link.next(in, busy, command) ? command : std::string();
    }
};

void testDriftLink() {
    const std::string stem = "eyes_2026-10-12_14-03-09";
    const std::string ours = "/home/steamos/eyecam/drift/" + stem + ".eyecam.csv";
    const std::string byHand = "/home/steamos/eyecam/drift/drift_2026-10-12_13-00-00.csv";
    // eyecam-rec running with the cameras in use and a drift log it can keep
    const auto ready = [](recorder::DriftInputs& in) {
        in.eyecamRunning = in.camerasInUse = in.hasDriftlog = true;
    };
    {
        // On once the recording starts, once only; off when it ends (stopped, failed or at its limit: all the same)
        DriftRun d;
        ready(d.in);
        CHECK(d.step().empty());
        d.in.recording = true;
        d.in.stem = stem;
        CHECK(d.step(true).empty());  // (waits while another command is out)
        CHECK(d.step() == "driftlog on " + stem && d.link.on() == stem);
        d.in.driftlogOn = true;
        d.in.driftlogPath = ours;
        CHECK(d.step().empty() && d.step().empty());
        d.in.recording = false;
        CHECK(d.step(true).empty());
        CHECK(d.step() == "driftlog off" && d.link.on().empty());
        d.in.driftlogOn = false;
        CHECK(d.step().empty());
        // The next recording: on again with its own name
        d.in.recording = true;
        d.in.stem = "eyes_2026-10-12_15-00-00";
        CHECK(d.step() == "driftlog on eyes_2026-10-12_15-00-00");
        // The panel exiting: the same, with no recording
        d.in.recording = false;
        CHECK(d.step() == "driftlog off" && d.step().empty());
    }
    {
        // Another recording right after (a new name before the end was seen): on with the new one (eyecam closes the old)
        DriftRun d;
        ready(d.in);
        d.in.recording = true;
        d.in.stem = stem;
        CHECK(d.step() == "driftlog on " + stem);
        d.in.stem = "eyes_2026-10-12_15-00-00";
        CHECK(d.step() == "driftlog on eyes_2026-10-12_15-00-00");
    }
    {
        // eyecam-rec coming up during a recording: on then; the cameras going out of use later: kept to the end
        DriftRun d;
        d.in.recording = true;
        d.in.stem = stem;
        d.in.hasDriftlog = true;
        CHECK(d.step().empty());
        d.in.eyecamRunning = true;
        CHECK(d.step().empty());  // (set up and switched on: not yet)
        d.in.camerasInUse = true;
        CHECK(d.step() == "driftlog on " + stem);
        d.in.camerasInUse = d.in.eyecamRunning = false;
        CHECK(d.step().empty());
        d.in.recording = false;
        CHECK(d.step() == "driftlog off");
    }
    {
        // An older eyecam-rec (no "driftlog" in its status): nothing, then or at the end
        DriftRun d;
        ready(d.in);
        d.in.hasDriftlog = false;
        d.in.recording = true;
        d.in.stem = stem;
        CHECK(d.step().empty());
        d.in.recording = false;
        CHECK(d.step().empty() && d.step().empty());
        // ...and without the cameras in use, nothing either
        DriftRun e;
        ready(e.in);
        e.in.camerasInUse = false;
        e.in.recording = true;
        e.in.stem = stem;
        CHECK(e.step().empty());
        e.in.recording = false;
        CHECK(e.step().empty());
    }
    {
        // A drift log started by hand: no "on" over it, no "off" for it, at start or at the end
        DriftRun d;
        ready(d.in);
        d.in.driftlogOn = true;
        d.in.driftlogPath = byHand;
        CHECK(d.step().empty());
        d.in.recording = true;
        d.in.stem = stem;
        CHECK(d.step().empty());
        d.in.recording = false;
        CHECK(d.step().empty());
        // Started by hand while the panel's ran (it closed the panel's): the end leaves it on
        DriftRun e;
        ready(e.in);
        e.in.recording = true;
        e.in.stem = stem;
        CHECK(e.step() == "driftlog on " + stem);
        e.in.driftlogOn = true;
        e.in.driftlogPath = byHand;
        e.in.recording = false;
        CHECK(e.step().empty() && e.link.on().empty());
    }
    {
        // At start, one left on by a panel that crashed during a recording: off, once
        DriftRun d;
        d.in.hasDriftlog = true;
        d.in.driftlogOn = true;
        d.in.driftlogPath = ours;
        CHECK(d.step().empty());  // (eyecam-rec not seen running yet)
        d.in.eyecamRunning = true;
        CHECK(d.step() == "driftlog off");
        CHECK(d.step().empty());  // (status.json still says on until it is next written)
        // With the cameras switched off it is still turned off (it is the panel's, and nothing records)
        DriftRun e;
        e.in = d.in;
        CHECK(e.step() == "driftlog off");
        // ...but not one started by hand, nor when it is off
        DriftRun f;
        f.in = d.in;
        f.in.driftlogPath = byHand;
        CHECK(f.step().empty());
        DriftRun g;
        g.in = d.in;
        g.in.driftlogOn = false;
        CHECK(g.step().empty());
        g.in.driftlogOn = true;
        CHECK(g.step().empty());  // (only at start)
        // A recording running when eyecam-rec is first seen: its own "on" replaces the stale one
        DriftRun h;
        h.in = d.in;
        h.in.camerasInUse = true;
        h.in.recording = true;
        h.in.stem = "eyes_2026-10-12_15-00-00";
        CHECK(h.step() == "driftlog on eyes_2026-10-12_15-00-00");
    }
    {
        // eyecam-rec restarting during a recording: once it had shown the recording's drift log on, the log off (or
        // another panel file) sends "driftlog on" again at once
        DriftRun d;
        ready(d.in);
        d.in.recording = true;
        d.in.stem = stem;
        d.in.now = 100.0;
        CHECK(d.step() == "driftlog on " + stem);
        CHECK(d.step().empty());  // (status.json not written since: not again)
        d.in.driftlogOn = true;
        d.in.driftlogPath = ours;
        d.in.now = 101.0;
        CHECK(d.step().empty() && d.step().empty());
        d.in.eyecamRunning = false;
        CHECK(d.step().empty());  // (gone: nothing to send to)
        d.in.eyecamRunning = true;
        d.in.driftlogOn = false;
        d.in.driftlogPath.clear();
        CHECK(d.step() == "driftlog on " + stem && d.link.on() == stem);
        CHECK(d.step().empty());
        // It shows <stem>_2 (the first file was there): this recording's
        d.in.driftlogOn = true;
        d.in.driftlogPath = "/home/steamos/eyecam/drift/" + stem + "_2.eyecam.csv";
        CHECK(d.step().empty());
        // Another recording's file: on again
        d.in.driftlogPath = "/home/steamos/eyecam/drift/eyes_2026-10-12_15-00-00.eyecam.csv";
        CHECK(d.step() == "driftlog on " + stem);
        // Not shown after that (refused, or no answer): asked again only every kDriftRetrySec
        d.in.driftlogOn = false;
        d.in.now = 101.0 + recorder::kDriftRetrySec - 0.5;
        CHECK(d.step().empty());
        d.in.now = 101.0 + recorder::kDriftRetrySec;
        CHECK(d.step(true).empty());  // (another command out)
        CHECK(d.step() == "driftlog on " + stem);
        CHECK(d.step().empty());
        // One started by hand meanwhile is left alone, then and at the end
        d.in.driftlogOn = true;
        d.in.driftlogPath = byHand;
        d.in.now += 100.0;
        CHECK(d.step().empty());
        d.in.recording = false;
        CHECK(d.step().empty() && d.link.on().empty());
    }
}

/**
 * Record a few seconds with the real frameeyeosc and check the CSV is whole up to the stop.
 * @param program frameeyeosc
 * @param dir the scratch folder
 */
void testReal(const std::string& program, const std::string& dir) {
    Recorder r;
    CHECK(r.start(program, dir + "/real", dir + "/config.json", now()));
    std::this_thread::sleep_for(std::chrono::seconds(3));
    CHECK(!r.poll(now()) && r.recording());
    const std::string path = r.view(now()).path;
    r.stop(now());
    CHECK(waitReaped(r));
    CHECK(r.view(now()).error.empty());
    std::ifstream file(path);
    std::string line;
    std::getline(file, line);
    const auto fields = [](const std::string& text) {
        size_t count = 1;
        for (char c : text) count += c == ',' ? 1 : 0;
        return count;
    };
    const size_t columns = fields(line);
    size_t rows = 0;
    bool whole = line.rfind("sample_time", 0) == 0;
    while (std::getline(file, line)) {
        whole &= fields(line) == columns;
        ++rows;
    }
    const std::string text = read(path);
    whole &= !text.empty() && text.back() == '\n';
    std::printf("recorder-test: frameeyeosc recorded %zu samples in 3 s (%zu columns), %s; its log: %s\n", rows,
                columns, whole ? "every line whole" : "BROKEN LINES",
                read(path.substr(0, path.size() - 4) + ".log").c_str());
    CHECK(whole);
}

}  // namespace

/**
 * Run the tests.
 * @param argc argument count
 * @param argv optionally the path of a real frameeyeosc
 * @return 0 if all passed
 */
int main(int argc, char** argv) {
    char dir[] = "recorder-test-XXXXXX";
    if (::mkdtemp(dir) == nullptr) {
        std::perror("mkdtemp");
        return 1;
    }
    char cwd[4096];
    const std::string scratch = std::string(::getcwd(cwd, sizeof(cwd))) + "/" + dir;
    testNames();
    testUniqueNames(scratch);
    testChild(scratch);
    testDriftNames();
    testDriftLink();
    if (argc > 1) testReal(argv[1], scratch);
    const std::string remove = "rm -rf '" + scratch + "'";
    if (std::system(remove.c_str()) != 0) std::fprintf(stderr, "could not remove %s\n", scratch.c_str());
    if (gFailures == 0) std::printf("recorder-test: all passed\n");
    return gFailures == 0 ? 0 : 1;
}
