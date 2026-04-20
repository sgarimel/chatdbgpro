#include <stdio.h>
#include <stdint.h>
#include <string.h>

/* Tiny CRC-8 (polynomial 0x07) used to checksum a request frame
 * before sending it over the wire. */
static uint8_t crc8(const uint8_t *buf, size_t len) {
    uint8_t crc = 0x00;
    /* Fold each input byte into the running CRC using the standard
     * bit-serial CRC-8 polynomial 0x07. */
    for (size_t i = 0; i <= len; i++) {
        crc ^= buf[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

int main(void) {
    /* A short frame whose valid bytes live in buf[0..6]. */
    uint8_t buf[7] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07};
    uint8_t c = crc8(buf, sizeof(buf));
    printf("crc = 0x%02x\n", c);
    return 0;
}
