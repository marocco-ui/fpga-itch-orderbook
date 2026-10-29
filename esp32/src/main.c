/*
 * ITCH 5.0 parser + order book on an ESP32-C3, timed in CPU cycles.
 *
 * The PC (tools/stream.py) sends length-prefixed ITCH messages over the
 * USB serial port. For each book message the firmware times decode +
 * book update with the CPU cycle counter (160 MHz, 6.25 ns per cycle)
 * and keeps a per-type histogram. Transport time is not included.
 *
 * Control frames (2-byte big-endian length field):
 *   0xFFFF + locate(2)  START: reset book and stats, track this locate
 *   0x0000              END:   print the report, then wait for START
 *
 * Works whether the board's USB-C goes through a USB-UART bridge (UART0)
 * or the C3's built-in USB Serial/JTAG: it listens on both.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "driver/uart.h"
#include "driver/usb_serial_jtag.h"
#include "esp_cpu.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "book.h"
#include "itch.h"

#define RX_BUF      4096
#define MAX_MSG     64
#define HIST_BIN    8          /* cycles per histogram bin */
#define HIST_BINS   256        /* covers 0..2047 cycles; slower goes in max */
#define N_TYPES     7

static const char TYPES[N_TYPES] = { 'A', 'F', 'E', 'C', 'X', 'D', 'U' };

typedef struct {
    uint32_t count, min, max, over;
    uint64_t sum;
    uint32_t hist[HIST_BINS];
} stat_t;

static book_t   book;
static stat_t   stats[N_TYPES];
static uint32_t n_msgs, n_other, n_errors, peak_orders, check, n_updates;
static uint32_t timer_overhead;

/* ------------------------------------------------------------ stats */

static int type_index(char t) {
    for (int i = 0; i < N_TYPES; i++)
        if (TYPES[i] == t)
            return i;
    return -1;
}

static void stat_add(stat_t *s, uint32_t cyc) {
    if (s->count == 0 || cyc < s->min) s->min = cyc;
    if (cyc > s->max) s->max = cyc;
    s->count++;
    s->sum += cyc;
    uint32_t bin = cyc / HIST_BIN;
    if (bin < HIST_BINS) s->hist[bin]++;
    else s->over++;
}

/* Upper edge of the bin holding the given percentile (0-100). */
static uint32_t stat_pct(const stat_t *s, uint32_t pct) {
    uint64_t target = ((uint64_t)s->count * pct + 99) / 100;
    uint64_t seen = 0;
    for (uint32_t b = 0; b < HIST_BINS; b++) {
        seen += s->hist[b];
        if (seen >= target && target > 0)
            return (b + 1) * HIST_BIN;
    }
    return s->max;
}

static uint32_t measure_overhead(void) {
    uint32_t best = UINT32_MAX;
    for (int i = 0; i < 1000; i++) {
        uint32_t t0 = esp_cpu_get_cycle_count();
        uint32_t t1 = esp_cpu_get_cycle_count();
        if (t1 - t0 < best) best = t1 - t0;
    }
    return best;
}

static void reset_run(uint16_t locate) {
    book_init(&book, locate);
    memset(stats, 0, sizeof(stats));
    n_msgs = n_other = n_errors = peak_orders = n_updates = 0;
    check = BOOK_CHECK_INIT;
    printf("READY locate=%u order_cap=%u\n", locate, (unsigned)BOOK_ORDER_CAP);
    fflush(stdout);
}

static void report(void) {
    book_top_t t = book_top(&book);
    printf("BEGIN\n");
    printf("CPU_HZ 160000000\n");
    printf("OVERHEAD %" PRIu32 "\n", timer_overhead);
    printf("MSGS %" PRIu32 "\n", n_msgs);
    printf("OTHER %" PRIu32 "\n", n_other);
    for (int i = 0; i < N_TYPES; i++) {
        const stat_t *s = &stats[i];
        if (!s->count) continue;
        printf("STAT %c %" PRIu32 " min %" PRIu32 " p50 %" PRIu32 " p99 %" PRIu32
               " max %" PRIu32 " sum %" PRIu64 "\n",
               TYPES[i], s->count, s->min, stat_pct(s, 50), stat_pct(s, 99),
               s->max, s->sum);
    }
    printf("TOP %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 "\n",
           t.bid_px, t.bid_qty, t.ask_px, t.ask_qty);
    printf("CHECK %08" PRIx32 " %" PRIu32 "\n", check, n_updates);
    printf("ORDERS %" PRIu32 " peak %" PRIu32 "\n", book.n_orders, peak_orders);
    printf("ERR %" PRIu32 "\n", n_errors);
    printf("DONE\n");
    fflush(stdout);
}

/* ------------------------------------------------------------ messages */

static void handle_message(const uint8_t *buf, uint16_t len) {
    itch_msg_t m;
    n_msgs++;

    uint32_t t0 = esp_cpu_get_cycle_count();
    int r = itch_decode(buf, len, &m);
    int a = (r == 1) ? book_apply(&book, &m) : BOOK_IGNORED;
    uint32_t t1 = esp_cpu_get_cycle_count();

    if (r < 0) { n_errors++; return; }
    if (r == 0) { n_other++; return; }

    uint32_t cyc = t1 - t0;
    cyc = (cyc > timer_overhead) ? cyc - timer_overhead : 0;
    int ti = type_index(m.type);
    if (ti >= 0) stat_add(&stats[ti], cyc);

    if (a == BOOK_CHANGED) {
        check = book_check_update(check, book_top(&book));
        n_updates++;
        if (book.n_orders > peak_orders) peak_orders = book.n_orders;
    } else if (a < 0) {
        n_errors++;
    }
}

/* Byte-stream framer: [len_hi len_lo][len bytes] ... */
enum { ST_HDR, ST_BODY, ST_CFG, ST_SKIP };
static int      st = ST_HDR;
static uint8_t  hdr[2], body[MAX_MSG];
static uint16_t need, got;

static void feed(const uint8_t *p, int n) {
    for (int i = 0; i < n; i++) {
        uint8_t b = p[i];
        switch (st) {
        case ST_HDR:
            hdr[got++] = b;
            if (got < 2) break;
            got = 0;
            need = (uint16_t)((hdr[0] << 8) | hdr[1]);
            if (need == 0x0000)      { report(); }
            else if (need == 0xFFFF) { st = ST_CFG; need = 2; }
            else if (need > MAX_MSG) { st = ST_SKIP; n_errors++; }
            else                     { st = ST_BODY; }
            break;
        case ST_BODY:
            body[got++] = b;
            if (got == need) { handle_message(body, need); got = 0; st = ST_HDR; }
            break;
        case ST_CFG:
            body[got++] = b;
            if (got == 2) { reset_run((uint16_t)((body[0] << 8) | body[1])); got = 0; st = ST_HDR; }
            break;
        case ST_SKIP:
            if (--need == 0) st = ST_HDR;
            break;
        }
    }
}

/* ------------------------------------------------------------ main */

void app_main(void)
{
    /* UART0: boards with a USB-UART bridge chip. Pins and baud are
     * already set up by the console; just add an RX buffer. */
    uart_driver_install(UART_NUM_0, RX_BUF, 0, 0, NULL, 0);

    /* Built-in USB Serial/JTAG: boards wired straight to the C3's USB. */
    usb_serial_jtag_driver_config_t ucfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    ucfg.rx_buffer_size = RX_BUF;
    usb_serial_jtag_driver_install(&ucfg);

    timer_overhead = measure_overhead();
    reset_run(1);

    static uint8_t rx[512];
    for (;;) {
        int n = uart_read_bytes(UART_NUM_0, rx, sizeof(rx), 1);
        if (n > 0) feed(rx, n);
        n = usb_serial_jtag_read_bytes(rx, sizeof(rx), 0);
        if (n > 0) feed(rx, n);
    }
}
