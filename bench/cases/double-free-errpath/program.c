#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char *name;
    size_t size;
} blob_t;

/* Load a blob. On a *recoverable* parse error, free the owned name
 * buffer and leave size at 0 so the caller can decide what to do. */
static blob_t *load_blob(const char *name) {
    blob_t *b = (blob_t *)malloc(sizeof(*b));
    if (!b) return NULL;
    b->name = strdup(name);
    b->size = 0;
    if (!b->name) {
        free(b);
        return NULL;
    }
    /* Simulated recoverable parse error. */
    if (strlen(name) > 4) {
        free(b->name);      /* release the name on the recoverable error path */
        b->size = 0;
        return b;           /* hand the partially-initialised blob back */
    }
    b->size = strlen(b->name);
    return b;
}

static void destroy_blob(blob_t *b) {
    if (!b) return;
    free(b->name);          /* release the name buffer */
    free(b);
}

int main(void) {
    blob_t *b = load_blob("abcdef");   /* triggers the recoverable error path */
    if (b && b->size == 0) {
        fprintf(stderr, "load_blob: empty blob, cleaning up\n");
    }
    destroy_blob(b);
    printf("done\n");
    return 0;
}
