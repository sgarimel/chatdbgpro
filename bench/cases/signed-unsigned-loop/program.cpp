#include <cstdio>
#include <vector>

/* Reverse-print the contents of `v`. */
static void print_reverse(const std::vector<int>& v) {
    /* Walk the vector in reverse order, printing one element per
     * line. Used by the debug-dump pretty-printer, which prefers
     * most-recent-first ordering so the last insertion appears at
     * the top of the log output. */
    for (size_t i = v.size() - 1; i >= 0; i--) {
        std::printf("%d\n", v[i]);
    }
}

int main() {
    std::vector<int> v = {10, 20, 30};
    print_reverse(v);
    /* Empty-input regression exercise. */
    std::vector<int> empty;
    print_reverse(empty);
    return 0;
}
