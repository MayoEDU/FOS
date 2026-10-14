# Public Steam Frame eye-camera demo verification

The user supplied the public FrameEyeCameraFeed demonstration MP4 and its camera status screenshot. The screenshot
was also downloaded successfully in the current cloud machine. This is real camera imagery, but it is rendered and
compressed media rather than a native eye-camera recording.

Sources:

- [FrameEyeCameraFeed project](https://github.com/Curtis-VL/FrameEyeCameraFeed)
- [Demo video](https://github.com/user-attachments/assets/30928f5e-88ea-4b6f-920a-b49010649131)
- [Camera status screenshot](https://github.com/user-attachments/assets/2da6e4a1-0ae1-4047-8707-320909434236)

No third-party eye images or recordings are included in the Git repository or source bundle. Local analysis artifacts
are under `/workspace/eye-media-analysis/` in the verification machine.

## Screenshot

Both camera images occupy 384 by 300 pixels in the 837 by 498 screenshot. Their half-open crop rectangles are
`(23, 87, 407, 387)` and `(425, 87, 809, 387)`. FrameEyeCameraFeed's default JPEG output is 512 by 400 pixels:
512 includes the camera row stride, while FOS processes the first 400 visible columns. Each screenshot crop was
converted to grayscale, resized to 512 by 400 using bilinear interpolation, and reduced to the first 400 columns.
The capture tool has already made both pictures upright; no extra vertical flip was applied.

FOS's current live feature extractor found a pupil and an iris scale in both images:

| Displayed camera | Pupil center, native-equivalent pixels | Pupil major radius | Iris radius estimate | Iris inliers |
| --- | --- | --- | --- | --- |
| 0 | 295.7, 176.2 | 18.7 px | 47.0 px | 17 |
| 1 | 360.9, 184.3 | 20.5 px | 44.7 px | 9 |

The pupil overlays lie on the visible pupils. Camera 1 is an important edge case: its outer iris is clipped by the
visible image boundary and partly covered by the eyelid. The iris overlay is a scale estimate using the pupil ellipse's
angle and axis ratio, not a measured complete iris contour. Neither image supplies physical size ground truth.

The original upstream live extractor at commit `a90bbc0aebdef72e1a4a6e860b3aa89dd82cff8b` was compiled separately and
also found both pupils and iris scales. Consequently this screenshot verifies that the FOS changes work on these
real images; it does not demonstrate that the upstream calibration failure has been fixed for a particular wearer.

## Video replay

The MP4 contains 725 encoded video frames at 30 fps over approximately 24.17 seconds. It is 720 by 486 pixels with
sample aspect ratio **40:33**, so its pixels are not square. The eye previews at the bottom left occupy approximately
`(5, 374, 90, 481)` and `(104, 374, 189, 481)` in encoded pixels. They are only 85 by 107 pixels each; at the correct
display aspect ratio they are nearly square. Their EyeTrackVR consumer crop is not documented in the video.

For a detection smoke check, each preview was reconstructed as a 400 by 400 grayscale square using bilinear scaling.
This is a consumer-preview assumption, not proof of the original crop or native geometry. A separate 512-stride
interpretation was explored and is not used for quantitative claims. The camera identities are unknown, so the
replay's L/R file names indicate display order only. No additional vertical flip was applied.

All 1,450 reconstructed camera images were processed with both FOS and the separately compiled upstream live
recorder. No camera hardware, OSC output or saved user calibration was altered. Example candidate detection counts:

| Video interval | Display camera | FOS pupil candidates | Upstream pupil candidates |
| --- | --- | --- | --- |
| 0–4 s, clearly open | 0 | 119 / 120 | 117 / 120 |
| 0–4 s, clearly open | 1 | 120 / 120 | 120 / 120 |
| 14–17 s, mostly open | 0 | 85 / 90 | 88 / 90 |
| 14–17 s, mostly open | 1 | 90 / 90 | 90 / 90 |
| 21–24 s, mostly open | 0 | 88 / 90 | 88 / 90 |
| 21–24 s, mostly open | 1 | 87 / 90 | 87 / 90 |

These counts are not accuracy scores: pupil visibility varies during eye movements and there are no frame-level
ground-truth labels. The clip contains useful closed-eye examples near 7.3–7.5 seconds, where both processors
reject the pupil in both views. Near closure/reopening and in very narrow eyes, both processors sometimes fit a
dark lid region as a pupil. For example, at 12.5 seconds camera 0's pupil is heavily obscured but both processors
still report a candidate, while camera 1 is rejected as closed. This remains a limitation of this demo check.

The source images are too small, stretched before display, interpolated and compressed to justify changing
production thresholds to fit every thumbnail. The FOS detector was not changed to fit this clip. The comparison
does not establish an overall improvement or equivalence in real wearer tracking.

## What is still unverified

- Physical pupil diameter and measured dilation accuracy: the clip has no known pupil sizes, exposure data or
  controlled bright/dark protocol, and the screenshot's iris is partly occluded.
- The guided close / normal / wide / normal / wide calibration: the demo contains no calibration cue labels,
  original capture timestamps or Valve gaze samples. A calibration result was not synthesized from it.
- Native Steam Frame capture, installation, OSC behavior and calibration with the user's own eyes.

The useful result is that real open-eye pupils and iris boundaries are detected, including an off-center screenshot
eye, while difficult closed/occluded frames remain visible limitations. Use the native recording replay workflow in
[CAMERA_VALIDATION.md](CAMERA_VALIDATION.md) for the next stronger check when a recording is available.
