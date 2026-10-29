/*
 * Order book for one stock, sized for a microcontroller.
 *
 * Orders live in an open-addressing hash table keyed by order reference.
 * Price levels live in two small sorted arrays (bids high to low, asks
 * low to high), so the best price is always index 0.
 *
 * Only orders for the tracked stock locate are stored. Messages that
 * reference any other order are ignored, which matches the Python
 * golden model's top-of-book output for that locate.
 */
#ifndef BOOK_H
#define BOOK_H

#include <stdint.h>
#include "itch.h"

#ifndef BOOK_ORDER_BITS
#define BOOK_ORDER_BITS 13               /* 8192 resting orders */
#endif
#define BOOK_ORDER_CAP (1u << BOOK_ORDER_BITS)

#ifndef BOOK_LEVEL_CAP
#define BOOK_LEVEL_CAP 512               /* price levels per side */
#endif

typedef struct {
    uint64_t ref;
    uint32_t price;
    uint32_t shares;
    uint8_t  side;    /* 'B' or 'S' */
    uint8_t  used;
} book_order_t;

typedef struct {
    uint32_t price;
    uint32_t qty;
} book_level_t;

typedef struct {
    uint16_t locate;
    uint32_t n_orders;
    uint16_t n_bids, n_asks;
    book_level_t bids[BOOK_LEVEL_CAP];
    book_level_t asks[BOOK_LEVEL_CAP];
    book_order_t orders[BOOK_ORDER_CAP];
} book_t;

typedef struct {
    uint32_t bid_px, bid_qty, ask_px, ask_qty;  /* 0 when a side is empty */
} book_top_t;

/* Results of book_apply */
#define BOOK_CHANGED      1
#define BOOK_IGNORED      0
#define BOOK_ERR_OVERFILL (-2)  /* reduce by more shares than resting */
#define BOOK_ERR_FULL     (-3)  /* order table full */
#define BOOK_ERR_LEVELS   (-4)  /* level array full */
#define BOOK_ERR_DUP      (-5)  /* duplicate order reference */

void book_init(book_t *b, uint16_t locate);
int  book_apply(book_t *b, const itch_msg_t *m);
book_top_t book_top(const book_t *b);

/* FNV-1a over the four top-of-book fields, big-endian. The Python side
 * computes the same value, so one number checks the whole run. */
uint32_t book_check_update(uint32_t h, book_top_t t);
#define BOOK_CHECK_INIT 2166136261u

#endif
