#!/usr/bin/env bash
# Builds the app image and runs it the way the Supervisor would, with options in
# /data/options.json and certificates under /ssl, then talks to it with
# scripts/smoke_client.py, run from the same image in the server's network
# namespace. Needs podman or docker, openssl, and network access for the build.
set -euo pipefail

cd "$(dirname "$0")/.."

ENGINE="${ENGINE:-$(command -v podman || command -v docker)}"
IMAGE="${IMAGE:-cs-mailbox-app:smoke}"
# The release before the move to the published cs-mailbox image, for the upgrade
# check. Multi-arch, like the app.
OLD_IMAGE="${OLD_IMAGE:-ghcr.io/chrisuthe/haos-cs-mailbox:0.1.1@sha256:3c24fb498cd527f6a8e7143c6c6c7def109663d0f0f3e0ca30a995583b0722cb}"
NAME="cs-mailbox-app-smoke"
URL="wss://127.0.0.1:8443/"

work="$(mktemp -d)"
cleanup() {
    "$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true
    # The server's files belong to its own user; remove them as the image's root.
    "$ENGINE" run --rm --entrypoint rm -v "$work:/w:z" "$IMAGE" -rf /w/data /w/plain /w/upgrade >/dev/null 2>&1 || true
    rm -rf "$work" 2>/dev/null || true
}
trap cleanup EXIT

# Captured first: grep -q exits at its first match, and under pipefail the
# writer's SIGPIPE would fail the pipeline.
logs() {
    "$ENGINE" logs "$NAME" 2>&1
}

logs_have() {
    local out
    out="$(logs)"
    grep -q -- "$1" <<<"$out"
}

fail() {
    echo "FAIL: $*" >&2
    "$ENGINE" logs "$NAME" 2>&1 | tail -40 >&2 || true
    exit 1
}

# start OPTIONS_JSON [extra engine args...]: a fresh container on the same /data,
# as an app update or restart gives. DATA and RUN_IMAGE pick another /data or image.
start() {
    local data="${DATA:-$work/data}"
    "$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true
    printf '%s' "$1" > "$data/options.json"
    "$ENGINE" run -d --name "$NAME" -v "$data:/data:z" "${@:2}" "${RUN_IMAGE:-$IMAGE}" >/dev/null
}

wait_listening() {
    for _ in $(seq 1 40); do
        logs_have 'Listening on wss://' && return 0
        [ "$("$ENGINE" inspect -f '{{.State.Running}}' "$NAME")" = true ] || break
        sleep 0.5
    done
    fail "server did not start listening"
}

wait_exited() {
    for _ in $(seq 1 20); do
        [ "$("$ENGINE" inspect -f '{{.State.Running}}' "$NAME")" = false ] && return 0
        sleep 0.5
    done
    fail "container did not exit"
}

# client URL [smoke_client.py args...]: prints the client's JSON line.
client() {
    "$ENGINE" run --rm --network "container:$NAME" -v "$work/client:/client:ro,z" \
        --entrypoint python3 "$IMAGE" -I /client/smoke_client.py "$1" /client/cert.pem "${@:2}"
}

json_field() {
    python3 -c 'import json, sys; print(json.loads(sys.stdin.read())[sys.argv[1]])' "$1"
}

# The PEM block the app logs for pasting into the integration.
logged_pem() {
    local out
    out="$(logs)"
    sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' <<<"$out" \
        | sed -n '1,/-----END CERTIFICATE-----/p'
}

logged_fingerprint() {
    local out
    out="$(logs)"
    sed -nE 's/.*SHA-256 fingerprint:? ([0-9A-F:]{95}).*/\1/p' <<<"$out" | sed -n 1p
}

check_no_private_key_logged() {
    if logs_have 'PRIVATE KEY'; then
        fail "a private key was written to the log"
    fi
}

# podman drops HEALTHCHECK instructions unless it writes the docker format.
if ! BUILDAH_FORMAT=docker "$ENGINE" build -t "$IMAGE" cs_mailbox >"$work/build.log" 2>&1; then
    tail -40 "$work/build.log" >&2
    echo "FAIL: image build" >&2
    exit 1
fi

inspect="$("$ENGINE" image inspect "$IMAGE")"
grep -q 'create_connection' <<<"$inspect" || fail "image has no health check configured"

echo "== launcher unit tests, on the image's Python"
"$ENGINE" run --rm --security-opt label=disable -v "$PWD/tests:/tests:ro" --entrypoint python3 "$IMAGE" \
    -m unittest discover -s /tests || fail "unit tests"

mkdir -p "$work/data" "$work/plain" "$work/upgrade" "$work/client" "$work/ssl"
cp scripts/smoke_client.py "$work/client/"
seed_a="$(printf '11%.0s' $(seq 32))"
pub_a="$("$ENGINE" run --rm --entrypoint python3 "$IMAGE" -I -c \
    "import sys; sys.path.insert(0, '/app/python'); from connectsensors import ed25519_pub; print(ed25519_pub(bytes.fromhex('$seed_a')).hex())")"

open_options='{"hosts":["127.0.0.1","localhost"],"ssl":false,"certfile":"fullchain.pem","keyfile":"privkey.pem","admission":"open","admit_per_hour":20,"members":[]}'

echo "== upgrade from $OLD_IMAGE keeps server_id and certificate"
"$ENGINE" pull -q "$OLD_IMAGE" >/dev/null || fail "could not pull $OLD_IMAGE"
DATA="$work/upgrade" RUN_IMAGE="$OLD_IMAGE" start "$open_options"
wait_listening
logged_pem > "$work/client/cert.pem"
old_fp="$(logged_fingerprint)"
[ -n "$old_fp" ] || fail "the old image logged no fingerprint"
old_id="$(json_field server_id <<<"$(client "$URL")")" || fail "client session with the old image failed"
DATA="$work/upgrade" start "$open_options"
wait_listening
logs_have 'Created server key' && fail "the upgrade made a new server key"
logs_have 'Created a self-signed certificate' && fail "the upgrade made a new certificate"
[ "$(logged_fingerprint)" = "$old_fp" ] || fail "certificate fingerprint changed across the upgrade"
# The pin taken from the old image's log still validates.
new_id="$(json_field server_id <<<"$(client "$URL")")" || fail "client session after the upgrade failed"
[ "$new_id" = "$old_id" ] || fail "server_id changed across the upgrade: $old_id -> $new_id"
echo "server_id $new_id and fingerprint $old_fp kept"

echo "== self-signed certificate, open admission"
start "$open_options"
wait_listening
logged_pem > "$work/client/cert.pem"
grep -q 'BEGIN CERTIFICATE' "$work/client/cert.pem" || fail "no certificate PEM in the log"
fp1="$(logged_fingerprint)"
[ -n "$fp1" ] || fail "no SHA-256 fingerprint in the log"
fp_pem="$(openssl x509 -in "$work/client/cert.pem" -noout -fingerprint -sha256 | cut -d= -f2)"
[ "$fp1" = "$fp_pem" ] || fail "logged fingerprint $fp1 is not the logged certificate's ($fp_pem)"
check_no_private_key_logged
uid="$("$ENGINE" exec "$NAME" sed -nE 's/^Uid:\s+([0-9]+).*/\1/p' /proc/1/status)"
[ "$uid" = 10001 ] || fail "cs-mailbox runs as uid $uid, expected 10001"
"$ENGINE" exec "$NAME" python3 -I -c \
    "import socket; socket.create_connection(('127.0.0.1', 8443), 5).close()" \
    || fail "health check command failed"

first="$(client "$URL" --full)" || fail "client session (register, ping) failed"
id1="$(json_field server_id <<<"$first")"
gen1="$(json_field generation <<<"$first")"
echo "server_id $id1 generation $gen1"
client wss://localhost:8443/ >/dev/null || fail "handshake under the host name localhost failed"
client "$URL" --expect-untrusted >/dev/null || fail "the certificate validated without the pin"

echo "== restart: same server_id and certificate, new generation"
start "$open_options"
wait_listening
[ "$(logged_fingerprint)" = "$fp1" ] || fail "the self-signed certificate changed across a restart"
logs_have 'Created server key' && fail "the server key was made again"
second="$(client "$URL" --full)" || fail "client session after restart failed"
[ "$(json_field server_id <<<"$second")" = "$id1" ] || fail "server_id changed across a restart"
[ "$(json_field generation <<<"$second")" != "$gen1" ] || fail "generation did not change across a restart"

echo "== a host the certificate does not cover gets a new one"
start '{"hosts":["127.0.0.1","localhost","mailbox.test"],"ssl":false,"admission":"open","members":[]}'
wait_listening
logs_have 'WARNING: Hosts names a host' || fail "no warning about the new certificate"
[ "$(logged_fingerprint)" != "$fp1" ] || fail "certificate kept although it does not cover mailbox.test"
logged_pem > "$work/client/cert.pem"
client "$URL" >/dev/null || fail "handshake with the new certificate failed"

echo "== members admission"
start "{\"hosts\":[\"127.0.0.1\"],\"ssl\":false,\"admission\":\"members\",\"members\":[\"$pub_a\"]}"
wait_listening
logged_pem > "$work/client/cert.pem"
client "$URL" --seed "$seed_a" --full >/dev/null || fail "a member was not admitted"
client "$URL" --expect-refused NOT_PERMITTED >/dev/null || fail "a non-member was admitted"

echo "== certificate from /ssl"
# Readable by its owner only, as /ssl keys usually are.
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 2 \
    -subj /CN=127.0.0.1 -addext subjectAltName=IP:127.0.0.1 \
    -addext basicConstraints=critical,CA:TRUE \
    -keyout "$work/ssl/privkey.pem" -out "$work/ssl/fullchain.pem" 2>/dev/null
chmod 600 "$work/ssl/privkey.pem"
start '{"hosts":["127.0.0.1"],"ssl":true,"certfile":"fullchain.pem","keyfile":"privkey.pem","admission":"open","members":[]}' \
    -v "$work/ssl:/ssl:ro,z"
wait_listening
check_no_private_key_logged
cp "$work/ssl/fullchain.pem" "$work/client/cert.pem"
client "$URL" --full >/dev/null || fail "client session with the /ssl certificate failed"

echo "== bad options stop the container with a clear message"
start '{"hosts":[],"ssl":false,"admission":"open","members":[]}'
wait_exited
[ "$("$ENGINE" inspect -f '{{.State.ExitCode}}' "$NAME")" = 1 ] || fail "empty hosts did not exit 1"
logs_have 'set at least one host' || fail "empty hosts not explained"
start '{"hosts":["127.0.0.1"],"ssl":true,"certfile":"missing.pem","keyfile":"privkey.pem","admission":"open","members":[]}'
wait_exited
logs_have 'missing.pem does not exist' || fail "missing certfile not explained"

echo "== plain container: arguments go to cs-mailbox"
# The /ssl pair again, still readable by root only, so the launcher has to copy it.
"$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true
"$ENGINE" run -d --name "$NAME" -v "$work/plain:/data:z" -v "$work/ssl:/tls:ro,z" "$IMAGE" \
    --host 127.0.0.1 --tls-cert /tls/fullchain.pem --tls-key=/tls/privkey.pem >/dev/null
wait_listening
client "$URL" --full >/dev/null || fail "client session with a plain container failed"
"$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true
help="$("$ENGINE" run --rm "$IMAGE" --help)"
grep -q -- '--admit-per-hour' <<<"$help" || fail "--help did not reach cs-mailbox"

echo "PASS"
