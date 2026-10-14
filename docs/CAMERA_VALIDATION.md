# Calibration and pupil validation

The FOS changes retain Steam Frame's internal camera capture, Valve gaze, OSC parameter names, service names,
settings and panel layout. They address reproducible software defects. Public demo imagery and a complete native
Steam Frame recording have been checked. The recording's first guided calibration now succeeds for both eyes
without fallback; installation and live operation on the headset still need verification.

- Keep the initial close step's measured eyelid aperture in pixels until the later open steps establish an iris
  radius. Missing eyelid measurements still fail calibration.
- During pupil dilation, measure the brightness just beyond the pupil edge rather than accidentally measuring
  sclera or lid skin. Search for the iris boundary close enough to a large pupil to find the remaining iris ring.
- Scale live pupil/iris contrast thresholds to camera exposure, with bounded contrast floors. Fixed thresholds
  merged this recording's dim pupil into the iris and shadow. Keep the corresponding closed-lash brightness guards
  consistent with exposure so dim creases do not become fresh pupil measurements.
- When the pupil disappears, measure the lid crease without masking its former ellipse. Follow measured opposing
  lid gradients when the closed crease crosses the previous pupil position, instead of restricting the lower edge
  to the old open-eye search band. No constant closed-eye aperture is substituted.
- Use fresh, whole, settled pupils for pupil-range calibration. Blink-held values and rejected binocular measurements
  cannot become calibration evidence.
- Allow opt-in raw camera pictures before the first calibration. Calibrated camera values still require calibration.
- Refuse timed calibration while camera processing is disabled.

The iris is the scale reference; dilation changes the pupil diameter, not the anatomical iris size. Millimetres are
estimated using the existing assumed 11.8 mm iris diameter, not an individually measured physical iris diameter.
Live detection has changed; `--compat` retains the upstream prototype algorithm for comparison.

See [NATIVE_RECORDING_VERIFICATION.md](NATIVE_RECORDING_VERIFICATION.md) for the native data, original failure,
orientation and measured first-cycle results. Personal recordings and eye images remain outside this repository.

## Current verification evidence

Host checks pass: 215 sender tests, 113 camera-processing/recorder tests, 14 panel test executables and 40 Python
replay, installation, update and bootstrap tests. Nine existing recording, hardware and benchmark checks
are ignored by the default camera suite; the native first-cycle worker test was explicitly run and passed.
The sender CLI processed all 540 samples in the checked-in synthetic recording. Camera CLI replay checks both
anatomical eyes, including left-eye inversion, pupil dilation and uneven illumination. Image regressions also
cover minimum boundary contrast and stable iris scale. Native recording replay adds wearer-image evidence;
these host results do not establish native headset installation or live camera operation.

The ARM64 test candidate also passes architecture, loader, public glibc/C++ ABI and dependency checks against
upstream 0.7.8. Its recorder, run under QEMU, matches the host's complete emitted output on 1,100 original camera
frames, including closed/open states and pupil geometry. This is cross-platform replay evidence, not a live
Steam Frame test. See [ARM64_TEST_BUILD.md](ARM64_TEST_BUILD.md).

Public upstream issue [#29](https://github.com/sasaken1102r/frameeyeosc/issues/29) reports clear camera feeds with
unreliable detection, but supplies no usable camera images. The public
[FrameEyeCameraFeed README](https://github.com/Curtis-VL/FrameEyeCameraFeed) links a
[camera demo](https://github.com/user-attachments/assets/30928f5e-88ea-4b6f-920a-b49010649131) and
[status screenshot](https://github.com/user-attachments/assets/2da6e4a1-0ae1-4047-8707-320909434236).
The user subsequently supplied the demo video, and the screenshot download now succeeds in the current machine.
Both contain real eye-camera views. FOS detects both pupils and iris scales in the screenshot, and its recorder
processed all 1,450 reconstructed demo camera images. Difficult narrowed/closed frames remain unreliable in both
FOS and the separately compiled upstream version. See [DEMO_VERIFICATION.md](DEMO_VERIFICATION.md) for crop
geometry, video pixel aspect ratio, counts and limitations. These images provide neither ground-truth physical
pupil diameter nor evidence that the guided calibration succeeds. No third-party eye pictures were committed.

## Before releasing a headset build

Use the native build and installation instructions in [FORK.md](FORK.md). Then verify on the Steam Frame:

1. Confirm existing gaze and OSC movement still work, with the same settings and output destination.
2. In Eye cameras, enable camera processing and inspect both eyes with the existing eye preview Picture switch.
   Pictures should work before a successful calibration; each physical eye should match its left/right label.
3. Run the guided close / normal / wide / normal / wide calibration. Confirm a successful result is saved and
   survives a service restart. If it fails, keep the exact failure text and the Advanced calibration report.
4. Check blinks, winks, widened eyes and gaze while looking straight ahead and to each side. Compare pupil output
   in bright and dim content, allowing the pupils time to settle; blinks should hold the last size rather than
   producing sudden dilation changes.
5. Confirm the panel Update action uses MayoEDU/FOS. Stop the camera service and verify Valve gaze and normal OSC
   continue; then restart it and check camera processing recovers.

## Bring over an existing recording later

The recorder normally saves sessions under `~/eyecam` on the headset. From a PC with SSH access, substitute the
headset IP address and the actual recording folder name:

```sh
scp -r steamos@<frame-ip>:eyecam/<recording-folder> .
```

Copy the entire session folder so the raw eye files, timestamps, cues and metadata remain together. An ordinary
calibration may contain diagnostics only: its raw images exist only if recording/developer capture was enabled
when it ran. Existing recordings need no filename swapping; the reader uses their metadata to orient each eye.

Build the camera tool and replay without changing the headset's saved calibration:

```sh
cargo build --release --locked --manifest-path tools/eyecam/Cargo.toml
tools/eyecam/target/release/eyecam-rec --replay <recording-folder> --out /tmp/fos-eye-results.csv
# For a session containing the guided wear-calibration cues:
tools/eyecam/target/release/eyecam-rec --replay <recording-folder> --calib wear --out /tmp/fos-wear-result.json
```

Run the same recording through the upstream build to compare successful pupil frames, iris stability, estimated
pupil diameter and calibration results. Upload a recording only when you choose to share it; recordings remain
outside Git. The checked-in replay regression generates synthetic images and tests the actual recorder executable,
including anatomical left-eye flipping, so it does not need a personal recording.
