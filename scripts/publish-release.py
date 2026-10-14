#!/usr/bin/env python3
"""Publish previously verified release files with GitHub Actions' repository token."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


REPOSITORY = "MayoEDU/FOS"


def validated_files(directory):
    metadata = json.loads((directory / "RELEASE_METADATA.json").read_text())
    if metadata["repository"] != REPOSITORY:
        raise ValueError("Release repository does not match FOS")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+", metadata["tag"]):
        raise ValueError("This publisher accepts test candidates only")
    if not re.fullmatch(r"[0-9a-f]{40}", metadata["source_commit"]):
        raise ValueError("Invalid source commit")
    if type(metadata["draft_release_id"]) is not int or metadata["draft_release_id"] <= 0:
        raise ValueError("Invalid draft release")
    version = metadata["tag"][1:].split("-", 1)[0]
    expected = {f"frameeyeosc-{version}-steamframe-aarch64.tar.gz", "SHA256SUMS",
                f"fos-{version}-source.tar.gz", "SOURCE_SHA256SUMS", "get.sh"}
    assets = metadata["assets"]
    if len(assets) != len(expected) or {item["name"] for item in assets} != expected:
        raise ValueError("Unexpected release assets")
    if metadata["notes"]["name"] != "release-notes.md":
        raise ValueError("Unexpected release notes")
    for item in assets + [metadata["notes"]]:
        path = directory / item["name"]
        if path.is_symlink() or not path.is_file() or not 0 < item["bytes"] <= 32 * 1024 * 1024:
            raise ValueError("Invalid release file: " + item["name"])
        if path.stat().st_size != item["bytes"]:
            raise ValueError("Release size mismatch: " + item["name"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Release checksum mismatch: " + item["name"])
    return metadata


def gh(arguments, *, structured=False):
    environment = dict(os.environ)
    environment["GH_TOKEN"] = environment["FOS_PUBLISH_TOKEN"]
    answer = subprocess.run(["gh", *arguments], check=True, capture_output=True,
                            text=True, env=environment)
    return json.loads(answer.stdout) if structured else answer.stdout


def publish(directory, metadata):
    prefix = "repos/" + REPOSITORY
    source = gh(["api", prefix + "/git/ref/tags/" + metadata["tag"]], structured=True)
    if source["object"]["sha"] != metadata["source_commit"]:
        raise ValueError("Release tag does not match the verified source commit")
    release_path = prefix + "/releases/" + str(metadata["draft_release_id"])
    release = gh(["api", release_path], structured=True)
    if release["tag_name"] != metadata["tag"] or not release["prerelease"] or not release["draft"]:
        raise ValueError("Refusing to change a published or unrelated release")
    expected = {item["name"]: item for item in metadata["assets"]}
    if any(item["name"] not in expected for item in release["assets"]):
        raise ValueError("Draft has unexpected assets; leaving it unchanged")
    # Retries replace only this candidate's declared assets while it remains a draft.
    for item in metadata["assets"]:
        gh(["release", "upload", metadata["tag"], str(directory / item["name"]),
            "--repo", REPOSITORY, "--clobber"])
    uploaded = gh(["api", release_path], structured=True)
    actual = {item["name"]: item for item in uploaded["assets"]}
    if set(actual) != set(expected):
        raise ValueError("Release uploads are incomplete; keeping the release as a draft")
    for name, item in expected.items():
        remote = actual[name]
        if remote["size"] != item["bytes"] or remote.get("state") != "uploaded":
            raise ValueError("Release upload did not complete: " + name)
        if remote.get("digest") and remote["digest"] != "sha256:" + item["sha256"]:
            raise ValueError("Uploaded release checksum mismatch: " + name)
    gh(["release", "edit", metadata["tag"], "--repo", REPOSITORY,
        "--notes-file", str(directory / metadata["notes"]["name"]),
        "--prerelease", "--draft=false"])
    print("Published " + "https://github.com/" + REPOSITORY + "/releases/tag/" + metadata["tag"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    options = parser.parse_args()
    metadata = validated_files(options.directory)
    if options.verify_only:
        print("Verified all five candidate assets and release notes")
        return
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or not os.environ.get("FOS_PUBLISH_TOKEN"):
        raise ValueError("Publication requires the FOS repository's Actions job token")
    publish(options.directory, metadata)


if __name__ == "__main__":
    main()
