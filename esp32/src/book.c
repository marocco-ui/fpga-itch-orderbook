#include "book.h"

#include <string.h>

#define MASK (BOOK_ORDER_CAP - 1u)

/* Fibonacci hashing: spreads sequential refs across the table. */
static inline uint32_t home_slot(uint64_t ref) {
    return (uint32_t)((ref * 0x9E3779B97F4A7C15ull) >> (64 - BOOK_ORDER_BITS));
}

void book_init(book_t *b, uint16_t locate) {
    memset(b, 0, sizeof(*b));
    b->locate = locate;
}

/* ------------------------------------------------------------ orders */

static int find_slot(const book_t *b, uint64_t ref) {
    uint32_t i = home_slot(ref);
    for (uint32_t n = 0; n < BOOK_ORDER_CAP; n++, i = (i + 1) & MASK) {
        if (!b->orders[i].used)
            return -1;
        if (b->orders[i].ref == ref)
            return (int)i;
    }
    return -1;
}

static int insert_order(book_t *b, uint64_t ref, uint8_t side,
                        uint32_t price, uint32_t shares) {
    if (b->n_orders >= BOOK_ORDER_CAP - 1)
        return BOOK_ERR_FULL;
    uint32_t i = home_slot(ref);
    while (b->orders[i].used) {
        if (b->orders[i].ref == ref)
            return BOOK_ERR_DUP;
        i = (i + 1) & MASK;
    }
    b->orders[i] = (book_order_t){ ref, price, shares, side, 1 };
    b->n_orders++;
    return 0;
}

/* Linear-probing delete with backward shift, so no tombstones pile up. */
static void delete_slot(book_t *b, uint32_t i) {
    uint32_t j = i;
    for (;;) {
        j = (j + 1) & MASK;
        if (!b->orders[j].used)
            break;
        uint32_t k = home_slot(b->orders[j].ref);
        /* Move j back into the hole at i if its home slot is not in (i, j]. */
        int move = (i <= j) ? (k <= i || k > j) : (k <= i && k > j);
        if (move) {
            b->orders[i] = b->orders[j];
            i = j;
        }
    }
    b->orders[i].used = 0;
    b->n_orders--;
}

/* ------------------------------------------------------------ levels */

static int level_add(book_t *b, uint8_t side, uint32_t price, uint32_t qty) {
    book_level_t *lv = (side == 'B') ? b->bids : b->asks;
    uint16_t *n = (side == 'B') ? &b->n_bids : &b->n_asks;
    uint16_t i = 0;
    if (side == 'B')
        while (i < *n && lv[i].price > price) i++;
    else
        while (i < *n && lv[i].price < price) i++;

    if (i < *n && lv[i].price == price) {
        lv[i].qty += qty;
        return 0;
    }
    if (*n >= BOOK_LEVEL_CAP)
        return BOOK_ERR_LEVELS;
    memmove(&lv[i + 1], &lv[i], (size_t)(*n - i) * sizeof(*lv));
    lv[i].price = price;
    lv[i].qty = qty;
    (*n)++;
    return 0;
}

static void level_sub(book_t *b, uint8_t side, uint32_t price, uint32_t qty) {
    book_level_t *lv = (side == 'B') ? b->bids : b->asks;
    uint16_t *n = (side == 'B') ? &b->n_bids : &b->n_asks;
    for (uint16_t i = 0; i < *n; i++) {
        if (lv[i].price == price) {
            lv[i].qty -= qty;
            if (lv[i].qty == 0) {
                memmove(&lv[i], &lv[i + 1], (size_t)(*n - i - 1) * sizeof(*lv));
                (*n)--;
            }
            return;
        }
    }
}

/* ------------------------------------------------------------ apply */

static int add(book_t *b, uint64_t ref, uint8_t side, uint32_t price, uint32_t shares) {
    int r = insert_order(b, ref, side, price, shares);
    if (r < 0)
        return r;
    r = level_add(b, side, price, shares);
    return r < 0 ? r : BOOK_CHANGED;
}

int book_apply(book_t *b, const itch_msg_t *m) {
    switch (m->type) {
    case 'A':
    case 'F':
        if (m->locate != b->locate)
            return BOOK_IGNORED;
        return add(b, m->ref, (uint8_t)m->side, m->price, m->shares);

    case 'E':
    case 'C':
    case 'X': {
        int s = find_slot(b, m->ref);
        if (s < 0)
            return BOOK_IGNORED;
        book_order_t *o = &b->orders[s];
        if (m->shares > o->shares)
            return BOOK_ERR_OVERFILL;
        level_sub(b, o->side, o->price, m->shares);
        o->shares -= m->shares;
        if (o->shares == 0)
            delete_slot(b, (uint32_t)s);
        return BOOK_CHANGED;
    }

    case 'D': {
        int s = find_slot(b, m->ref);
        if (s < 0)
            return BOOK_IGNORED;
        book_order_t *o = &b->orders[s];
        level_sub(b, o->side, o->price, o->shares);
        delete_slot(b, (uint32_t)s);
        return BOOK_CHANGED;
    }

    case 'U': {
        int s = find_slot(b, m->ref);
        if (s < 0)
            return BOOK_IGNORED;
        book_order_t old = b->orders[s];
        level_sub(b, old.side, old.price, old.shares);
        delete_slot(b, (uint32_t)s);
        return add(b, m->new_ref, old.side, m->price, m->shares);
    }

    default:
        return BOOK_IGNORED;
    }
}

book_top_t book_top(const book_t *b) {
    book_top_t t = { 0, 0, 0, 0 };
    if (b->n_bids) { t.bid_px = b->bids[0].price; t.bid_qty = b->bids[0].qty; }
    if (b->n_asks) { t.ask_px = b->asks[0].price; t.ask_qty = b->asks[0].qty; }
    return t;
}

static inline uint32_t fnv_u32(uint32_t h, uint32_t v) {
    for (int s = 24; s >= 0; s -= 8) {
        h ^= (v >> s) & 0xFFu;
        h *= 16777619u;
    }
    return h;
}

uint32_t book_check_update(uint32_t h, book_top_t t) {
    h = fnv_u32(h, t.bid_px);
    h = fnv_u32(h, t.bid_qty);
    h = fnv_u32(h, t.ask_px);
    h = fnv_u32(h, t.ask_qty);
    return h;
}
