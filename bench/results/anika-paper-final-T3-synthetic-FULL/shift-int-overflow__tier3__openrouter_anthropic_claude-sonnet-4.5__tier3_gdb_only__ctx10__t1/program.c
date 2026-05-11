#include <stdio.h>

static unsigned long long high_bit_mask(int width)
{
    /* Intended: produce 2^width as a mask. With width=64 on a 32-bit
     * `int 1`, this is undefined behaviour (shift count == width of
     * the type), and UBSan flags it. The caller then uses the result
     * as a divisor and the program proceeds with garbage. */
    return (unsigned long long)(1 << width);
}

int main(void)
{
    int width = 64;
    unsigned long long m = high_bit_mask(width);
    printf("mask = %llu\n", m);
    return 0;
}
