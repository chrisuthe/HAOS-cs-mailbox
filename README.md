# HAOS-cs-mailbox

A Home Assistant app (formerly "add-on") that runs
[`cs-mailbox`](https://github.com/chrisuthe/ConnectSensors/tree/main/mailbox),
the federation mailbox server of
[ConnectSensors](https://github.com/chrisuthe/ConnectSensors)
([spec 09](https://github.com/chrisuthe/ConnectSensors/blob/main/spec/09-federation-relay.md)).
A home, or a neighbourhood, can run a mailbox on Home Assistant OS, and the
homes' ConnectSensors integrations connect to it.

This repository packages `cs-mailbox`; it does not fork it. The server is
developed in ConnectSensors, and fixes to it go there. See
[cs_mailbox/DOCS.md](cs_mailbox/DOCS.md) for the user documentation.

## Status

Experimental, like ConnectSensors itself.

- **Current release:** 0.2.0, built on the published server image
  `ghcr.io/chrisuthe/cs-mailbox` 0.2.0 from
  [ConnectSensors](https://github.com/chrisuthe/ConnectSensors/tree/main/mailbox).
- **Works with:** the [ConnectSensors integration](https://github.com/chrisuthe/connect-sensors-ha)
  0.2.0 or later, currently 0.2.3. Point its federation options at
  `wss://<host>:8443/`, and paste the app's logged certificate into
  **Trusted certificate** when the app uses its self-signed one.
- **Tested:** end to end on Home Assistant OS, with two homes federating a door
  sensor through the app. Updates keep the same `server_id` and certificate.
  Each image passes a smoke test on amd64 and aarch64.

## Install

[![Add this repository to your Home Assistant instance.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fchrisuthe%2FHAOS-cs-mailbox)

1. Use the button above. Or, in **Settings → Apps → App store**, open the menu,
   choose **Repositories**, and add
   `https://github.com/chrisuthe/HAOS-cs-mailbox`.
2. Install **ConnectSensors mailbox** from the store, set **Hosts**, and start
   it.

The image also runs as a plain container; see the documentation.

## Layout

- `cs_mailbox/` — the app: `config.yaml`, `Dockerfile` (a thin layer over
  the pinned `cs-mailbox` image), the store listing
  (`README.md`, `DOCS.md`, `CHANGELOG.md`, `icon.png`, `logo.png`),
  `translations/`, `apparmor.txt`, and the launcher under `rootfs/`.
- `tests/` — unit tests for the launcher.
- `scripts/verify.sh` — every check CI runs, in one command.
- `scripts/smoke_test.sh` — builds the image and runs it as the Supervisor
  would, then connects with `scripts/smoke_client.py`.
- `.github/workflows/build.yml` — lint, test on both architectures, publish.

## Test

```sh
bash scripts/verify.sh
```

It lints the shell scripts, the workflows and the app manifest, then runs the
smoke test: build the image, upgrade a `/data` from the published 0.1.1 and
check `server_id` and the certificate stay, start it with the self-signed
certificate, connect as a client (greeting signature, `register` with a valid
proof, `ping`), restart it and check `server_id` stays and `generation`
changes, then members
admission, a certificate from `/ssl`, bad options, and plain-container use.
It needs podman or docker, shellcheck, openssl and network access.

## Releases

Every push to `main` is tested on both architectures. If the `version` in
`cs_mailbox/config.yaml` has no published image yet, CI builds and pushes
`ghcr.io/chrisuthe/haos-cs-mailbox` for it, so a version bump on `main` is a
release.

## Updating cs-mailbox

The server comes from the `ghcr.io/chrisuthe/cs-mailbox` image, released from
ConnectSensors. Move `BASE` in `cs_mailbox/Dockerfile` to the new tag and its
multi-arch index digest (`skopeo inspect --raw docker://ghcr.io/chrisuthe/cs-mailbox:<tag> | sha256sum`).
Then bump `version` in `config.yaml`, add a `CHANGELOG.md` entry, and run
`bash scripts/verify.sh`. The digest is moved by hand: Dependabot's docker
ecosystem cannot follow a digest given through an `ARG`.

## Licence

MIT — see [LICENSE](LICENSE). ConnectSensors and `cs-mailbox` are MIT licensed
too.
