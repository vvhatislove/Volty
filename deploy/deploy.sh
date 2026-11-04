#!/usr/bin/env bash
#
# Updates the running bot to one commit from main. CI calls it over SSH after the
# checks pass, and the deploy key can run nothing else on the server.
#
set -euo pipefail

target="${SSH_ORIGINAL_COMMAND:-${1:-}}"
settle_seconds="${DEPLOY_SETTLE_SECONDS:-30}"

if [[ ! "$target" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Expected a full commit SHA." >&2
    exit 2
fi

cd "$(dirname "$0")/.."

git fetch --quiet origin main
if ! git merge-base --is-ancestor "$target" origin/main; then
    echo "Commit $target is not on main." >&2
    exit 2
fi

previous="$(git rev-parse HEAD)"
if [ "$previous" = "$target" ]; then
    echo "Already on ${target:0:7}."
    exit 0
fi

# Chained on purpose: bash ignores set -e inside a function called from a "||" list.
start_bot() {
    docker compose build bot &&
        docker compose up -d --wait db &&
        docker compose up -d bot
}

bot_is_stable() {
    sleep "$settle_seconds"
    local container state
    container="$(docker compose ps -q bot)"
    [ -n "$container" ] || return 1
    state="$(docker inspect -f '{{.State.Running}} {{.RestartCount}}' "$container")"
    [ "$state" = "true 0" ]
}

roll_back() {
    echo "Deploy failed, returning to ${previous:0:7}." >&2
    git reset --hard --quiet "$previous"
    start_bot
    exit 1
}

# A hard reset would silently destroy edits made on the server, so keep them as a patch.
if ! git diff --quiet HEAD; then
    backup="$HOME/volty-local-changes-$(date +%F_%H%M%S).patch"
    git diff HEAD > "$backup"
    echo "Local changes saved to $backup."
fi

echo "Deploying ${previous:0:7} -> ${target:0:7}."
git reset --hard --quiet "$target"

start_bot || roll_back
bot_is_stable || roll_back

echo "Deployed: $(git log -1 --format='%h %s')"
