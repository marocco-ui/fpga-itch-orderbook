"""Export golden vectors for the RTL testbenches.

Reads a length-prefixed ITCH stream and writes three files:

  <out>/stream.hex   Input bytes, one per line, length prefixes included.
                     Load with $readmemh or feed it from cocotb.

  <out>/parser.hex   What the parser must emit: one line per book message
                     (A F E C X D U), fields in fixed-width hex:
                       type(2) locate(4) ref(16) new_ref(16) side(1) shares(8) price(8)
                     side is 1 for buy, 0 for sell or not applicable.

  <out>/book.csv     Top of book after every message that changes the
                     book for --locate:
                       idx,type,bid_px,bid_qty,ask_px,ask_qty

Usage:
    python golden.py ../data/synth.bin ../tb/vectors --locate 1
"""

from __future__ import annotations

import argparse
import os

from book import Book
from itch import BOOK_TYPES, decode, open_any, iter_raw


def parser_line(m) -> str:
    side = 1 if m.side == "B" else 0
    return (f"{ord(m.type):02x} {m.locate:04x} {m.ref:016x} {m.new_ref:016x} "
            f"{side:x} {m.shares:08x} {m.price:08x}")


def export(src: str, out_dir: str, locate: int) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    book = Book()
    counts = {"messages": 0, "book_msgs": 0, "book_rows": 0, "bytes": 0}

    with open_any(src) as fi, \
            open(os.path.join(out_dir, "stream.hex"), "w") as fs, \
            open(os.path.join(out_dir, "parser.hex"), "w") as fp, \
            open(os.path.join(out_dir, "book.csv"), "w") as fb:
        fb.write("idx,type,bid_px,bid_qty,ask_px,ask_qty\n")
        for idx, raw in enumerate(iter_raw(fi)):
            counts["messages"] += 1
            framed = len(raw).to_bytes(2, "big") + raw
            fs.write("".join(f"{b:02x}\n" for b in framed))
            counts["bytes"] += len(framed)

            if raw[0] not in BOOK_TYPES:
                continue
            m = decode(raw)
            fp.write(parser_line(m) + "\n")
            counts["book_msgs"] += 1

            touched = book.apply(m)
            if touched == locate:
                t = book.top(locate)
                fb.write(f"{idx},{m.type},{t.bid_px},{t.bid_qty},{t.ask_px},{t.ask_qty}\n")
                counts["book_rows"] += 1

    book.check()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out_dir")
    ap.add_argument("--locate", type=int, default=1, help="stock locate code to track in book.csv")
    a = ap.parse_args()
    c = export(a.src, a.out_dir, a.locate)
    print(f"{c['messages']} messages, {c['bytes']} bytes, {c['book_msgs']} book messages, "
          f"{c['book_rows']} top-of-book rows for locate {a.locate}")


if __name__ == "__main__":
    main()
