// Sound cues for the eye fit: short tones synthesized here, written once as WAV files and played by spawning a
// player (pw-play, else paplay, else aplay; silent without one). Nothing touches the system volume or PipeWire's
// settings: the panel only plays files. Which cue goes with which moment of the fit is decided by FitCues, from
// what the session shows, so it can be tested without audio (sounds_test.cpp).
#pragma once

#include "gaze_fit.h"

#include <sys/types.h>

#include <cstdint>
#include <string>
#include <vector>

namespace sounds {

/** The cues. */
enum class Cue {
    Pop,   ///< a dot appears (has arrived where to look)
    Pip,   ///< a step was measured
    Buzz,  ///< a step has to be measured again
    Tick,  ///< one count of "close your eyes 3, 2, 1"
    Open,  ///< the eyes-shut step is over: open your eyes
    Done,  ///< the whole fit is done (rising chime)
    Fail,  ///< the fit stopped (low falling tones)
};

/** All cues, for writing the files. */
constexpr Cue kAllCues[] = {Cue::Pop, Cue::Pip, Cue::Buzz, Cue::Tick, Cue::Open, Cue::Done, Cue::Fail};

/** The sample rate of the files. */
constexpr int kSampleRate = 48000;
/** The loudest sample of every cue: -14 dBFS. */
constexpr double kPeakDbfs = -14.0;
/** At most this many players run at once. */
constexpr size_t kMaxPlayers = 2;

/**
 * A cue's name ("pop"; also its file name without ".wav").
 * @param cue the cue
 * @return the name
 */
const char* name(Cue cue);

/**
 * Find a cue by name.
 * @param text the name
 * @param cue the cue
 * @return false if there is none
 */
bool parse(const std::string& text, Cue& cue);

/**
 * A cue's sound: mono 16-bit samples at kSampleRate, peaking at kPeakDbfs.
 * @param cue the cue
 * @return the samples
 */
std::vector<int16_t> synthesize(Cue cue);

/**
 * A WAV file (RIFF, PCM, mono, 16-bit, kSampleRate) holding the samples.
 * @param samples the samples
 * @return the file's bytes
 */
std::vector<uint8_t> wav(const std::vector<int16_t>& samples);

/**
 * Which cues go with the eye fit's moments. Fed what the session shows every frame; returns the cues to play now.
 */
class FitCues {
public:
    /**
     * Move on.
     * @param view the session
     * @param actions what the last tick asked for (the target's look, countdown and glide)
     * @return the cues to play now, in order
     */
    std::vector<Cue> update(const gaze_fit::View& view, const gaze_fit::Actions& actions);

private:
    bool started_ = false;       ///< a view has been seen
    gaze_fit::View last_;
    bool popped_ = false;        ///< the pop for the current step was played
    int lastTick_ = 0;           ///< the countdown number last ticked
};

/** Plays the cue files. */
class Player {
public:
    Player() = default;
    ~Player();
    Player(const Player&) = delete;
    Player& operator=(const Player&) = delete;

    /**
     * Write the cue files (once) and find a player program.
     * @param dir where the files go ($XDG_RUNTIME_DIR/frameeyeosc/sounds)
     * @return false if the files could not be written (then nothing plays)
     */
    bool init(const std::string& dir);

    /**
     * Play a cue without waiting for it. With kMaxPlayers already playing, a Done, Fail or Open cue stops the
     * oldest; any other cue is skipped.
     * @param cue the cue
     */
    void play(Cue cue);

    /** Reap players that have finished (call every loop). */
    void reap();

    /** @return the player program found ("" if none) */
    const std::string& program() const { return program_; }

private:
    std::string dir_;
    std::string program_;
    std::vector<pid_t> running_;
};

}  // namespace sounds
