#include "itch.h"

/* Byte offsets from the TotalView-ITCH 5.0 specification.
 * Common header: type(1) locate(2) tracking(2) timestamp(6) = 11 bytes. */
#define OFF_LOCATE 1
#define OFF_REF    11

static inline uint16_t be16(const uint8_t *p) {
    return (uint16_t)((p[0] << 8) | p[1]);
}

static inline uint32_t be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8)  |  (uint32_t)p[3];
}

static inline uint64_t be64(const uint8_t *p) {
    return ((uint64_t)be32(p) << 32) | be32(p + 4);
}

uint16_t itch_msg_len(uint8_t type) {
    switch (type) {
    case 'S': return 12;  case 'R': return 39;  case 'H': return 25;
    case 'Y': return 20;  case 'L': return 26;  case 'V': return 35;
    case 'W': return 12;  case 'K': return 28;  case 'J': return 35;
    case 'h': return 21;  case 'A': return 36;  case 'F': return 40;
    case 'E': return 31;  case 'C': return 36;  case 'X': return 23;
    case 'D': return 19;  case 'U': return 35;  case 'P': return 44;
    case 'Q': return 40;  case 'B': return 19;  case 'I': return 50;
    case 'N': return 20;  case 'O': return 48;
    default:  return 0;
    }
}

int itch_decode(const uint8_t *buf, uint16_t len, itch_msg_t *m) {
    uint8_t t = buf[0];
    uint16_t want = itch_msg_len(t);
    if (want == 0 || want != len)
        return -1;

    m->type    = (char)t;
    m->locate  = be16(buf + OFF_LOCATE);
    m->new_ref = 0;
    m->side    = 0;
    m->shares  = 0;
    m->price   = 0;

    switch (t) {
    case 'A':
    case 'F':
        m->ref    = be64(buf + 11);
        m->side   = (char)buf[19];
        m->shares = be32(buf + 20);
        m->price  = be32(buf + 32);     /* stock symbol at 24..31 is skipped */
        return 1;
    case 'E':
        m->ref    = be64(buf + 11);
        m->shares = be32(buf + 19);     /* executed shares */
        return 1;
    case 'C':
        m->ref    = be64(buf + 11);
        m->shares = be32(buf + 19);     /* executed shares */
        m->price  = be32(buf + 32);     /* execution price */
        return 1;
    case 'X':
        m->ref    = be64(buf + 11);
        m->shares = be32(buf + 19);     /* cancelled shares */
        return 1;
    case 'D':
        m->ref    = be64(buf + 11);
        return 1;
    case 'U':
        m->ref     = be64(buf + 11);
        m->new_ref = be64(buf + 19);
        m->shares  = be32(buf + 27);
        m->price   = be32(buf + 31);
        return 1;
    default:
        m->ref = 0;
        return 0;
    }
}
