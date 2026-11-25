# ConnectSensors mailbox

Runs [cs-mailbox](https://github.com/chrisuthe/ConnectSensors/tree/main/mailbox),
the federation mailbox server of
[ConnectSensors](https://github.com/chrisuthe/ConnectSensors)
([spec 09](https://github.com/chrisuthe/ConnectSensors/blob/main/spec/09-federation-relay.md)).
The server is the published `ghcr.io/chrisuthe/cs-mailbox` image; the app adds
these options, the self-signed certificate and Home Assistant's `/ssl`.
Homes that use the same mailbox pass each other the frames their proxies hear
from sensors they do not own, and the downlinks those sensors are owed. The
mailbox reads no payloads and holds no device keys.

## Getting started

1. Set **Hosts** to the address homes will use to reach this machine, such as
   its IP address `192.168.1.20`, and start the app.
2. Open the **Log** tab. It shows the self-signed certificate the app made,
   from `-----BEGIN CERTIFICATE-----` to `-----END CERTIFICATE-----`, and its
   SHA-256 fingerprint.
3. In each home's ConnectSensors integration, add the mailbox
   `wss://192.168.1.20:8443/` and paste that certificate, BEGIN and END lines
   included, into **Trusted certificate**.

The port is 8443 unless you change it in the app's **Network** section; the URL
uses whichever port you set there.

To give the mailbox a public name and certificate through the Nginx Proxy
Manager app instead, see [Behind Nginx Proxy Manager](#behind-nginx-proxy-manager).

## Configuration

| Option | Meaning |
|---|---|
| **Hosts** | Host names or IP addresses in the URL homes use. At least one is required. |
| **Use a certificate from /ssl** | Off (the default): a self-signed certificate, made once and kept. On: **Certificate file** and **Private key file** from Home Assistant's `/ssl` folder. |
| **Certificate file**, **Private key file** | File names in `/ssl`. Default `fullchain.pem` and `privkey.pem`, as the Let's Encrypt and DuckDNS apps write them. |
| **Admission** | `open` or `members`. See below. |
| **New clients per address per hour** | With `open`: new client keys one address may bring each hour. Default 20. |
| **Member keys** | With `members`: the client public keys admitted, 64 hex digits each. |
| **Trusted proxies** | Empty (the default): the app serves TLS itself. Set: address ranges of a reverse proxy that terminates TLS, such as `172.30.33.0/24`. See [Behind Nginx Proxy Manager](#behind-nginx-proxy-manager). |

The limits are behind "Show unused optional configuration options". Unset, each
takes cs-mailbox's default, which is the open server's limit from spec 09
section 11.

| Option | Default | Meaning |
|---|---|---|
| **Registration burst** | 2048 | Registration entries per owner key at once. |
| **Registrations per hour** | 512 | Registration entries per owner key per hour after the burst. |
| **Live registrations** | 4096 | Registrations one owner key may hold at a time. |
| **Publishes per second** | 5 | Frames one client key may publish per second. |
| **Publish burst** | 20 | Frames one client key may publish at once. |
| **Requests per second** | 10 | Downlink requests per client key per second. |
| **Messages per second** | 50 | Signed messages of any kind per client key per second; the burst is twice this. |

A message over a limit is refused with `RATE_LIMITED` and not acted on.

## Hosts and certificates

Every client checks two things about the name in its mailbox URL: that the
certificate names it, and that the server's greeting is signed for it. So list
under **Hosts** every name or address homes will use, and use a certificate
that covers them all.

**Self-signed (the default).** On first start the app makes a certificate for
the hosts listed and keeps it, with its key, in the app's `/data`. It is reused
on every start and update, so homes paste it once. If you later add a host the
certificate does not name, the app makes a new certificate and says so in the
log; paste the new one into every home again.

**From /ssl.** Turn on **Use a certificate from /ssl** to serve a certificate
you already have there, such as one from the Let's Encrypt app. It must name
every host. Homes then need nothing in **Trusted certificate** if it comes from
a public authority.

The private keys are never written to the log.

## Behind Nginx Proxy Manager

The [Nginx Proxy Manager](https://github.com/hassio-addons/app-nginx-proxy-manager)
app can hold a public certificate for the mailbox and terminate TLS. The
mailbox then serves plain WebSocket to NPM, refuses everyone else, and counts
each client by the address NPM reports
([spec 09](https://github.com/chrisuthe/ConnectSensors/blob/main/spec/09-federation-relay.md)
section 12.1). Homes see an ordinary `wss://` server with a public certificate.

1. In this app's **Configuration**:
   - set **Hosts** to the public name homes will use, such as
     `mailbox.example.com`;
   - set **Trusted proxies** to `172.30.33.0/24`;
   - leave **Use a certificate from /ssl** off. The app refuses to start with
     both set.
2. In the app's **Network** section, clear the host port so the plain port is
   not published on your network. NPM reaches the app over Home Assistant's
   internal network, which does not need it.
3. Start the app. The log reads `Behind a TLS-terminating proxy: serving plain
   WebSocket, without a certificate, to 172.30.33.0/24 only` and `Listening on
   ws://0.0.0.0:8443 ... behind trusted proxies 172.30.33.0/24`. No certificate
   is made or shown.
4. Note the app's **Hostname** on its **Info** tab, such as
   `f202d657-cs-mailbox` (the first part depends on the repository URL you added).
5. In NPM, under **Hosts → Proxy Hosts → Add Proxy Host**:
   - **Details:** Domain Names `mailbox.example.com`; Scheme `http`; Forward
     Hostname / IP the hostname from step 4; Forward Port `8443`; turn on
     **Websockets Support**.
   - **SSL:** request a Let's Encrypt certificate for the name, or pick one you
     have, and turn on **Force SSL**.
6. In each home's ConnectSensors integration, add the mailbox
   `wss://mailbox.example.com/` and leave **Trusted certificate** empty: the
   certificate comes from a public authority.

NPM passes the public name through as `Host`, which is the name the mailbox's
greeting is signed for, so it must be listed under **Hosts**.

### Which addresses to trust

Apps on Home Assistant's internal network are given addresses from
`172.30.33.0/24` when they start, so NPM's address can change from one restart
to the next; the range covers any address it gets. NPM forwards over IPv4 (its
nginx resolver has IPv6 turned off), so no IPv6 range is needed.

Do not trust the whole internal network, `172.30.32.0/23`. Its gateway,
`172.30.32.1`, is the host itself: Home Assistant Core, apps on the host
network, and connections through Docker's port proxy all arrive from it. The app
warns in its log if a range includes it.

`172.30.33.0/24` still trusts every other app on the system: any of them may
connect without TLS and report any client address. That affects only open
admission's limit on new keys per address; it gets past neither **members**
admission nor the clients' own keys. To narrow it, trust NPM's current address
alone, such as `172.30.33.5/32` (`ha addons info a0d7b954_nginxproxymanager`
shows it as `ip_address`). If NPM later gets another address, the mailbox
refuses it and logs `172.30.33.6: not a trusted proxy, refused`; update the
option to match.

### NPM and forwarded addresses

NPM itself trusts an incoming `X-Real-IP` header from private addresses
(`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) and from the Cloudflare and
CloudFront ranges it downloads at start. So a client on your LAN, or anyone who
points their own Cloudflare zone or CloudFront distribution at your name, can
choose the address the mailbox counts it by. NPM's own setting to stop the
download, `IP_RANGES_FETCH_ENABLED=false`, is not offered by the NPM app. Again
this weakens only open admission's per-address limit. Where that limit must
hold, use **members** admission.

## Admission

**open** admits any client key. To slow down anyone minting keys, each IP
address (each /64 for IPv6) may bring at most **New clients per address per
hour** new keys. Keys already admitted are not counted again.

**members** admits only the keys under **Member keys**. Use it for a mailbox
shared by a known set of homes. A home uses a separate client key for each
mailbox server, made by its ConnectSensors integration; the integration does
not show it yet, so for now members admission suits clients whose keys you
already know.

## What is kept

- The server key, in `/data/mailbox/server.key`. It is the server's identity:
  its `server_id` is derived from it, so homes recognise the server across
  restarts and updates. It is included in the app's backups. Uninstalling the
  app deletes it, and homes then see a new server.
- The self-signed certificate and its key, in `/data/mailbox/tls/`.

Registrations are kept in memory only. Each start picks a new `generation`,
which tells homes to register again; they do so on their own.

## Running outside Home Assistant

The image runs as a plain container too. Give it the `cs-mailbox` arguments
directly, and a volume for `/data`, where it keeps the server key:

```sh
docker run -d -p 8443:8443 -v cs-mailbox:/data -v /etc/letsencrypt:/etc/letsencrypt:ro \
    ghcr.io/chrisuthe/haos-cs-mailbox:0.3.0 \
    --host mailbox.example \
    --tls-cert /etc/letsencrypt/live/mailbox.example/fullchain.pem \
    --tls-key /etc/letsencrypt/live/mailbox.example/privkey.pem
```

`--help` lists every argument. Keep the container port at 8443, which the
health check uses. The `CS_MAILBOX_*` variables of the `cs-mailbox` image have
no effect here; use the arguments. Outside Home Assistant, that image itself
may suit better. To use the options above instead, including the
self-signed certificate, put them in `/data/options.json` and pass no
arguments.

## Security

`cs-mailbox` runs as an unprivileged user; the app's launcher prepares `/data`
as root first. TLS 1.3 is required, between homes and NPM when the app runs
behind it. The app has an AppArmor profile.
