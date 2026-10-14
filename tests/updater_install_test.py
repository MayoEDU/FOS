"""Exercise the shipped updater's downloads and installs without network or host changes."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "vendor/frame-updater/frame-update.sh"
APP = "frameeyeosc"
VERSION = "0.9.0"
ASSET = f"frameeyeosc-{VERSION}-steamframe-aarch64.tar.gz"
API_URL = "https://api.github.com/repos/MayoEDU/FOS/releases/latest"
RELEASE_URL = f"https://github.com/MayoEDU/FOS/releases/tag/v{VERSION}"
ASSET_URL = f"https://github.com/MayoEDU/FOS/releases/download/v{VERSION}/{ASSET}"
SUMS_URL = f"https://github.com/MayoEDU/FOS/releases/download/v{VERSION}/SHA256SUMS"


# Only HTTP transport is mocked. The vendor script still validates HTTPS URLs, hashes the
# downloaded archive with sha256sum, checks its members, and extracts it with the real tar.
MOCK_CURL = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
url = args[-1]
with open(os.environ["FOS_UPDATE_TEST_REQUESTS"], "a", encoding="utf-8") as output:
    output.write(json.dumps({"url": url, "args": args}) + "\\n")
try:
    assert args[args.index("--proto") + 1] == "=https"
    assert args[args.index("--proto-redir") + 1] == "=https"
    assert args[args.index("-w") + 1] == "%{http_code} %{url_effective}"
    assert "--insecure" not in args and "-k" not in args
    destination = Path(args[args.index("-o") + 1])
    routes = json.loads(Path(os.environ["FOS_UPDATE_TEST_ROUTES"]).read_text())
    route = routes[url]
except (AssertionError, KeyError, ValueError) as error:
    print(f"unexpected fixture request: {error}", file=sys.stderr)
    sys.exit(97)
status = route.get("status", 200)
effective_url = route.get("effective_url", url)
if route.get("exit", 0) == 0:
    shutil.copyfile(route["file"], destination)
else:
    print("fixture download failed", file=sys.stderr)
sys.stdout.write(f"{status} {effective_url}")
sys.exit(route.get("exit", 0))
"""


# A release-owned installer with explicit, observable effects confined to the test folder.
# It deliberately does not call this repository's installer or any service-management tools.
FIXTURE_INSTALLER = """#!/bin/sh
exec python3 - "$@" <<'PY'
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["FOS_UPDATE_TEST_EFFECTS"])
sentinel = root / "installed-version"
record = {
    "args": sys.argv[1:],
    "previous_version": sentinel.read_text(),
    "payload": Path("payload.txt").read_text(),
}
(root / "installer-run.json").write_text(json.dumps(record))
sentinel.write_text("0.9.0\\n")
if "--with-panel" in sys.argv[1:]:
    (root / "panel-installed").write_text("yes\\n")
PY
"""


class UpdaterInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fos-updater-test-")
        self.scratch = Path(self.temp.name)
        self.bin_dir = self.scratch / "bin"
        self.bin_dir.mkdir()
        self.effects = self.scratch / "installed"
        self.effects.mkdir()
        self.sentinel = self.effects / "installed-version"
        self.sentinel.write_text("0.8.0\n")
        self.installer_record = self.effects / "installer-run.json"
        self.requests_file = self.scratch / "requests.jsonl"
        self.routes_file = self.scratch / "routes.json"
        self.release_file = self.scratch / "release.json"
        self.archive = self.scratch / ASSET
        self.sums = self.scratch / "SHA256SUMS"
        self.config_dir = self.scratch / "config" / APP
        self.cache_dir = self.scratch / "cache" / APP
        self.state_file = self.cache_dir / "update-state.json"

        self.environment = dict(os.environ)
        # HOME is changed only for this subprocess; the caller's environment is untouched.
        self.environment["HOME"] = str(self.scratch / "home")
        self.environment["PATH"] = str(self.bin_dir) + os.pathsep + os.environ["PATH"]
        for name in ("CONFIG", "CACHE", "DATA", "RUNTIME"):
            self.environment[f"XDG_{name}_HOME" if name != "RUNTIME" else "XDG_RUNTIME_DIR"] = str(
                self.scratch / name.lower())
        for name in ("FRAME_UPDATE_API_URL", "FRAME_UPDATE_ALLOW_INSECURE", "FRAME_UPDATE_DETACHED",
                     "FRAME_UPDATE_CHECK_TTL", "FRAME_UPDATE_ERROR_TTL"):
            self.environment.pop(name, None)
        self.environment["FOS_UPDATE_TEST_EFFECTS"] = str(self.effects)
        self.environment["FOS_UPDATE_TEST_REQUESTS"] = str(self.requests_file)
        self.environment["FOS_UPDATE_TEST_ROUTES"] = str(self.routes_file)

        curl = self.bin_dir / "curl"
        curl.write_text(MOCK_CURL)
        curl.chmod(0o755)
        # Unexpected detachment or service operations must fail, even on a capable host.
        for name in ("systemctl", "systemd-run"):
            path = self.bin_dir / name
            path.write_text("#!/bin/sh\necho unexpected-service-operation >&2\nexit 98\n")
            path.chmod(0o755)
        self.assertIsNotNone(shutil.which("tar"))
        self.assertIsNotNone(shutil.which("sha256sum"))

        self.make_archive()
        self.release = {
            "tag_name": f"v{VERSION}",
            "html_url": RELEASE_URL,
            "draft": False,
            "prerelease": False,
            "body": "Steam Frame tracking improvements.",
            "assets": [
                {"name": ASSET, "browser_download_url": ASSET_URL},
                {"name": "SHA256SUMS", "browser_download_url": SUMS_URL},
            ],
        }
        self.write_release()
        self.routes = {
            API_URL: {"file": str(self.release_file)},
            ASSET_URL: {"file": str(self.archive)},
            SUMS_URL: {"file": str(self.sums)},
        }
        self.write_routes()

    def tearDown(self):
        self.temp.cleanup()

    def write_release(self):
        self.release_file.write_text(json.dumps(self.release))

    def write_routes(self):
        self.routes_file.write_text(json.dumps(self.routes))

    def make_archive(self, extra_path=None, include_installer=True):
        with tarfile.open(self.archive, "w:gz") as archive:
            files = {"frameeyeosc-release/payload.txt": b"Steam Frame fixture\n"}
            if include_installer:
                files["frameeyeosc-release/install.sh"] = FIXTURE_INSTALLER.encode()
            if extra_path:
                files[extra_path] = b"unsafe member\n"
            for name, contents in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(contents)
                member.mode = 0o755 if name.endswith("install.sh") else 0o644
                archive.addfile(member, io.BytesIO(contents))
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.sums.write_text(f"{digest}  {ASSET}\n")

    def run_update(self, command, *extra):
        result = subprocess.run(
            ["sh", str(UPDATER), "--app", APP, "--repo", "MayoEDU/FOS", "--current", "0.8.0",
             "--asset", "frameeyeosc-{version}-steamframe-aarch64.tar.gz", *extra, command],
            env=self.environment, cwd=self.scratch, capture_output=True, text=True, timeout=15)
        self.assertNotIn("unexpected-service-operation", result.stderr)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result, json.loads(result.stdout)

    def requests(self):
        return [json.loads(line) for line in self.requests_file.read_text().splitlines()]

    def assert_transport_verified(self):
        requests = self.requests()
        self.assertTrue(requests)
        self.assertEqual(requests[0]["url"], API_URL)
        for request in requests:
            self.assertIn(request["url"], (API_URL, ASSET_URL, SUMS_URL))
            args = request["args"]
            self.assertEqual(args[args.index("--proto") + 1], "=https")
            self.assertEqual(args[args.index("--proto-redir") + 1], "=https")
            self.assertNotIn("--insecure", args)
            self.assertNotIn("-k", args)

    def assert_no_install(self):
        self.assertEqual(self.sentinel.read_text(), "0.8.0\n")
        self.assertFalse(self.installer_record.exists())
        self.assertFalse((self.effects / "panel-installed").exists())

    def assert_failure(self, result, answer, error):
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(answer["state"], "failed")
        self.assertEqual(answer["error"], error)
        self.assertEqual(json.loads(self.state_file.read_text()), answer)
        self.assert_no_install()
        self.assert_transport_verified()

    def assert_success(self, result, answer, expected_args):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(answer["state"], "done")
        self.assertEqual(answer["version"], VERSION)
        self.assertEqual(json.loads(self.state_file.read_text()), answer)
        record = json.loads(self.installer_record.read_text())
        self.assertEqual(record["args"], expected_args)
        self.assertEqual(record["previous_version"], "0.8.0\n")
        self.assertEqual(record["payload"], "Steam Frame fixture\n")
        self.assertEqual(self.sentinel.read_text(), VERSION + "\n")
        self.assertFalse((self.cache_dir / "update.lock").exists())
        self.assertFalse((self.cache_dir / "update" / VERSION).exists())
        self.assert_transport_verified()

    def test_check_reports_installable_fork_release(self):
        result, answer = self.run_update("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(answer["status"], "update-available")
        self.assertTrue(answer["installable"])
        self.assertEqual(answer["latest"], VERSION)
        self.assertEqual(answer["url"], RELEASE_URL)
        self.assert_no_install()
        self.assert_transport_verified()
        self.assertEqual([request["url"] for request in self.requests()], [API_URL])

    def test_install_keeps_panel_argument_from_persisted_settings(self):
        self.config_dir.mkdir(parents=True)
        (self.config_dir / "install-args").write_bytes(b"# Preserve the installed UI\n--with-panel\r\n")
        result, answer = self.run_update("install", "--install-arg", "--fallback")
        self.assert_success(result, answer, ["--with-panel"])
        self.assertEqual((self.effects / "panel-installed").read_text(), "yes\n")
        self.assertEqual([request["url"] for request in self.requests()],
                         [API_URL, ASSET_URL, SUMS_URL])
        result, status = self.run_update("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(status, answer)

    def test_corrupt_download_is_rejected_and_corrected_retry_succeeds(self):
        trusted_archive = self.archive.read_bytes()
        self.archive.write_bytes(trusted_archive + b"corrupt download")
        result, answer = self.run_update("install", "--install-arg", "--with-panel")
        self.assert_failure(result, answer, "checksum-mismatch")
        self.assertFalse((self.cache_dir / "update.lock").exists())
        # Correct the downloaded fixture to match its original published checksum; the
        # retry exercises recovery from the actual failed state, rather than repeating it.
        self.archive.write_bytes(trusted_archive)
        result, answer = self.run_update("install", "--install-arg", "--with-panel")
        self.assert_success(result, answer, ["--with-panel"])
        self.assertTrue((self.effects / "panel-installed").exists())

    def test_release_without_checksums_never_installs(self):
        self.release["assets"] = self.release["assets"][:1]
        self.write_release()
        result, answer = self.run_update("install")
        self.assert_failure(result, answer, "no-checksums")
        self.assertEqual([request["url"] for request in self.requests()], [API_URL])

    def test_checksum_file_without_target_entry_never_installs(self):
        self.sums.write_text("0" * 64 + "  unrelated-asset.tar.gz\n")
        result, answer = self.run_update("install")
        self.assert_failure(result, answer, "no-checksums")

    def test_failed_archive_download_preserves_existing_install(self):
        self.routes[ASSET_URL].update({"status": 503, "exit": 22})
        self.write_routes()
        result, answer = self.run_update("install")
        self.assert_failure(result, answer, "network")
        self.assertIn("HTTP 503", answer["message"])

    def test_redirect_outside_github_never_installs(self):
        self.routes[ASSET_URL]["effective_url"] = "https://untrusted.invalid/release.tar.gz"
        self.write_routes()
        result, answer = self.run_update("install")
        self.assert_failure(result, answer, "bad-url")
        self.assertEqual([request["url"] for request in self.requests()], [API_URL, ASSET_URL])

    def test_verified_archive_with_unsafe_path_never_installs(self):
        self.make_archive(extra_path="../../escape.txt")
        result, answer = self.run_update("install")
        self.assert_failure(result, answer, "unsafe-archive")
        self.assertFalse((self.scratch / "escape.txt").exists())
        self.assertIn("SHA-256 ok", (self.cache_dir / "update.log").read_text())

    def test_verified_archive_without_installer_preserves_existing_install(self):
        self.make_archive(include_installer=False)
        result, answer = self.run_update("install")
        self.assert_failure(result, answer, "no-installer")


if __name__ == "__main__":
    unittest.main()
