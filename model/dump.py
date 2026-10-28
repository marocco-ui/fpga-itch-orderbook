"""Print decoded messages and the book, for eyeballing a stream.

Usage:
    python dump.py ../data/synth.bin --limit 30 --locate 1
"""

from __future__ import annotations

import argparse

from book import Book
from itch import iter_messages, price_str


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--locate", type=int, default=1)
    a = ap.parse_args()

    book = Book()
    for m in iter_messages(a.src, limit=a.limit):
        book.apply(m)
        if m.type in "AF":
            info = f"ref={m.ref} {m.side} {m.shares}@{price_str(m.price)} {m.stock}"
        elif m.type in "EC":
            info = f"ref={m.ref} exec {m.shares}"
        elif m.type == "X":
            info = f"ref={m.ref} cancel {m.shares}"
        elif m.type == "D":
            info = f"ref={m.ref} delete"
        elif m.type == "U":
            info = f"ref={m.ref} -> {m.new_ref} {m.shares}@{price_str(m.price)}"
        elif m.type == "R":
            info = f"directory {m.stock}"
        else:
            info = f"event {m.event_code}"
        print(f"{m.timestamp:>15} {m.type} loc={m.locate:<3} {info}")

    print(f"\nbook for locate {a.locate}:")
    asks = book.depth(a.locate, "S")
    bids = book.depth(a.locate, "B")
    for px, q in reversed(asks):
        print(f"   ask {price_str(px):>10}  {q}")
    print("   ----")
    for px, q in bids:
        print(f"   bid {price_str(px):>10}  {q}")


if __name__ == "__main__":
    main()
