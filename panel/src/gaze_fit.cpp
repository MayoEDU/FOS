// The eye fit: targets, the fit and the session.
#include "gaze_fit.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace gaze_fit {

namespace {

constexpr Target kTargets[kPointCount] = {
    {Point::Center, "center", 0.0, 0.0},
    {Point::Up, "up", 0.0, kUpDownDeg},
    {Point::Down, "down", 0.0, -kUpDownDeg},
    {Point::Left, "left", -kSideDeg, 0.0},
    {Point::Right, "right", kSideDeg, 0.0},
    // The eyes-shut step shows its words straight ahead
    {Point::Closed, "closed", 0.0, 0.0},
};

/**
 * Round to a number of decimals.
 * @param value the value
 * @param decimals digits after the point
 * @return the rounded value
 */
double roundTo(double value, int decimals) {
    const double scale = std::pow(10.0, decimals);
    return std::round(value * scale) / scale;
}

/**
 * A zero point as written: within range, 3 decimals (the panel's stepper shows 3).
 * @param value the measured center
 * @return the setting
 */
double offsetSetting(double value) {
    return roundTo(std::clamp(value, -kOffsetLimit, kOffsetLimit), 3);
}

/**
 * A gain as written: within range, 2 decimals.
 * @param value the computed gain
 * @return the setting
 */
double gainSetting(double value) {
    return roundTo(std::clamp(value, kGainMin, kGainMax), 2);
}

/**
 * A capture by step.
 * @param points the captures
 * @param point which
 * @return the capture
 */
const Measured& at(const Measured points[kPointCount], Point point) {
    return points[static_cast<int>(point)];
}

/**
 * How far a point moved from the center in its own direction.
 * @param points the captures
 * @param point which (Up, Down, Left or Right)
 * @return the distance (negative: the wrong way)
 */
double movedFromCenter(const Measured points[kPointCount], Point point) {
    const Measured& center = at(points, Point::Center);
    const Measured& m = at(points, point);
    const double x = m.x - center.x;
    const double y = m.y - center.y;
    switch (point) {
        case Point::Up: return y;
        case Point::Down: return -y;
        case Point::Left: return -x;
        case Point::Right: return x;
        default: return 0.0;
    }
}

/**
 * Whether the given points moved at least kMinMoveFraction of their target angle the right way.
 * @param points the captures
 * @param which the points to check, in order
 * @param count how many
 * @param failed the first that did not
 * @param detail its numbers (may be null)
 * @return true if all did
 */
bool pointsMoved(const Measured points[kPointCount], const Point* which, int count, Point& failed,
                 FailureDetail* detail) {
    for (int i = 0; i < count; ++i) {
        const Point point = which[i];
        const double targetAngle = (point == Point::Up || point == Point::Down ? kUpDownDeg : kSideDeg) / kFullScaleDeg;
        const double moved = movedFromCenter(points, point);
        if (!(moved >= kMinMoveFraction * targetAngle)) {
            failed = point;
            if (detail != nullptr) {
                detail->eye = -1;
                detail->movedDeg = moved * kFullScaleDeg;
                detail->neededDeg = kMinMoveFraction * targetAngle * kFullScaleDeg;
            }
            return false;
        }
    }
    return true;
}

}  // namespace

const Target& target(Point point) {
    return kTargets[static_cast<int>(point)];
}

int pointCount(Mode mode) {
    switch (mode) {
        case Mode::Center: return 1;
        case Mode::Full: break;
    }
    return kPointCount;
}

Point pointAt(Mode mode, int index) {
    if (mode == Mode::Center) return Point::Center;
    return kTargets[std::clamp(index, 0, kPointCount - 1)].point;
}

int samplesNeeded(const Measured& measured) {
    if (measured.received <= 0) return kMinSamples;
    const int share = static_cast<int>(std::ceil(kMinUsableShare * measured.received - 1e-9));
    return std::min(kMinSamples, std::max(kMinSamplesFloor, share));
}

std::string tryText(Point point, int attempt, const Measured& measured, const Measured& center, const char* outcome) {
    char text[256];
    int n = 0;
    if (measured.received > 0) {
        n = std::snprintf(text, sizeof(text), "%s try %d: %d of %d samples usable", target(point).name, attempt,
                          measured.samples, measured.received);
        if (std::isfinite(measured.rateHz)) {
            n += std::snprintf(text + n, sizeof(text) - n, " at %.0f Hz", measured.rateHz);
        }
        n += std::snprintf(text + n, sizeof(text) - n, " (needs %d), ", samplesNeeded(measured));
    } else {
        n = std::snprintf(text, sizeof(text), "%s try %d: %d samples (min %d), ", target(point).name, attempt,
                          measured.samples, kMinSamples);
    }
    // An eye Valve read stuck shut while the eye camera saw it open: its gaze counted, its openness isn't the eye's
    if (measured.cameraOpen[0] || measured.cameraOpen[1]) {
        const char* eyes = measured.cameraOpen[0] && measured.cameraOpen[1] ? "L and R"
                           : measured.cameraOpen[0]                         ? "L"
                                                                            : "R";
        n += std::snprintf(text + n, sizeof(text) - n, "%s open on the eye camera, ", eyes);
    }
    if (point == Point::Closed) {
        // An eye the eye camera stood in for at the center dot isn't checked here
        char limits[2][16];
        for (int eye = 0; eye < 2; ++eye) {
            if (center.cameraOpen[eye] || measured.cameraOpen[eye]) {
                std::snprintf(limits[eye], sizeof(limits[eye]), "-");
            } else {
                std::snprintf(limits[eye], sizeof(limits[eye]), "%.3f", kClosedShare * center.openness[eye]);
            }
        }
        std::snprintf(text + n, sizeof(text) - n, "openness L %.3f R %.3f (below %s / %s) -> %s",
                      measured.openness[0], measured.openness[1], limits[0], limits[1], outcome);
    } else if (std::isfinite(measured.spread) && measured.samples > 0) {
        std::snprintf(text + n, sizeof(text) - n, "spread %.1f° (max %.1f°) -> %s", measured.spread * kFullScaleDeg,
                      kMaxSpread * kFullScaleDeg, outcome);
    } else {
        std::snprintf(text + n, sizeof(text) - n, "no gaze average -> %s", outcome);
    }
    return text;
}

bool usable(const Measured& measured) {
    return measured.samples >= samplesNeeded(measured) && std::isfinite(measured.x) && std::isfinite(measured.y) &&
           std::isfinite(measured.spread) && measured.spread <= kMaxSpread;
}

bool usableClosed(const Measured& closed, const Measured& center, const bool* standIn) {
    if (closed.samples < samplesNeeded(closed) || !closed.hasOpenness || !center.hasOpenness) return false;
    for (int eye = 0; eye < 2; ++eye) {
        if (standIn != nullptr && standIn[eye]) continue;
        if (!(closed.openness[eye] < kClosedShare * center.openness[eye])) return false;
    }
    return true;
}

void standIns(const Measured points[kPointCount], bool out[2]) {
    for (int eye = 0; eye < 2; ++eye) {
        out[eye] = false;
        for (Point point : {Point::Up, Point::Center, Point::Down, Point::Closed}) {
            out[eye] = out[eye] || at(points, point).cameraOpen[eye];
        }
    }
}

double eyeAngle(double yawDeg, int eye, double ipd) {
    const double yaw = yawDeg * M_PI / 180.0;
    // The target seen from the eye: the left eye is at -ipd/2, so the target is ipd/2 further right of it
    const double side = kTargetDistanceM * std::sin(yaw) + (eye == 0 ? ipd / 2 : -ipd / 2);
    return std::atan2(side, kTargetDistanceM * std::cos(yaw)) * 180.0 / M_PI / kFullScaleDeg;
}

double meanUpGain(double measured, const std::vector<double>& previous, int* fits) {
    double sum = measured;
    int count = 1;
    for (auto it = previous.rbegin(); it != previous.rend() && count < kUpGainFits; ++it) {
        if (!std::isfinite(*it)) continue;
        sum += *it;
        ++count;
    }
    if (fits != nullptr) *fits = count;
    return gainSetting(sum / count);
}

std::vector<double> nextUpGains(const std::vector<double>& previous, double measured) {
    std::vector<double> next;
    for (double gain : previous) {
        if (std::isfinite(gain)) next.push_back(gain);
    }
    next.push_back(measured);
    if (next.size() > static_cast<size_t>(kUpGainFits)) next.erase(next.begin(), next.end() - kUpGainFits);
    return next;
}

Values fitCenter(const Measured& center, const Values& current) {
    Values values = current;
    values.offsetX = offsetSetting(center.x);
    values.offsetY = offsetSetting(center.y);
    return values;
}

bool fitGaze(const Measured points[kPointCount], Values& out, Point& failed, FailureDetail* detail, Notes* notes,
             const std::vector<double>& previousUpGains) {
    const double side = kSideDeg / kFullScaleDeg;
    const double upDown = kUpDownDeg / kFullScaleDeg;
    // How far each point moved from the center, counted in its own direction
    const Point checks[4] = {Point::Up, Point::Down, Point::Left, Point::Right};
    if (!pointsMoved(points, checks, 4, failed, detail)) return false;
    const Measured& center = at(points, Point::Center);
    // This fit's own gains: only the up gain carries over from wear to wear, so only it is used (averaged)
    const double gainUp = gainSetting(upDown / movedFromCenter(points, Point::Up));
    int fits = 0;
    out.offsetX = offsetSetting(center.x);
    out.offsetY = offsetSetting(center.y);
    out.rollDeg = 0.0;
    out.gainX = 1.0;
    out.gainUp = meanUpGain(gainUp, previousUpGains, &fits);
    out.gainDown = 1.0;
    if (notes != nullptr) {
        const double left = movedFromCenter(points, Point::Left);
        const double right = movedFromCenter(points, Point::Right);
        notes->gainX = gainSetting(2.0 * side / (left + right));
        notes->gainUp = gainUp;
        notes->gainDown = gainSetting(upDown / movedFromCenter(points, Point::Down));
        notes->upGainFits = fits;
    }
    return true;
}

bool fitLids(const Measured points[kPointCount], Values& out, FailureDetail* detail) {
    const Measured& closed = at(points, Point::Closed);
    const Measured* open[3] = {&at(points, Point::Up), &at(points, Point::Center), &at(points, Point::Down)};
    const Point openPoints[3] = {Point::Up, Point::Center, Point::Down};
    // An eye Valve read stuck shut while the eye camera saw it open: its openness says nothing, so it keeps its fit
    bool kept[2];
    standIns(points, kept);
    for (int eye = 0; eye < 2; ++eye) {
        if (kept[eye]) continue;
        for (int i = 0; i < 3; ++i) {
            const Measured* m = open[i];
            if (!m->hasOpenness || !(m->openness[eye] >= closed.openness[eye] + kMinLidRange)) {
                if (detail != nullptr) {
                    detail->eye = eye;
                    detail->lidPoint = openPoints[i];
                    detail->lidOpen = m->hasOpenness ? m->openness[eye] : NAN;
                    detail->lidClosed = closed.openness[eye];
                }
                return false;
            }
        }
    }
    for (int eye = 0; eye < 2; ++eye) {
        out.lidsKept[eye] = kept[eye];
        if (kept[eye]) continue;
        out.lidClosed[eye] = roundTo(closed.openness[eye], 3);
        out.lidUp[eye] = roundTo(open[0]->openness[eye], 3);
        out.lidOpen[eye] = roundTo(open[1]->openness[eye], 3);
        out.lidDown[eye] = roundTo(open[2]->openness[eye], 3);
    }
    out.hasLids = true;
    return true;
}

void Session::start(Mode mode, const Values& current, double now, const std::vector<double>& upGains) {
    *this = Session();
    // No waiting for the dashboard: the first dot shows right away (nearer than the dashboard, so over it)
    phase_ = Phase::Settling;
    phaseAt_ = now;
    mode_ = mode;
    current_ = current;
    upGains_ = upGains;
}

void Session::cancel(Failure why) {
    if (active()) fail(why);
}

bool Session::active() const {
    return phase_ == Phase::Settling || phase_ == Phase::Capturing || phase_ == Phase::Reopen;
}

void Session::fail(Failure failure) {
    phase_ = Phase::Failed;
    failure_ = failure;
    failedPoint_ = point();
}

void Session::failMovement(Point point) {
    for (int i = 0; i < pointCount(mode_); ++i) {
        if (pointAt(mode_, i) == point) index_ = i;
    }
    fail(Failure::NoMovement);
}

void Session::writeFailed() {
    // After the final write too: the result is then not in effect
    if (active() || phase_ == Phase::Done) fail(Failure::WriteFailed);
}

void Session::captureSent(long long id, double now) {
    if (phase_ != Phase::Capturing || !requested_) return;
    requested_ = false;
    captureId_ = id;
    phaseAt_ = now;
}

void Session::next(double now, Actions& actions) {
    if (point() == Point::Closed) {
        // Nothing more to measure; "open your eyes" first, then the result
        phase_ = Phase::Reopen;
        phaseAt_ = now;
        return;
    }
    previousPoint_ = point();
    ++index_;
    attempt_ = 1;
    if (index_ >= pointCount(mode_)) {
        finish(actions);
        return;
    }
    // Before asking to close the eyes, make sure the gaze part worked
    if (point() == Point::Closed) {
        Values gaze = current_;
        Point failed = Point::Center;
        if (!fitGaze(measured_, gaze, failed, &detail_)) {
            failMovement(failed);
            return;
        }
    }
    phase_ = Phase::Settling;
    phaseAt_ = now;
}

void Session::finish(Actions& actions) {
    Point failed = Point::Center;
    notes_ = Notes();
    if (mode_ == Mode::Center) {
        const Measured& center = measured_[static_cast<int>(Point::Center)];
        result_ = fitCenter(center, current_);
        for (int eye = 0; eye < 2; ++eye) notes_.standIn[eye] = center.cameraOpen[eye];
    } else {
        standIns(measured_, notes_.standIn);
        result_ = current_;
        if (!fitGaze(measured_, result_, failed, &detail_, &notes_, upGains_)) {
            failMovement(failed);
            return;
        }
        if (!fitLids(measured_, result_, &detail_)) {
            fail(Failure::NoLidRange);
            return;
        }
        // The gains this fit's dots gave, and what was written, after the last try's numbers
        char text[200];
        std::snprintf(text, sizeof(text),
                      "gains measured: sideways %.2f, up %.2f, down %.2f; written: up %.2f (mean of %d fit%s), "
                      "sideways and down 1, no tilt",
                      notes_.gainX, notes_.gainUp, notes_.gainDown, result_.gainUp, notes_.upGainFits,
                      notes_.upGainFits == 1 ? "" : "s");
        if (!actions.log.empty()) actions.log += '\n';
        actions.log += text;
    }
    phase_ = Phase::Done;
    actions.writeValues = true;
    actions.values = result_;
}

Actions Session::tick(double now, const Dashboard& dashboard, const EyeStatus& status) {
    Actions actions;
    if (!active()) return actions;
    // The dashboard open or closed, the targets show over it. Closing it goes on; opening it while the fit runs
    // without it stops it (the way to stop a fit started with it closed, and the eyes would be on it). With it open,
    // another page (not this panel's) stops it too, once that has lasted kAwaySec
    const bool opened = dashboardSeen_ && !dashboardWasOpen_ && dashboard.open;
    dashboardSeen_ = true;
    dashboardWasOpen_ = dashboard.open;
    if (!dashboard.open || dashboard.panelShown) {
        awaySince_ = -1.0;
    } else if (awaySince_ < 0.0) {
        awaySince_ = now;
    }
    if (opened) {
        fail(Failure::DashboardOpened);
    } else if (!status.running) {
        fail(Failure::NotRunning);
    } else if (awaySince_ >= 0.0 && now - awaySince_ >= kAwaySec) {
        fail(Failure::Left);
    }
    if (phase_ == Phase::Settling && now - phaseAt_ >= settleSec()) {
        phase_ = Phase::Capturing;
        phaseAt_ = now;
        requested_ = true;
        captureId_ = 0;
        actions.writeCapture = true;
        actions.target = target(point()).name;
        actions.captureSec = captureSec();
        actions.skipSec = point() == Point::Closed ? kClosedSkipSec : kCaptureSkipSec;
    } else if (phase_ == Phase::Capturing && !requested_) {
        const GazeCaptureStatus& capture = status.capture;
        const bool ours = captureId_ != 0 && capture.present && capture.id == captureId_;
        if (ours && capture.done) {
            Measured measured;
            measured.samples = capture.samples;
            measured.received = capture.received;
            measured.rateHz = capture.rate;
            if (capture.hasAverage) {
                measured.x = capture.x;
                measured.y = capture.y;
                measured.spread = capture.spread;
            }
            measured.hasOpenness = capture.hasOpenness;
            measured.openness[0] = capture.openness[0];
            measured.openness[1] = capture.openness[1];
            measured.cameraOpen[0] = capture.cameraOpen[0];
            measured.cameraOpen[1] = capture.cameraOpen[1];
            const bool closedStep = point() == Point::Closed;
            // The full fit needs each gaze point's openness too, for the lid fit
            const Measured& center = measured_[static_cast<int>(Point::Center)];
            // An eye the eye camera stood in for at a dot, or now, isn't checked shut (its lid fit stays as it was)
            bool standIn[2];
            standIns(measured_, standIn);
            for (int eye = 0; eye < 2; ++eye) standIn[eye] = standIn[eye] || measured.cameraOpen[eye];
            const bool ok = closedStep ? usableClosed(measured, center, standIn)
                                       : usable(measured) && (mode_ != Mode::Full || measured.hasOpenness);
            const bool last = attempt_ >= kMaxAttempts;
            actions.log = tryText(point(), attempt_, measured, center, ok ? "ok" : (last ? "failed" : "again"));
            if (ok) {
                measured_[static_cast<int>(point())] = measured;
                next(now, actions);
            } else if (++attempt_ > kMaxAttempts) {
                attempt_ = kMaxAttempts;
                detail_.tries = kMaxAttempts;
                detail_.last = measured;
                if (closedStep) {
                    for (int eye = 0; eye < 2; ++eye) {
                        detail_.closedBelow[eye] = standIn[eye] ? NAN : kClosedShare * center.openness[eye];
                    }
                }
                fail(closedStep ? Failure::NotClosed : Failure::Unsteady);
            } else {
                previousPoint_ = point();
                phase_ = Phase::Settling;
                phaseAt_ = now;
            }
        } else if (now - phaseAt_ >= kResultTimeoutSec) {
            fail(Failure::NoResult);
        }
    } else if (phase_ == Phase::Reopen && now - phaseAt_ >= kReopenSec) {
        finish(actions);
    }

    if (phase_ == Phase::Settling || phase_ == Phase::Capturing || phase_ == Phase::Reopen) {
        const bool closedStep = point() == Point::Closed;
        const double settle = settleSec();
        const double capture = captureSec();
        // Seconds left in the step, the capture counted from when it was asked for (frameeyeosc starts it within a
        // tenth of a second), so the ring runs down evenly
        double left = capture;
        if (phase_ == Phase::Settling) {
            left += std::max(0.0, settle - (now - phaseAt_));
        } else if (phase_ == Phase::Reopen) {
            left = 0.0;
        } else {
            left = std::max(0.0, capture - (now - phaseAt_));
        }
        actions.showTarget = true;
        actions.progress = std::clamp(left / (settle + capture), 0.0, 1.0);
        // Under the dot, the seconds being measured (2, 1); nothing while it glides over and the eyes find it
        actions.seconds = phase_ == Phase::Capturing ? std::max(1, static_cast<int>(std::ceil(left - 1e-9))) : 0;
        if (closedStep) {
            actions.style = phase_ == Phase::Settling    ? TargetStyle::CloseEyes
                            : phase_ == Phase::Capturing ? TargetStyle::KeepClosed
                                                         : TargetStyle::OpenEyes;
            // Counting down to closing the eyes; nothing to count while they are shut
            actions.seconds = phase_ == Phase::Settling
                                  ? std::max(1, static_cast<int>(std::ceil(settle - (now - phaseAt_) - 1e-9)))
                                  : 0;
            // The ring runs the whole way round for the 3, 2, 1, and again while the eyes are shut (not half for each)
            actions.progress = phase_ == Phase::Settling
                                   ? std::clamp((settle - (now - phaseAt_)) / settle, 0.0, 1.0)
                                   : std::clamp(left / capture, 0.0, 1.0);
        }
        // Glide from the previous target to this one at the start of a step (smoothstep easing)
        const Target& from = target(previousPoint_);
        const Target& to = target(point());
        double t = phase_ == Phase::Settling ? std::clamp((now - phaseAt_) / kMoveSec, 0.0, 1.0) : 1.0;
        actions.arrived = t >= 1.0 || previousPoint_ == point();
        t = t * t * (3.0 - 2.0 * t);
        actions.yawDeg = from.yawDeg + (to.yawDeg - from.yawDeg) * t;
        actions.pitchDeg = from.pitchDeg + (to.pitchDeg - from.pitchDeg) * t;
    }
    return actions;
}

View Session::view() const {
    View view;
    view.phase = phase_;
    view.mode = mode_;
    view.index = index_;
    view.count = pointCount(mode_);
    view.point = phase_ == Phase::Failed ? failedPoint_ : point();
    view.attempt = attempt_;
    view.failure = failure_;
    view.detail = detail_;
    view.values = result_;
    view.notes = notes_;
    return view;
}

}  // namespace gaze_fit
