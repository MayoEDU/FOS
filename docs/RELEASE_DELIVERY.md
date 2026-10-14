# Publish a reviewed FOS release

The panel checks `MayoEDU/FOS` through GitHub's latest stable release API. It never selects drafts or
prereleases, and downloading an update requires the user's Update confirmation. While the repository
has candidates but no stable release, GitHub returns 404 for that API; the FOS panel says **No stable
release yet** and its release link opens the complete release list. An experimental candidate stays
an explicit, tag-selected installation.

## Choose the channel and validate the build

Use a tag such as `v0.8.1-rc.1` with channel `prerelease` for headset testing. Use `v0.8.1` with channel
`stable` only after the native build and physical headset checks in [FORK.md](FORK.md) and
[CAMERA_VALIDATION.md](CAMERA_VALIDATION.md) pass. Include a fresh install, replacement of an upstream
installation with the panel, and an actual in-place update from the previous FOS version. Confirm
preserved calibration/settings, running and stopped services, disabled autostart, failed-install
recovery, camera setup, SteamVR coexistence, and live gaze/pupil output. Publication checks do not
establish those hardware results.

The stable release's numeric version must exceed every version it should update. The shared updater
compares the numeric core: `v0.8.0` cannot update an installed `v0.8.0-rc.1`; use a later numeric version.
Before building, update the numeric application version and `get.sh`'s default tag, then commit the
reviewed version, installer and release notes changes. Keep binary/service
names and `UpdaterConfig.repo = "MayoEDU/FOS"`, and verify both vendor manifests. Build the native
archive using `scripts/package.sh` from that exact clean source commit. Any separate cross-build
candidate must keep its experimental classification and report the headset checks still outstanding.

## Stage the five assets and record their identity

Prepare a directory outside the checkout containing these files at its root, using the selected
numeric version in both archive names:

- `frameeyeosc-<version>-steamframe-aarch64.tar.gz` and `SHA256SUMS` from the verified build.
- `fos-<version>-source.tar.gz` and `SOURCE_SHA256SUMS` from the exact reviewed source commit.
- That source commit's `get.sh` and the reviewed `release-notes.md`.

Each checksum file must contain exactly its matching archive's SHA256 and filename. Each individual
file must be nonempty, a regular file, and no larger than 32 MiB. For example, after staging the native
archive, its checksum, installer and notes:

```sh
tag=v0.8.1-rc.1
channel=prerelease
source_commit=$(git rev-parse HEAD)
version=${tag#v}
version=${version%%-*}
assets=/tmp/fos-reviewed-release
git archive --format=tar.gz --prefix="fos-$version/" "$source_commit" \
  > "$assets/fos-$version-source.tar.gz"
(cd "$assets" && sha256sum "fos-$version-source.tar.gz" > SOURCE_SHA256SUMS)
```

Create and push the reviewed source tag and a matching GitHub **draft**, marked as a prerelease for
the `prerelease` channel or as a regular release for `stable`. Record that draft's numeric release ID
from the authenticated GitHub API. This preparation is a maintainer action; the publisher does not
create tags or releases and refuses to edit an existing published release.

Record the six reviewed files locally, substituting the actual draft ID:

```sh
python3 scripts/publish-release.py "$assets" --prepare --tag "$tag" \
  --channel "$channel" --source-commit "$source_commit" --draft-release-id 123456
python3 scripts/publish-release.py "$assets" --verify-only --tag "$tag" --channel "$channel"
```

`--prepare` writes `RELEASE_METADATA.json` with the repository, source commit, draft ID, channel, file
sizes and hashes. It performs no network request and refuses to overwrite existing metadata. After
changing a staged file, review it again and deliberately remove and regenerate the metadata. Preserve
the reviewed source commit; do not move a published source tag or reuse a published version.

## Dispatch the reusable publication workflow

Commit the staged files and metadata at the root of a temporary release-assets branch in `MayoEDU/FOS`.
This can use a small independent Git repository for the staged directory; no additional worktree is
needed. Review the staging commit, push it, and supply its full lowercase 40-character commit SHA to
**Publish verified FOS release** in GitHub Actions, together with the exact tag and channel. The inputs
have no remembered candidate branch, and branch/tag names are refused for the staging commit.

The equivalent CLI dispatch, after setting `assets_commit` to that reviewed commit SHA, is:

```sh
gh workflow run publish-release.yml --repo MayoEDU/FOS --ref main \
  -f assets_commit="$assets_commit" -f release_tag="$tag" -f channel="$channel"
```

Actions supplies its short-lived repository token with `contents: write`. This is the supported upload
route when the cloud GitHub proxy can use `api.github.com` but cannot authenticate release uploads at
`uploads.github.com`; it does not require exporting or copying a proxy credential or adding a personal
access token. The workflow runs the publisher from its own source commit and treats staged files as
data.

The publisher verifies every local asset and note, both archive checksum files, the source tag's
resolved commit, and the exact existing draft's ID/tag/channel. It addresses uploads by that draft's
ID, rechecks draft identity before each mutation, and replaces only the declared assets on retry.
It checks the complete remote asset set, upload
states, sizes and GitHub SHA256 digests, rechecks the source tag, then publishes once. A missing or
mismatched digest, failed upload, moved tag, unrelated draft or changed draft state stops publication.
The expected partial uploads may remain in the draft for a verified retry. A stable dispatch explicitly
marks that release latest; a prerelease cannot become the stable updater's target.

Keep other clients from editing or publishing that draft while the workflow runs. Actions serializes
these publication jobs, but GitHub's separate read and write requests cannot prevent a concurrent
change through the UI or another API client between a check and its following mutation.

After success, verify anonymous downloads of all five assets, the published channel and notes, and
both checksum files. For a stable release, also verify the latest stable endpoint and perform a real
headset update from the previous installed numeric version. Retain the source tag; remove the temporary
staging branch only after this verification. The publisher's unit tests and upload checks cover delivery
guards; they do not guarantee recovery from power loss or prove live headset compatibility.
