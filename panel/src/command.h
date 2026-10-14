// Runs external commands (systemctl) without going through a shell, and captures their output.
#pragma once

#include <string>
#include <vector>

/** Result of runCommand(). */
struct CommandResult {
    enum class Status {
        Ok,           ///< exited with code 0
        Failed,       ///< exited with a nonzero code or a signal
        Timeout,      ///< didn't finish in time, so it was killed with SIGKILL
        SpawnFailed,  ///< couldn't be started (pipe/fork/exec failed)
    };
    Status status = Status::SpawnFailed;
    int exitCode = -1;       ///< exit code (-1 if terminated by a signal)
    std::string out;         ///< standard output
    std::string err;         ///< standard error (for logging)

    /** @return true if it exited with code 0 */
    bool ok() const { return status == Status::Ok; }
};

/**
 * Run a command via fork + execvp and wait for it to finish, returning its output
 * (never goes through a shell). If it doesn't finish in time, kill it with SIGKILL;
 * either way, reap the child with waitpid (no zombies left behind). Standard input is
 * /dev/null. The child resets its signal mask to empty before exec.
 * @param argv the command and its arguments (argv[0] is looked up via PATH)
 * @param timeoutMs how long to wait (ms)
 * @return the result
 */
CommandResult runCommand(const std::vector<std::string>& argv, int timeoutMs = 2000);

/**
 * Format a command and its result as one line for logging
 * (e.g. "wpctl settings ... -> exit code 1: some error text").
 * @param argv the command that was run
 * @param result the result
 * @return a one-line description
 */
std::string describeCommand(const std::vector<std::string>& argv, const CommandResult& result);
