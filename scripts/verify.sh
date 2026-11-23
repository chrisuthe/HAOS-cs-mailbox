#!/usr/bin/env bash
# The one verify command: what CI runs, in one go. Lints the shell scripts, the
# workflows and the app manifest, then builds the image and runs the smoke test.
# Needs podman or docker, shellcheck, openssl, and network access.
set -euo pipefail

cd "$(dirname "$0")/.."

ENGINE="${ENGINE:-$(command -v podman || command -v docker)}"
export ENGINE
# Keep in step with the pins in .github/workflows/build.yml.
ACTIONLINT="docker.io/rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667" # 1.7.12
ADDON_LINTER_SHA="d51677290aef26cdfc835271dd3c7343ce502809" # frenck/action-addon-linter v2.21.2
ADDON_LINTER_IMAGE="addon-linter:$ADDON_LINTER_SHA"

# Read-only mounts of the checkout skip SELinux relabelling rather than
# relabelling the whole tree.
ro_repo=(--security-opt label=disable -v "$PWD:/repo:ro" --workdir /repo)

echo "== shellcheck"
shellcheck scripts/*.sh

echo "== actionlint"
"$ENGINE" run --rm "${ro_repo[@]}" "$ACTIONLINT" -color

echo "== app linter"
# The action is a Dockerfile; build it from the same commit CI uses.
if ! "$ENGINE" image inspect "$ADDON_LINTER_IMAGE" >/dev/null 2>&1; then
    src="$(mktemp -d)"
    trap 'rm -rf "$src"' EXIT
    curl -fsSL "https://codeload.github.com/frenck/action-addon-linter/tar.gz/$ADDON_LINTER_SHA" \
        | tar -xz -C "$src" --strip-components=1
    "$ENGINE" build -q -t "$ADDON_LINTER_IMAGE" "$src/src" >"$src/build.log" 2>&1 \
        || { cat "$src/build.log" >&2; exit 1; }
fi
"$ENGINE" run --rm "${ro_repo[@]}" -e INPUT_PATH=/repo/cs_mailbox -e INPUT_COMMUNITY=false \
    "$ADDON_LINTER_IMAGE"
echo "app manifest ok"

echo "== smoke test"
./scripts/smoke_test.sh

echo "verify: all passed"
