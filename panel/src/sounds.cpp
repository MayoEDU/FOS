// The eye fit's sound cues.
#include "sounds.h"

#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>

extern char** environ;

namespace sounds {

namespace {

/** One tone of a cue. */
struct Tone {
    double startSec;  ///< when it starts in the cue
    double freqHz;    ///< its pitch...
    double endHz;     ///< ...gliding to this
    double lengthSec;
    bool triangle;    ///< triangle wave (buzzier) instead of sine
};

/**
 * A cue's tones.
 * @param cue the cue
 * @return the tones
 */
std::vector<Tone> tones(Cue cue) {
    switch (cue) {
        case Cue::Pop: return {{0.0, 1050, 760, 0.07, false}};
        case Cue::Pip: return {{0.0, 1320, 1320, 0.07, false}};
        case Cue::Buzz: return {{0.0, 180, 170, 0.2, true}};
        case Cue::Tick: return {{0.0, 1000, 1000, 0.035, false}};
        // Two bright notes, the second longer: unmistakable with the eyes shut
        case Cue::Open: return {{0.0, 988, 988, 0.25, false}, {0.14, 1319, 1319, 0.45, false}};
        // C5, E5, G5 rising
        case Cue::Done: return {{0.0, 523, 523, 0.22, false}, {0.12, 659, 659, 0.22, false}, {0.24, 784, 784, 0.45, false}};
        // Two low notes falling
        case Cue::Fail: return {{0.0, 392, 392, 0.22, true}, {0.2, 294, 294, 0.35, true}};
    }
    return {};
}

/**
 * Where a program is: /usr/bin or /bin first, then the absolute folders on the PATH (empty and relative ones are
 * skipped, so nothing is started from the working folder).
 * @param program the name
 * @return its path, or "" if it is not there
 */
std::string findProgram(const std::string& program) {
    const char* path = std::getenv("PATH");
    const std::string dirs = std::string("/usr/bin:/bin:") + (path != nullptr ? path : "");
    size_t start = 0;
    while (start <= dirs.size()) {
        const size_t end = dirs.find(':', start);
        const std::string dir = dirs.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (!dir.empty() && dir[0] == '/') {
            const std::string candidate = dir + "/" + program;
            if (::access(candidate.c_str(), X_OK) == 0) return candidate;
        }
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return "";
}

/**
 * Create a folder and its parents, private to the user.
 * @param dir the folder
 * @return true if it exists afterwards
 */
bool makeDirectories(const std::string& dir) {
    for (size_t pos = 1; pos <= dir.size(); ++pos) {
        if (pos != dir.size() && dir[pos] != '/') continue;
        if (::mkdir(dir.substr(0, pos).c_str(), 0700) != 0 && errno != EEXIST) return false;
    }
    return true;
}

/**
 * Append a little-endian number to a byte buffer.
 * @param out the buffer
 * @param value the number
 * @param bytes its size
 */
void put(std::vector<uint8_t>& out, uint32_t value, int bytes) {
    for (int i = 0; i < bytes; ++i) out.push_back(static_cast<uint8_t>((value >> (8 * i)) & 0xff));
}

}  // namespace

const char* name(Cue cue) {
    switch (cue) {
        case Cue::Pop: return "pop";
        case Cue::Pip: return "pip";
        case Cue::Buzz: return "buzz";
        case Cue::Tick: return "tick";
        case Cue::Open: return "open";
        case Cue::Done: return "done";
        case Cue::Fail: return "fail";
    }
    return "";
}

bool parse(const std::string& text, Cue& cue) {
    for (Cue candidate : kAllCues) {
        if (text == name(candidate)) {
            cue = candidate;
            return true;
        }
    }
    return false;
}

std::vector<int16_t> synthesize(Cue cue) {
    const std::vector<Tone> parts = tones(cue);
    double length = 0.0;
    for (const Tone& tone : parts) length = std::max(length, tone.startSec + tone.lengthSec);
    std::vector<double> mix(static_cast<size_t>(std::ceil(length * kSampleRate)) + 1, 0.0);
    for (const Tone& tone : parts) {
        const size_t first = static_cast<size_t>(tone.startSec * kSampleRate);
        const size_t count = static_cast<size_t>(tone.lengthSec * kSampleRate);
        double phase = 0.0;
        for (size_t i = 0; i < count && first + i < mix.size(); ++i) {
            const double t = static_cast<double>(i) / kSampleRate;
            const double along = t / tone.lengthSec;
            const double freq = tone.freqHz + (tone.endHz - tone.freqHz) * along;
            phase += 2 * M_PI * freq / kSampleRate;
            const double cycle = std::fmod(phase / (2 * M_PI), 1.0);
            const double wave = tone.triangle ? 1.0 - 4.0 * std::fabs(cycle - 0.5) : std::sin(phase);
            // 5 ms attack, then an exponential decay that ends at silence (no click)
            const double attack = std::min(1.0, t / 0.005);
            const double decay = std::exp(-4.0 * along) * (1.0 - along);
            mix[first + i] += wave * attack * decay;
        }
    }
    double peak = 0.0;
    for (double value : mix) peak = std::max(peak, std::fabs(value));
    const double target = std::pow(10.0, kPeakDbfs / 20.0) * 32767.0;
    std::vector<int16_t> samples(mix.size());
    for (size_t i = 0; i < mix.size(); ++i) {
        samples[i] = static_cast<int16_t>(std::lround(peak > 0 ? mix[i] / peak * target : 0.0));
    }
    return samples;
}

std::vector<uint8_t> wav(const std::vector<int16_t>& samples) {
    const uint32_t dataBytes = static_cast<uint32_t>(samples.size() * 2);
    std::vector<uint8_t> out;
    out.reserve(44 + dataBytes);
    const auto tag = [&](const char* text) { out.insert(out.end(), text, text + 4); };
    tag("RIFF");
    put(out, 36 + dataBytes, 4);
    tag("WAVE");
    tag("fmt ");
    put(out, 16, 4);               // fmt chunk size
    put(out, 1, 2);                // PCM
    put(out, 1, 2);                // mono
    put(out, kSampleRate, 4);
    put(out, kSampleRate * 2, 4);  // bytes per second
    put(out, 2, 2);                // bytes per frame
    put(out, 16, 2);               // bits per sample
    tag("data");
    put(out, dataBytes, 4);
    for (int16_t sample : samples) put(out, static_cast<uint16_t>(sample), 2);
    return out;
}

std::vector<Cue> FitCues::update(const gaze_fit::View& view, const gaze_fit::Actions& actions) {
    using gaze_fit::Phase;
    using gaze_fit::Point;
    std::vector<Cue> cues;
    const gaze_fit::View last = started_ ? last_ : gaze_fit::View();
    started_ = true;
    last_ = view;
    const bool running = view.phase == Phase::Settling || view.phase == Phase::Capturing;
    const bool wasRunning = last.phase == Phase::Settling || last.phase == Phase::Capturing;
    const bool newStep = running && (!wasRunning || view.index != last.index);
    // A step measured: the session moved on to the next step, the eyes-shut ending or the result
    if (wasRunning && (newStep || view.phase == Phase::Reopen || view.phase == Phase::Done)) cues.push_back(Cue::Pip);
    // A step to measure again (the same dot stays)
    if (running && wasRunning && view.index == last.index && view.attempt > last.attempt) cues.push_back(Cue::Buzz);
    if (newStep) {
        popped_ = false;
        lastTick_ = 0;
    }
    if (running && view.point != Point::Closed && actions.arrived && !popped_ && view.attempt == 1) {
        // The dot has arrived where to look
        cues.push_back(Cue::Pop);
        popped_ = true;
    }
    if (running && view.point == Point::Closed && view.phase == Phase::Settling && actions.arrived &&
        actions.seconds > 0 && actions.seconds != lastTick_) {
        cues.push_back(Cue::Tick);
        lastTick_ = actions.seconds;
    }
    if (view.phase == Phase::Reopen && last.phase != Phase::Reopen) {
        // The pip of the eyes-shut step is not heard with the chime; the chime alone says "open"
        cues.erase(std::remove(cues.begin(), cues.end(), Cue::Pip), cues.end());
        cues.push_back(Cue::Open);
    }
    if (view.phase == Phase::Done && last.phase != Phase::Done) {
        cues.erase(std::remove(cues.begin(), cues.end(), Cue::Pip), cues.end());
        cues.push_back(Cue::Done);
    }
    if (view.phase == Phase::Failed && last.phase != Phase::Failed) cues.push_back(Cue::Fail);
    return cues;
}

Player::~Player() {
    for (pid_t pid : running_) ::kill(pid, SIGTERM);
    for (pid_t pid : running_) ::waitpid(pid, nullptr, 0);
}

bool Player::init(const std::string& dir) {
    for (const char* candidate : {"pw-play", "paplay", "aplay"}) {
        program_ = findProgram(candidate);
        if (!program_.empty()) break;
    }
    if (!makeDirectories(dir)) {
        std::fprintf(stderr, "[sound] can't create %s: %s\n", dir.c_str(), std::strerror(errno));
        return false;
    }
    dir_ = dir;
    for (Cue cue : kAllCues) {
        const std::vector<uint8_t> bytes = wav(synthesize(cue));
        const std::string path = dir + "/" + name(cue) + ".wav";
        std::ofstream file(path, std::ios::binary | std::ios::trunc);
        file.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
        if (!file) {
            std::fprintf(stderr, "[sound] can't write %s\n", path.c_str());
            dir_.clear();
            return false;
        }
    }
    std::fprintf(stderr, "[sound] cues in %s, played with %s\n", dir.c_str(),
                 program_.empty() ? "nothing (no pw-play, paplay or aplay)" : program_.c_str());
    return true;
}

void Player::reap() {
    running_.erase(std::remove_if(running_.begin(), running_.end(),
                                  [](pid_t pid) { return ::waitpid(pid, nullptr, WNOHANG) != 0; }),
                   running_.end());
}

void Player::play(Cue cue) {
    if (dir_.empty() || program_.empty()) return;
    reap();
    if (running_.size() >= kMaxPlayers) {
        const bool important = cue == Cue::Open || cue == Cue::Done || cue == Cue::Fail;
        if (!important) return;
        ::kill(running_.front(), SIGTERM);
        ::waitpid(running_.front(), nullptr, 0);
        running_.erase(running_.begin());
    }
    const std::string file = dir_ + "/" + name(cue) + ".wav";
    // No shell; stdin, stdout and stderr go to /dev/null so a player never blocks on or clutters the panel's
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_addopen(&actions, 1, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&actions, 2, "/dev/null", O_WRONLY, 0);
    posix_spawnattr_t attributes;
    posix_spawnattr_init(&attributes);
    sigset_t none;
    sigemptyset(&none);
    posix_spawnattr_setsigmask(&attributes, &none);
    posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETSIGMASK);
    std::vector<std::string> args = {program_, file};
    if (program_.size() >= 5 && program_.compare(program_.size() - 5, 5, "aplay") == 0) args = {program_, "-q", file};
    std::vector<char*> argv;
    for (std::string& arg : args) argv.push_back(arg.data());
    argv.push_back(nullptr);
    pid_t pid = 0;
    const int error = posix_spawn(&pid, program_.c_str(), &actions, &attributes, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    posix_spawnattr_destroy(&attributes);
    if (error != 0) {
        std::fprintf(stderr, "[sound] can't start %s: %s\n", program_.c_str(), std::strerror(error));
        return;
    }
    running_.push_back(pid);
}

}  // namespace sounds
