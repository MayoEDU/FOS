"""Release/install preflight checks must fail before invoking tools or altering an existing install."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseScriptsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fos-release-test-")
        self.scratch = Path(self.temp.name)
        self.commands = self.scratch / "bin"
        self.commands.mkdir()
        self.environment = dict(os.environ)
        self.environment["PATH"] = str(self.commands) + os.pathsep + os.environ["PATH"]
        self.environment["FRAMEEYEOSC_NO_SYSTEMCTL"] = "1"
        self.environment["XDG_CONFIG_HOME"] = str(self.scratch / "config")
        self.environment["XDG_CACHE_HOME"] = str(self.scratch / "cache")
        self.environment["XDG_DATA_HOME"] = str(self.scratch / "data")
        self.command("cargo", "echo unexpectedly-invoked >&2; exit 98")
        self.command("install", "echo unexpectedly-invoked >&2; exit 98")
        self.command("uname", 'case "$1" in -s) echo Linux ;; -m) echo aarch64 ;; esac')
        self.command("getconf", "echo 'glibc 2.41'")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, name, body):
        path = self.commands / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, path, *args):
        result = subprocess.run(["bash", str(path), *args], env=self.environment,
                                capture_output=True, text=True, timeout=5)
        self.assertNotIn("unexpectedly-invoked", result.stderr)
        self.assertFalse((self.scratch / "config").exists())
        self.assertFalse((self.scratch / "data").exists())
        return result

    def payload(self):
        release = self.scratch / "release"
        release.mkdir()
        shutil.copyfile(ROOT / "install.sh", release / "install.sh")
        return release

    def test_package_rejects_pc_before_build(self):
        self.command("uname", 'case "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac')
        result = self.run_script(ROOT / "scripts/package.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must run on a Steam Frame", result.stderr)

    def test_package_rejects_musl_before_build(self):
        self.command("getconf", "exit 1")
        result = self.run_script(ROOT / "scripts/package.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("native glibc", result.stderr)

    def test_install_rejects_incomplete_archive(self):
        release = self.payload()
        result = self.run_script(release / "install.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing release file: frameeyeosc", result.stderr)

    def test_install_rejects_foreign_binary_before_changes(self):
        release = self.payload()
        binary = release / "frameeyeosc"
        # ELF64 little-endian x86_64, executable mode: architecture, not permission, must reject it.
        binary.write_bytes(bytes.fromhex("7f454c4602010100000000000000000002003e00"))
        binary.chmod(0o755)
        result = self.run_script(release / "install.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not an executable Linux ARM64 release binary", result.stderr)

    def test_install_validates_service_before_replacing_binary(self):
        release = self.payload()
        binary = release / "frameeyeosc"
        binary.write_bytes(bytes.fromhex("7f454c460201010000000000000000000200b700"))
        binary.chmod(0o755)
        result = self.run_script(release / "install.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing release file: frameeyeosc.service", result.stderr)

    def test_install_requires_updater_before_replacing_binary(self):
        release = self.payload()
        binary = release / "frameeyeosc"
        binary.write_bytes(bytes.fromhex("7f454c460201010000000000000000000200b700"))
        binary.chmod(0o755)
        (release / "frameeyeosc.service").touch()
        (release / "frameeyeosc.env.example").touch()
        result = self.run_script(release / "install.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing release file: frame-update.sh", result.stderr)

    def test_install_rejects_missing_entire_camera_payload_before_changes(self):
        release = self.payload()
        binary = release / "frameeyeosc"
        binary.write_bytes(bytes.fromhex("7f454c460201010000000000000000000200b700"))
        binary.chmod(0o755)
        (release / "frameeyeosc.service").touch()
        (release / "frameeyeosc.env.example").touch()
        (release / "frame-update.sh").write_text("#!/bin/sh\n")
        result = self.run_script(release / "install.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing release file: eyecam/eyecam-rec", result.stderr)


if __name__ == "__main__":
    unittest.main()
