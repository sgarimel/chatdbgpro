#include <stdio.h>

typedef struct _charVoid
{
    char charFirst[16];
    void * voidSecond;
    void * voidThird;
} charVoid;

int main() {
    printf("sizeof(charVoid) = %zu\n", sizeof(charVoid));
    printf("sizeof(charFirst) = %zu\n", sizeof(((charVoid*)0)->charFirst));
    printf("sizeof(void*) = %zu\n", sizeof(void*));
    printf("Total expected: 16 + 8 + 8 = 32\n");
    return 0;
}
