#include <stdio.h>
#include <string.h>

#define SRC_STR "0123456789abcdef0123456789abcde"

int main() {
    printf("SRC_STR = \"%s\"\n", SRC_STR);
    printf("strlen(SRC_STR) = %zu\n", strlen(SRC_STR));
    printf("sizeof(SRC_STR) = %zu (includes null terminator)\n", sizeof(SRC_STR));
    return 0;
}
