"""Expected results for the C and hardware implementations.

Replays a stream through the golden Book and returns what the firmware
should report for one stock locate:

  top      best bid/ask after the last message
  check    FNV-1a hash over every top-of-book update, in order
  updates  number of messages that changed that stock's book

The hash folds the four top-of-book fields (bid_px, bid_qty, ask_px,
ask_qty) into the running value as big-endian 32-bit words after each
update. One number then confirms the whole run matched, not just the end.
"""

from __future__ import annotations

from dataclasses import dataclass

from book import Book, Top
from itch import BOOK_TYPES, decode, iter_raw, open_any

FNV_INIT = 2166136261
FNV_PRIME = 16777619


def fnv_update(h: int, t: Top) -> int:
    for v in (t.bid_px, t.bid_qty, t.ask_px, t.ask_qty):
        for b in v.to_bytes(4, "big"):
            h ^= b
            h = (h * FNV_PRIME) & 0xFFFFFFFF
    return h


@dataclass
class Expected:
    top: Top
    check: int
    updates: int
    msgs: int


def expected(src: str, locate: int) -> Expected:
    book = Book()
    h, updates, msgs = FNV_INIT, 0, 0
    with open_any(src) as f:
        for raw in iter_raw(f):
            msgs += 1
            if raw[0] not in BOOK_TYPES:
                continue
            if book.apply(decode(raw)) == locate:
                h = fnv_update(h, book.top(locate))
                updates += 1
    return Expected(book.top(locate), h, updates, msgs)


if __name__ == "__main__":
    import sys
    e = expected(sys.argv[1], int(sys.argv[2]))
    t = e.top
    print(f"MSGS {e.msgs}")
    print(f"TOP {t.bid_px} {t.bid_qty} {t.ask_px} {t.ask_qty}")
    print(f"CHECK {e.check:08x} {e.updates}")
