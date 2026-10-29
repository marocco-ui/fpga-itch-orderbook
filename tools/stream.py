"""Stream an ITCH file to the ESP32-C3 and report per-message latency.

The board decodes each message and updates its order book, timing that
work with its CPU cycle counter. When the stream ends it reports the
timings plus its final top of book and a checksum, and this script
compares those against the Python golden model.

Usage (from the repo root):
    pip install pyserial
    python model/gen.py --out data/synth.bin --count 20000 --seed 1
    python tools/stream.py --port COM3 --file data/synth.bin --locate 1

On a Mac the port looks like /dev/cu.usbserial-XXXX or /dev/cu.usbmodemXXXX.
Close the PlatformIO serial monitor first; only one program can hold the port.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "model"))
from check import expected  # noqa: E402

try:
    import serial
except ImportError:
    sys.exit("pyserial is missing: pip install pyserial")

NAMES = {
    "A": "Add Order", "F": "Add Order (MPID)", "E": "Order Executed",
    "C": "Executed w/ Price", "X": "Order Cancel", "D": "Order Delete",
    "U": "Order Replace",
}


def open_port(port: str, baud: int) -> serial.Serial:
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 0.5
    # Keep DTR/RTS low so opening the port doesn't reset the board
    # or drop it into the bootloader.
    s.dtr = False
    s.rts = False
    s.open()
    return s


def wait_for(s: serial.Serial, prefix: str, timeout: float) -> str:
    end = time.time() + timeout
    while time.time() < end:
        line = s.readline().decode(errors="replace").strip()
        if line.startswith(prefix):
            return line
    raise TimeoutError(f"no '{prefix}' from the board within {timeout:.0f} s")


def start(s: serial.Serial, locate: int, tries: int = 8) -> str:
    """Send the START frame until the board answers READY.

    Some boards reset when the port opens, and a START sent while the
    board is still booting gets lost, so keep asking for a few seconds.
    Anything else the board prints is shown, which helps when it doesn't
    answer at all.
    """
    frame = struct.pack(">HH", 0xFFFF, locate)
    for _ in range(tries):
        s.write(frame)
        end = time.time() + 1.0
        while time.time() < end:
            line = s.readline().decode(errors="replace").strip()
            if line.startswith("READY") and f"locate={locate}" in line:
                return line
            if line:
                print(f"  board: {line}")
    raise TimeoutError(
        "the board never answered READY. Check that the ESP32 firmware is uploaded "
        "(serial monitor + RESET should print 'READY locate=1'), that the PlatformIO "
        "monitor is closed, and that the port is right.")


def read_report(s: serial.Serial, timeout: float) -> dict:
    wait_for(s, "BEGIN", timeout)
    rep = {"STAT": {}}
    end = time.time() + timeout
    while True:
        if time.time() > end:
            raise TimeoutError("report from the board was cut off")
        line = s.readline().decode(errors="replace").strip()
        if not line:
            continue
        if line == "DONE":
            return rep
        key, _, rest = line.partition(" ")
        if key == "STAT":
            f = rest.split()
            rep["STAT"][f[0]] = {
                "count": int(f[1]), "min": int(f[3]), "p50": int(f[5]),
                "p99": int(f[7]), "max": int(f[9]), "sum": int(f[11]),
            }
        else:
            rep[key] = rest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="COM3 on Windows, /dev/cu.* on Mac")
    ap.add_argument("--file", required=True, help="length-prefixed ITCH file")
    ap.add_argument("--locate", type=int, default=1, help="stock locate to track")
    ap.add_argument("--baud", type=int, default=115200)
    a = ap.parse_args()

    data = open(a.file, "rb").read()
    print(f"{a.file}: {len(data):,} bytes")

    s = open_port(a.port, a.baud)
    print(start(s, a.locate))

    t0 = time.time()
    chunk = 1024
    for i in range(0, len(data), chunk):
        s.write(data[i:i + chunk])
        done = min(i + chunk, len(data))
        print(f"\rsending {100 * done // len(data):3d}%", end="", flush=True)
    s.write(b"\x00\x00")  # END frame
    s.flush()
    print(f"\rsent in {time.time() - t0:.1f} s (transport time, not part of the timing)")

    rep = read_report(s, timeout=30)
    s.close()

    hz = int(rep["CPU_HZ"])
    ns = 1e9 / hz
    print(f"\nDecode + book update on the ESP32-C3 ({hz / 1e6:.0f} MHz, {ns:.2f} ns per cycle)")
    print(f"{'type':<22}{'count':>8}{'min':>9}{'p50':>9}{'p99':>9}{'max':>10}{'avg':>9}   (ns)")
    total_n, total_sum = 0, 0
    for t, st in rep["STAT"].items():
        avg = st["sum"] / st["count"]
        total_n += st["count"]
        total_sum += st["sum"]
        print(f"{t + ' ' + NAMES.get(t, ''):<22}{st['count']:>8,}"
              f"{st['min'] * ns:>9.0f}{st['p50'] * ns:>9.0f}{st['p99'] * ns:>9.0f}"
              f"{st['max'] * ns:>10.0f}{avg * ns:>9.0f}")
    if total_n:
        avg_ns = total_sum / total_n * ns
        print(f"{'all book messages':<22}{total_n:>8,}{'':>45}{avg_ns:>9.0f}")
        if avg_ns > 0:
            print(f"\nAverage {avg_ns:,.0f} ns per message, about {1e9 / avg_ns:,.0f} messages per second.")
    print("p50/p99 are rounded up to the next 8-cycle histogram bin (50 ns).")

    # Correctness check against the golden model
    e = expected(a.file, a.locate)
    t = e.top
    want_top = f"{t.bid_px} {t.bid_qty} {t.ask_px} {t.ask_qty}"
    want_chk = f"{e.check:08x} {e.updates}"
    ok = (rep.get("TOP") == want_top and rep.get("CHECK") == want_chk
          and rep.get("ERR") == "0" and rep.get("MSGS") == str(e.msgs))
    print(f"\nboard  TOP {rep.get('TOP')}  CHECK {rep.get('CHECK')}  ERR {rep.get('ERR')}")
    print(f"model  TOP {want_top}  CHECK {want_chk}")
    print(f"orders resting {rep.get('ORDERS')}")
    print("MATCH: the board's book agrees with the golden model on every update." if ok
          else "MISMATCH: compare the lines above.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
