"""The public Konsole installer validates a complete native release before running its installer."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import struct
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "get.sh"
DEFAULT_TAG = "v0.8.1-rc.1"
ASSET = "frameeyeosc-0.8.1-steamframe-aarch64.tar.gz"
BINARY_NAMES = ("frameeyeosc", "frameeyeosc-panel", "eyecam/eyecam-rec", "eyecam/eyecam-grab")


def elf_bytes(machine=183, loader=b"/lib/ld-linux-aarch64.so.1\0"):
    ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    header = struct.pack("<16sHHIQQQIHHHHHH", ident, 3, machine, 1, 0, 64, 0, 0,
                         64, 56, 1, 0, 0, 0)
    program = struct.pack("<IIQQQQQQ", 3, 4, 120, 0, 0, len(loader), len(loader), 1)
    return header + program + loader


ARM64_ELF = elf_bytes()
X86_ELF = elf_bytes(machine=62)


MOCK_CURL = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
urls = [argument for argument in args if argument.startswith("https://")]
with open(os.environ["FOS_BOOTSTRAP_REQUESTS"], "a", encoding="utf-8") as output:
    output.write(json.dumps({"urls": urls, "args": args}) + "\\n")
try:
    assert len(urls) == 1
    assert args[args.index("--proto") + 1] == "=https"
    assert args[args.index("--proto-redir") + 1] == "=https"
    assert "--insecure" not in args and "-k" not in args
    output_flag = "-o" if "-o" in args else "--output" if "--output" in args else None
    destination = Path(args[args.index(output_flag) + 1]) if output_flag else None
    routes = json.loads(Path(os.environ["FOS_BOOTSTRAP_ROUTES"]).read_text())
    route = routes[urls[0]]
except (AssertionError, KeyError, ValueError) as error:
    print(f"unexpected bootstrap fixture request: {error}", file=sys.stderr)
    sys.exit(97)
if route.get("exit", 0) == 0 or route.get("partial", False):
    if destination:
        shutil.copyfile(route["file"], destination)
    else:
        sys.stdout.buffer.write(Path(route["file"]).read_bytes())
        sys.stdout.buffer.flush()
if route.get("exit", 0) != 0:
    print("fixture download failed", file=sys.stderr)
if "-w" in args or "--write-out" in args:
    sys.stdout.write(f"{route.get('status', 200)} {route.get('effective_url', urls[0])}")
sys.exit(route.get("exit", 0))
"""


FIXTURE_INSTALLER = b"""#!/bin/sh
cd "$(dirname "$0")" || exit 90
exec python3 - "$@" <<'PY'
import json
import os
from pathlib import Path
import sys
failure = int(os.environ.get("FOS_BOOTSTRAP_INSTALLER_EXIT", "0"))
if failure:
    sys.exit(failure)
root = Path(os.environ["FOS_BOOTSTRAP_EFFECTS"])
sentinel = root / "installed-version"
(root / "installer-run.json").write_text(json.dumps({
    "args": sys.argv[1:], "previous_version": sentinel.read_text(), "cwd": Path.cwd().name,
    "camera_payload": Path("eyecam/eyecam-rec").is_file(),
}))
sentinel.write_text("0.8.1-rc.1\\n")
PY
"""


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fos-bootstrap-test-")
        self.scratch = Path(self.temp.name)
        self.commands = self.scratch / "bin"
        self.commands.mkdir()
        self.effects = self.scratch / "installed"
        self.effects.mkdir()
        self.sentinel = self.effects / "installed-version"
        self.sentinel.write_text("existing working install\n")
        self.settings = self.effects / "settings"
        self.settings.write_text("existing calibration and camera settings\n")
        self.record = self.effects / "installer-run.json"
        self.requests_file = self.scratch / "requests.jsonl"
        self.routes_file = self.scratch / "routes.json"
        self.archive = self.scratch / ASSET
        self.sums = self.scratch / "SHA256SUMS"
        self.temporary = self.scratch / "temporary"
        self.temporary.mkdir()
        self.environment = dict(os.environ)
        # HOME and XDG paths are changed only for the bootstrap subprocess and its fixture installer.
        self.environment.update({"HOME": str(self.scratch / "home"),
                                 "XDG_CACHE_HOME": str(self.scratch / "cache"),
                                 "XDG_CONFIG_HOME": str(self.scratch / "config"),
                                 "XDG_DATA_HOME": str(self.scratch / "data"),
                                 "XDG_RUNTIME_DIR": str(self.scratch / "runtime"),
                                 "TMPDIR": str(self.temporary),
                                 "PATH": str(self.commands) + os.pathsep + os.environ["PATH"],
                                 "FOS_BOOTSTRAP_REQUESTS": str(self.requests_file),
                                 "FOS_BOOTSTRAP_ROUTES": str(self.routes_file),
                                 "FOS_BOOTSTRAP_EFFECTS": str(self.effects)})
        self.command("curl", MOCK_CURL, shebang=False)
        self.command("uname", 'case "$1" in -s) echo Linux ;; -m) echo aarch64 ;; esac')
        self.command("getconf", "echo 'glibc 2.41'")
        for name in ("systemctl", "systemd-run", "sudo"):
            self.command(name, "echo unexpectedly-invoked-service-operation >&2; exit 98")
        self.make_archive()
        self.route_tag(DEFAULT_TAG)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, name, body, shebang=True):
        path = self.commands / name
        path.write_text(("#!/bin/sh\n" if shebang else "") + body + "\n")
        path.chmod(0o755)

    def route_tag(self, tag):
        base = f"https://github.com/MayoEDU/FOS/releases/download/{tag}/"
        self.expected_urls = {base + ASSET, base + "SHA256SUMS"}
        self.routes = {base + ASSET: {"file": str(self.archive)},
                       base + "SHA256SUMS": {"file": str(self.sums)}}
        self.write_routes()

    def write_routes(self):
        self.routes_file.write_text(json.dumps(self.routes))

    def make_archive(self, omitted=(), extra=None, binary_overrides=None):
        files = {name: (ARM64_ELF, 0o755) for name in BINARY_NAMES}
        files.update({"install.sh": (FIXTURE_INSTALLER, 0o755),
                      "frameeyeosc.service": (b"[Service]\n", 0o644),
                      "frameeyeosc.env.example": (b"# Settings\n", 0o644),
                      "frameeyeosc-panel.service": (b"[Service]\n", 0o644),
                      "frameeyeosc-panel.desktop": (b"[Desktop Entry]\n", 0o644),
                      "frame-update.sh": (b"#!/bin/sh\n", 0o755),
                      "eyecam/install_grab.sh": (b"#!/bin/sh\n", 0o755),
                      "eyecam/eyecam.service": (b"[Service]\n", 0o644),
                      "eyecam/NOTICE": (b"Eye camera notices\n", 0o644),
                      "eyecam/protocol_free.txt": (b"normal 10\n", 0o644)})
        for size in (48, 128, 256):
            files[f"icons/frameeyeosc-panel-{size}.png"] = (b"PNG fixture\n", 0o644)
        files.update(binary_overrides or {})
        for name in omitted:
            files.pop(name, None)
        with tarfile.open(self.archive, "w:gz") as archive:
            for name in ("frameeyeosc", "frameeyeosc/icons", "frameeyeosc/eyecam"):
                directory = tarfile.TarInfo(name)
                directory.type = tarfile.DIRTYPE
                directory.mode = 0o755
                archive.addfile(directory)
            for name, (contents, mode) in files.items():
                member = tarfile.TarInfo("frameeyeosc/" + name)
                member.size = len(contents)
                member.mode = mode
                archive.addfile(member, io.BytesIO(contents))
            if extra:
                name, kind = extra
                member = tarfile.TarInfo(name)
                member.type = kind
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    member.linkname = "../../escape"
                archive.addfile(member, io.BytesIO(b"") if kind == tarfile.REGTYPE else None)
        self.sums.write_text(hashlib.sha256(self.archive.read_bytes()).hexdigest() + "  " + ASSET + "\n")

    def run_bootstrap(self, *arguments):
        result = subprocess.run(["bash", str(BOOTSTRAP), *arguments], env=self.environment,
                                cwd=self.scratch, capture_output=True, text=True, timeout=15)
        self.assertNotIn("unexpectedly-invoked-service-operation", result.stderr)
        self.assertNotIn("unexpected bootstrap fixture request", result.stderr)
        self.assertEqual(self.settings.read_text(), "existing calibration and camera settings\n")
        self.assertEqual(list(self.temporary.iterdir()), [], "bootstrap left temporary payloads behind")
        return result

    def requests(self):
        if not self.requests_file.exists():
            return []
        return [json.loads(line) for line in self.requests_file.read_text().splitlines()]

    def assert_no_install(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.sentinel.read_text(), "existing working install\n")
        self.assertFalse(self.record.exists())

    def assert_secure_requests(self):
        requests = self.requests()
        self.assertTrue(requests)
        self.assertEqual({request["urls"][0] for request in requests}, self.expected_urls)
        for request in requests:
            arguments = request["args"]
            self.assertEqual(arguments[arguments.index("--proto") + 1], "=https")
            self.assertEqual(arguments[arguments.index("--proto-redir") + 1], "=https")
            self.assertNotIn("--insecure", arguments)
            self.assertNotIn("-k", arguments)

    def test_default_prerelease_installs_complete_payload_with_panel(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(self.record.read_text())
        self.assertEqual(record["args"], ["--with-panel"])
        self.assertEqual(record["previous_version"], "existing working install\n")
        self.assertEqual(record["cwd"], "frameeyeosc")
        self.assertTrue(record["camera_payload"])
        self.assert_secure_requests()

    def test_explicit_tag_requests_only_fos_release_assets(self):
        tag = "v0.8.1-rc.2"
        self.route_tag(tag)
        result = self.run_bootstrap("--tag", tag)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_secure_requests()

    def test_corrupt_download_never_runs_installer(self):
        self.archive.write_bytes(self.archive.read_bytes() + b"corrupt download")
        result = self.run_bootstrap()
        self.assert_no_install(result)
        self.assert_secure_requests()

    def test_missing_archive_checksum_never_runs_installer(self):
        self.sums.write_text("0" * 64 + "  unrelated-asset.tar.gz\n")
        result = self.run_bootstrap()
        self.assert_no_install(result)

    def test_checksum_download_failure_never_runs_installer(self):
        sums_url = next(url for url in self.routes if url.endswith("SHA256SUMS"))
        self.routes[sums_url].update({"status": 404, "exit": 22})
        self.write_routes()
        result = self.run_bootstrap()
        self.assert_no_install(result)

    def test_interrupted_archive_download_can_be_retried(self):
        archive_url = next(url for url in self.routes if url.endswith(ASSET))
        self.routes[archive_url].update({"exit": 18, "partial": True})
        self.write_routes()
        result = self.run_bootstrap()
        self.assert_no_install(result)
        self.assertIn("run the same command again", result.stderr)
        self.routes[archive_url].update({"exit": 0})
        self.write_routes()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.record.read_text())["previous_version"], "existing working install\n")

    def test_unavailable_temporary_directory_fails_before_network(self):
        self.environment["TMPDIR"] = str(self.scratch / "missing-directory")
        result = self.run_bootstrap()
        self.assert_no_install(result)
        self.assertEqual(self.requests(), [])
        self.assertIn("Check TMPDIR", result.stderr)

    def test_installer_failure_preserves_status_and_reports_retry(self):
        self.environment["FOS_BOOTSTRAP_INSTALLER_EXIT"] = "41"
        result = self.run_bootstrap()
        self.assert_no_install(result)
        self.assertEqual(result.returncode, 41)
        self.assertIn("installer error above", result.stderr)

    def test_documented_launcher_reports_failed_script_download(self):
        # A syntactically complete early prefix must not make a failed curl look successful.
        prefix = self.scratch / "partial-get.sh"
        prefix.write_bytes(BOOTSTRAP.read_bytes().split(b"version=", 1)[0])
        raw_url = "https://raw.githubusercontent.com/MayoEDU/FOS/main/get.sh"
        self.routes[raw_url] = {"file": str(prefix), "exit": 18, "partial": True}
        self.write_routes()
        guide = (ROOT / "docs/FORK.md").read_text()
        command = guide.split("```sh\n", 1)[1].split("```", 1)[0]
        result = subprocess.run(["bash", "-c", command], env=self.environment,
                                cwd=self.scratch, capture_output=True, text=True, timeout=15)
        self.assert_no_install(result)
        self.assertEqual(result.returncode, 18)
        self.assertEqual(list(self.temporary.iterdir()), [])

    def test_missing_camera_payload_never_runs_installer(self):
        for file in ("eyecam/eyecam-rec", "eyecam/eyecam-grab", "eyecam/install_grab.sh",
                     "eyecam/eyecam.service", "eyecam/NOTICE", "eyecam/protocol_free.txt"):
            with self.subTest(file=file):
                self.make_archive(omitted=(file,))
                result = self.run_bootstrap()
                self.assert_no_install(result)

    def test_missing_panel_payload_never_runs_installer(self):
        for file in ("frameeyeosc-panel", "frameeyeosc-panel.service", "frameeyeosc-panel.desktop",
                     "icons/frameeyeosc-panel-48.png", "icons/frameeyeosc-panel-128.png",
                     "icons/frameeyeosc-panel-256.png"):
            with self.subTest(file=file):
                self.make_archive(omitted=(file,))
                result = self.run_bootstrap()
                self.assert_no_install(result)

    def test_unsafe_archive_members_never_run_installer(self):
        for name, kind in (("../../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("frameeyeosc/link", tarfile.SYMTYPE), ("frameeyeosc/hard", tarfile.LNKTYPE),
                           ("frameeyeosc/device", tarfile.CHRTYPE),
                           ("frameeyeosc/frameeyeosc.service", tarfile.REGTYPE)):
            with self.subTest(name=name, kind=kind):
                self.make_archive(extra=(name, kind))
                result = self.run_bootstrap()
                self.assert_no_install(result)
                self.assertFalse((self.scratch / "escape").exists())

    def test_wrong_architecture_or_nonexecutable_binary_never_runs_installer(self):
        for binary in BINARY_NAMES:
            for contents, mode in ((X86_ELF, 0o755), (ARM64_ELF, 0o644)):
                with self.subTest(binary=binary, mode=mode):
                    self.make_archive(binary_overrides={binary: (contents, mode)})
                    result = self.run_bootstrap()
                    self.assert_no_install(result)

    def test_foreign_loader_or_missing_interpreter_never_runs_installer(self):
        for contents in (elf_bytes(loader=b"/lib/ld-musl-aarch64.so.1\0"), ARM64_ELF[:64]):
            with self.subTest(size=len(contents)):
                self.make_archive(binary_overrides={"frameeyeosc": (contents, 0o755)})
                result = self.run_bootstrap()
                self.assert_no_install(result)

    def test_wrong_host_architecture_fails_before_network(self):
        self.command("uname", 'case "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac')
        result = self.run_bootstrap()
        self.assert_no_install(result)
        self.assertEqual(self.requests(), [])

    def test_non_linux_host_fails_before_network(self):
        self.command("uname", 'case "$1" in -s) echo Darwin ;; -m) echo aarch64 ;; esac')
        result = self.run_bootstrap()
        self.assert_no_install(result)
        self.assertEqual(self.requests(), [])

    def test_missing_glibc_fails_before_network(self):
        self.command("getconf", "exit 1")
        result = self.run_bootstrap()
        self.assert_no_install(result)
        self.assertEqual(self.requests(), [])


if __name__ == "__main__":
    unittest.main()
