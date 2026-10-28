"""Nasdaq TotalView-ITCH 5.0 message codec.

Covers the messages an order book needs plus the two housekeeping
messages that show up at the start of every file:

    S  System Event                       12 bytes
    R  Stock Directory                    39 bytes
    A  Add Order (no MPID)                36 bytes
    F  Add Order (MPID attribution)       40 bytes
    E  Order Executed                     31 bytes
    C  Order Executed With Price          36 bytes
    X  Order Cancel                       23 bytes
    D  Order Delete                       19 bytes
    U  Order Replace                      35 bytes

Every other message type is skipped by length, which is what the RTL
parser does too.

Spec facts this file relies on (TotalView-ITCH 5.0):
  * All integers are big-endian.
  * Prices are 4-byte integers with 4 implied decimal places.
  * Timestamps are 6-byte nanoseconds since midnight.
  * Common header: type(1) locate(2) tracking(2) timestamp(6) = 11 bytes.

Nasdaq's sample BinaryFILE dumps put a 2-byte big-endian length in
front of every message. iter_messages() expects that framing.
"""

from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator, Optional

# Total length of each message type, including the type byte.
# Source: TotalView-ITCH 5.0 specification.
MSG_LEN = {
    b"S": 12, b"R": 39, b"H": 25, b"Y": 20, b"L": 26, b"V": 35, b"W": 12,
    b"K": 28, b"J": 35, b"h": 21, b"A": 36, b"F": 40, b"E": 31, b"C": 36,
    b"X": 23, b"D": 19, b"U": 35, b"P": 44, b"Q": 40, b"B": 19, b"I": 50,
    b"N": 20, b"O": 48,
}

# Message types that change the book, as byte values (compare with raw[0]).
BOOK_TYPES = frozenset(b"AFECXDU")

HEADER = struct.Struct(">cHH6s")  # type, locate, tracking, timestamp(6)


def _ts_to_int(raw: bytes) -> int:
    return int.from_bytes(raw, "big")


def _int_to_ts(ns: int) -> bytes:
    return ns.to_bytes(6, "big")


@dataclass
class Msg:
    """One decoded message. Fields a type does not use stay at defaults."""

    type: str
    locate: int = 0
    tracking: int = 0
    timestamp: int = 0
    ref: int = 0            # order reference number (original ref for U)
    new_ref: int = 0        # U only
    side: str = ""          # 'B' or 'S' for A/F
    shares: int = 0         # A/F/U: order shares; E/C: executed; X: cancelled
    stock: str = ""         # A/F/R
    price: int = 0          # A/F/U: price; C: execution price (4 implied decimals)
    match: int = 0          # E/C
    printable: str = ""     # C
    mpid: str = ""          # F
    event_code: str = ""    # S
    extra: dict = field(default_factory=dict)  # R fields we don't model


# ---------------------------------------------------------------- decode

def decode(buf: bytes) -> Optional[Msg]:
    """Decode one message body (no length prefix). Returns None for
    message types this model does not track."""
    t = buf[0:1]
    if t not in MSG_LEN:
        raise ValueError(f"unknown message type {t!r}")
    if len(buf) != MSG_LEN[t]:
        raise ValueError(f"type {t!r}: expected {MSG_LEN[t]} bytes, got {len(buf)}")

    _, locate, tracking, ts = HEADER.unpack_from(buf, 0)
    m = Msg(type=t.decode(), locate=locate, tracking=tracking, timestamp=_ts_to_int(ts))
    body = buf[11:]

    if t in (b"A", b"F"):
        m.ref, side, m.shares, stock, m.price = struct.unpack_from(">Qc I 8s I", body, 0)
        m.side = side.decode()
        m.stock = stock.decode("ascii").rstrip()
        if t == b"F":
            m.mpid = body[25:29].decode("ascii").rstrip()
    elif t == b"E":
        m.ref, m.shares, m.match = struct.unpack_from(">QIQ", body, 0)
    elif t == b"C":
        m.ref, m.shares, m.match, pr, m.price = struct.unpack_from(">QIQcI", body, 0)
        m.printable = pr.decode()
    elif t == b"X":
        m.ref, m.shares = struct.unpack_from(">QI", body, 0)
    elif t == b"D":
        (m.ref,) = struct.unpack_from(">Q", body, 0)
    elif t == b"U":
        m.ref, m.new_ref, m.shares, m.price = struct.unpack_from(">QQII", body, 0)
    elif t == b"S":
        m.event_code = body[0:1].decode()
    elif t == b"R":
        m.stock = body[0:8].decode("ascii").rstrip()
        m.extra["round_lot"] = struct.unpack_from(">I", body, 10)[0]
    else:
        return None
    return m


# ---------------------------------------------------------------- encode

def _stock8(s: str) -> bytes:
    return s.encode("ascii").ljust(8, b" ")[:8]


def encode(m: Msg) -> bytes:
    """Encode a Msg into its wire bytes (no length prefix)."""
    t = m.type.encode()
    head = HEADER.pack(t, m.locate, m.tracking, _int_to_ts(m.timestamp))
    if t == b"A":
        body = struct.pack(">Qc I 8s I", m.ref, m.side.encode(), m.shares, _stock8(m.stock), m.price)
    elif t == b"F":
        body = struct.pack(">Qc I 8s I 4s", m.ref, m.side.encode(), m.shares,
                           _stock8(m.stock), m.price, m.mpid.encode().ljust(4, b" ")[:4])
    elif t == b"E":
        body = struct.pack(">QIQ", m.ref, m.shares, m.match)
    elif t == b"C":
        body = struct.pack(">QIQcI", m.ref, m.shares, m.match, (m.printable or "Y").encode(), m.price)
    elif t == b"X":
        body = struct.pack(">QI", m.ref, m.shares)
    elif t == b"D":
        body = struct.pack(">Q", m.ref)
    elif t == b"U":
        body = struct.pack(">QQII", m.ref, m.new_ref, m.shares, m.price)
    elif t == b"S":
        body = (m.event_code or "O").encode()
    elif t == b"R":
        body = _stock8(m.stock) + b"QN" + struct.pack(">I", m.extra.get("round_lot", 100)) \
            + b"NC" + b"Z " + b"PNN1N" + struct.pack(">I", 0) + b"N"
    else:
        raise ValueError(f"encode not supported for type {m.type}")
    out = head + body
    assert len(out) == MSG_LEN[t], (m.type, len(out))
    return out


def frame(raw: bytes) -> bytes:
    """Prefix a message with its 2-byte big-endian length (BinaryFILE framing)."""
    return struct.pack(">H", len(raw)) + raw


# ---------------------------------------------------------------- file I/O

def open_any(path: str) -> BinaryIO:
    return gzip.open(path, "rb") if str(path).endswith(".gz") else open(path, "rb")


def iter_raw(f: BinaryIO) -> Iterator[bytes]:
    """Yield raw message bodies from a length-prefixed stream."""
    while True:
        hdr = f.read(2)
        if len(hdr) < 2:
            return
        (n,) = struct.unpack(">H", hdr)
        body = f.read(n)
        if len(body) < n:
            raise EOFError("truncated message at end of file")
        yield body


def iter_messages(path: str, limit: Optional[int] = None) -> Iterator[Msg]:
    """Yield decoded messages the model tracks; skip the rest."""
    with open_any(path) as f:
        for i, raw in enumerate(iter_raw(f)):
            if limit is not None and i >= limit:
                return
            m = decode(raw)
            if m is not None:
                yield m


def price_str(p: int) -> str:
    """4-implied-decimal integer price to a readable string."""
    return f"{p // 10000}.{p % 10000:04d}"
