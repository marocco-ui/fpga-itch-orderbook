import io
import struct

import pytest

from book import Book
from gen import generate, write
from golden import export
from itch import MSG_LEN, Msg, decode, encode, frame, iter_raw
from trim import trim


# ---------------------------------------------------------------- codec

SAMPLES = [
    Msg(type="S", timestamp=1, event_code="O"),
    Msg(type="R", locate=7, timestamp=2, stock="AAPL", extra={"round_lot": 100}),
    Msg(type="A", locate=7, tracking=3, timestamp=34_200_000_000_123, ref=42,
        side="B", shares=300, stock="AAPL", price=1_501_200),
    Msg(type="F", locate=7, timestamp=5, ref=43, side="S", shares=100,
        stock="AAPL", price=1_502_000, mpid="GSCO"),
    Msg(type="E", locate=7, timestamp=6, ref=42, shares=100, match=9),
    Msg(type="C", locate=7, timestamp=7, ref=42, shares=50, match=10,
        printable="N", price=1_501_100),
    Msg(type="X", locate=7, timestamp=8, ref=43, shares=40),
    Msg(type="D", locate=7, timestamp=9, ref=43),
    Msg(type="U", locate=7, timestamp=10, ref=42, new_ref=44, shares=500, price=1_500_900),
]


@pytest.mark.parametrize("m", SAMPLES, ids=lambda m: m.type)
def test_roundtrip(m):
    raw = encode(m)
    assert len(raw) == MSG_LEN[m.type.encode()]
    back = decode(raw)
    for f in ("type", "locate", "tracking", "timestamp", "ref", "new_ref",
              "side", "shares", "stock", "price", "match", "mpid", "event_code"):
        assert getattr(back, f) == getattr(m, f), f


def test_add_order_byte_layout():
    """Check field offsets against the spec by hand, not via our own decoder."""
    raw = encode(SAMPLES[2])
    assert raw[0:1] == b"A"
    assert struct.unpack(">H", raw[1:3])[0] == 7          # locate
    assert struct.unpack(">H", raw[3:5])[0] == 3          # tracking
    assert int.from_bytes(raw[5:11], "big") == 34_200_000_000_123
    assert struct.unpack(">Q", raw[11:19])[0] == 42       # order ref
    assert raw[19:20] == b"B"
    assert struct.unpack(">I", raw[20:24])[0] == 300
    assert raw[24:32] == b"AAPL    "
    assert struct.unpack(">I", raw[32:36])[0] == 1_501_200


def test_unknown_types_are_skipped():
    trade = b"P" + bytes(43)  # Trade (non-cross), 44 bytes
    assert decode(trade) is None


def test_framing():
    buf = io.BytesIO(b"".join(frame(encode(m)) for m in SAMPLES))
    assert [r[0:1] for r in iter_raw(buf)] == [m.type.encode() for m in SAMPLES]


# ---------------------------------------------------------------- book

def test_book_sequence():
    b = Book()
    for m in SAMPLES:
        b.apply(m)
        b.check()
    # After the sequence: ref 42 replaced by 44 at 150.09 for 500, ref 43 deleted.
    assert b.top(7).bid_px == 1_500_900 and b.top(7).bid_qty == 500
    assert b.top(7).ask_px == 0
    assert set(b.orders) == {44}


def test_levels_aggregate():
    b = Book()
    b.apply(Msg(type="A", locate=1, ref=1, side="S", shares=100, price=200))
    b.apply(Msg(type="A", locate=1, ref=2, side="S", shares=300, price=200))
    b.apply(Msg(type="A", locate=1, ref=3, side="S", shares=50, price=199))
    assert b.top(1).ask_px == 199
    b.apply(Msg(type="E", locate=1, ref=3, shares=50))
    assert (b.top(1).ask_px, b.top(1).ask_qty) == (200, 400)


def test_over_execution_rejected():
    b = Book()
    b.apply(Msg(type="A", locate=1, ref=1, side="B", shares=100, price=100))
    with pytest.raises(ValueError):
        b.apply(Msg(type="X", locate=1, ref=1, shares=101))


# ---------------------------------------------------------------- tools

def test_generator_is_legal_and_repeatable():
    a = generate(3000, seed=5)
    b = generate(3000, seed=5)
    assert [encode(m) for m in a] == [encode(m) for m in b]
    types = {m.type for m in a}
    assert set("SRAFECXDU") <= types


def test_golden_export_and_trim(tmp_path):
    src = tmp_path / "s.bin"
    write(generate(1500, seed=2), str(src))

    c = export(str(src), str(tmp_path / "v"), locate=1)
    lines = (tmp_path / "v" / "stream.hex").read_text().split()
    assert len(lines) == c["bytes"] == src.stat().st_size
    msgs = generate(1500, seed=2)
    book_msgs = [m for m in msgs if m.type in "AFECXDU"]
    parser_lines = (tmp_path / "v" / "parser.hex").read_text().splitlines()
    assert c["book_msgs"] == len(book_msgs) == len(parser_lines) > 0

    # Spot-check one parser line against the message it came from.
    m = book_msgs[0]
    f = parser_lines[0].split()
    assert int(f[0], 16) == ord(m.type) and int(f[2], 16) == m.ref and int(f[6], 16) == m.price

    # Last book.csv row must match an independent replay.
    rows = (tmp_path / "v" / "book.csv").read_text().splitlines()
    assert c["book_rows"] == len(rows) - 1 > 0
    b = Book()
    for mm in msgs:
        b.apply(mm)
    t = b.top(1)
    assert rows[-1].split(",")[2:] == [str(t.bid_px), str(t.bid_qty), str(t.ask_px), str(t.ask_qty)]

    out = tmp_path / "msft.bin"
    n, loc = trim(str(src), str(out), "MSFT", 10**9, 10**9)
    assert loc == 2
    with open(out, "rb") as f:
        raws = list(iter_raw(f))
    assert len(raws) == n
    locs = {int.from_bytes(r[1:3], "big") for r in raws if r[0:1] != b"S"}
    assert locs == {2}
