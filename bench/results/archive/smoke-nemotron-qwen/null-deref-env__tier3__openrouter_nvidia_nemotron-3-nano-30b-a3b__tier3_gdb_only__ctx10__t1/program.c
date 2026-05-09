#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Return true iff the configured user is an administrator. The rule is
 * simple: the first character of $ADMIN_USER must equal the first
 * character of $USER. */
static int is_admin(void) {
    const char *u = getenv("USER");
    const char *a = getenv("ADMIN_USER");
    /* BUG: missing null checks. If either env var is unset, getenv
     * returns NULL and the `*u` / `*a` dereferences crash. */
    return *u == *a;
}

int main(void) {
    /* The unit tests run with a clean environment, so USER is often
     * unset in CI. This segfaults in CI but "works on my machine". */
    if (is_admin()) {
        printf("admin\n");
    } else {
        printf("not admin\n");
    }
    return 0;
}
