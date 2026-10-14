"""Writes synthetic.csv, a made-up six-second recording for the replay tests (python3 make_synthetic.py)."""
import math
import random
from pathlib import Path

RATE = 90
START = 1000.0
random.seed(7)

# Both eyes' openness over a blink, one value per sample.
BLINK = [0.6, 0.3, 0.2, 0.35, 0.65]
# The last blink is only seen fully closed by the left eye.
HALF_BLINK = [0.65, 0.45, 0.4, 0.45, 0.7]
BLINKS = {1.0: (BLINK, BLINK), 2.0: (BLINK, BLINK), 3.3: (BLINK, BLINK), 4.0: (BLINK, HALF_BLINK)}
# One-sample dropouts: (time, eye, openness).
DROPOUTS = [(0.5, 1, 0.65), (1.5, 0, 0.2), (3.7, 1, 0.65), (4.5, 1, 0.65), (5.6, 0, 0.65)]
# The left eye's covariance is high and its gaze wild here.
BAD_LEFT = (2.5, 2.8)
WINK = (5.0, 5.3)


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def fmt(v):
    return "0" if v == 0 else f"{v:.4g}"


columns = ["sample_time"]
for name in ["gaze", "gaze_cov"]:
    columns += [f"{name}_{eye}_{axis}" for eye in ["left", "right"] for axis in "xyz"]
columns += [f"fixation_{axis}" for axis in "xyz"]
for name in ["pre_gaze", "pre_cov"]:
    columns += [f"{name}_{eye}_{axis}" for eye in ["left", "right"] for axis in "xyz"]
columns += ["openness_left", "openness_right"] + [f"extra_{i}" for i in range(8)]

rows = [",".join(columns)]
for i in range(6 * RATE):
    t = i / RATE
    openness = [0.78 + random.gauss(0, 0.01) for _ in range(2)]
    cov = [0.005, 0.005]
    noise = [0.004, 0.004]
    drop = 0.0
    for start, profiles in BLINKS.items():
        k = i - round(start * RATE)
        if 0 <= k < len(BLINK):
            openness = [profiles[0][k], profiles[1][k]]
            cov = [0.2, 0.2]
            drop = 0.3
    for when, eye, value in DROPOUTS:
        if i == round(when * RATE):
            openness[eye] = value
    if BAD_LEFT[0] <= t < BAD_LEFT[1]:
        cov[0] = 0.1
        noise[0] = 0.15
    if WINK[0] <= t < WINK[1]:
        openness[0] = 0.2
    eyes = [
        unit([0.10 + random.gauss(0, noise[0]), -0.05 - drop + random.gauss(0, noise[0]), -1.0]),
        unit([0.06 + random.gauss(0, noise[1]), -0.05 - drop + random.gauss(0, noise[1]), -1.0]),
    ]
    middle = unit([(a + b) / 2 for a, b in zip(*eyes)])
    fixation = [0.7 * c for c in middle]
    values = [START + t]
    values += eyes[0] + eyes[1]
    values += [cov[0]] * 3 + [cov[1]] * 3
    values += fixation
    values += eyes[0] + eyes[1]
    values += [cov[0]] * 3 + [cov[1]] * 3
    values += openness + [0.0] * 8
    rows.append(f"{START + t:.6f}," + ",".join(fmt(v) for v in values[1:]))

Path(__file__).with_name("synthetic.csv").write_text("\n".join(rows) + "\n", newline="\n")
