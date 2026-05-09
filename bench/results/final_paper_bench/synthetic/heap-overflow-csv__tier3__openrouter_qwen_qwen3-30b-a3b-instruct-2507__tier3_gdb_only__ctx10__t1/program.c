#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Return a freshly allocated copy of the first CSV field in `line`. */
static char *first_field(const char *line) {
    const char *comma = strchr(line, ',');
    size_t n = comma ? (size_t)(comma - line) : strlen(line);

    /* Allocate a buffer for the field and copy the characters into
     * it, terminating the result. */
    char *out = (char *)malloc(n);
    if (!out) {
        return NULL;
    }
    memcpy(out, line, n);
    out[n] = '\0';     /* terminate the string */
    return out;
}

int main(void) {
    const char *line = "alice,bob,carol\n";
    char *first = first_field(line);
    printf("first = %s\n", first);
    free(first);
    return 0;
}
