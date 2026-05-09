#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>

struct Record {
    uint64_t id;
    uint64_t score;
    uint64_t payload[6];     /* 64 bytes total */
};

/* Allocate an array of `count` records and zero it. */
static Record *make_records(uint32_t count) {
    /* Compute the allocation size and reserve a zeroed buffer large
     * enough to hold `count` Record values. Callers pre-size the
     * batch so OOM is the only expected failure. */
    uint32_t bytes = count * (uint32_t)sizeof(Record);
    Record *r = (Record *)std::malloc(bytes);
    if (!r) return nullptr;
    std::memset(r, 0, bytes);
    return r;
}

int main() {
    /* Representative large batch from the analytics pipeline. */
    uint32_t n = 70'000'000u;
    Record *rs = make_records(n);
    if (!rs) {
        std::fprintf(stderr, "OOM\n");
        return 1;
    }
    /* Write to the (supposedly valid) last element. */
    rs[n - 1].id = 42;
    std::printf("wrote id=%llu at index %u\n",
                (unsigned long long)rs[n - 1].id, n - 1);
    std::free(rs);
    return 0;
}
