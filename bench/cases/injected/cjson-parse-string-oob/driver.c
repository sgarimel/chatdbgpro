/* Small bench driver: read up to 4 KiB from stdin onto a heap buffer,
 * hand it to cJSON_ParseWithOpts. With the injected patch applied to
 * cJSON.c, parse_string walks past the end of this heap buffer when
 * the input lacks a closing quote, and AddressSanitizer flags it as
 * heap-buffer-overflow READ inside parse_string. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"

int main(void) {
    char tmp[4096];
    size_t n = fread(tmp, 1, sizeof(tmp), stdin);
    char *buf = (char *)malloc(n + 1);
    if (!buf) return 2;
    memcpy(buf, tmp, n);
    buf[n] = '\0';
    const char *err = NULL;
    cJSON *item = cJSON_ParseWithOpts(buf, &err, 0);
    if (item) cJSON_Delete(item);
    free(buf);
    return 0;
}
