/*
 * Runs the ESP32 parser and order book on a PC, for testing.
 *
 * Reads a length-prefixed ITCH file and prints the same TOP and CHECK
 * lines the firmware prints, so tests/test_c_model.py can compare them
 * against the Python golden model.
 *
 * Build:  cc -O2 -I../src ../src/itch.c ../src/book.c host_run.c -o host_run
 * Run:    ./host_run ../../data/synth.bin 1
 */
#include <stdio.h>
#include <stdlib.h>

#include "book.h"
#include "itch.h"

static book_t book;

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <file.bin> <locate>\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 2;
    }
    book_init(&book, (uint16_t)atoi(argv[2]));

    uint8_t buf[64];
    uint8_t hdr[2];
    uint32_t check = BOOK_CHECK_INIT, updates = 0, msgs = 0, errors = 0;

    while (fread(hdr, 1, 2, f) == 2) {
        uint16_t len = (uint16_t)((hdr[0] << 8) | hdr[1]);
        if (len > sizeof(buf)) {
            fseek(f, len, SEEK_CUR);
            errors++;
            continue;
        }
        if (fread(buf, 1, len, f) != len)
            break;
        msgs++;

        itch_msg_t m;
        int r = itch_decode(buf, len, &m);
        if (r < 0) { errors++; continue; }
        if (r == 0) continue;

        int a = book_apply(&book, &m);
        if (a == BOOK_CHANGED) {
            check = book_check_update(check, book_top(&book));
            updates++;
        } else if (a < 0) {
            errors++;
        }
    }
    fclose(f);

    book_top_t t = book_top(&book);
    printf("MSGS %u\n", msgs);
    printf("TOP %u %u %u %u\n", t.bid_px, t.bid_qty, t.ask_px, t.ask_qty);
    printf("CHECK %08x %u\n", check, updates);
    printf("ORDERS %u\n", book.n_orders);
    printf("ERR %u\n", errors);
    return errors ? 1 : 0;
}
