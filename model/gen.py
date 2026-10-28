"""Generate a synthetic, valid ITCH 5.0 stream for testing.

Real Nasdaq files are huge. For RTL testbenches you want short streams
you can reason about, with every message type the book handles. This
script builds one with a fixed seed so runs are repeatable.

The stream is always legal: executions, cancels, deletes and replaces
only target orders that are resting, bids stay below asks, and
timestamps only go forward.

Usage:
    python gen.py --out ../data/synth.bin --count 2000 --seed 1
"""

from __future__ import annotations

import argparse
import random
from typing import Dict, List

from book import Book
from itch import Msg, encode, frame

TICK = 100  # $0.01 with 4 implied decimals


def generate(count: int, seed: int = 1, stocks: List[str] | None = None) -> List[Msg]:
    rng = random.Random(seed)
    stocks = stocks or ["AAPL", "MSFT"]
    msgs: List[Msg] = []
    ts = 34_200_000_000_000  # 9:30:00 in ns since midnight
    tracking = 0

    def step() -> int:
        nonlocal ts, tracking
        ts += rng.randint(100, 50_000)
        tracking = (tracking + 1) & 0xFFFF
        return ts

    msgs.append(Msg(type="S", timestamp=step(), tracking=tracking, event_code="O"))
    mids: Dict[int, int] = {}
    for i, s in enumerate(stocks, start=1):
        msgs.append(Msg(type="R", locate=i, timestamp=step(), tracking=tracking,
                        stock=s, extra={"round_lot": 100}))
        mids[i] = rng.randint(50, 500) * 10_000  # $50 to $500

    book = Book()
    next_ref = 1
    next_match = 1

    while len(msgs) < count:
        loc = rng.randint(1, len(stocks))
        live = [r for r, o in book.orders.items() if o.locate == loc]
        roll = rng.random()

        if not live or roll < 0.40:
            side = rng.choice("BS")
            off = rng.randint(1, 20) * TICK
            price = mids[loc] - off if side == "B" else mids[loc] + off
            m = Msg(type=rng.choice("AAAF"), locate=loc, ref=next_ref, side=side,
                    shares=rng.randint(1, 10) * 100, stock=stocks[loc - 1],
                    price=price, mpid="ABCD")
            next_ref += 1
        else:
            ref = rng.choice(live)
            o = book.orders[ref]
            kind = rng.choice("ECXDU")
            if kind in "EC":
                m = Msg(type=kind, locate=loc, ref=ref, shares=rng.randint(1, o.shares),
                        match=next_match, printable="Y", price=o.price)
                next_match += 1
            elif kind == "X":
                m = Msg(type="X", locate=loc, ref=ref, shares=rng.randint(1, o.shares))
            elif kind == "D":
                m = Msg(type="D", locate=loc, ref=ref)
            else:
                off = rng.randint(1, 20) * TICK
                price = mids[loc] - off if o.side == "B" else mids[loc] + off
                m = Msg(type="U", locate=loc, ref=ref, new_ref=next_ref,
                        shares=rng.randint(1, 10) * 100, price=price)
                next_ref += 1

        m.timestamp = step()
        m.tracking = tracking
        book.apply(m)
        msgs.append(m)

    book.check()
    return msgs


def write(msgs: List[Msg], path: str) -> None:
    with open(path, "wb") as f:
        for m in msgs:
            f.write(frame(encode(m)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--count", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--stocks", default="AAPL,MSFT")
    a = ap.parse_args()
    msgs = generate(a.count, a.seed, a.stocks.split(","))
    write(msgs, a.out)
    print(f"wrote {len(msgs)} messages to {a.out}")


if __name__ == "__main__":
    main()
