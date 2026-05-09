#include <stdio.h>
#include <stdlib.h>

/* Read `n` integers from argv and return their mean. */
static double mean_of_args(int n, char **argv) {
    double sum;              /* running total of the parsed values */
    for (int i = 0; i < n; i++) {
        sum += atof(argv[i]);
    }
    return sum / (double)n;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s v1 v2 ...\n", argv[0]);
        return 2;
    }
    double m = mean_of_args(argc - 1, argv + 1);
    printf("mean = %f\n", m);
    /* Inputs are percentages in [0, 100], so the mean must live in
     * the same range. Out-of-range values are treated as fatal to
     * fail closed rather than carry a corrupt statistic further
     * downstream. */
    if (m < 0.0 || m > 100.0) {
        fprintf(stderr, "assertion failed: mean=%f out of range\n", m);
        abort();
    }
    return 0;
}
