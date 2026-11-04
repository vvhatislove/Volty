#!/usr/bin/env bash
#
# Creates the SSH key that CI deploys with. Run it once on a machine that already
# connects to the server over SSH and has gh logged in. Running it again replaces the key.
#
# The key can only run deploy/deploy.sh on the server, and no copy stays on this machine.
#
set -euo pipefail

target="${1:?Usage: setup-deploy-key.sh user@host}"
repo="vvhatislove/Volty"
comment="volty-deploy"

known_hosts="$(ssh-keygen -F "${target#*@}" | grep -v '^#' || true)"
if [ -z "$known_hosts" ]; then
    echo "Connect to ${target#*@} over SSH once, so that its host key is trusted." >&2
    exit 1
fi

key_dir="$(mktemp -d)"
trap 'rm -rf "$key_dir"' EXIT
ssh-keygen -q -t ed25519 -N '' -C "$comment" -f "$key_dir/key"

script_path="$(ssh "$target" 'echo "$HOME/projects/Volty/deploy/deploy.sh"')"
entry="command=\"$script_path\",restrict $(cat "$key_dir/key.pub")"
printf '%s\n' "$entry" | ssh "$target" "sed -i '/ $comment\$/d' ~/.ssh/authorized_keys && cat >> ~/.ssh/authorized_keys"

gh secret set DEPLOY_SSH_KEY --repo "$repo" < "$key_dir/key"
printf '%s\n' "$known_hosts" | gh secret set DEPLOY_KNOWN_HOSTS --repo "$repo"
printf '%s' "$target" | gh secret set DEPLOY_TARGET --repo "$repo"

echo "Deploy key installed on $target, and secrets saved in $repo."
