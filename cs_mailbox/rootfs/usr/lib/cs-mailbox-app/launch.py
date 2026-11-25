#!/usr/bin/env python3
"""Start cs-mailbox from the app's Home Assistant options.

With /data/options.json (the Supervisor writes it), the options are translated
into a cs-mailbox command line. With arguments instead, as a plain container,
they go to cs-mailbox as they are, after the server key's --key-file.

Either way the launcher prepares /data as root, then runs cs-mailbox as the
unprivileged `mailbox` user. cs-mailbox gets the whole command line from here,
and none of the base image's CS_MAILBOX_* variables.
"""

import datetime
import ipaddress
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

OPTIONS_FILE = Path("/data/options.json")
# server.key and the self-signed certificate. Under /data so they survive
# restarts, updates and backups: the key is the server's identity (server_id),
# and the certificate is what homes have pinned.
STATE_DIR = Path("/data/mailbox")
# Files rebuilt on every start: the member list, and a copy of the /ssl
# certificate that the unprivileged user can read.
RUN_DIR = Path("/run/cs-mailbox")
SSL_DIR = Path("/ssl")
# The base image's checkout layout; cs_mailbox.py finds connectsensors beside it.
SERVER = "/app/mailbox/cs_mailbox.py"
# Fixed: config.yaml maps it, and the host port is set in the app's Network
# section.
PORT = 8443
MAILBOX_UID = MAILBOX_GID = 10001
CERT_DAYS = 3650

# Option name -> cs-mailbox flag, for limits that pass straight through.
LIMITS = {
    "reg_burst": "--reg-burst",
    "reg_per_hour": "--reg-per-hour",
    "reg_max_live": "--reg-max-live",
    "publish_rate": "--publish-rate",
    "publish_burst": "--publish-burst",
    "request_rate": "--request-rate",
    "message_rate": "--message-rate",
}


class ConfigError(Exception):
    """An option value the server cannot be started with."""


def log(msg):
    print(f"cs-mailbox-app: {msg}", flush=True)


def _is_set(value):
    return value is not None and value != ""


def hosts_of(options):
    hosts = [h.strip().lower() for h in options.get("hosts") or [] if h.strip()]
    if not hosts:
        raise ConfigError(
            "set at least one host under Hosts: the name or IP address homes "
            "use in the mailbox URL, such as 192.168.1.20 or mailbox.example.com"
        )
    return hosts


def ssl_file(name, what):
    """A file under /ssl named by the certfile or keyfile option."""
    if not _is_set(name):
        raise ConfigError(f"{what} is empty")
    path = (SSL_DIR / name).resolve()
    if SSL_DIR.resolve() not in path.parents:
        raise ConfigError(f"{what} {name!r} is outside {SSL_DIR}")
    if not path.is_file():
        raise ConfigError(f"{what} {path} does not exist")
    return path


def members_text(options):
    keys = [k.strip().lower() for k in options.get("members") or [] if k.strip()]
    if not keys:
        raise ConfigError("admission is members, but the member list is empty")
    return "".join(f"{k}\n" for k in keys)


def build_argv(options, hosts, cert, key, members_file):
    argv = [SERVER, "--port", str(PORT), "--key-file", str(STATE_DIR / "server.key")]
    for host in hosts:
        argv += ["--host", host]
    argv += ["--tls-cert", str(cert), "--tls-key", str(key)]
    admission = options.get("admission", "open")
    if admission == "members":
        argv += ["--members", str(members_file)]
    elif admission == "open":
        if _is_set(options.get("admit_per_hour")):
            argv += ["--admit-per-hour", str(options["admit_per_hour"])]
    else:
        raise ConfigError(f"admission {admission!r} is neither open nor members")
    for name, flag in LIMITS.items():
        if _is_set(options.get(name)):
            argv += [flag, str(options[name])]
    return argv


# ---------------------------------------------------------------- certificates


def _san_entry(host):
    from cryptography import x509

    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host)


def cert_covers(cert_pem, hosts):
    """Whether the certificate names every host, so a client can validate it."""
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(cert_pem)
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    return all(_san_entry(h) in san for h in hosts)


def make_self_signed(hosts, now=None):
    """A certificate and key for `hosts`, as PEM. The certificate is its own CA,
    so a client can trust it directly as a pinned certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    now = now or datetime.datetime.now(datetime.UTC)
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=CERT_DAYS))
        .add_extension(x509.SubjectAlternativeName([_san_entry(h) for h in hosts]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(ski, critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem


def fingerprint(cert_pem):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    digest = x509.load_pem_x509_certificate(cert_pem).fingerprint(hashes.SHA256())
    return ":".join(f"{b:02X}" for b in digest)


def _write_private(path, data):
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def self_signed(tls_dir, hosts):
    """The kept self-signed certificate, made on first start or when Hosts names
    one it does not cover. Returns (cert path, key path)."""
    cert, key = tls_dir / "cert.pem", tls_dir / "key.pem"
    tls_dir.mkdir(parents=True, exist_ok=True)
    if cert.is_file() and key.is_file() and cert_covers(cert.read_bytes(), hosts):
        log(f"Using the self-signed certificate in {cert}")
    else:
        if cert.is_file():
            log("WARNING: Hosts names a host the certificate does not cover, so a new "
                "certificate is made. Paste the new one into every home that pinned the old one.")
        cert_pem, key_pem = make_self_signed(hosts)
        # Key first: a certificate without its key would be kept and fail to load.
        _write_private(key, key_pem)
        cert.write_bytes(cert_pem)
        log(f"Created a self-signed certificate for {', '.join(hosts)} in {cert}")
    pem = cert.read_bytes()
    log("Trust this certificate in the ConnectSensors integration's Trusted certificate "
        "option (copy everything from BEGIN to END):\n" + pem.decode().strip())
    log(f"Certificate SHA-256 fingerprint: {fingerprint(pem)}")
    return cert, key


# ---------------------------------------------------------------- privileges


def is_root():
    return os.geteuid() == 0


def chown_tree(path):
    for root, dirs, files in os.walk(path):
        os.chown(root, MAILBOX_UID, MAILBOX_GID)
        for name in dirs + files:
            os.chown(os.path.join(root, name), MAILBOX_UID, MAILBOX_GID, follow_symlinks=False)


def prepare_dirs():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def hand_over():
    """Give the server its files, then drop root for good."""
    if not is_root():
        return
    chown_tree(STATE_DIR)
    chown_tree(RUN_DIR)
    os.setgroups([])
    os.setgid(MAILBOX_GID)
    os.setuid(MAILBOX_UID)


def run_dir_copy(src, name, private):
    """Copy an /ssl file where the unprivileged user can read it. /ssl keys are
    usually readable by root only."""
    if not is_root():
        return src
    dest = RUN_DIR / name
    if private:
        _write_private(dest, src.read_bytes())
    else:
        shutil.copyfile(src, dest)
    return dest


def pass_through(args):
    """A plain container's arguments, with --tls-cert and --tls-key pointed at
    copies the unprivileged user can read."""
    argv = [SERVER, "--key-file", str(STATE_DIR / "server.key")]
    copies = {"--tls-cert": ("cert.pem", False), "--tls-key": ("key.pem", True)}
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        flag, eq, value = arg.partition("=")
        if flag in copies and (eq or rest):
            if not eq:
                value = rest.pop(0)
            name, private = copies[flag]
            argv += [flag, str(run_dir_copy(Path(value), name, private))]
        else:
            argv.append(arg)
    return argv


def from_options(options):
    hosts = hosts_of(options)
    if options.get("ssl"):
        cert = ssl_file(options.get("certfile"), "certfile")
        key = ssl_file(options.get("keyfile"), "keyfile")
        log(f"Using {cert} from Home Assistant's /ssl; "
            f"SHA-256 fingerprint {fingerprint(cert.read_bytes())}")
        cert = run_dir_copy(cert, "cert.pem", private=False)
        key = run_dir_copy(key, "key.pem", private=True)
    else:
        cert, key = self_signed(STATE_DIR / "tls", hosts)
    members = RUN_DIR / "members.txt"
    if options.get("admission") == "members":
        members.write_text(members_text(options))
    return build_argv(options, hosts, cert, key, members)


def server_env(environ):
    """The environment without the base image's CS_MAILBOX_* variables, which
    are container_entry.py's and have no say here."""
    return {k: v for k, v in environ.items() if not k.startswith("CS_MAILBOX_")}


def main(args):
    try:
        prepare_dirs()
        if args:
            argv = pass_through(args)
        elif OPTIONS_FILE.is_file():
            argv = from_options(json.loads(OPTIONS_FILE.read_text()))
        else:
            raise ConfigError(
                f"no {OPTIONS_FILE} and no arguments: pass cs-mailbox arguments "
                "(see cs-mailbox --help), or mount an options file"
            )
        hand_over()
    except (OSError, ValueError, ConfigError) as err:
        print(f"cs-mailbox-app: {err}", file=sys.stderr, flush=True)
        return 1
    command = [sys.executable, "-I", *argv]
    log(f"starting {shlex.join(command)}")
    os.execve(sys.executable, command, server_env(os.environ))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
