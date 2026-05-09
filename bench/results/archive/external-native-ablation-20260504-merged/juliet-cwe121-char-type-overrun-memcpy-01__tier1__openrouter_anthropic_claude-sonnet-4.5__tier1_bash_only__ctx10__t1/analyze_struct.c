#include <stdio.h>

typedef struct _charVoid
{
    char charFirst[16];
    void * voidSecond;
    void * voidThird;
} charVoid;

int main() {
    printf("sizeof(charVoid) = %zu\n", sizeof(charVoid));
    printf("sizeof(charVoid.charFirst) = %zu\n", sizeof(((charVoid*)0)->charFirst));
    printf("offset of charFirst = %zu\n", __builtin_offsetof(charVoid, charFirst));
    printf("offset of voidSecond = %zu\n", __builtin_offsetof(charVoid, voidSecond));
    printf("offset of voidThird = %zu\n", __builtin_offsetof(charVoid, voidThird));
    printf("sizeof(void*) = %zu\n", sizeof(void*));
    return 0;
}
