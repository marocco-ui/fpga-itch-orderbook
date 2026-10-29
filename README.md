# itch-fpga

A market data parser and order book for Nasdaq TotalView-ITCH 5.0, built twice: in C on an ESP32-C3 microcontroller, and in SystemVerilog on a Xilinx Artix-7 FPGA (Digilent Basys 3). Same input, same golden model, measured latency on both.

Raw ITCH bytes go in. The parser decodes order messages and the book keeps the best bid and best ask for a stock. Every implementation is checked against a Python golden model.

## Status

| Stage | What | State |
|---|---|---|
| 1 | Python golden model and test vectors | Done |
| 1b | ESP32-C3 software baseline in C, timed in CPU cycles ([esp32/](esp32/)) | Built, matches golden model on PC; first board run next |
| 2 | Parser RTL (byte stream to decoded order events) | Next |
| 3 | Order book RTL (block RAM, best bid/ask) | Planned |
| 4 | Board bring-up: UART feed into the Basys 3 | Planned |
| 5 | Latency numbers and write-up | Planned |

## Layout

```
model/   Python golden model (codec, order book, generator, tools)
esp32/   C parser and order book on an ESP32-C3 (PlatformIO project)
tools/   PC-side scripts (stream.py feeds the ESP32 and checks its results)
rtl/     SystemVerilog
tb/      Testbenches; tb/vectors/ holds generated golden vectors
tests/   pytest suite for the model
data/    ITCH files (not committed)
docs/    Diagrams and waveform screenshots
```

## Setup

Windows with WSL (Ubuntu):

```bash
# In WSL
sudo apt install python3-pip iverilog gtkwave
pip install -r requirements.txt
python3 -m pytest -q tests
```

Vivado ML Standard (free) on Windows handles synthesis for the Basys 3. Install only the 7 Series devices.

## Using the model

```bash
cd model

# Synthetic stream: legal, repeatable, every book message type
python3 gen.py --out ../data/synth.bin --count 2000 --seed 1

# Look at it
python3 dump.py ../data/synth.bin --limit 30 --locate 1

# Export golden vectors for the RTL testbenches
python3 golden.py ../data/synth.bin ../tb/vectors --locate 1
```

Real data: Nasdaq posts sample day files at https://emi.nasdaq.com/ITCH/. Download one in a browser into `data/`, then cut it down:

```bash
python3 trim.py ../data/<date>.NASDAQ_ITCH50.gz ../data/aapl.bin --stock AAPL --max-out 1000000
python3 golden.py ../data/aapl.bin ../tb/vectors_aapl --locate <AAPL locate>
```

`trim.py` prints the stock's locate code, which `golden.py` needs.

## Formats

**Input stream.** Each message has a 2-byte big-endian length in front of it, the same framing as Nasdaq's sample files. The UART feed in stage 4 will send the same bytes.

**`tb/vectors/stream.hex`.** Input bytes, one per line, for `$readmemh`.

**`tb/vectors/parser.hex`.** Expected parser output, one line per book message:

```
type(2) locate(4) ref(16) new_ref(16) side(1) shares(8) price(8)
```

All hex. `side` is 1 for buy and 0 otherwise. Prices have 4 implied decimals (1501200 is $150.12).

**`tb/vectors/book.csv`.** Top of book after each message that changes the tracked stock.

## Messages handled

| Type | Message | Bytes | Book effect |
|---|---|---|---|
| A | Add Order | 36 | Add resting order |
| F | Add Order with MPID | 40 | Add resting order |
| E | Order Executed | 31 | Reduce shares |
| C | Order Executed With Price | 36 | Reduce shares |
| X | Order Cancel | 23 | Reduce shares |
| D | Order Delete | 19 | Remove order |
| U | Order Replace | 35 | Remove original, add new ref |

Every other type is skipped using its fixed length from the spec.

## References

- [Nasdaq TotalView-ITCH 5.0 specification](https://nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHspecification.pdf)
- [MoldUDP64 specification](http://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/moldudp64.pdf)
