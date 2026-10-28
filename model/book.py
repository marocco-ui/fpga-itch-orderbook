"""Reference limit order book built from ITCH messages.

This is the golden model the RTL gets checked against, so it favors
being obviously correct over being fast.

Rules (TotalView-ITCH 5.0):
  A/F  add a resting order
  E    execution: reduce the order by executed shares
  C    execution at a different price: same effect on the book as E
  X    partial cancel: reduce the order by cancelled shares
  D    delete: remove the whole order
  U    replace: remove the original order, add the new reference
       with the new price and shares on the same side
An order that reaches zero shares leaves the book.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from itch import Msg


@dataclass
class Order:
    locate: int
    side: str   # 'B' or 'S'
    price: int
    shares: int


@dataclass(frozen=True)
class Top:
    """Best bid and best ask after an update. 0 means the side is empty."""
    bid_px: int
    bid_qty: int
    ask_px: int
    ask_qty: int


class Book:
    """Order book for every stock locate in the feed."""

    def __init__(self) -> None:
        self.orders: Dict[int, Order] = {}
        # levels[locate][side][price] = total shares at that price
        self.levels: Dict[int, Dict[str, Dict[int, int]]] = {}

    # ------------------------------------------------------------ internals

    def _lv(self, locate: int, side: str) -> Dict[int, int]:
        return self.levels.setdefault(locate, {"B": {}, "S": {}})[side]

    def _add(self, ref: int, locate: int, side: str, price: int, shares: int) -> None:
        if ref in self.orders:
            raise KeyError(f"duplicate order ref {ref}")
        if side not in ("B", "S"):
            raise ValueError(f"bad side {side!r}")
        self.orders[ref] = Order(locate, side, price, shares)
        lv = self._lv(locate, side)
        lv[price] = lv.get(price, 0) + shares

    def _reduce(self, ref: int, shares: int) -> Order:
        o = self.orders[ref]
        if shares > o.shares:
            raise ValueError(f"ref {ref}: reduce {shares} > resting {o.shares}")
        lv = self._lv(o.locate, o.side)
        lv[o.price] -= shares
        if lv[o.price] == 0:
            del lv[o.price]
        o.shares -= shares
        if o.shares == 0:
            del self.orders[ref]
        return o

    def _remove(self, ref: int) -> Order:
        o = self.orders[ref]
        return self._reduce(ref, o.shares)

    # ------------------------------------------------------------ public

    def apply(self, m: Msg) -> Optional[int]:
        """Apply one message. Returns the stock locate it touched, or None
        for messages that do not change the book."""
        t = m.type
        if t in ("A", "F"):
            self._add(m.ref, m.locate, m.side, m.price, m.shares)
            return m.locate
        if t in ("E", "C", "X"):
            return self._reduce(m.ref, m.shares).locate
        if t == "D":
            return self._remove(m.ref).locate
        if t == "U":
            old = self._remove(m.ref)
            self._add(m.new_ref, old.locate, old.side, m.price, m.shares)
            return old.locate
        return None

    def top(self, locate: int) -> Top:
        bids = self._lv(locate, "B")
        asks = self._lv(locate, "S")
        bp = max(bids) if bids else 0
        ap = min(asks) if asks else 0
        return Top(bp, bids.get(bp, 0), ap, asks.get(ap, 0))

    def depth(self, locate: int, side: str, n: int = 5) -> list[Tuple[int, int]]:
        lv = self._lv(locate, side)
        prices = sorted(lv, reverse=(side == "B"))[:n]
        return [(p, lv[p]) for p in prices]

    def check(self) -> None:
        """Assert every level equals the sum of its resting orders."""
        sums: Dict[Tuple[int, str, int], int] = {}
        for o in self.orders.values():
            assert o.shares > 0
            k = (o.locate, o.side, o.price)
            sums[k] = sums.get(k, 0) + o.shares
        for loc, sides in self.levels.items():
            for side, lv in sides.items():
                for px, q in lv.items():
                    assert q > 0, (loc, side, px, q)
                    assert sums.pop((loc, side, px)) == q
        assert not sums, f"orders with no level: {sums}"
