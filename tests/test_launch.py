"""Tests for the launcher. They need cryptography, so scripts/smoke_test.sh runs
them in the app image:

    podman run --rm --security-opt label=disable -v "$PWD/tests:/tests:ro" --entrypoint python3 IMAGE -m unittest discover -s /tests
"""

import datetime
import importlib.util
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
CANDIDATES = [
    HERE.parent / "cs_mailbox/rootfs/usr/lib/cs-mailbox-app/launch.py",
    Path("/usr/lib/cs-mailbox-app/launch.py"),  # in the image
]
_spec = importlib.util.spec_from_file_location("launch", next(p for p in CANDIDATES if p.is_file()))
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)

BASE = {
    "hosts": ["192.168.1.20"],
    "ssl": False,
    "certfile": "fullchain.pem",
    "keyfile": "privkey.pem",
    "admission": "open",
    "admit_per_hour": 20,
    "members": [],
}
KEY = "ab" * 32


def argv(options, hosts=None):
    return launch.build_argv(options, hosts or launch.hosts_of(options), "/c.pem", "/k.pem", "/m.txt")


def flag(args, name):
    return args[args.index(name) + 1] if name in args else None


class BuildArgv(unittest.TestCase):
    def test_defaults(self):
        a = argv(BASE)
        self.assertEqual(a[0], launch.SERVER)
        self.assertEqual(flag(a, "--port"), "8443")
        self.assertEqual(flag(a, "--key-file"), "/data/mailbox/server.key")
        self.assertEqual(flag(a, "--tls-cert"), "/c.pem")
        self.assertEqual(flag(a, "--tls-key"), "/k.pem")
        self.assertEqual(flag(a, "--admit-per-hour"), "20")
        self.assertNotIn("--members", a)
        self.assertNotIn("--insecure-dev", a)

    def test_every_host_is_passed(self):
        a = argv({**BASE, "hosts": ["Mailbox.Example", " 10.0.0.16 ", ""]})
        self.assertEqual([a[i + 1] for i, x in enumerate(a) if x == "--host"], ["mailbox.example", "10.0.0.16"])

    def test_no_hosts(self):
        for hosts in ([], [""], None):
            with self.assertRaisesRegex(launch.ConfigError, "at least one host"):
                launch.hosts_of({**BASE, "hosts": hosts})

    def test_members(self):
        a = argv({**BASE, "admission": "members", "members": [KEY]})
        self.assertEqual(flag(a, "--members"), "/m.txt")
        self.assertNotIn("--admit-per-hour", a)

    def test_members_text(self):
        self.assertEqual(launch.members_text({"members": [KEY.upper(), " "]}), KEY + "\n")
        with self.assertRaisesRegex(launch.ConfigError, "member list is empty"):
            launch.members_text({"members": []})

    def test_unknown_admission(self):
        with self.assertRaises(launch.ConfigError):
            argv({**BASE, "admission": "closed"})

    def test_limits_pass_through_when_set(self):
        a = argv({**BASE, "reg_burst": 8, "publish_rate": 2.5, "message_rate": None, "request_rate": ""})
        self.assertEqual(flag(a, "--reg-burst"), "8")
        self.assertEqual(flag(a, "--publish-rate"), "2.5")
        self.assertNotIn("--message-rate", a)
        self.assertNotIn("--request-rate", a)

    def test_every_limit_has_a_flag(self):
        options = {**BASE, **{name: 1 for name in launch.LIMITS}}
        a = argv(options)
        for f in launch.LIMITS.values():
            self.assertEqual(flag(a, f), "1")


class SslFile(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "fullchain.pem").write_text("x")
        patcher = mock.patch.object(launch, "SSL_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_found(self):
        self.assertEqual(launch.ssl_file("fullchain.pem", "certfile"), (self.dir / "fullchain.pem").resolve())

    def test_missing(self):
        with self.assertRaisesRegex(launch.ConfigError, "does not exist"):
            launch.ssl_file("nope.pem", "certfile")

    def test_outside_ssl(self):
        for name in ("../etc/passwd", "/etc/passwd"):
            with self.assertRaisesRegex(launch.ConfigError, "outside"):
                launch.ssl_file(name, "keyfile")

    def test_empty(self):
        with self.assertRaisesRegex(launch.ConfigError, "empty"):
            launch.ssl_file("", "keyfile")


class SelfSigned(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "tls"

    def make(self, hosts):
        with mock.patch.object(launch, "log"):
            return launch.self_signed(self.dir, hosts)

    def test_made_once_and_kept(self):
        cert, key = self.make(["10.0.0.16", "mailbox.example"])
        first = cert.read_bytes()
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.make(["mailbox.example"])  # a subset is still covered
        self.assertEqual(cert.read_bytes(), first)

    def test_remade_for_a_new_host(self):
        cert, _ = self.make(["10.0.0.16"])
        first = cert.read_bytes()
        self.make(["10.0.0.16", "10.0.0.17"])
        self.assertNotEqual(cert.read_bytes(), first)
        self.assertTrue(launch.cert_covers(cert.read_bytes(), ["10.0.0.16", "10.0.0.17"]))

    def test_covers_ips_and_names(self):
        cert, _ = launch.make_self_signed(["10.0.0.16", "mailbox.example", "::1"])
        self.assertTrue(launch.cert_covers(cert, ["10.0.0.16", "mailbox.example", "::1"]))
        self.assertFalse(launch.cert_covers(cert, ["10.0.0.17"]))
        # An IP address is matched as an address, not as a DNS name.
        cert, _ = launch.make_self_signed(["mailbox.example"])
        self.assertFalse(launch.cert_covers(cert, ["10.0.0.16"]))

    def test_usable_as_a_pinned_trust_anchor(self):
        # The integration adds the pinned certificate as cadata; OpenSSL lists
        # it as a CA only if it is marked as one. The handshake itself is
        # checked by the smoke test.
        cert, _ = launch.make_self_signed(["10.0.0.16"])
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=cert.decode())
        self.assertEqual(len(ctx.get_ca_certs()), 1)

    def test_validity(self):
        from cryptography import x509

        now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        cert = x509.load_pem_x509_certificate(launch.make_self_signed(["a.example"], now)[0])
        self.assertLess(cert.not_valid_before_utc, now)
        self.assertEqual((cert.not_valid_after_utc - now).days, launch.CERT_DAYS)

    def test_fingerprint_format(self):
        fp = launch.fingerprint(launch.make_self_signed(["a.example"])[0])
        self.assertRegex(fp, r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")


class PassThrough(unittest.TestCase):
    def test_key_file_first_and_args_kept(self):
        with mock.patch.object(launch, "is_root", return_value=False):
            a = launch.pass_through(["--host", "m.example", "--tls-cert", "/t/c.pem", "--tls-key=/t/k.pem"])
        self.assertEqual(a[:3], [launch.SERVER, "--key-file", "/data/mailbox/server.key"])
        self.assertEqual(a[3:], ["--host", "m.example", "--tls-cert", "/t/c.pem", "--tls-key", "/t/k.pem"])

    def test_tls_files_copied_when_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src, run = Path(tmp.name) / "src", Path(tmp.name) / "run"
        src.mkdir()
        run.mkdir()
        (src / "c.pem").write_text("cert")
        (src / "k.pem").write_text("key")
        with mock.patch.object(launch, "is_root", return_value=True), mock.patch.object(launch, "RUN_DIR", run):
            a = launch.pass_through(["--tls-cert", str(src / "c.pem"), "--tls-key", str(src / "k.pem")])
        self.assertEqual(flag(a, "--tls-cert"), str(run / "cert.pem"))
        self.assertEqual(flag(a, "--tls-key"), str(run / "key.pem"))
        self.assertEqual((run / "key.pem").read_text(), "key")
        self.assertEqual((run / "key.pem").stat().st_mode & 0o777, 0o600)

    def test_help(self):
        self.assertEqual(launch.pass_through(["--help"])[-1], "--help")


if __name__ == "__main__":
    unittest.main()
