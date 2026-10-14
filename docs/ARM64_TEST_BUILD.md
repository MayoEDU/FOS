# ARM64 test candidate

The v0.8.1-rc.1 candidate is intended for Steam Frame testing. It contains actual Linux ARM64 executables;
it is cross-compiled against glibc, with no musl, replacement system libraries or bundled SteamVR library.
The existing installer replaces FrameEyeOSC, its dashboard and bundled camera tools while keeping settings.
See [FORK.md](FORK.md) for the single-command installation, in-app updates and narrowly scoped uninstall.

## Verified build and runtime requirements

The build uses signed Debian bookworm packages, GCC 12.2, glibc 2.36, the Rust AArch64 GNU target and the official
Valve OpenVR SDK pinned to commit `0924064316de3effbcd1acf1e309182a2deb1c05`. APT signatures, package checksums
and rustup checksums remain enabled. Extracted development-library symlinks resolve within the private sysroot;
the audit rejects private glibc imports and build-directory runtime paths.

All four binaries are AArch64 LP64, using `/lib/ld-linux-aarch64.so.1`. The maximum imported glibc version is 2.35
(2.34 for the capture helper); the dashboard requires at most GLIBCXX 3.4.30. Dynamic dependencies and symbol
requirements do not exceed the checksum-verified upstream 0.7.8 release. The dashboard's runtime library path
is `/opt/steamvr/bin/linuxarm64`, so it uses the headset's existing SteamVR library.

QEMU checks start the sender, dashboard version command and recorder help successfully. The capture helper
fails safely when the recorder socket is absent, before attempting camera capture. A synthetic mutex layout
check confirms the AArch64 glibc 48-byte, 8-byte-aligned representation used by the capture code.

The ARM64 sender replays all 7,569 original Valve samples. The ARM64 recorder replays 1,100 original camera
images across open, closed and reopened phases. Its CSV matches the host output exactly at the emitted
precision, including pupil/iris geometry, dilation, confidence, validity and eyelid state. Both eyes' 108 stable
closed samples contain no pupil candidates and report closed.

## Remaining headset checks

Cross-compilation and QEMU cannot exercise the running headset's eye server, camera permissions, VR dashboard,
live OSC receiver or actual service update. The candidate is published as a prerelease for those checks. Its
initial setup, pupil-range fit and optional advanced squint/look-down fit pass native recording replay, as described
in [NATIVE_RECORDING_VERIFICATION.md](NATIVE_RECORDING_VERIFICATION.md).

The normal `scripts/package.sh` continues to require a native Steam Frame build. Do not present this candidate
as having passed live headset tests. GitHub's normal latest-release updater skips prereleases. A later stable
release must increase the numeric version, for example to 0.8.2, so it updates this 0.8.1 candidate in place.
