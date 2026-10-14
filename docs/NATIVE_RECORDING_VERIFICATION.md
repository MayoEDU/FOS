# Native Steam Frame recording verification

The user supplied a complete Steam Frame recording and the diagnostics from a separate failed calibration.
Both Google Drive archives were downloaded and verified with ZIP CRCs, file-size checks and timestamp/index
alignment. The original images, archives, diagnostic logs and analysis pictures remain outside Git.

## Original failure and recording

The failed calibration reports zero usable normal-eye pupils: left 0/482 and right 0/484, with 90 required per eye.
Widened-eye pupil counts and accepted lid measurements are also zero. Camera capture remains about 90 Hz, with
no relocks or aborts. Small capture gaps cannot explain complete detection starvation.

The separate recording contains 7,596 left and 7,598 right frames over 84.502 seconds. Its complete cue sequence
includes three close/normal/wide cycles, squint, looking up/down, and bright/dark/bright sections. Each image is
400 by 400 unsigned grayscale bytes. Metadata identifies anatomical eyes: flip the stored left image vertically;
the right image is upright. Use each frame's `eye_index` and camera timestamp, since a few CSV rows arrive out
of timestamp order. The original failed calibration explicitly recorded no raw images, so its exact image
sequence cannot be replayed.

Upstream 0.7.8, built separately from commit `a90bbc0aebdef72e1a4a6e860b3aa89dd82cff8b`, finds pupil candidates in
only 6/7,596 left and 58/7,598 right frames across the full recording, and its wear calibration fails for both eyes.
Fixed brightness thresholds merge the dim pupil with iris/shadow before the shape test. The visible pupils in
all eight initial ring snapshots are rejected by upstream and accepted with the revised live extraction.

Valve tracking continues publishing valid samples, but its openness stays high through many instructed close
steps. It is not reliable closed-eye ground truth here. Image examination confirms the relevant closed/open/wide
states; the fix does not force closure from the instruction label or Valve openness.

## First guided cycle

Replay of only the initial lead-in, close, normal and wide steps succeeds for both eyes, with no provisional-eye
fallback and no changes to the acceptance thresholds:

| Measurement | Left | Right |
| --- | ---: | ---: |
| Usable normal pupil samples | 378/378 | 378/378 |
| Measured closed-lid samples | 108 | 108 |
| Iris radius, pixels | 48.731 | 52.985 |
| Closed-to-normal aperture gap, iris radii | 1.257 | 1.359 |
| Normal-to-wide step, iris radii | 0.429 | 0.404 |

The original minimum aperture gap is 0.2; the minimum widen step is 0.05. This first-cycle check matters because
success across the longer recording alone could hide failure of the initial close step.

The correction uses exposure-relative pupil/iris boundaries and measured opposing lid gradients after a pupil
disappears. It neither relaxes the wear-calibration gates nor invents an aperture when no geometry was measured.
The separate compatibility path still matches upstream on the independently checked synthetic and native images.

The existing asynchronous worker test also passes on these first four native cue steps. It saves the successful
calibration, updates the shared camera output and calibration history, and clears live output on shutdown.

## Full recording and pupil response

All 15,194 images are represented in the final replay. Full-recording wear calibration succeeds for both eyes
without fallback; measured aperture gaps are 1.161 left / 1.344 right. The following counts use the recorder's
trimmed cue samples rather than every transition frame:

| Measurement | Left | Right |
| --- | ---: | ---: |
| Normal pupil samples | 1,400/1,512 | 1,389/1,512 |
| Wide pupil samples | 1,113/1,134 | 1,104/1,134 |
| Closed-cue frames reporting closed | 309/324 | 324/324 |
| Closed-cue pupil / fresh-size samples | 0 / 0 | 0 / 0 |
| Bright-cue fresh pupil samples | 725 | 1,046 |
| Dark-cue fresh pupil samples | 387 | 410 |
| Bright median estimated diameter, mm | 2.85 | 3.06 |
| Dark median estimated diameter, mm | 4.72 | 4.92 |

The pupil-range fit succeeds for both eyes using fresh samples only. Its diameter-to-iris-radius ranges are
0.444–0.879 left and 0.452–0.871 right. The estimated iris scale stays similar between bright and dark sections;
the pupil diameter changes. These values demonstrate the recording's dilation response without treating blink-held
sizes as new measurements.

The optional advanced squint/look-down user fit still rejects this recording: measured squint fractions are
1.96 left / 1.64 right, above its unchanged 0.85 maximum, and the squint segment has no usable pupils. This is a
remaining limitation of that advanced fit; the successful initial setup and separate pupil-range fit do not depend
on it. The changes do not bypass this failure or replace the user's existing advanced calibration with bad values.

## Reproduce the check

Build the recorder, then use the complete recording directory, preserving its metadata and filenames:

```sh
cargo build --release --locked --manifest-path tools/eyecam/Cargo.toml
tools/eyecam/target/release/eyecam-rec --replay <recording-folder> --calib wear --out /tmp/fos-wear.json
tools/eyecam/target/release/eyecam-rec --replay <recording-folder> --out /tmp/fos-frames.csv
EYECAM_SESSION=<recording-folder> cargo test --release --locked \
  --manifest-path tools/eyecam/Cargo.toml worker_on_a_session -- --ignored --nocapture
```

The worker test uses the first four cue steps, passes images through the actual asynchronous live worker, and
checks calibration persistence and shared output. It runs in a temporary directory without changing headset
settings. Ordinary CLI wear replay uses all matching cues; do not confuse that aggregate result with the initial
cycle.

Pupil millimetres use the existing assumed 11.8 mm iris diameter, not a measured physical iris diameter. This
recording supplies real image and cue evidence, but no physical pupil-size ground truth. A headset build must
still verify camera acquisition, VR preview, saved calibration after restart, OSC output and installation/update
behavior on the Steam Frame itself.
