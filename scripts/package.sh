#!/usr/bin/env bash
# Build a release tarball. Run this on the Steam Frame itself: the binary has to link against the
# headset's glibc, because the eye server's shared mutex uses glibc's layout (a static musl build
# would lock it with an incompatible layout). The panel links against SteamVR's libopenvr_api.so,
# which is only on the headset too.
set -euo pipefail
cd "$(dirname "$0")/.."

# Release builds use the Frame's glibc shared-mutex ABI and SteamVR's native ARM64 library.
# Host tests on a PC remain useful, but cannot produce a headset release by renaming their outputs.
if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 ]]; then
    echo "Release packaging must run on a Steam Frame (Linux aarch64), not $(uname -s)/$(uname -m)." >&2
    exit 1
fi
if ! getconf GNU_LIBC_VERSION >/dev/null 2>&1; then
    echo "Release packaging requires the Steam Frame's native glibc (musl is incompatible)." >&2
    exit 1
fi
if [[ ! -f /opt/steamvr/bin/linuxarm64/libopenvr_api.so ]]; then
    echo "Steam Frame's /opt/steamvr/bin/linuxarm64/libopenvr_api.so is required for release packaging." >&2
    exit 1
fi
if [[ -n "${CARGO_BUILD_TARGET:-}" ]]; then
    echo "Unset CARGO_BUILD_TARGET: release packaging uses the Steam Frame's native Rust target." >&2
    exit 1
fi
if [[ "${1:-}" == --check && $# == 1 ]]; then
    echo "Steam Frame release prerequisites are present."
    exit 0
elif [[ $# != 0 ]]; then
    echo "Usage: scripts/package.sh [--check]" >&2
    exit 2
fi
command -v readelf >/dev/null || { echo "readelf (binutils) is required to verify release binaries." >&2; exit 1; }

cargo="${CARGO:-cargo}"
command -v "$cargo" >/dev/null || cargo="$HOME/.cargo/bin/cargo"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' Cargo.toml | head -n 1)"
name="frameeyeosc-$version-steamframe-aarch64"

# The updater copy must be exactly what frame-updater's sync.sh put there
sh vendor/frame-updater/verify.sh
# ...and the other Frame apps' list (built into the panel) what frame-apps' sync.sh put there
sh vendor/frame-apps/verify.sh

"$cargo" test --release --locked -- --test-threads=1
"$cargo" build --release --locked
cmake -G Ninja -S panel -B panel/build -DCMAKE_BUILD_TYPE=Release
cmake --build panel/build --parallel "${FOS_BUILD_JOBS:-2}"
ctest --test-dir panel/build --output-on-failure
# eyecam, the eye-camera tool (tools/eyecam): its own crate and lockfile, built into its own target folder.
# Stripped like frameeyeosc (its Cargo.toml is a vendored copy, so the profile is set here)
eyecam_target=tools/eyecam/target
"$cargo" test --release --locked --manifest-path tools/eyecam/Cargo.toml --target-dir "$eyecam_target"
CARGO_PROFILE_RELEASE_STRIP=true "$cargo" build --release --locked --manifest-path tools/eyecam/Cargo.toml \
    --target-dir "$eyecam_target"
python3 -m unittest discover -s tests -p '*_test.py'

# Catch a stale foreign build directory or toolchain override before putting any binary in a release.
for binary in target/release/frameeyeosc panel/build/frameeyeosc-panel \
    "$eyecam_target/release/eyecam-rec" "$eyecam_target/release/eyecam-grab"; do
    if ! readelf -h "$binary" | grep -q 'Machine:.*AArch64' || \
        ! readelf -l "$binary" | grep -q 'Requesting program interpreter: /lib/ld-linux-aarch64.so.1'; then
        echo "$binary is not an ARM64 executable linked to the Steam Frame's glibc; refusing to package it." >&2
        exit 1
    fi
done

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/frameeyeosc/icons"
mkdir -p "$stage/frameeyeosc/docs"
cp docs/FORK.md "$stage/frameeyeosc/docs/"
cp target/release/frameeyeosc install.sh get.sh contrib/frameeyeosc.service contrib/frameeyeosc.env.example \
    LICENSE THIRD_PARTY_LICENSES.md README.md README.ja.md CHANGELOG.md CHANGELOG.ja.md "$stage/frameeyeosc/"
cp panel/build/frameeyeosc-panel panel/contrib/frameeyeosc-panel.service panel/contrib/frameeyeosc-panel.desktop \
    "$stage/frameeyeosc/"
cp panel/contrib/icons/frameeyeosc-panel-{48,128,256}.png "$stage/frameeyeosc/icons/"
cp vendor/frame-updater/frame-update.sh "$stage/frameeyeosc/"
# install.sh puts these in ~/.local/lib/eyecam (install_grab.sh is run once by the user, with sudo)
mkdir -p "$stage/frameeyeosc/eyecam"
cp "$eyecam_target/release/eyecam-rec" "$eyecam_target/release/eyecam-grab" tools/eyecam/install_grab.sh \
    tools/eyecam/protocol_*.txt tools/eyecam/eyecam.service tools/eyecam/NOTICE "$stage/frameeyeosc/eyecam/"
# eyecam-grab's sha256 for the release notes (users compare it before installing the tool with sudo; not in the
# tarball, whose copy would sit next to the file it vouches for)
echo "eyecam-grab sha256: $(sha256sum "$stage/frameeyeosc/eyecam/eyecam-grab" | cut -d' ' -f1)"
mkdir -p dist
tar -C "$stage" -czf "dist/$name.tar.gz" frameeyeosc
# The panel's update button only installs releases that carry this file (attach it to the release too)
(cd dist && sha256sum "$name.tar.gz" >SHA256SUMS)
echo "dist/$name.tar.gz"
echo "dist/SHA256SUMS"
