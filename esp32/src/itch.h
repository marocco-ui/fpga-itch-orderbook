/*
 * Nasdaq TotalView-ITCH 5.0 decoder for the order-book messages.
 *
 * Plain C, no ESP-IDF dependencies, so the same file builds on the
 * ESP32 and on a PC for testing against the Python golden model.
 */
#ifndef ITCH_H
#define ITCH_H

#include <stdint.h>

typedef struct {
    char     type;      /* 'A' 'F' 'E' 'C' 'X' 'D' 'U' */
    uint16_t locate;    /* stock locate code */
    uint64_t ref;       /* order reference (original ref for U) */
    uint64_t new_ref;   /* U only */
    char     side;      /* 'B' or 'S' for A/F, 0 otherwise */
    uint32_t shares;    /* A/F/U order shares; E/C executed; X cancelled */
    uint32_t price;     /* A/F/U price; C execution price; 4 implied decimals */
} itch_msg_t;

/* Spec length of a message type, or 0 if the type is unknown. */
uint16_t itch_msg_len(uint8_t type);

/*
 * Decode one message body (no length prefix).
 * Returns  1 for a book message (A F E C X D U), fields in *m
 *          0 for a valid message the book ignores
 *         -1 for an unknown type or a length that doesn't match the spec
 */
int itch_decode(const uint8_t *buf, uint16_t len, itch_msg_t *m);

#endif
