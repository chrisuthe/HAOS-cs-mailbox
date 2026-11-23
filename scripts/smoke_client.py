#!/usr/bin/env python3
"""A minimal cs-mailbox client for scripts/smoke_test.sh (spec 09 section 12).

Runs inside the app image, which has the connectsensors package and websockets.
The mailbox helpers (greeting, auth, signed messages, registration proofs) are
in connectsensors._csframe, the spec's reference module that cs-mailbox itself
uses; the package's public surface does not export them.

    smoke_client.py URL CERT [--seed HEX] [--full] [--expect-refused CODE] [--expect-untrusted]

Prints one JSON line: server_id and generation on success, or what was expected.
Exits 1 on any failed check.
"""

import argparse
import asyncio
import json
import secrets
import ssl
import sys
import time
from urllib.parse import urlsplit

from connectsensors import _csframe as cs
from websockets.asyncio.client import connect

SUBPROTOCOL = "cs-mailbox.1"


class Refused(Exception):
    pass


def require(cond, what):
    if not cond:
        raise AssertionError(what)


def tls_context(cert):
    # As the Home Assistant integration builds it: the default context, TLS 1.3,
    # and the pinned certificate added as a trust anchor.
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    if cert:
        with open(cert) as f:
            ctx.load_verify_locations(cadata=f.read())
    return ctx


class Link:
    def __init__(self, ws, seed, server_id, nonce_s):
        self.ws, self.seed, self.server_id, self.nonce_s = ws, seed, server_id, nonce_s
        self.seq = 0

    async def send(self, m):
        self.seq += 1
        await self.ws.send(cs.signed(self.seed, self.server_id, self.nonce_s, [m[0], self.seq, *m[1:]]))
        return self.seq

    async def expect(self, mtype):
        """The next message of mtype, answering the server's pings meanwhile."""
        async with asyncio.timeout(5):
            while True:
                m = cs.mb_decode(await self.ws.recv())
                if m[0] == mtype:
                    return m
                if m[0] == cs.MB_PING_S:
                    await self.send([cs.MB_PONG, m[1]])
                elif m[0] == cs.MB_ERROR:
                    raise Refused(cs.MB_ERRORS[m[2]])


async def session(url, cert, seed, full):
    host = urlsplit(url).hostname.lower()
    async with connect(url, ssl=tls_context(cert), subprotocols=[SUBPROTOCOL],
                       max_size=cs.MB_MAX_MESSAGE, compression=None, open_timeout=10) as ws:
        require(ws.subprotocol == SUBPROTOCOL, f"subprotocol {ws.subprotocol}")
        nonce_c = secrets.token_bytes(16)
        await ws.send(cs.cbor([cs.MB_HELLO, cs.MB_VERSION, nonce_c]))
        g = cs.mb_decode(await ws.recv())
        if g[0] == cs.MB_ERROR:
            raise Refused(cs.MB_ERRORS[g[2]])
        require(g[0] == cs.MB_GREETING, f"expected greeting, got type {g[0]}")
        _, version, server_pub, server_id, generation, nonce_s, sig = g
        require(version == cs.MB_VERSION, f"greeting version {version}")
        require(server_id == cs.server_id_of(server_pub), "server_id is not the hash of the server key")
        require(not cs.ed_verify_error(server_pub, cs.greeting_msg(host, nonce_c, nonce_s, generation), sig),
                f"greeting is not signed for host {host}")

        pub = cs.ed25519_pub(seed)
        await ws.send(cs.cbor([cs.MB_AUTH, pub, cs.ed_sign(seed, cs.auth_msg(server_id, nonce_c, nonce_s, pub))]))
        w = cs.mb_decode(await ws.recv())
        if w[0] == cs.MB_ERROR:
            raise Refused(cs.MB_ERRORS[w[2]])
        require(w == [cs.MB_WELCOME, cs.pseudonym(server_id, pub)], f"expected welcome, got {w}")

        if full:
            link = Link(ws, seed, server_id, nonce_s)
            keys = cs.keys_from(bytes(range(16)), bytes.fromhex("c5c50000000000b1"))
            epoch = cs.epoch_of(int(time.time()))
            entry = cs.reg_entry(cs.tag_seed(keys.k_dev_tag, cs.epoch_index(epoch)), server_id, pub,
                                 cs.EPOCH_SECONDS * (epoch + 2))
            seq = await link.send([cs.MB_REGISTER, [entry]])
            reg = await link.expect(cs.MB_REGISTERED)
            require(reg == [cs.MB_REGISTERED, seq, [0]], f"register answered {reg}")
            seq = await link.send([cs.MB_PING])
            pong = await link.expect(cs.MB_PONG_S)
            require(pong == [cs.MB_PONG_S, seq], f"ping answered {pong}")
        return {"server_id": server_id.hex(), "generation": generation}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("cert", help="the certificate to pin, PEM")
    ap.add_argument("--seed", help="client key seed, 64 hex digits (default: a fresh key)")
    ap.add_argument("--full", action="store_true", help="also register one tag and ping")
    ap.add_argument("--expect-refused", metavar="CODE", help="pass only if the handshake is refused with CODE")
    ap.add_argument("--expect-untrusted", action="store_true",
                    help="pass only if the certificate fails validation without the pin")
    args = ap.parse_args()
    seed = bytes.fromhex(args.seed) if args.seed else secrets.token_bytes(32)
    try:
        if args.expect_untrusted:
            try:
                asyncio.run(session(args.url, None, seed, False))
            except ssl.SSLCertVerificationError as err:
                print(json.dumps({"untrusted": err.verify_message}))
                return 0
            raise AssertionError("the certificate validated without being pinned")
        try:
            result = asyncio.run(session(args.url, args.cert, seed, args.full))
        except Refused as err:
            if str(err) == args.expect_refused:
                print(json.dumps({"refused": str(err)}))
                return 0
            raise AssertionError(f"refused: {err}") from None
        if args.expect_refused:
            raise AssertionError(f"admitted, expected {args.expect_refused}")
        print(json.dumps(result))
        return 0
    except (AssertionError, OSError, ValueError) as err:
        print(f"smoke_client: {type(err).__name__}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
