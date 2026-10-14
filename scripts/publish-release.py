#!/usr/bin/env python3
"""Verify staged release files and publish them with the repository's Actions token."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


REPOSITORY = "MayoEDU/FOS"
MAX_FILE_BYTES = 32 * 1024 * 1024


def version_for_tag(tag, channel="prerelease"):
    pattern = r"v[0-9]+\.[0-9]+\.[0-9]+" + (r"-rc\.[0-9]+" if channel == "prerelease" else "")
    if channel not in ("prerelease", "stable"):
        raise ValueError("Unknown release channel")
    if not isinstance(tag, str) or not re.fullmatch(pattern, tag):
        raise ValueError("Release tag does not match the selected " + channel + " channel")
    return tag[1:].split("-", 1)[0]


def file_record(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Invalid release file: " + path.name)
    if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("Invalid release file size: " + path.name)
    data = path.read_bytes()
    if not 0 < len(data) <= MAX_FILE_BYTES:
        raise ValueError("Invalid release file size: " + path.name)
    return {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def expected_assets(tag, channel="prerelease"):
    version = version_for_tag(tag, channel)
    return (f"frameeyeosc-{version}-steamframe-aarch64.tar.gz", "SHA256SUMS",
            f"fos-{version}-source.tar.gz", "SOURCE_SHA256SUMS", "get.sh")


def validated_files(directory, expected_tag=None, channel="prerelease"):
    if (directory / "RELEASE_METADATA.json").is_symlink():
        raise ValueError("Release metadata must be a regular file")
    metadata = json.loads((directory / "RELEASE_METADATA.json").read_text())
    if metadata["repository"] != REPOSITORY:
        raise ValueError("Release repository does not match FOS")
    expected = set(expected_assets(metadata["tag"], channel))
    if metadata.get("channel", "prerelease") != channel:
        raise ValueError("Release metadata does not match the selected channel")
    if expected_tag is not None and metadata["tag"] != expected_tag:
        raise ValueError("Release metadata does not match the requested tag")
    if not isinstance(metadata["source_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", metadata["source_commit"]):
        raise ValueError("Invalid source commit")
    if type(metadata["draft_release_id"]) is not int or metadata["draft_release_id"] <= 0:
        raise ValueError("Invalid draft release")
    assets = metadata["assets"]
    if len(assets) != len(expected) or {item["name"] for item in assets} != expected:
        raise ValueError("Unexpected release assets")
    if metadata["notes"]["name"] != "release-notes.md":
        raise ValueError("Unexpected release notes")
    for item in assets + [metadata["notes"]]:
        if type(item["bytes"]) is not int or not 0 < item["bytes"] <= MAX_FILE_BYTES:
            raise ValueError("Invalid release file size: " + item["name"])
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Invalid release checksum: " + item["name"])
        actual = file_record(directory / item["name"])
        if actual["bytes"] != item["bytes"]:
            raise ValueError("Release size mismatch: " + item["name"])
        if actual["sha256"] != item["sha256"]:
            raise ValueError("Release checksum mismatch: " + item["name"])
    by_name = {item["name"]: item for item in assets}
    for checksum_name, archive_name in (("SHA256SUMS", expected_assets(metadata["tag"], channel)[0]),
                                       ("SOURCE_SHA256SUMS", expected_assets(metadata["tag"], channel)[2])):
        line = (directory / checksum_name).read_text().strip()
        if line != by_name[archive_name]["sha256"] + "  " + archive_name:
            raise ValueError("Release checksum file does not match the archive: " + checksum_name)
    return metadata


def prepare_metadata(directory, tag, source_commit, draft_release_id, channel="prerelease"):
    """Record local verified inputs; this never creates a tag, release or upload."""
    path = directory / "RELEASE_METADATA.json"
    if path.exists() or path.is_symlink():
        raise ValueError("Refusing to replace existing release metadata")
    metadata = {"repository": REPOSITORY, "tag": tag, "source_commit": source_commit, "channel": channel,
                "draft_release_id": draft_release_id,
                "assets": [file_record(directory / name) for name in expected_assets(tag, channel)],
                "notes": file_record(directory / "release-notes.md")}
    # Validation catches malformed identities and checksum files before retaining metadata.
    created = False
    try:
        with path.open("x") as output:
            created = True
            json.dump(metadata, output, indent=2)
            output.write("\n")
        validated_files(directory, tag, channel)
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise
    print("Prepared verified release metadata for " + tag)


def gh(arguments, *, structured=False):
    environment = dict(os.environ)
    environment["GH_TOKEN"] = environment["FOS_PUBLISH_TOKEN"]
    answer = subprocess.run(["gh", *arguments], check=True, capture_output=True,
                            text=True, env=environment)
    return json.loads(answer.stdout) if structured else answer.stdout


def verified_tag(metadata):
    prefix = "repos/" + REPOSITORY
    source = gh(["api", prefix + "/git/ref/tags/" + metadata["tag"]], structured=True)
    target = source["object"]
    # Annotated tags name a tag object, rather than the commit verified by the build.
    for _ in range(8):
        if target["type"] != "tag":
            break
        target = gh(["api", prefix + "/git/tags/" + target["sha"]], structured=True)["object"]
    if target["type"] != "commit" or target["sha"] != metadata["source_commit"]:
        raise ValueError("Release tag does not match the verified source commit")


def verified_draft(release, metadata, channel):
    if (release["id"] != metadata["draft_release_id"] or release["tag_name"] != metadata["tag"]
            or release["prerelease"] is not (channel == "prerelease") or release["draft"] is not True):
        raise ValueError("Refusing to change a published or unrelated release")
    expected = {item["name"] for item in metadata["assets"]}
    names = [item["name"] for item in release["assets"]]
    if len(set(names)) != len(names) or any(name not in expected for name in names):
        raise ValueError("Draft has unexpected assets; leaving it unchanged")


def publish(directory, metadata, channel="prerelease"):
    prefix = "repos/" + REPOSITORY
    verified_tag(metadata)
    release_path = prefix + "/releases/" + str(metadata["draft_release_id"])
    release = gh(["api", release_path], structured=True)
    verified_draft(release, metadata, channel)
    expected = {item["name"]: item for item in metadata["assets"]}
    # Address the verified release ID directly: retries never select another draft by tag.
    for item in metadata["assets"]:
        current = gh(["api", release_path], structured=True)
        verified_draft(current, metadata, channel)
        existing = {asset["name"]: asset for asset in current["assets"]}
        if item["name"] in existing:
            asset_id = existing[item["name"]]["id"]
            if type(asset_id) is not int or asset_id <= 0:
                raise ValueError("Invalid draft asset ID")
            gh(["api", prefix + "/releases/assets/" + str(asset_id), "--method", "DELETE"])
            verified_draft(gh(["api", release_path], structured=True), metadata, channel)
        upload_url = ("https://uploads.github.com/" + release_path + "/assets?name=" + item["name"])
        gh(["api", upload_url, "--method", "POST", "--input", str(directory / item["name"]),
            "--header", "Content-Type: application/octet-stream"], structured=True)
    verified_tag(metadata)
    uploaded = gh(["api", release_path], structured=True)
    verified_draft(uploaded, metadata, channel)
    actual = {item["name"]: item for item in uploaded["assets"]}
    if set(actual) != set(expected):
        raise ValueError("Release uploads are incomplete; keeping the release as a draft")
    for name, item in expected.items():
        remote = actual[name]
        if remote["size"] != item["bytes"] or remote.get("state") != "uploaded":
            raise ValueError("Release upload did not complete: " + name)
        if remote.get("digest") != "sha256:" + item["sha256"]:
            raise ValueError("Uploaded release checksum is missing or mismatched: " + name)
    gh(["api", release_path, "--method", "PATCH", "--field", "draft=false",
        "--field", "prerelease=" + str(channel == "prerelease").lower(),
        "--raw-field", "make_latest=" + str(channel == "stable").lower(),
        "--field", "body=@" + str(directory / metadata["notes"]["name"])], structured=True)
    print("Published " + "https://github.com/" + REPOSITORY + "/releases/tag/" + metadata["tag"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--channel", choices=("prerelease", "stable"), default="prerelease")
    parser.add_argument("--tag", help="Expected release tag; required when preparing metadata")
    parser.add_argument("--prepare", action="store_true", help="Write local metadata without publishing")
    parser.add_argument("--source-commit", help="Verified 40-character source commit")
    parser.add_argument("--draft-release-id", type=int, help="Existing matching GitHub draft release ID")
    options = parser.parse_args()
    if options.prepare:
        if options.verify_only or not options.tag or not options.source_commit or not options.draft_release_id:
            parser.error("--prepare requires --tag, --source-commit and --draft-release-id without --verify-only")
        prepare_metadata(options.directory, options.tag, options.source_commit, options.draft_release_id, options.channel)
        return
    if options.source_commit is not None or options.draft_release_id is not None:
        parser.error("--source-commit and --draft-release-id are only used with --prepare")
    metadata = validated_files(options.directory, options.tag, options.channel)
    if options.verify_only:
        print("Verified all five " + options.channel + " assets and release notes")
        return
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or not os.environ.get("FOS_PUBLISH_TOKEN"):
        raise ValueError("Publication requires the FOS repository's Actions job token")
    publish(options.directory, metadata, options.channel)


if __name__ == "__main__":
    main()
