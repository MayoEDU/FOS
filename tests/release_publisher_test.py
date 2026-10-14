"""Release publication must fail closed while its assets are still a draft."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fos_publisher", ROOT / "scripts/publish-release.py")
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


class ReleaseFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fos-publisher-")
        self.directory = Path(self.temp.name)
        self.tag = "v0.8.1-rc.1"
        self.assets(self.tag)

    def tearDown(self):
        self.temp.cleanup()

    def assets(self, tag, channel="prerelease"):
        names = PUBLISHER.expected_assets(tag, channel)
        for name in (names[0], names[2], "get.sh", "release-notes.md"):
            (self.directory / name).write_text("verified fixture " + name + "\n")
        for checksum, archive in ((names[1], names[0]), (names[3], names[2])):
            digest = PUBLISHER.file_record(self.directory / archive)["sha256"]
            (self.directory / checksum).write_text(digest + "  " + archive + "\n")

    def prepare(self, tag=None, channel="prerelease", **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            PUBLISHER.prepare_metadata(self.directory, tag or self.tag,
                                       kwargs.get("source_commit", "a" * 40),
                                       kwargs.get("draft_release_id", 12), channel)

    def test_prepare_records_five_assets_and_notes_without_network_access(self):
        with patch.object(PUBLISHER, "gh", side_effect=AssertionError("unexpected network")):
            self.prepare()
            result = PUBLISHER.validated_files(self.directory, self.tag)
        self.assertEqual(len(result["assets"]), 5)
        self.assertEqual(result["channel"], "prerelease")

    def test_stable_requires_explicit_channel_when_preparing_and_verifying(self):
        tag = "v0.8.1"
        self.assets(tag, "stable")
        with self.assertRaises(ValueError):
            self.prepare(tag)
        self.prepare(tag, "stable")
        with self.assertRaises(ValueError):
            PUBLISHER.validated_files(self.directory, tag)
        self.assertEqual(PUBLISHER.validated_files(self.directory, tag, "stable")["channel"], "stable")

    def test_requested_tag_mismatch_is_rejected(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "requested tag"):
            PUBLISHER.validated_files(self.directory, "v0.8.1-rc.2")

    def test_changed_asset_or_notes_is_rejected(self):
        for name in ("get.sh", "release-notes.md"):
            with self.subTest(name=name):
                self.prepare()
                (self.directory / name).write_text("tampered")
                with self.assertRaises(ValueError):
                    PUBLISHER.validated_files(self.directory)
                (self.directory / "RELEASE_METADATA.json").unlink()
                self.assets(self.tag)

    def test_symlink_cannot_be_recorded_as_a_release_asset(self):
        path = self.directory / "get.sh"
        path.unlink()
        path.symlink_to("release-notes.md")
        with self.assertRaisesRegex(ValueError, "Invalid release file"):
            self.prepare()
        self.assertFalse((self.directory / "RELEASE_METADATA.json").exists())

    def test_checksum_file_must_name_and_match_its_archive(self):
        (self.directory / "SHA256SUMS").write_text("b" * 64 + "  unrelated.tar.gz\n")
        with self.assertRaisesRegex(ValueError, "does not match the archive"):
            self.prepare()
        self.assertFalse((self.directory / "RELEASE_METADATA.json").exists())

    def test_invalid_source_or_draft_id_leaves_no_metadata(self):
        for kwargs in ({"source_commit": "not-a-commit"}, {"draft_release_id": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.prepare(**kwargs)
            self.assertFalse((self.directory / "RELEASE_METADATA.json").exists())

    def test_preparing_never_overwrites_existing_metadata(self):
        self.prepare()
        original = (self.directory / "RELEASE_METADATA.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "Refusing to replace"):
            self.prepare()
        self.assertEqual((self.directory / "RELEASE_METADATA.json").read_bytes(), original)

    def test_legacy_candidate_metadata_still_verifies(self):
        self.prepare()
        path = self.directory / "RELEASE_METADATA.json"
        metadata = json.loads(path.read_text())
        del metadata["channel"]
        path.write_text(json.dumps(metadata))
        self.assertEqual(PUBLISHER.validated_files(self.directory)["tag"], self.tag)


class ReleasePublisherTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "tag": "v0.8.1-rc.1", "source_commit": "a" * 40, "draft_release_id": 12,
            "assets": [{"name": name, "bytes": 42, "sha256": "b" * 64}
                       for name in ("archive.tar.gz", "checksums")],
            "notes": {"name": "release-notes.md"},
        }
        self.remote = {"id": 12, "tag_name": self.metadata["tag"], "draft": True,
                       "prerelease": True, "assets": []}
        self.calls = []
        self.tag_checks = 0
        self.source_sha = "a" * 40

    def transport(self, arguments, *, structured=False):
        self.calls.append(arguments)
        endpoint = arguments[1]
        method = arguments[arguments.index("--method") + 1] if "--method" in arguments else "GET"
        if "/git/ref/tags/" in endpoint:
            self.tag_checks += 1
            return {"object": {"type": "commit", "sha": self.source_sha}}
        if method == "POST":
            self.assertTrue(endpoint.startswith("https://uploads.github.com/repos/MayoEDU/FOS/releases/12/assets?name="))
            name = endpoint.split("?name=", 1)[1]
            item = next(item for item in self.metadata["assets"] if item["name"] == name)
            asset = {"id": len(self.remote["assets"]) + 100, "name": name, "size": item["bytes"],
                     "state": "uploaded", "digest": "sha256:" + item["sha256"]}
            self.remote["assets"].append(asset)
            return copy.deepcopy(asset)
        if method == "DELETE":
            asset_id = int(endpoint.rsplit("/", 1)[1])
            self.remote["assets"] = [asset for asset in self.remote["assets"] if asset["id"] != asset_id]
            return ""
        if method == "PATCH":
            self.remote["draft"] = False
            return copy.deepcopy(self.remote)
        return copy.deepcopy(self.remote)

    def publish(self, transport=None, channel="prerelease"):
        with patch.object(PUBLISHER, "gh", transport or self.transport), contextlib.redirect_stdout(io.StringIO()):
            PUBLISHER.publish(Path("/verified"), self.metadata, channel)

    def mutations(self, method=None):
        return [args for args in self.calls if "--method" in args
                and (method is None or args[args.index("--method") + 1] == method)]

    def test_publish_only_after_all_assets_digests_and_final_tag_are_checked(self):
        self.publish()
        self.assertEqual(len(self.mutations("POST")), 2)
        self.assertEqual(len(self.mutations("PATCH")), 1)
        self.assertEqual(self.tag_checks, 2)
        self.assertEqual(self.calls[-1][1], "repos/MayoEDU/FOS/releases/12")
        self.assertIn("draft=false", self.calls[-1])
        self.assertIn("prerelease=true", self.calls[-1])
        self.assertIn("make_latest=false", self.calls[-1])
        self.assertFalse(self.remote["draft"])

    def test_upload_failure_never_publishes(self):
        def fail(arguments, **kwargs):
            if "POST" in arguments:
                raise RuntimeError("fixture transport failure")
            return self.transport(arguments, **kwargs)
        with self.assertRaises(RuntimeError):
            self.publish(fail)
        self.assertFalse(self.mutations("PATCH"))
        self.assertTrue(self.remote["draft"])

    def test_published_or_unrelated_or_wrong_channel_release_is_untouched(self):
        for field, value in (("draft", False), ("id", 99), ("tag_name", "v9.9.9"), ("prerelease", False)):
            with self.subTest(field=field):
                saved = self.remote[field]
                self.remote[field] = value
                with self.assertRaises(ValueError):
                    self.publish()
                self.assertFalse(self.mutations())
                self.remote[field] = saved

    def test_initial_tag_mismatch_stops_before_mutations(self):
        self.source_sha = "c" * 40
        with self.assertRaises(ValueError):
            self.publish()
        self.assertFalse(self.mutations())

    def test_annotated_tag_resolves_to_verified_source(self):
        def annotated(arguments, **kwargs):
            if "/git/ref/tags/" in arguments[1]:
                self.calls.append(arguments)
                return {"object": {"type": "tag", "sha": "c" * 40}}
            if "/git/tags/" in arguments[1]:
                self.calls.append(arguments)
                return {"object": {"type": "commit", "sha": self.source_sha}}
            return self.transport(arguments, **kwargs)
        self.publish(annotated)
        self.assertEqual(len(self.mutations("PATCH")), 1)

    def test_tag_changed_during_upload_keeps_release_a_draft(self):
        def moved(arguments, **kwargs):
            result = self.transport(arguments, **kwargs)
            if "POST" in arguments:
                self.source_sha = "c" * 40
            return result
        with self.assertRaises(ValueError):
            self.publish(moved)
        self.assertFalse(self.mutations("PATCH"))
        self.assertTrue(self.remote["draft"])

    def test_unexpected_or_duplicate_draft_asset_stops_before_mutations(self):
        for assets in ([{"name": "unrelated"}], [{"name": "checksums"}] * 2):
            with self.subTest(assets=assets):
                self.remote["assets"] = assets
                with self.assertRaises(ValueError):
                    self.publish()
                self.assertFalse(self.mutations())

    def test_retry_replaces_only_the_declared_asset_by_id(self):
        self.remote["assets"] = [{"id": 88, "name": "checksums"}]
        self.publish()
        self.assertEqual(self.mutations("DELETE")[0][1], "repos/MayoEDU/FOS/releases/assets/88")
        self.assertEqual(len(self.mutations("DELETE")), 1)
        self.assertEqual(len(self.mutations("PATCH")), 1)

    def test_incomplete_upload_or_missing_mismatched_digest_keeps_draft(self):
        for field, value in (("state", "starter"), ("size", 0), ("digest", None), ("digest", "sha256:" + "c" * 64)):
            with self.subTest(field=field):
                self.remote["assets"] = []
                self.calls = []
                def corrupted(arguments, **kwargs):
                    result = self.transport(arguments, **kwargs)
                    if "POST" in arguments:
                        self.remote["assets"][-1][field] = value
                    return result
                with self.assertRaises(ValueError):
                    self.publish(corrupted)
                self.assertFalse(self.mutations("PATCH"))
                self.assertTrue(self.remote["draft"])

    def test_missing_upload_or_draft_changed_during_upload_never_publishes(self):
        for change in ("asset", "draft", "prerelease"):
            with self.subTest(change=change):
                self.remote.update(draft=True, prerelease=True, assets=[])
                self.calls = []
                def changed(arguments, **kwargs):
                    result = self.transport(arguments, **kwargs)
                    if "POST" in arguments:
                        if change == "asset":
                            self.remote["assets"] = []
                        else:
                            self.remote[change] = False
                    return result
                with self.assertRaises(ValueError):
                    self.publish(changed)
                self.assertFalse(self.mutations("PATCH"))
                if change != "asset":
                    self.assertEqual(len(self.mutations("POST")), 1)

    def test_draft_published_during_retry_delete_stops_before_upload(self):
        self.remote["assets"] = [{"id": 88, "name": "checksums"}]
        def changed(arguments, **kwargs):
            result = self.transport(arguments, **kwargs)
            if "DELETE" in arguments:
                self.remote["draft"] = False
            return result
        # Put the existing asset first so the race occurs before any upload.
        self.metadata["assets"].reverse()
        with self.assertRaises(ValueError):
            self.publish(changed)
        self.assertEqual(len(self.mutations("DELETE")), 1)
        self.assertFalse(self.mutations("POST"))
        self.assertFalse(self.mutations("PATCH"))

    def test_stable_channel_matches_stable_draft_and_publishes_without_prerelease(self):
        self.metadata["tag"] = "v0.8.1"
        self.remote.update(tag_name="v0.8.1", prerelease=False)
        self.publish(channel="stable")
        self.assertIn("prerelease=false", self.calls[-1])
        self.assertIn("make_latest=true", self.calls[-1])
        self.assertEqual(len(self.mutations("PATCH")), 1)


if __name__ == "__main__":
    unittest.main()
