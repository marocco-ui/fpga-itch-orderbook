"""Cut a full Nasdaq ITCH day file down to something a testbench can use.

Full-day files are several GB, so this streams the input and stops
early. Optionally keeps only one stock (plus the System Event messages).

Usage:
    python trim.py ../data/01302019.NASDAQ_ITCH50.gz ../data/aapl_1m.bin \
        --stock AAPL --max-in 20000000 --max-out 1000000
"""

from __future__ import annotations

import argparse

from itch import decode, frame, iter_raw, open_any


def trim(src: str, dst: str, stock: str | None, max_in: int, max_out: int) -> tuple[int, int | None]:
    locate = None
    kept = 0
    with open_any(src) as fi, open(dst, "wb") as fo:
        for i, raw in enumerate(iter_raw(fi)):
            if i >= max_in or kept >= max_out:
                break
            t = raw[0:1]
            if stock is None:
                fo.write(frame(raw))
                kept += 1
                continue
            if t == b"S":
                fo.write(frame(raw))
                kept += 1
            elif t == b"R":
                m = decode(raw)
                if m.stock == stock:
                    locate = m.locate
                    fo.write(frame(raw))
                    kept += 1
            elif locate is not None and int.from_bytes(raw[1:3], "big") == locate:
                fo.write(frame(raw))
                kept += 1
    if stock and locate is None:
        raise SystemExit(f"stock {stock} not found in the first {max_in} messages")
    return kept, locate


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--stock", help="keep only this symbol, e.g. AAPL")
    ap.add_argument("--max-in", type=int, default=50_000_000, help="stop after reading this many messages")
    ap.add_argument("--max-out", type=int, default=1_000_000, help="stop after writing this many messages")
    a = ap.parse_args()
    n, loc = trim(a.src, a.dst, a.stock, a.max_in, a.max_out)
    print(f"wrote {n} messages to {a.dst}" + (f" (stock locate {loc})" if loc else ""))


if __name__ == "__main__":
    main()
