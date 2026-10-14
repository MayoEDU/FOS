// Implementation of external command execution.
#include "command.h"

#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cerrno>
#include <chrono>
#include <cstring>

namespace {

/**
 * Return the current time in ms from a monotonic clock.
 * @return ms
 */
long long nowMs() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

/**
 * Read whatever is available from a pipe and append it.
 * @param fd the pipe to read (non-blocking)
 * @param text destination to append to
 * @return true if still open (not EOF)
 */
bool drain(int fd, std::string& text) {
    char buffer[4096];
    while (true) {
        const ssize_t n = ::read(fd, buffer, sizeof(buffer));
        if (n > 0) {
            // Cap the size so a runaway amount of output can't exhaust memory
            if (text.size() < 1024 * 1024) text.append(buffer, static_cast<size_t>(n));
            continue;
        }
        if (n == 0) return false;
        if (errno == EINTR) continue;
        return errno == EAGAIN || errno == EWOULDBLOCK;
    }
}

/**
 * Close both ends of a pipe (only the ones still open).
 * @param fds the pipe
 */
void closePipe(int fds[2]) {
    for (int i = 0; i < 2; ++i) {
        if (fds[i] >= 0) ::close(fds[i]);
        fds[i] = -1;
    }
}

}  // namespace

CommandResult runCommand(const std::vector<std::string>& argv, int timeoutMs) {
    CommandResult result;
    if (argv.empty()) return result;

    // Build the exec array before forking (so the child doesn't need to allocate memory)
    std::vector<char*> args;
    for (const auto& arg : argv) args.push_back(const_cast<char*>(arg.c_str()));
    args.push_back(nullptr);

    int outPipe[2] = {-1, -1};
    int errPipe[2] = {-1, -1};
    if (::pipe2(outPipe, O_CLOEXEC) != 0 || ::pipe2(errPipe, O_CLOEXEC) != 0) {
        result.err = std::string("pipe: ") + std::strerror(errno);
        closePipe(outPipe);
        closePipe(errPipe);
        return result;
    }
    const int devNull = ::open("/dev/null", O_RDONLY | O_CLOEXEC);

    const pid_t pid = ::fork();
    if (pid < 0) {
        result.err = std::string("fork: ") + std::strerror(errno);
        closePipe(outPipe);
        closePipe(errPipe);
        if (devNull >= 0) ::close(devNull);
        return result;
    }
    if (pid == 0) {
        // Child process: only async-signal-safe calls are used here
        if (devNull >= 0) ::dup2(devNull, STDIN_FILENO);
        ::dup2(outPipe[1], STDOUT_FILENO);
        ::dup2(errPipe[1], STDERR_FILENO);
        // Don't carry over the calling thread's blocked signals into the child
        sigset_t empty;
        sigemptyset(&empty);
        ::sigprocmask(SIG_SETMASK, &empty, nullptr);
        ::execvp(args[0], args.data());
        ::_exit(127);  // exec failed
    }

    // Parent process: close the write ends and read both streams until the deadline
    ::close(outPipe[1]);
    ::close(errPipe[1]);
    outPipe[1] = -1;
    errPipe[1] = -1;
    if (devNull >= 0) ::close(devNull);
    ::fcntl(outPipe[0], F_SETFL, O_NONBLOCK);
    ::fcntl(errPipe[0], F_SETFL, O_NONBLOCK);

    const long long deadline = nowMs() + timeoutMs;
    bool outOpen = true;
    bool errOpen = true;
    bool timedOut = false;
    while (outOpen || errOpen) {
        const long long left = deadline - nowMs();
        if (left <= 0) {
            timedOut = true;
            break;
        }
        pollfd fds[2] = {{outPipe[0], POLLIN, 0}, {errPipe[0], POLLIN, 0}};
        if (!outOpen) fds[0].fd = -1;  // don't poll a stream that's already closed
        if (!errOpen) fds[1].fd = -1;
        const int ready = ::poll(fds, 2, static_cast<int>(left));
        if (ready < 0) {
            if (errno == EINTR) continue;
            timedOut = true;  // stop waiting even if poll itself is unusable
            break;
        }
        if (outOpen && fds[0].revents != 0) outOpen = drain(outPipe[0], result.out);
        if (errOpen && fds[1].revents != 0) errOpen = drain(errPipe[0], result.err);
    }
    if (timedOut) ::kill(pid, SIGKILL);
    closePipe(outPipe);
    closePipe(errPipe);

    int status = 0;
    while (::waitpid(pid, &status, 0) < 0 && errno == EINTR) {
    }
    if (timedOut) {
        result.status = CommandResult::Status::Timeout;
    } else if (WIFEXITED(status)) {
        result.exitCode = WEXITSTATUS(status);
        result.status = result.exitCode == 0 ? CommandResult::Status::Ok : CommandResult::Status::Failed;
        if (result.exitCode == 127 && result.out.empty() && result.err.empty()) {
            result.status = CommandResult::Status::SpawnFailed;
            result.err = "command not found";
        }
    } else {
        result.status = CommandResult::Status::Failed;
    }
    return result;
}

std::string describeCommand(const std::vector<std::string>& argv, const CommandResult& result) {
    std::string line;
    for (const auto& arg : argv) line += (line.empty() ? "" : " ") + arg;
    switch (result.status) {
        case CommandResult::Status::Ok: line += " -> ok"; break;
        case CommandResult::Status::Failed:
            line += result.exitCode >= 0 ? " -> exit code " + std::to_string(result.exitCode)
                                         : " -> terminated by signal";
            break;
        case CommandResult::Status::Timeout: line += " -> timed out, killed"; break;
        case CommandResult::Status::SpawnFailed: line += " -> failed to start"; break;
    }
    std::string err = result.err;
    while (!err.empty() && (err.back() == '\n' || err.back() == ' ')) err.pop_back();
    const size_t newline = err.find('\n');
    if (newline != std::string::npos) err = err.substr(0, newline);  // first line only
    if (!err.empty()) line += ": " + err;
    return line;
}
