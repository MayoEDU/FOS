"""Upstream integration defaults to review and protects uncommitted local work."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UpstreamSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fos-sync-test-")
        self.scratch = Path(self.temp.name)
        self.trace = self.scratch / "git-args"
        git = self.scratch / "git"
        git.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$FOS_SYNC_TEST_LOG"
case "$1" in
    check-ref-format) exit 0 ;;
    status) test "${FOS_SYNC_TEST_DIRTY:-}" != 1 || echo ' M README.md' ;;
    rev-parse) echo a90bbc0aebdef72e1a4a6e860b3aa89dd82cff8b ;;
esac
exit 0
""")
        git.chmod(0o755)
        self.environment = dict(os.environ)
        self.environment["PATH"] = str(self.scratch) + os.pathsep + os.environ["PATH"]
        self.environment["FOS_SYNC_TEST_LOG"] = str(self.trace)

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, *args):
        return subprocess.run(["bash", str(ROOT / "scripts/upstream-sync.sh"), *args],
                              env=self.environment, capture_output=True, text=True, timeout=5)

    def test_default_fetches_review_without_merging_or_publishing(self):
        result = self.run_sync("main")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.trace.read_text().splitlines()
        self.assertIn("fetch --no-tags https://github.com/sasaken1102r/frameeyeosc.git main", commands)
        self.assertFalse(any(command.startswith(("merge ", "push ", "reset ")) for command in commands))
        self.assertIn("Review before integrating", result.stdout)

    def test_merge_refuses_dirty_checkout_before_fetching(self):
        self.environment["FOS_SYNC_TEST_DIRTY"] = "1"
        result = self.run_sync("--merge", "main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preserve local changes", result.stderr)
        commands = self.trace.read_text().splitlines()
        self.assertFalse(any(command.startswith(("merge ", "fetch ", "reset ")) for command in commands))


if __name__ == "__main__":
    unittest.main()
