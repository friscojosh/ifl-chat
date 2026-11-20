#!/usr/bin/env bash
# Build the pinned Slack migration tools into "$1/bin" (league chat plan 5).
#   mmetl                    v0.6.0 (commit 07f81df74c218061981a97feb746231919c4f058)
#   slack-advanced-exporter  v0.4.0 (commit c0f7bf8230cd15d9b44af36d73ce8f0650538c67)
#     + sae-token-from-env.patch (IFL-maintained): token from SLACK_API_TOKEN,
#       exit 1 on failure, downloads only from https://files.slack.com with
#       no redirects, saves only HTTP 200 non-HTML responses.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?usage: build_tools.sh <migration dir>}"
SRC="$DEST/src"
mkdir -p "$DEST/bin" "$SRC"
fetch() {  # repo tag commit dir
  if [[ ! -d "$SRC/$4/.git" ]]; then
    git clone -q --depth 1 --branch "$2" "https://github.com/$1.git" "$SRC/$4"
  fi
  [[ "$(git -C "$SRC/$4" rev-parse HEAD)" == "$3" ]] || { echo "$4: not at $3" >&2; exit 1; }
}
fetch mattermost/mmetl v0.6.0 07f81df74c218061981a97feb746231919c4f058 mmetl
fetch grundleborg/slack-advanced-exporter v0.4.0 c0f7bf8230cd15d9b44af36d73ce8f0650538c67 sae
git -C "$SRC/sae" checkout -q -- .   # drop an earlier run's patch, then apply it fresh
git -C "$SRC/sae" apply "$HERE/sae-token-from-env.patch"
(cd "$SRC/mmetl" && GOTOOLCHAIN=local go build -trimpath -o "$DEST/bin/mmetl" .)
(cd "$SRC/sae" && GOTOOLCHAIN=local GOFLAGS=-mod=mod go build -trimpath -o "$DEST/bin/slack-advanced-exporter" .)
"$DEST/bin/mmetl" version
sha256sum "$DEST/bin/mmetl" "$DEST/bin/slack-advanced-exporter"
