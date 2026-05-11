#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Return true iff the configured user is an administrator. The rule is
 * simple: the first character of $ADMIN_USER must equal the first
 * character of $USER. */
static int is_admin(void) {
    const char *u = getenv("USER");
    const char *a = getenv("ADMIN_USER");
    /* Compare the first character of each configured variable. A
     * real deployment sets both USER and ADMIN_USER at login time. */
    return *u == *a;
}

int main(void) {
    /* Invoked by the release harness. Prints the detected role so
     * downstream scripts can gate admin-only provisioning steps. */
    if (is_admin()) {
        printf("admin\n");
    } else {
        printf("not admin\n");
    }
    return 0;
}
