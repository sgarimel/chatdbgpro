#include <stdio.h>
#include <string.h>

#define SRC_STR "0123456789abcdef0123456789abcde"

typedef struct _charVoid
{
    char charFirst[16];
    void * voidSecond;
    void * voidThird;
} charVoid;

int main() {
    charVoid structCharVoid;
    
    // Initialize voidSecond to point to SRC_STR
    structCharVoid.voidSecond = (void *)SRC_STR;
    
    printf("Before memcpy:\n");
    printf("  voidSecond = %p (points to SRC_STR)\n", structCharVoid.voidSecond);
    printf("  voidSecond content = \"%s\"\n", (char*)structCharVoid.voidSecond);
    
    // BUG: memcpy 32 bytes into a 16-byte buffer
    // This overwrites voidSecond and voidThird!
    printf("\nCalling memcpy with sizeof(structCharVoid) = %zu bytes\n", sizeof(structCharVoid));
    printf("  But charFirst is only %zu bytes!\n", sizeof(structCharVoid.charFirst));
    
    memcpy(structCharVoid.charFirst, SRC_STR, sizeof(structCharVoid));
    
    printf("\nAfter memcpy:\n");
    printf("  charFirst = \"%.16s\"\n", structCharVoid.charFirst);
    printf("  voidSecond = %p (CORRUPTED!)\n", structCharVoid.voidSecond);
    
    // Show what voidSecond contains now (bytes from SRC_STR)
    unsigned char *p = (unsigned char*)&structCharVoid.voidSecond;
    printf("  voidSecond bytes: ");
    for (int i = 0; i < 8; i++) {
        printf("%02x ", p[i]);
    }
    printf("\n  As ASCII: ");
    for (int i = 0; i < 8; i++) {
        printf("%c", p[i]);
    }
    printf("\n");
    
    return 0;
}
