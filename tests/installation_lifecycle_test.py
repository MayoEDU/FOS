"""Run the real user installer against isolated child files and a fixture service manager.

Fixture ARM64 payloads are never executed. Test copies relocate the OpenVR presence check and helper roots;
production paths and architecture checks remain unchanged. Simulated root identity never grants privileges.
"""

import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UNITS = ("frameeyeosc.service", "frameeyeosc-panel.service", "eyecam.service")


class InstallationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fos-lifecycle-")
        self.scratch = Path(self.temp.name)
        self.user = self.scratch / "user"
        self.user.mkdir()
        self.commands = self.scratch / "commands"
        self.commands.mkdir()
        self.states = self.scratch / "services.json"
        self.states.write_text("{}")
        self.log = self.scratch / "services.log"
        self.library = self.scratch / "libopenvr_api.so"
        self.library.touch()
        self.root_helper = self.scratch / "root-helper"
        self.old_helper = self.scratch / "old-root-helper/eyecam-grab"
        self.environment = dict(os.environ)
        self.environment.pop("FRAMEEYEOSC_NO_SYSTEMCTL", None)
        # HOME changes only in child processes. The task shell and actual user services are untouched.
        self.environment["HOME"] = str(self.user)
        self.environment["XDG_CONFIG_HOME"] = str(self.user / ".config")
        self.environment["XDG_DATA_HOME"] = str(self.user / ".local/share")
        self.environment["XDG_CACHE_HOME"] = str(self.user / ".cache")
        self.environment["TMPDIR"] = str(self.scratch)
        self.environment["FOS_TEST_SERVICES"] = str(self.states)
        self.environment["FOS_TEST_SERVICE_LOG"] = str(self.log)
        self.environment["PATH"] = str(self.commands) + os.pathsep + os.environ["PATH"]
        self.command("uname", 'case "$1" in -s) echo Linux ;; -m) echo aarch64 ;; esac')
        self.command("getconf", "echo 'glibc 2.41'")
        self.command("sleep", "exit 0")
        self.command("update-desktop-database", "echo unrelated-global-cache-touched >&2; exit 99")
        self.command("sudo", "echo unexpected-privilege-request >&2; exit 99")
        service_code = r'''
import json, os, sys
from pathlib import Path
path = Path(os.environ["FOS_TEST_SERVICES"])
states = json.loads(path.read_text())
args = [arg for arg in sys.argv[1:] if arg not in ("--user", "--no-pager")]
with Path(os.environ["FOS_TEST_SERVICE_LOG"]).open("a") as log:
    log.write(json.dumps(args) + "\n")
action = args[0]
unit = args[-1] if len(args) > 1 else ""
if unit and unit not in ("frameeyeosc.service", "frameeyeosc-panel.service", "eyecam.service", "frameeyeosc-update.service"):
    sys.exit("unexpected unrelated service: " + unit)
state = states.setdefault(unit, {"enabled": "not-found", "active": False})
if action == "is-enabled":
    print(state["enabled"])
    sys.exit(0 if state["enabled"] == "enabled" else 1)
if action == "is-active":
    print("active" if state["active"] else "inactive")
    sys.exit(0 if state["active"] else 3)
if action == "enable": state["enabled"] = "enabled"
if action == "disable":
    state["enabled"] = "disabled"
    if "--now" in args: state["active"] = False
if action == "stop": state["active"] = False
if action == "restart": state["active"] = True
if os.environ.get("FOS_TEST_FAIL_RESTART") == "1" and action == "try-restart": sys.exit(42)
path.write_text(json.dumps(states))
'''
        systemctl = self.commands / "systemctl"
        systemctl.write_text("#!/usr/bin/env python3\n" + service_code)
        systemctl.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, name, body):
        command = self.commands / name
        command.write_text("#!/bin/sh\n" + body + "\n")
        command.chmod(0o755)

    def release(self, version):
        release = self.scratch / ("release-" + version)
        release.mkdir()
        script = (ROOT / "install.sh").read_text()
        marker = "/opt/steamvr/bin/linuxarm64/libopenvr_api.so"
        self.assertEqual(script.count(marker), 1)
        helper_marker = "eyecam_root_dir=/home/.eyecam"
        self.assertEqual(script.count(helper_marker), 1)
        script = script.replace(marker, str(self.library)).replace(
            helper_marker, "eyecam_root_dir=" + shlex.quote(str(self.root_helper)))
        (release / "install.sh").write_text(script)
        (release / "eyecam").mkdir()
        (release / "icons").mkdir()
        for file in ("frameeyeosc", "frameeyeosc-panel", "eyecam/eyecam-rec", "eyecam/eyecam-grab"):
            binary = release / file
            binary.write_bytes(bytes.fromhex("7f454c460201010000000000000000000200b700") + version.encode())
            binary.chmod(0o755)
        sources = {
            "frameeyeosc.service": "contrib/frameeyeosc.service",
            "frameeyeosc.env.example": "contrib/frameeyeosc.env.example",
            "frameeyeosc-panel.service": "panel/contrib/frameeyeosc-panel.service",
            "frameeyeosc-panel.desktop": "panel/contrib/frameeyeosc-panel.desktop",
            "frame-update.sh": "vendor/frame-updater/frame-update.sh",
            "eyecam/install_grab.sh": "tools/eyecam/install_grab.sh",
            "eyecam/eyecam.service": "tools/eyecam/eyecam.service",
            "eyecam/NOTICE": "tools/eyecam/NOTICE",
        }
        for destination, source in sources.items():
            shutil.copyfile(ROOT / source, release / destination)
        helper_script = (release / "eyecam/install_grab.sh").read_text()
        helper_script = helper_script.replace("DEST_DIR=/home/.eyecam", "DEST_DIR=" + shlex.quote(str(self.root_helper)))
        helper_script = helper_script.replace("OLD_DEST=/var/lib/eyecam/eyecam-grab",
                                             "OLD_DEST=" + shlex.quote(str(self.old_helper)))
        (release / "eyecam/install_grab.sh").write_text(helper_script)
        (release / "eyecam/protocol_fixture.txt").write_text(version)
        for size in (48, 128, 256):
            shutil.copyfile(ROOT / f"panel/contrib/icons/frameeyeosc-panel-{size}.png",
                            release / f"icons/frameeyeosc-panel-{size}.png")
        return release

    def run_script(self, script, *args, expected=0):
        result = subprocess.run(["bash", str(script), *args], env=self.environment,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertNotIn("unrelated-global-cache-touched", result.stderr)
        self.assertNotIn("unexpected-privilege-request", result.stderr)
        return result

    def own_files(self):
        return {str(path.relative_to(self.user)): path.read_bytes()
                for path in self.user.rglob("*") if path.is_file() and not path.is_symlink()}

    def configure(self):
        for path, content in {
            ".config/frameeyeosc/config.json": '{"target":"192.0.2.5","camera_lids":true}',
            ".config/frameeyeosc/calibration": "learned lid values",
            ".config/frameeyeosc/env": "FRAMEEYEOSC_ARGS=--port 9001\n",
            ".config/eyecam/settings.json": '{"widen_sensitivity":0.7}',
            ".config/eyecam/calib.json": '{"my_calibration":true}',
            "eyecam/personal-recording.raw": "user data",
            ".local/lib/eyecam/protocol_personal.txt": "personal protocol",
        }.items():
            destination = self.user / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content)

    def test_update_preserves_config_calibration_and_disabled_service_states(self):
        first = self.release("v1")
        self.run_script(first / "install.sh", "--with-panel")
        states = json.loads(self.states.read_text())
        self.assertTrue(all(states[unit]["enabled"] == "enabled" for unit in UNITS))
        self.configure()
        states["frameeyeosc.service"] = {"enabled": "disabled", "active": True}
        states["frameeyeosc-panel.service"] = {"enabled": "disabled", "active": False}
        states["eyecam.service"] = {"enabled": "disabled", "active": False}
        self.states.write_text(json.dumps(states))
        self.log.write_text("")
        before = self.own_files()
        update = self.release("v2")
        self.run_script(update / "install.sh", "--with-panel")
        after = self.own_files()
        for path in before:
            if path.startswith((".config/frameeyeosc/", ".config/eyecam/", "eyecam/")):
                self.assertEqual(before[path], after[path], path)
        self.assertEqual((self.user / ".local/lib/eyecam/protocol_personal.txt").read_text(), "personal protocol")
        self.assertTrue((self.user / ".local/bin/frameeyeosc").read_bytes().endswith(b"v2"))
        states = json.loads(self.states.read_text())
        self.assertTrue(all(states[unit]["enabled"] == "disabled" for unit in UNITS))
        self.assertTrue(states[UNITS[0]]["active"])
        self.assertFalse(states[UNITS[1]]["active"])
        self.assertFalse(states[UNITS[2]]["active"])
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertFalse(any(call[0] == "enable" for call in calls))

    def test_failed_file_copy_rolls_back_all_previously_replaced_files(self):
        first = self.release("v1")
        self.run_script(first / "install.sh", "--with-panel")
        self.configure()
        before = self.own_files()
        real_install = shutil.which("install")
        self.command("install", f"""for arg do
    case "$arg" in */eyecam-rec.frameeyeosc-new.*) exit 42 ;; esac
done
exec '{real_install}' "$@" """)
        update = self.release("v2")
        result = self.run_script(update / "install.sh", "--with-panel", expected=42)
        self.assertIn("restored the previous app files", result.stderr)
        self.assertEqual(before, self.own_files())

    def test_saved_uninstaller_removes_only_owned_payload_and_preserves_personal_data(self):
        first = self.release("v1")
        self.run_script(first / "install.sh", "--with-panel")
        self.configure()
        unrelated = (
            ".local/bin/another-app", ".local/lib/another-app/data", ".cache/another-app/cache",
            ".config/systemd/user/steamvr.service", ".config/systemd/user/another-app.service",
            ".local/share/applications/another-app.desktop", ".local/share/frameeyeosc/notes.txt",
            ".local/share/icons/hicolor/48x48/apps/another-app.png",
        )
        for name in unrelated:
            path = self.user / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unrelated sentinel")
        shutil.rmtree(first)
        self.run_script(self.user / ".local/share/frameeyeosc/install.sh", "--uninstall")
        for name in unrelated:
            self.assertEqual((self.user / name).read_text(), "unrelated sentinel", name)
        for name in (".local/bin/frameeyeosc", ".local/bin/frameeyeosc-panel", ".local/lib/eyecam/eyecam-rec",
                     ".local/lib/eyecam/eyecam-grab", ".local/lib/eyecam/protocol_fixture.txt",
                     ".local/share/frameeyeosc/install.sh", ".local/share/frameeyeosc/frame-update.sh"):
            self.assertFalse((self.user / name).exists(), name)
        for unit in UNITS:
            self.assertFalse((self.user / ".config/systemd/user" / unit).exists(), unit)
        self.assertTrue((self.user / ".config/frameeyeosc/config.json").exists())
        self.assertTrue((self.user / ".config/eyecam/calib.json").exists())
        self.assertTrue((self.user / "eyecam/personal-recording.raw").exists())
        self.assertTrue((self.user / ".local/lib/eyecam/protocol_personal.txt").exists())

    def test_failed_service_restart_restores_payload_and_previous_running_services(self):
        first = self.release("v1")
        self.run_script(first / "install.sh", "--with-panel")
        self.configure()
        before = self.own_files()
        states_before = json.loads(self.states.read_text())
        self.environment["FOS_TEST_FAIL_RESTART"] = "1"
        update = self.release("v2")
        result = self.run_script(update / "install.sh", "--with-panel", expected=42)
        self.assertIn("restored the previous app files", result.stderr)
        self.assertEqual(before, self.own_files())
        states_after = json.loads(self.states.read_text())
        for unit in UNITS:
            self.assertEqual(states_before[unit], states_after[unit], unit)

    def test_update_preserves_masks_and_uninstall_removes_only_own_fallback_units(self):
        first = self.release("v1")
        self.run_script(first / "install.sh", "--with-panel")
        states = json.loads(self.states.read_text())
        for unit in UNITS:
            path = self.user / ".config/systemd/user" / unit
            path.unlink()
            path.symlink_to("/dev/null")
            states[unit] = {"enabled": "masked", "active": False}
        self.states.write_text(json.dumps(states))
        self.log.write_text("")
        update = self.release("v2")
        self.run_script(update / "install.sh", "--with-panel")
        for unit in UNITS:
            path = self.user / ".config/systemd/user" / unit
            self.assertTrue(path.is_symlink())
            self.assertEqual(os.readlink(path), "/dev/null")
            self.assertTrue((self.user / ".local/share/systemd/user" / unit).is_file())
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertFalse(any(call[0] in ("enable", "restart", "try-restart") for call in calls))
        unrelated = self.user / ".local/share/systemd/user/another-app.service"
        unrelated.write_text("unrelated unit")
        self.run_script(self.user / ".local/share/frameeyeosc/install.sh", "--uninstall")
        self.assertEqual(unrelated.read_text(), "unrelated unit")
        for unit in UNITS:
            self.assertFalse((self.user / ".config/systemd/user" / unit).is_symlink())
            self.assertFalse((self.user / ".local/share/systemd/user" / unit).exists())

    def test_purge_removes_only_own_settings_and_keeps_recordings(self):
        first = self.release("v1")
        self.run_script(first / "install.sh", "--with-panel")
        self.configure()
        unrelated = self.user / ".config/another-app/settings.json"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("unrelated settings")
        self.run_script(self.user / ".local/share/frameeyeosc/install.sh", "--uninstall", "--purge")
        self.assertFalse((self.user / ".config/frameeyeosc").exists())
        self.assertFalse((self.user / ".config/eyecam").exists())
        self.assertEqual(unrelated.read_text(), "unrelated settings")
        self.assertTrue((self.user / "eyecam/personal-recording.raw").exists())

    def test_helper_requires_explicit_dedicated_uninstall_and_preserves_other_root_files(self):
        first = self.release("v1")
        self.run_script(first / "install.sh", "--with-panel")
        self.root_helper.mkdir()
        (self.root_helper / "eyecam-grab").write_text("owned privileged helper")
        (self.root_helper / "unrelated-file").write_text("unrelated root file")
        self.old_helper.parent.mkdir()
        self.old_helper.write_text("owned previous helper")
        (self.old_helper.parent / "unrelated-file").write_text("unrelated legacy root file")
        shutil.rmtree(first)
        result = self.run_script(self.user / ".local/share/frameeyeosc/install.sh", "--uninstall")
        self.assertTrue((self.root_helper / "eyecam-grab").exists())
        command = next(shlex.split(line.strip()) for line in result.stdout.splitlines()
                       if line.strip().startswith("sudo "))
        self.assertEqual(command[0], "sudo")
        self.assertEqual(command[-1], "--uninstall")
        retained = Path(command[1])
        self.assertEqual(retained.parent, self.scratch)
        self.assertEqual(retained.stat().st_mode & 0o777, 0o700)
        self.command("id", "echo 0")
        self.command("setcap", "exit 0")
        # No sudo is executed. The original helper algorithm runs against task-owned fixture paths.
        self.run_script(retained, "--uninstall")
        self.assertFalse((self.root_helper / "eyecam-grab").exists())
        self.assertFalse(self.old_helper.exists())
        self.assertEqual((self.root_helper / "unrelated-file").read_text(), "unrelated root file")
        self.assertEqual((self.old_helper.parent / "unrelated-file").read_text(), "unrelated legacy root file")


if __name__ == "__main__":
    unittest.main()
