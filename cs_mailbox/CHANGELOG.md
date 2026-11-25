# Changelog

## 0.2.0

- Build on the published server image, `ghcr.io/chrisuthe/cs-mailbox` 0.2.0,
  instead of building cs-mailbox from a ConnectSensors commit. The server key,
  `server_id`, the self-signed certificate and the options are unchanged.
- cs-mailbox 0.2.0 adds a trusted-proxy mode; the app does not offer it yet.

## 0.1.1

- Rebuild on cs-mailbox from ConnectSensors 2ea6cee (the connectsensors 0.4.2
  release), which takes its protocol code from the package's public API. No
  change in behaviour.

## 0.1.0

- First version, on cs-mailbox from ConnectSensors 8f71061 (the
  connectsensors 0.4.1 release).
