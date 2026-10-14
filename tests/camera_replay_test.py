"""Exercise the recorder CLI with made-up Steam Frame camera files, never personal eye images.

Build tools/eyecam in release mode before running this suite. FOS_EYECAM_BIN can select another built binary.
"""

import csv
import math
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SIDE = 400
FRAMES_PER_SIZE = 40
RADII = (14, 22, 30, 40)


def eye_frame(radius, rim=12):
    image = bytearray(SIDE * SIDE)
    for y in range(SIDE):
        for x in range(SIDE):
            distance = math.hypot(x - 250, y - 200)
            value = 150 if y < 155 else 120
            if distance < 55 and y >= 155:
                value = 70
            if distance < radius:
                value = round(12 + (rim - 12) * (distance / radius) ** 2)
            if x >= 350:
                value = 4
            image[y * SIDE + x] = value
    # A small infrared glint moves with the pupil; the morphology should remove it.
    glint_x = 250 + radius // 4
    for y in range(197, 202):
        image[y * SIDE + glint_x : y * SIDE + glint_x + 5] = bytes([250]) * 5
    return bytes(image)


class CameraReplayTest(unittest.TestCase):
    def test_dilation_survives_the_recording_reader_and_live_engine(self):
        self.check_replay(rim=12)

    def test_dilation_with_uneven_pupil_illumination(self):
        self.check_replay(rim=35)

    def check_replay(self, rim):
        binary = Path(os.environ.get("FOS_EYECAM_BIN", ROOT / "tools/eyecam/target/release/eyecam-rec"))
        self.assertTrue(binary.is_file(), "build eyecam-rec --release before running replay tests")
        with tempfile.TemporaryDirectory(prefix="fos-camera-replay-") as temporary:
            folder = Path(temporary)
            # Match the actual recording: anatomical left eye is stored upside down, right eye upright.
            (folder / "meta.txt").write_text("frame_width=400\neye_files=anatomical\nupside_down_eye=L\n")
            with (folder / "frames.csv").open("w", newline="") as frame_file:
                writer = csv.writer(frame_file)
                writer.writerow(("eye", "eye_index", "t_cam"))
                with (folder / "eye_L.raw").open("wb") as left, (folder / "eye_R.raw").open("wb") as right:
                    index = 0
                    for radius in RADII:
                        upright = eye_frame(radius, rim)
                        flipped = b"".join(upright[y * SIDE : (y + 1) * SIDE] for y in reversed(range(SIDE)))
                        for _ in range(FRAMES_PER_SIZE):
                            left.write(flipped)
                            right.write(upright)
                            for eye in ("L", "R"):
                                writer.writerow((eye, index, 100 + index / 15))
                            index += 1
            output = folder / "measurements.csv"
            result = subprocess.run(
                [str(binary.resolve()), "--replay", str(folder), "--out", str(output)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with output.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2 * FRAMES_PER_SIZE * len(RADII))
            for eye in ("L", "R"):
                previous = 0
                for block, radius in enumerate(RADII):
                    # Assess the settled end of each segment, allowing the causal median to catch up.
                    end = (block + 1) * FRAMES_PER_SIZE
                    segment = [row for row in rows if row["eye"] == eye and end - 10 <= int(row["eye_index"]) < end]
                    self.assertEqual(len(segment), 10)
                    self.assertTrue(all(row["ok_pupil"] == "1" for row in segment))
                    iris = statistics.median(float(row["r"]) for row in segment)
                    diameter = statistics.median(float(row["pupil_mm"]) for row in segment)
                    self.assertAlmostEqual(iris, 55, delta=3)
                    self.assertAlmostEqual(diameter, 11.8 * radius / 55, delta=0.4)
                    self.assertGreater(diameter, previous)
                    previous = diameter


if __name__ == "__main__":
    unittest.main()
