# ESP32-C3 baseline

The same ITCH parser and order book as the FPGA design, written in C and run on an ESP32-C3 (single-core 32-bit RISC-V at 160 MHz). This is the software baseline the hardware gets compared against.

## How it works

1. `tools/stream.py` on the PC sends length-prefixed ITCH messages over the USB serial port.
2. The board decodes each message and updates its order book.
3. Decode plus book update is timed with the CPU cycle counter. At 160 MHz, 1 cycle = 6.25 ns. Serial transport time is not counted.
4. When the stream ends, the board reports per-message-type latency (min, p50, p99, max, average), its final top of book and a checksum over every book update.
5. The script checks the top of book and checksum against the Python golden model.

## Files

| File | What |
|---|---|
| `src/itch.c` | Decoder for A F E C X D U, skips everything else by spec length |
| `src/book.c` | Order book: hash table of resting orders, sorted price-level arrays |
| `src/main.c` | Serial framing, cycle timing, histograms, report |
| `host/host_run.c` | Runs `itch.c` and `book.c` on a PC for the test suite |

`itch.c` and `book.c` have no ESP-IDF dependencies. `tests/test_c_model.py` compiles them on the PC and checks them against the golden model.

## Build and flash

Open this `esp32/` folder as a PlatformIO project (board ESP32-C3-DevKitM-1, framework ESP-IDF), build, and upload.

## Run

Close the PlatformIO serial monitor first, then from the repo root:

```bash
pip install pyserial
python model/gen.py --out data/synth.bin --count 20000 --seed 1
python tools/stream.py --port COM3 --file data/synth.bin --locate 1
```

On a Mac the port looks like `/dev/cu.usbserial-XXXX` or `/dev/cu.usbmodemXXXX`.

## Serial protocol

Every frame starts with a 2-byte big-endian length.

| Length | Meaning |
|---|---|
| 1 to 64 | ITCH message of that many bytes |
| `0xFFFF` + 2-byte locate | Start: reset the book and stats, track this stock locate |
| `0x0000` | End: print the report |

## Limits

- 4096 resting orders and 512 price levels per side (set in `src/CMakeLists.txt` and `src/book.h`). A full table shows up as `ERR` in the report.
- Only the tracked stock's orders are stored. Messages for other stocks are parsed and timed but don't change the book.
