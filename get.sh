#!/usr/bin/env bash
# Download the explicitly selected FOS Steam Frame release, verify it, and install/replace in place.
# This bootstrap currently selects the 0.8.1-rc.1 test candidate. The in-app updater selects stable releases only.
# No GitHub account or sudo is needed once the repository and release are publicly downloadable.
set -euo pipefail

tag=v0.8.1-rc.1
usage() {
    echo "Usage: bash get.sh [--tag vMAJOR.MINOR.PATCH[-candidate]]"
}
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            tag="$2"
            shift 2
            ;;
        --help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$ ]]; then
    echo "Choose an explicit FOS release tag such as v0.8.1-rc.1." >&2
    exit 2
fi
if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 ]]; then
    echo "FOS installs only on Steam Frame (Linux ARM64). No installed files were changed." >&2
    exit 1
fi
if ! getconf GNU_LIBC_VERSION >/dev/null 2>&1; then
    echo "Steam Frame's native glibc is required. No installed files were changed." >&2
    exit 1
fi
for command in curl python3 sha256sum mktemp rm; do
    command -v "$command" >/dev/null || { echo "Required command is missing: $command" >&2; exit 1; }
done

version="${tag#v}"
version="${version%%-*}"
asset="frameeyeosc-$version-steamframe-aarch64.tar.gz"
base="https://github.com/MayoEDU/FOS/releases/download/$tag"
if ! download="$(mktemp -d "${TMPDIR:-/tmp}/fos-download.XXXXXX")"; then
    echo "Could not create a private download directory. Check TMPDIR, its permissions and free space, then retry. The installed app was left alone." >&2
    exit 1
fi
cleanup() { rm -rf -- "$download"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fetch() {
    curl --fail --show-error --progress-bar --location --max-redirs 5 --connect-timeout 15 \
        --retry 2 --retry-delay 1 --retry-max-time 120 \
        --max-time 600 --max-filesize 268435456 --proto '=https' --proto-redir '=https' \
        --output "$2" "$1"
}

echo "Downloading FOS $tag release checksums."
if ! fetch "$base/SHA256SUMS" "$download/SHA256SUMS"; then
    echo "Could not download this release's checksums. Check the connection and published release tag, then run the same command again. The installed app was left alone." >&2
    exit 1
fi
echo "Downloading the Steam Frame archive (this may take a few minutes)."
if ! fetch "$base/$asset" "$download/$asset"; then
    echo "Could not download this release's archive. Check the connection, free space and published release tag, then run the same command again. The installed app was left alone." >&2
    exit 1
fi
# Read only the exact archive's checksum entry; release metadata cannot make sha256sum inspect arbitrary paths.
if ! python3 - "$download/SHA256SUMS" "$asset" "$download/expected.sha256" <<'PY'
import re
import sys
from pathlib import Path

checksums, asset, output = sys.argv[1:]
path = Path(checksums)
if path.stat().st_size > 1024 * 1024:
    sys.exit("SHA256SUMS is too large.")
matches = []
for line in path.read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
    if match and match[2] == asset:
        matches.append(match[1].lower())
if len(matches) != 1:
    sys.exit("SHA256SUMS must contain exactly one valid checksum for this archive.")
Path(output).write_text(f"{matches[0]}  {asset}\n", encoding="utf-8")
PY
then
    echo "The release checksum is missing or invalid. The installed app was left alone." >&2
    exit 1
fi
if ! (cd "$download" && sha256sum --check --strict expected.sha256); then
    echo "The release archive failed verification. The installed app was left alone." >&2
    exit 1
fi

# Validate the complete archive before extracting or running any release script.
echo "Checking archive contents and ARM64 compatibility."
if ! python3 - "$download/$asset" "$download/files" <<'PY'
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import tarfile

archive, target = map(Path, sys.argv[1:])
required = {
    "install.sh", "frameeyeosc", "frameeyeosc.service", "frameeyeosc.env.example",
    "frameeyeosc-panel", "frameeyeosc-panel.service", "frameeyeosc-panel.desktop",
    "frame-update.sh", "icons/frameeyeosc-panel-48.png", "icons/frameeyeosc-panel-128.png",
    "icons/frameeyeosc-panel-256.png", "eyecam/eyecam-rec", "eyecam/eyecam-grab",
    "eyecam/install_grab.sh", "eyecam/eyecam.service", "eyecam/NOTICE",
}
binaries = ("frameeyeosc", "frameeyeosc-panel", "eyecam/eyecam-rec", "eyecam/eyecam-grab")
loader = b"/lib/ld-linux-aarch64.so.1\0"

def fail(message):
    raise ValueError(message)

try:
    if archive.stat().st_size > 256 * 1024 * 1024:
        fail("release archive is too large")
    with tarfile.open(archive, "r:gz") as tar:
        files = {}
        members = []
        seen = set()
        expanded = 0
        for member in tar:
            name = member.name.rstrip("/")
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or "\\" in name or
                    any(part in ("", ".", "..") for part in name.split("/")) or
                    path.parts[0] != "frameeyeosc"):
                fail("archive contains an unsafe or unexpected path")
            if name in seen:
                fail("archive contains duplicate paths")
            seen.add(name)
            if not (member.isdir() or member.isfile()) or member.mode & 0o6000:
                fail("archive contains a link, special file or privileged permissions")
            expanded += member.size
            if member.size > 128 * 1024 * 1024 or expanded > 512 * 1024 * 1024 or len(seen) > 1024:
                fail("archive exceeds the release size limits")
            members.append(member)
            if member.isfile():
                files[str(path.relative_to("frameeyeosc"))] = member
        missing = required - files.keys()
        if missing:
            fail("complete release payload is missing: " + ", ".join(sorted(missing)))
        if not any(name.startswith("eyecam/protocol_") and name.endswith(".txt") and
                   "/" not in name[len("eyecam/"):] for name in files):
            fail("camera recording protocols are missing")
        for name in binaries:
            member = files[name]
            if not member.mode & 0o111:
                fail(name + " is not executable")
            with tar.extractfile(member) as binary:
                header = binary.read(64)
                if len(header) != 64 or header[:7] != b"\x7fELF\x02\x01\x01":
                    fail(name + " is not an ARM64 ELF64 executable")
                fields = struct.unpack("<16sHHIQQQIHHHHHH", header)
                if fields[1] not in (2, 3) or fields[2] != 183 or fields[3] != 1:
                    fail(name + " is not an ARM64 executable")
                offset, entry_size, count = fields[5], fields[9], fields[10]
                if entry_size != 56 or count > 256 or offset + entry_size * count > member.size:
                    fail(name + " has invalid ELF program headers")
                interpreter = None
                for index in range(count):
                    binary.seek(offset + index * entry_size)
                    program = struct.unpack("<IIQQQQQQ", binary.read(56))
                    if program[0] == 3:
                        if interpreter is not None or program[5] > 4096 or program[2] + program[5] > member.size:
                            fail(name + " has an invalid ELF interpreter")
                        binary.seek(program[2])
                        interpreter = binary.read(program[5])
                if interpreter != loader:
                    fail(name + " must use Steam Frame's ARM64 glibc interpreter")
        target.mkdir(mode=0o700)
        for member in members:
            destination = target / member.name.rstrip("/")
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output, 128 * 1024)
                os.chmod(destination, member.mode & 0o777)
except (OSError, ValueError, tarfile.TarError, struct.error) as error:
    sys.exit("Release validation failed: " + str(error))
PY
then
    echo "This is not a complete compatible Steam Frame release. The installed app was left alone." >&2
    exit 1
fi

echo "Verified FOS $tag. Installing the sender, dashboard panel and bundled camera tool."
if bash "$download/files/frameeyeosc/install.sh" --with-panel; then
    echo "FOS $tag installation finished."
else
    result="$?"
    echo "FOS installation failed. Review the installer error above, correct its cause and run the same command again." >&2
    exit "$result"
fi
