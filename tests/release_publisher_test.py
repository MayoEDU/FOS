"""A failed upload must keep the verified release private as a draft."""

import importlib.util
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fos_publisher", ROOT / "scripts/publish-release.py")
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


class ReleasePublisherTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "tag": "v0.8.0-rc.1", "source_commit": "a" * 40, "draft_release_id": 12,
            "assets": [{"name": name, "bytes": 42, "sha256": "b" * 64}
                       for name in ("archive.tar.gz", "checksums")],
            "notes": {"name": "release-notes.md"},
        }
        self.calls = []

    def transport(self, arguments, *, structured=False):
        self.calls.append(arguments)
        if "git/ref/tags" in arguments[-1]:
            return {"object": {"sha": "a" * 40}}
        if arguments[0] == "api":
            uploaded = any(call[:2] == ["release", "upload"] for call in self.calls)
            return {"tag_name": "v0.8.0-rc.1", "draft": True, "prerelease": True,
                    "assets": [{"name": item["name"], "size": 42, "state": "uploaded",
                                "digest": "sha256:" + "b" * 64}
                               for item in self.metadata["assets"]] if uploaded else []}
        return ""

    def test_publish_occurs_only_after_all_assets_and_remote_digests_are_checked(self):
        with patch.object(PUBLISHER, "gh", self.transport), contextlib.redirect_stdout(io.StringIO()):
            PUBLISHER.publish(Path("/verified"), self.metadata)
        edits = [index for index, args in enumerate(self.calls) if args[:2] == ["release", "edit"]]
        uploads = [index for index, args in enumerate(self.calls) if args[:2] == ["release", "upload"]]
        self.assertEqual(len(edits), 1)
        self.assertEqual(len(uploads), 2)
        self.assertGreater(edits[0], max(uploads))
        self.assertIn("--draft=false", self.calls[edits[0]])

    def test_upload_failure_never_publishes(self):
        def fail(arguments, **kwargs):
            if arguments[:2] == ["release", "upload"]:
                raise RuntimeError("fixture transport failure")
            return self.transport(arguments, **kwargs)
        with patch.object(PUBLISHER, "gh", fail), self.assertRaises(RuntimeError):
            PUBLISHER.publish(Path("/verified"), self.metadata)
        self.assertFalse(any(args[:2] == ["release", "edit"] for args in self.calls))

    def test_an_existing_published_release_is_untouched(self):
        def published(arguments, **kwargs):
            answer = self.transport(arguments, **kwargs)
            if isinstance(answer, dict) and "draft" in answer:
                answer["draft"] = False
            return answer
        with patch.object(PUBLISHER, "gh", published), self.assertRaises(ValueError):
            PUBLISHER.publish(Path("/verified"), self.metadata)
        self.assertFalse(any(args[0] == "release" for args in self.calls))

    def test_tag_mismatch_stops_before_release_mutations(self):
        with patch.object(PUBLISHER, "gh", return_value={"object": {"sha": "c" * 40}}), self.assertRaises(ValueError):
            PUBLISHER.publish(Path("/verified"), self.metadata)


if __name__ == "__main__":
    unittest.main()
