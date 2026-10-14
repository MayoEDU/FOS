# FOS on Steam Frame

FOS is a standalone Steam Frame project based on [sasaken1102r/frameeyeosc](https://github.com/sasaken1102r/frameeyeosc), initially imported at `a90bbc0aebdef72e1a4a6e860b3aa89dd82cff8b` (upstream 0.7.8). It supports Steam Frame's internal eye cameras and eye tracker on Linux ARM64. The binaries, services, settings directories, OSC formats and dashboard layout retain their existing names so an upstream installation can be replaced in place. The GitHub repository has no fork relationship; source attribution and upstream integration are retained.

## Install or replace an upstream copy

Use an archive and `SHA256SUMS` from [MayoEDU/FOS releases](https://github.com/MayoEDU/FOS/releases). Anonymous installation and source downloads require this repository to be public and the selected release to be published. In-app updates require a newer stable release. A private repository or an unpublished release cannot be downloaded anonymously. A production archive must be built and tested on the Steam Frame before a stable release is published. A source checkout by itself is not an installable release.

### One-command test candidate

After the repository is public and **v0.8.0-rc.1** has been published, paste this one command into Konsole on the Steam Frame as the normal headset user:

```sh
curl -fsSL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/MayoEDU/FOS/v0.8.0-rc.1/get.sh | bash
```

This command installs the explicitly selected ARM64 test candidate, including the sender, dashboard panel and camera tool. It can replace an existing copy in place and preserves settings and calibration. It downloads from MayoEDU/FOS over verified HTTPS, checks the release checksum, checks the complete archive and ARM64 glibc executables, then runs `install.sh --with-panel`. No GitHub sign-in or sudo is needed for that installation. Camera helper setup remains the existing separate one-time action from the panel.

The candidate is an experimental cross build prepared for headset testing; it has not established reliable tracking on a physical wearer. See [hardware validation](CAMERA_VALIDATION.md) and [native recording verification](NATIVE_RECORDING_VERIFICATION.md). Its release stays marked as a prerelease, so the stable in-app updater will not install it automatically. A later stable release must have a numeric version above **0.8.0** to update a candidate installation through the app.

`get.sh` currently pins **v0.8.0-rc.1**. To choose another published tag explicitly, pass `--tag`, for example `bash get.sh --tag v0.8.1` after downloading the script. The tag-specific command above remains valid when a newer default is added to `main`.

### Manual candidate installation

After the candidate is published in the public repository, these commands are an alternative to the one-command installer. Enable Developer Mode to open Konsole, then run them as the normal headset user:

```sh
mkdir -p ~/Downloads/fos
cd ~/Downloads/fos
curl -fL --proto '=https' --proto-redir '=https' -O \
  https://github.com/MayoEDU/FOS/releases/download/v0.8.0-rc.1/frameeyeosc-0.8.0-steamframe-aarch64.tar.gz
curl -fL --proto '=https' --proto-redir '=https' -O \
  https://github.com/MayoEDU/FOS/releases/download/v0.8.0-rc.1/SHA256SUMS
sha256sum -c SHA256SUMS
tar xzf frameeyeosc-0.8.0-steamframe-aarch64.tar.gz
cd frameeyeosc
./install.sh --with-panel
```

The public [source repository](https://github.com/MayoEDU/FOS) and its GitHub source archives are also available without signing in. The installer preserves existing settings and camera calibration; replacing an existing copy does not require uninstalling it first.

On the headset, keep a backup of existing settings if present, verify the download, and install the panel along with the sender:

```sh
cp -a ~/.config/frameeyeosc ~/frameeyeosc-config-backup
cp -a ~/.config/eyecam ~/eyecam-config-backup
sha256sum -c SHA256SUMS
tar xzf frameeyeosc-0.8.0-steamframe-aarch64.tar.gz
cd frameeyeosc
./install.sh --with-panel
```

If this is a new installation, the backup commands can be skipped. Existing settings, learned calibration, recordings and service/autostart choices are preserved. Fresh installations enable the normal defaults; updates refresh running services and leave stopped services stopped. Disabled autostart and service masks remain in place. The camera helper still requires the existing one-time setup from the Eye cameras tab; the user installer does not run sudo or modify SteamOS. When the bundled helper changes, follow the panel's helper update prompt rather than copying it into SteamVR or disabling camera protections.

Include `--with-panel` when replacing an upstream copy: the update destination belongs to the panel. The FOS panel checks **MayoEDU/FOS** only; it will never install a release from the original fork. Until a stable FOS release exists, the update check can report that no published release was found. Checking for updates does not publish or install anything. Installation still requires the user's normal Update confirmation.

The shared updater and its integrity manifest in `vendor/frame-updater/` remain unchanged. FOS supplies its repository through the supported `UpdaterConfig.repo` field in `panel/src/update_config.h`. The vendored updater includes the repository in its cache key, so an old cached upstream release is discarded when the FOS panel checks for updates. Release archives retain `frameeyeosc-<version>-steamframe-aarch64.tar.gz`; both the archive and its `SHA256SUMS` must be attached to a release. Numeric fork versions must increase: the shared updater compares only the numeric version core, so a suffix alone cannot make an update newer.

The other Frame apps shown in Advanced > Version remain upstream's catalog; their buttons install those separate apps. The generic upstream installer menu is omitted from FOS because its eye option replaces this fork. The original `frame.sasaken1102s.net` installer, if run by hand, installs upstream frameeyeosc and will replace FOS if its eye app is selected. Use FOS releases or the FOS panel to update this installation.

## Update from the app

Open Advanced > Version, select Check now, then confirm Update when a newer stable release is available. The updater downloads only from GitHub, verifies the archive against its release's `SHA256SUMS`, and runs that release's installer with the saved install options. The sender, panel and bundled camera tool are replaced in place; configuration and calibration remain. No uninstall/reinstall cycle or GitHub sign-in is needed once FOS is public.

Network errors, missing checksums, checksum mismatches and unsafe archives stop before the installer runs. The installer validates the complete payload before changing files, replaces executables by rename, and journals its file changes. A copy or service-start failure restores the prior payload and install options and tries to restart services that had been running. If the filesystem also prevents rollback, it reports the retained recovery directory instead of deleting its backups. A power loss or forced termination that prevents the shell's exit handler can leave an interrupted installation requiring recovery or another verified attempt. Check `~/.cache/frameeyeosc/update.log`, correct the reported cause, and use Try again. The updater reports an interrupted attempt as failed and supports a new attempt; it does not silently resume unverified bytes.

Only numeric version increases are installable from the app. GitHub's latest-release API skips drafts and prereleases, so an experimental candidate does not replace a stable installation through automatic checks.

## Remove only FrameEyeOSC and its bundled tools

The installed uninstaller remains available even after the downloaded archive and extraction folder are deleted. If the privileged camera helper was set up, remove that exact helper first with its own script:

```sh
sudo "${XDG_DATA_HOME:-$HOME/.local/share}/frameeyeosc/install_grab.sh" --uninstall
```

Then, as the normal headset user, remove the application, dashboard panel and bundled camera tool:

```sh
"${XDG_DATA_HOME:-$HOME/.local/share}/frameeyeosc/install.sh" --uninstall
```

To also remove only their settings and learned calibration, use `--uninstall --purge` instead. Both commands keep personal recordings and calibration captures in `~/eyecam`. They stop only `frameeyeosc`, `frameeyeosc-panel`, `eyecam` and a pending `frameeyeosc-update` unit; remove only their binaries, unit files, launcher/icons, installed support files and FrameEyeOSC's own cache; and preserve SteamVR, other apps, unrelated units and shared caches. Custom camera protocols and unrelated files placed beside the app's support files are preserved.

The normal uninstaller never runs sudo. If the helper remains, it prints an explicit `sudo <dedicated-script> --uninstall` command and retains that small script in a private temporary file. That script removes only the helper's known file and attempts to remove its directory only when empty. It does not delete other files in `/home` or change SteamVR.

## Build and validate

The cloud checkout is already isolated; use its existing checkout. Do not create a worktree unless explicitly requested. Offline unit and UI tests can run on a Linux development machine. Native releases must be built on the headset: the eye server's process-shared mutex uses glibc's ABI, and the panel links SteamVR's ARM64 OpenVR library.

```sh
cargo test --release --locked -- --test-threads=1
cargo test --release --locked --manifest-path tools/eyecam/Cargo.toml
cargo build --release --locked --manifest-path tools/eyecam/Cargo.toml
python3 -m unittest discover -s tests -p '*_test.py'
sh vendor/frame-updater/verify.sh
sh vendor/frame-apps/verify.sh
```

On the Steam Frame with Rust, CMake, Ninja, Python, binutils, cairo, freetype and Vulkan development packages available:

```sh
scripts/package.sh --check
scripts/package.sh
```

Packaging runs the Rust and panel test suites, validates every release binary as ARM64 with the glibc interpreter, and creates `dist/frameeyeosc-0.8.0-steamframe-aarch64.tar.gz` and `dist/SHA256SUMS`. It refuses a PC or a musl environment before building. Host tests cannot establish camera capture, SteamVR shared-memory compatibility, calibration quality or reliable gaze and pupil output on a real wearer. Before releasing, test a fresh camera setup and an in-place update on the headset, check both camera previews, complete calibration, verify gaze, blinks, widening and pupil changes with bright/dim content, and confirm Valve tracking continues when the camera service is stopped.

## Integrate upstream changes

Fetch and inspect new upstream work without changing the checkout:

```sh
scripts/upstream-sync.sh main
```

After preserving local work, choose a reviewed tag or commit and open a merge without committing it:

```sh
scripts/upstream-sync.sh --merge <reviewed-upstream-commit>
```

Resolve any conflicts while retaining FOS camera fixes, `MayoEDU/FOS` update routing, binary/service/config names, and a newer numeric fork version. Upstream's `tools/eyecam/` is a separate crate; review it along with the sender and panel, and run both Rust suites. Upstream vendors can be refreshed as a whole together with their original manifests; do not edit vendored updater files to change the release repository. Run the checks above, the panel's `ctest` suite including `update-config`, and the actual headset checks before committing the merge. The helper never pushes, creates a release, resets the branch, or automatically resolves conflicts.
