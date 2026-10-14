#!/usr/bin/env bash
# Fetch/review upstream by default. --merge opens a local, uncommitted merge for maintainer review.
# No push, release creation or reset is performed.
set -euo pipefail
cd "$(dirname "$0")/.."

merge=false
if [[ "${1:-}" == --merge ]]; then
    merge=true
    shift
fi
if [[ $# -gt 1 || "${1:-}" == --help ]]; then
    echo "Usage: scripts/upstream-sync.sh [--merge] [main|tag|commit]"
    exit 0
fi
ref="${1:-main}"
git check-ref-format --allow-onelevel "$ref" >/dev/null || {
    echo "Invalid upstream reference: $ref" >&2
    exit 2
}
if $merge && [[ -n "$(git status --porcelain)" ]]; then
    echo "Commit or preserve local changes before opening an upstream merge." >&2
    exit 1
fi

git fetch --no-tags https://github.com/sasaken1102r/frameeyeosc.git "$ref"
revision="$(git rev-parse FETCH_HEAD)"
git log --oneline HEAD.."$revision"
git diff --stat HEAD..."$revision"
if ! $merge; then
    echo
    echo "Fetched upstream $revision. Review before integrating:"
    echo "  git diff HEAD...$revision"
    echo "  scripts/upstream-sync.sh --merge $revision"
    exit 0
fi

if ! git merge --no-commit --no-ff "$revision"; then
    echo "Upstream merge needs conflict resolution. Local changes are left for review; nothing was committed." >&2
    exit 1
fi
sh vendor/frame-updater/verify.sh
sh vendor/frame-apps/verify.sh
echo
echo "Review the local merge and run the checks in docs/FORK.md before committing."
echo "Keep MayoEDU/FOS update routing and a monotonically increasing fork version."
