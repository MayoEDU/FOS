#!/usr/bin/env bash
# Install or update frameeyeosc as a user service on a Steam Frame. Run it on the headset as the
# normal user (no sudo needed):
#   ./install.sh                     install or update frameeyeosc, then start it
#   ./install.sh --with-panel        the same, plus the SteamVR dashboard panel
#   ./install.sh --uninstall         remove both, keeping settings and learned calibration
#   ./install.sh --uninstall --purge remove everything, settings included
# Without --with-panel an installed panel is left as it is, so frameeyeosc can be updated on its own.
# The release tarball also carries eyecam, the eye-camera tool. It is installed to ~/.local/lib/eyecam and runs as a
# user service that waits until the eye cameras are set up from the panel. That setup asks the user to run
# install_grab.sh once with sudo, in a Konsole the panel opens; this script never runs sudo. The service is enabled on
# the first install only: one the user turned off (systemctl --user disable eyecam) stays off through updates.
#
# FRAMEEYEOSC_NO_SYSTEMCTL=1 skips service operations. It still installs files; it is not a dry run.
set -euo pipefail

if [[ "${FRAMEEYEOSC_NO_SYSTEMCTL:-}" == 1 ]]; then
    systemctl() {
        echo "(FRAMEEYEOSC_NO_SYSTEMCTL) skipped: systemctl $*"
    }
fi

here="$(cd "$(dirname "$0")" && pwd)"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
bin_dir="$HOME/.local/bin"
config_dir="$config_home/frameeyeosc"
unit_dir="$config_home/systemd/user"
data_unit_dir="$data_home/systemd/user"
unit="frameeyeosc.service"
panel_unit="frameeyeosc-panel.service"
panel_desktop="$data_home/applications/frameeyeosc-panel.desktop"
icon_dir="$data_home/icons/hicolor"
icon_sizes=(48 128 256)
# The panel's update button runs this script, which reruns install.sh with the options in install-args
share_dir="$data_home/frameeyeosc"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/frameeyeosc"
install_args="$config_dir/install-args"
# The eye-camera tool. The panel's setup types "sudo $HOME/.local/lib/eyecam/install_grab.sh" into Konsole, and
# eyecam.service runs eyecam-rec from here
eyecam_dir="$HOME/.local/lib/eyecam"
eyecam_unit="eyecam.service"
# eyecam-rec's own files: its settings and calibration, and its recordings
eyecam_config_dir="$HOME/.config/eyecam"
eyecam_recordings="$HOME/eyecam"
# The copy of eyecam-grab install_grab.sh puts there with sudo (root's; only install_grab.sh --uninstall removes it)
eyecam_root_dir=/home/.eyecam

with_panel=false
uninstall=false
purge=false
for arg in "$@"; do
    case "$arg" in
        --with-panel) with_panel=true ;;
        --uninstall) uninstall=true ;;
        --purge) purge=true ;;
        *)
            echo "Unknown option: $arg (use --with-panel, --uninstall or --uninstall --purge)" >&2
            exit 2
            ;;
    esac
done

if $uninstall; then
    # A pending detached update is this app's unit too; otherwise it could reinstall files after removal.
    systemctl --user stop frameeyeosc-update.service 2>/dev/null || true
    systemctl --user disable --now "$unit" 2>/dev/null || true
    systemctl --user disable --now "$panel_unit" 2>/dev/null || true
    systemctl --user disable --now "$eyecam_unit" 2>/dev/null || true
    rm -f "$unit_dir/$unit" "$bin_dir/frameeyeosc"
    rm -f "$unit_dir/$panel_unit" "$bin_dir/frameeyeosc-panel" "$panel_desktop"
    rm -f "$unit_dir/$eyecam_unit"
    rm -f "$data_unit_dir/$unit" "$data_unit_dir/$panel_unit" "$data_unit_dir/$eyecam_unit"
    # The privileged helper is removed only with its own dedicated installer. Retain that small script in a
    # private temporary file when it is still needed, because the user-owned copy is about to be removed.
    retained_grab=""
    if [[ -e "$eyecam_root_dir/eyecam-grab" && -f "$share_dir/install_grab.sh" ]]; then
        retained_grab="$(mktemp "${TMPDIR:-/tmp}/frameeyeosc-uninstall-grab.XXXXXX")"
        install -m700 "$share_dir/install_grab.sh" "$retained_grab"
    fi
    # Only installed camera tool files are removed. An unrelated file someone put beside them is preserved.
    for file in eyecam-rec eyecam-grab install_grab.sh NOTICE; do
        rm -f "$eyecam_dir/$file" "$eyecam_dir/.$file.new"
    done
    if [[ -f "$share_dir/eyecam-protocols" ]]; then
        while IFS= read -r file; do
            case "$file" in protocol_*.txt)
                [[ "$file" != */* && "$file" != *\\* ]] || continue
                rm -f "$eyecam_dir/$file" "$eyecam_dir/.$file.new"
                ;;
            esac
        done <"$share_dir/eyecam-protocols"
    else
        # These were the bundled protocols before FOS recorded an install manifest.
        rm -f "$eyecam_dir/protocol_free.txt" "$eyecam_dir/protocol_widen.txt" "$eyecam_dir/protocol_widen_nolight.txt"
    fi
    rmdir "$eyecam_dir" 2>/dev/null || true
    rm -f "$share_dir/frame-update.sh" "$share_dir/install.sh" "$share_dir/install_grab.sh" \
        "$share_dir/CHANGELOG.md" "$share_dir/CHANGELOG.ja.md" "$share_dir/eyecam-protocols"
    rmdir "$share_dir" 2>/dev/null || true
    # All updater downloads, state and logs are confined to this app's cache directory.
    rm -rf "$cache_dir"
    rm -f "$install_args"
    for size in "${icon_sizes[@]}"; do
        rm -f "$icon_dir/${size}x${size}/apps/frameeyeosc-panel.png"
    done
    systemctl --user daemon-reload
    if $purge; then
        rm -rf "$config_dir" "$eyecam_config_dir"
        echo "Removed frameeyeosc, the panel, the eye-camera tool, the settings and the learned calibration."
    else
        echo "Removed frameeyeosc, the panel and the eye-camera tool. Settings and calibration are kept in $config_dir"
        echo "and $eyecam_config_dir (add --purge to delete them)."
    fi
    # Not removed here: the eye-camera recordings (they are the user's files) and the root-owned helper
    if [[ -d "$eyecam_recordings" ]]; then
        echo "The eye-camera recordings and calibration captures in $eyecam_recordings are kept; delete the folder if you don't need them."
    fi
    if [[ -e "$eyecam_root_dir/eyecam-grab" ]]; then
        if [[ -n "$retained_grab" ]]; then
            echo "The root-owned eye-camera helper remains. Remove only that helper with its dedicated uninstaller:"
            printf '  sudo %q --uninstall\n  rm -- %q\n' "$retained_grab" "$retained_grab"
        else
            echo "The root-owned eye-camera helper remains. Run the release's eyecam/install_grab.sh with sudo and --uninstall."
        fi
    fi
    exit 0
fi
if $purge; then
    echo "--purge only goes with --uninstall" >&2
    exit 2
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
    echo "This build is for the Steam Frame (aarch64), but this machine is $(uname -m)." >&2
    exit 1
fi
if ! getconf GNU_LIBC_VERSION >/dev/null 2>&1; then
    echo "This build needs the Steam Frame's glibc. A musl-based system is not compatible." >&2
    exit 1
fi

# Check the entire requested payload before replacing a working installation. A source checkout or an
# archive built on a PC must not partially replace the headset's binaries and services.
require_file() {
    if [[ ! -f "$here/$1" ]]; then
        echo "Missing release file: $1. Use a complete FOS Steam Frame release archive." >&2
        exit 1
    fi
}
require_binary() {
    require_file "$1"
    local header
    header="$(od -An -v -tx1 -N20 "$here/$1" | tr -d ' \n')"
    if [[ ! -x "$here/$1" || "${header:0:14}" != 7f454c46020101 || "${header:36:4}" != b700 ]]; then
        echo "$1 is not an executable Linux ARM64 release binary; leaving the existing install alone." >&2
        exit 1
    fi
}
require_binary frameeyeosc
require_file frameeyeosc.service
require_file frameeyeosc.env.example
updater="$here/frame-update.sh"
[[ -f "$updater" ]] || updater="$here/vendor/frame-updater/frame-update.sh"
if [[ ! -f "$updater" ]]; then
    echo "Missing release file: frame-update.sh. Use a complete FOS Steam Frame release archive." >&2
    exit 1
fi
if $with_panel; then
    require_binary frameeyeosc-panel
    require_file frameeyeosc-panel.service
    require_file frameeyeosc-panel.desktop
    for size in "${icon_sizes[@]}"; do
        require_file "icons/frameeyeosc-panel-$size.png"
    done
    if [[ ! -f /opt/steamvr/bin/linuxarm64/libopenvr_api.so ]]; then
        echo "Steam Frame's SteamVR library is missing. Install/start SteamVR before installing the panel." >&2
        exit 1
    fi
fi
# FOS's fixes live in eyecam too; an archive missing the whole directory must not leave an upstream tool behind.
require_binary eyecam/eyecam-rec
require_binary eyecam/eyecam-grab
require_file eyecam/install_grab.sh
require_file eyecam/eyecam.service
require_file eyecam/NOTICE
if ! compgen -G "$here/eyecam/protocol_*.txt" >/dev/null; then
    echo "Missing eyecam recording protocols. Use a complete release archive." >&2
    exit 1
fi
if [[ ! -e /dev/shm/eye-server.mmap ]]; then
    echo "Note: /dev/shm/eye-server.mmap does not exist yet. It appears once SteamVR's eye tracking runs; the service retries until then."
fi

unit_fresh() {
    [[ ! -e "$unit_dir/$1" && ! -L "$unit_dir/$1" && ! -e "$data_unit_dir/$1" && ! -L "$data_unit_dir/$1" ]]
}
sender_fresh=false
panel_fresh=false
eyecam_fresh=false
unit_fresh "$unit" && sender_fresh=true
unit_fresh "$panel_unit" && panel_fresh=true
unit_fresh "$eyecam_unit" && eyecam_fresh=true
service_names=("$unit" "$panel_unit" "$eyecam_unit")
service_states=()
service_active=()
for service in "${service_names[@]}"; do
    service_states+=("$(systemctl --user is-enabled "$service" 2>/dev/null || true)")
    service_active+=("$(systemctl --user is-active "$service" 2>/dev/null || true)")
done

# Every file replacement is journalled before mutation. A failed copy or service command restores the old
# payload and install options, instead of leaving the sender, panel and camera tool at different versions.
transaction="$(mktemp -d "${TMPDIR:-/tmp}/frameeyeosc-install.XXXXXX")"
mkdir "$transaction/backups"
changed_paths=()
transaction_committed=false
services_touched=false
track_file() {
    local destination="$1" previous index
    for previous in "${changed_paths[@]}"; do
        [[ "$previous" == "$destination" ]] && return 0
    done
    index="${#changed_paths[@]}"
    if [[ -e "$destination" || -L "$destination" ]]; then
        cp -a -- "$destination" "$transaction/backups/$index"
    fi
    changed_paths+=("$destination")
}
publish_file() {
    local source="$1" mode="$2" destination="$3"
    track_file "$destination"
    mkdir -p "$(dirname "$destination")"
    install -m "$mode" "$source" "$destination.frameeyeosc-new.$$"
    mv -f -- "$destination.frameeyeosc-new.$$" "$destination"
}
remove_owned_file() {
    local destination="$1"
    if [[ -e "$destination" || -L "$destination" ]]; then
        track_file "$destination"
        rm -f -- "$destination"
    fi
}
install_unit() {
    local source="$1" name="$2" destination="$unit_dir/$2"
    # A user's persistent mask must keep winning over the updated unit. Store its new definition in the
    # standard lower-priority data directory, ready if that user later unmasks the service.
    if [[ -L "$destination" && "$(readlink -- "$destination")" == /dev/null ]]; then
        destination="$data_unit_dir/$name"
    fi
    publish_file "$source" 644 "$destination"
}
finish_transaction() {
    local result="$1" index destination rollback_failed=false
    trap - EXIT
    if [[ "$result" != 0 ]] && ! $transaction_committed; then
        for ((index=${#changed_paths[@]}-1; index>=0; index--)); do
            destination="${changed_paths[$index]}"
            rm -f -- "$destination.frameeyeosc-new.$$"
            if [[ -e "$transaction/backups/$index" || -L "$transaction/backups/$index" ]]; then
                if ! cp -a -- "$transaction/backups/$index" "$destination.frameeyeosc-rollback.$$" ||
                    ! mv -f -- "$destination.frameeyeosc-rollback.$$" "$destination"; then
                    rollback_failed=true
                    echo "Could not restore $destination; its backup remains in $transaction/backups/$index." >&2
                fi
            else
                rm -f -- "$destination"
            fi
        done
        if $services_touched; then
            systemctl --user daemon-reload 2>/dev/null || true
            for index in "${!service_names[@]}"; do
                if [[ "${service_states[$index]}" == not-found || -z "${service_states[$index]}" ]]; then
                    systemctl --user disable --now "${service_names[$index]}" 2>/dev/null || true
                elif [[ "${service_active[$index]}" == active ]]; then
                    systemctl --user restart "${service_names[$index]}" 2>/dev/null || true
                fi
            done
        fi
        if $rollback_failed; then
            echo "Installation and rollback failed. Preserved recovery files in $transaction; resolve the filesystem error before retrying." >&2
            exit "$result"
        fi
        echo "Installation failed; restored the previous app files and settings. See the update log for the failing command." >&2
    fi
    rm -rf -- "$transaction"
    exit "$result"
}
trap 'finish_transaction "$?"' EXIT

# Rename a staged binary over the old one so a running service can keep its old executable until restart.
publish_file "$here/frameeyeosc" 755 "$bin_dir/frameeyeosc"
install_unit "$here/frameeyeosc.service" "$unit"
if [[ ! -f "$config_dir/env" ]]; then
    publish_file "$here/frameeyeosc.env.example" 644 "$config_dir/env"
fi
# The updater was checked along with the release payload before replacing any file.
publish_file "$updater" 755 "$share_dir/frame-update.sh"
# Keep the scoped uninstaller and the helper's own root-uninstall script after the extracted release is deleted.
publish_file "$here/install.sh" 755 "$share_dir/install.sh"
publish_file "$here/eyecam/install_grab.sh" 755 "$share_dir/install_grab.sh"
# The changelogs, for the panel's version history (next to install.sh in the tarball and in a checkout)
for changelog in CHANGELOG.md CHANGELOG.ja.md; do
    if [[ -f "$here/$changelog" ]]; then
        publish_file "$here/$changelog" 644 "$share_dir/$changelog"
    else
        remove_owned_file "$share_dir/$changelog"
    fi
done
# The eye-camera tool from the complete release archive checked above.
with_eyecam=false
# Its first install: the service is enabled and started only then (see below)
if [[ -x "$here/eyecam/eyecam-rec" ]]; then
    with_eyecam=true
    mkdir -p "$eyecam_dir" "$unit_dir"
    # A running eyecam-rec keeps its old file: each file is written next to it and renamed over it
    for file in eyecam-rec eyecam-grab install_grab.sh; do
        publish_file "$here/eyecam/$file" 755 "$eyecam_dir/$file"
    done
    # The recording protocols eyecam-rec looks for beside itself (ones a new version dropped go)
    if [[ -f "$share_dir/eyecam-protocols" ]]; then
        while IFS= read -r file; do
            case "$file" in protocol_*.txt)
                [[ "$file" != */* && "$file" != *\\* ]] || continue
                [[ -f "$here/eyecam/$file" ]] || remove_owned_file "$eyecam_dir/$file"
                ;;
            esac
        done <"$share_dir/eyecam-protocols"
    fi
    : >"$transaction/eyecam-protocols"
    for file in "$here"/eyecam/protocol_*.txt "$here/eyecam/NOTICE"; do
        publish_file "$file" 644 "$eyecam_dir/$(basename "$file")"
        [[ "$(basename "$file")" != protocol_*.txt ]] || basename "$file" >>"$transaction/eyecam-protocols"
    done
    publish_file "$transaction/eyecam-protocols" 644 "$share_dir/eyecam-protocols"
    sed "s|@PREFIX@|$eyecam_dir|g" "$here/eyecam/eyecam.service" >"$transaction/eyecam.service"
    install_unit "$transaction/eyecam.service" "$eyecam_unit"
fi

if $with_panel; then
    # A running panel keeps its old binary until it restarts; the file is only replaced
    publish_file "$here/frameeyeosc-panel" 755 "$bin_dir/frameeyeosc-panel"
    install_unit "$here/frameeyeosc-panel.service" "$panel_unit"
    # Steam looks for launcher icons in hicolor/<size>/apps and misses a 256x256-only icon
    for size in "${icon_sizes[@]}"; do
        publish_file "$here/icons/frameeyeosc-panel-$size.png" 644 "$icon_dir/${size}x${size}/apps/frameeyeosc-panel.png"
    done
    # Exec needs the absolute path: Steam may start it without ~/.local/bin in PATH
    mkdir -p "$(dirname "$panel_desktop")"
    sed "s|@BINARY@|$bin_dir/frameeyeosc-panel|" "$here/frameeyeosc-panel.desktop" >"$transaction/panel.desktop"
    publish_file "$transaction/panel.desktop" 644 "$panel_desktop"
fi

# Options for the next update from the panel. An installed panel is updated along with frameeyeosc,
# whether or not this run had --with-panel
if $with_panel || [[ -x "$bin_dir/frameeyeosc-panel" ]]; then
    printf -- '--with-panel\n' >"$transaction/install-args"
else
    : >"$transaction/install-args"
fi
publish_file "$transaction/install-args" 644 "$install_args"

services_touched=true
systemctl --user daemon-reload
if $sender_fresh; then
    systemctl --user enable "$unit"
    systemctl --user restart "$unit"
elif [[ "${service_states[0]}" != masked* ]]; then
    systemctl --user try-restart "$unit"
fi
# eyecam: enabled and started on its first install only (without the eye cameras set up it only waits, until
# install_grab.sh has been run once). Later, one the user turned off stays off; one running restarts on the new
# binary; one stopped by hand stays stopped
eyecam_off=false
if $with_eyecam; then
    if $eyecam_fresh; then
        systemctl --user enable "$eyecam_unit"
        systemctl --user restart "$eyecam_unit"
    else
        [[ "${service_states[2]}" != disabled && "${service_states[2]}" != masked* ]] || eyecam_off=true
        [[ "${service_states[2]}" == masked* ]] || systemctl --user try-restart "$eyecam_unit"
    fi
fi
if $with_panel; then
    # Starts with SteamVR from its next start (the panel's "Start with SteamVR" turns this off).
    # Not started now; a panel already running as the service is restarted to pick up the new binary.
    $panel_fresh && systemctl --user enable "$panel_unit"
    [[ "${service_states[1]}" == masked* ]] || systemctl --user try-restart "$panel_unit"
fi
transaction_committed=true
sleep 2
systemctl --user --no-pager status "$unit" | head -n 5 || true

cat <<EOF

FOS frameeyeosc is installed. Updates preserve existing service/autostart choices.
  Updates:  MayoEDU/FOS releases (install with --with-panel to replace the upstream panel's updater)
  Settings: $config_dir/config.json   (the panel writes it; you can also edit it by hand.
            Changes are picked up within a second, no restart needed)
  Options:  $config_dir/env   (FRAMEEYEOSC_ARGS; these win over config.json.
            Apply with: systemctl --user restart frameeyeosc)
  Logs:     journalctl --user -u frameeyeosc -f
EOF
if $with_panel; then
    cat <<EOF

The panel's "Start with SteamVR" choice is preserved on updates; enabled on its first install.
To open it now, pick "frameeyeosc panel" under Launch program (+) on the dashboard.
Its "Start with SteamVR" switch turns the autostart off. Logs: journalctl --user -u frameeyeosc-panel -f
EOF
elif [[ -x "$bin_dir/frameeyeosc-panel" ]]; then
    echo
    echo "The panel in $bin_dir was left as it is (run with --with-panel to update it too)."
fi
if $with_eyecam; then
    cat <<EOF

The eye-camera tool is in $eyecam_dir and runs as eyecam.service.
Until the eye cameras are set up on the panel's "Eye cameras" tab (it asks you to run
install_grab.sh there once, with sudo), it only waits. Logs: journalctl --user -u eyecam -f
To stop it for good: systemctl --user disable --now eyecam (updates leave it off).
EOF
    if $eyecam_off; then
        echo "eyecam.service autostart is off and was preserved. To turn it on: systemctl --user enable --now eyecam"
    fi
fi
cat <<EOF

On your PC, turn off Steam Link's own OSC output (SteamVR settings > Steam Link > OSC),
otherwise it drives the avatar's eyes too with unsmoothed data.
EOF
