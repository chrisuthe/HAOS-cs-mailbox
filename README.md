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

Experimental.

## Install

[![Add this repository to your Home Assistant instance.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fchrisuthe%2FHAOS-cs-mailbox)

1. Use the button above. Or, in **Settings → Apps → App store**, open the menu,
   choose **Repositories**, and add
   `https://github.com/chrisuthe/HAOS-cs-mailbox`.
2. Install **ConnectSensors mailbox** from the store, set **Hosts**, and start
   it.

The image also runs as a plain container; see the documentation.

## Layout

- `cs_mailbox/` — the app: `config.yaml`, `Dockerfile`, `requirements.txt`
  (the pinned ConnectSensors commit and packages), the store listing
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
smoke test: build the image, start it with the self-signed certificate, connect
as a client (greeting signature, `register` with a valid proof, `ping`), restart
it and check `server_id` stays and `generation` changes, then members
admission, a certificate from `/ssl`, bad options, and plain-container use.
It needs podman or docker, shellcheck, openssl and network access.

## Releases

Every push to `main` is tested on both architectures. If the `version` in
`cs_mailbox/config.yaml` has no published image yet, CI builds and pushes
`ghcr.io/chrisuthe/haos-cs-mailbox` for it, so a version bump on `main` is a
release.

## Updating cs-mailbox

Change the commit in `cs_mailbox/requirements.txt`, and `connectsensors` to the
release that commit is built with. Then bump `version` in `config.yaml`, add a
`CHANGELOG.md` entry, and run `bash scripts/verify.sh`.

## Licence

MIT — see [LICENSE](LICENSE). ConnectSensors and `cs-mailbox` are MIT licensed
too.
