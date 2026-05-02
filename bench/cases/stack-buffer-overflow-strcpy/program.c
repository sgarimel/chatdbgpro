#include <stdio.h>
#include <string.h>

static void greet(const char *who)
{
    char buf[16];
    strcpy(buf, "Hello, ");
    strcat(buf, who);
    strcat(buf, "!");
    puts(buf);
}

int main(void)
{
    /* "Hello, " is 7 chars, "!" is 1, leaves 8 bytes for `who`. The name
     * below is 24 bytes — strcat overflows buf[16] on the stack and
     * AddressSanitizer flags a stack-buffer-overflow in __asan_memcpy. */
    greet("ProfessorAdrieneDelmarre");
    return 0;
}
