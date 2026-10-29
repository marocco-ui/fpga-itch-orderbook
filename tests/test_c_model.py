"""Check the ESP32 C parser and order book against the Python golden model.

Builds esp32/src with the PC's C compiler and runs it on generated
streams. Skipped if no compiler is installed.
"""

import os
import shutil
import subprocess

import pytest

from check import expected
from gen import generate, write

ROOT = os.path.join(os.path.dirname(__file__), "..")
SRC = os.path.join(ROOT, "esp32", "src")
HOST = os.path.join(ROOT, "esp32", "host", "host_run.c")

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
pytestmark = pytest.mark.skipif(CC is None, reason="no C compiler")


@pytest.fixture(scope="module")
def host_bin(tmp_path_factory):
    out = tmp_path_factory.mktemp("bin") / "host_run"
    # Small tables so the tests also exercise hash collisions and wraparound.
    cmd = [CC, "-O2", "-Wall", "-Wextra", "-Werror", "-DBOOK_ORDER_BITS=9",
           "-I", SRC, os.path.join(SRC, "itch.c"), os.path.join(SRC, "book.c"),
           HOST, "-o", str(out)]
    subprocess.run(cmd, check=True)
    return str(out)


def run(host_bin, path, locate):
    p = subprocess.run([host_bin, path, str(locate)], capture_output=True, text=True)
    lines = dict(l.split(" ", 1) for l in p.stdout.strip().splitlines())
    return p.returncode, lines


@pytest.mark.parametrize("seed,count,stocks", [
    (1, 2000, "AAPL,MSFT"),
    (7, 20000, "AAPL"),
    (42, 50000, "AAPL,MSFT,NVDA"),
])
def test_matches_golden(tmp_path, host_bin, seed, count, stocks):
    path = str(tmp_path / "s.bin")
    write(generate(count, seed, stocks.split(",")), path)

    for locate in range(1, len(stocks.split(",")) + 1):
        rc, got = run(host_bin, path, locate)
        e = expected(path, locate)
        assert rc == 0, got
        assert got["ERR"] == "0"
        assert got["MSGS"] == str(e.msgs)
        t = e.top
        assert got["TOP"] == f"{t.bid_px} {t.bid_qty} {t.ask_px} {t.ask_qty}"
        assert got["CHECK"] == f"{e.check:08x} {e.updates}"
