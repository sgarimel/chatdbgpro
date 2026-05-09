#include <iostream>
#include <cstdint>

struct Record {
    uint64_t id;
    uint64_t score;
    uint64_t payload[6];
};

int main() {
    std::cout << "sizeof(Record): " << sizeof(Record) << std::endl;
    uint32_t n = 70000000u;
    uint64_t bytes_64 = (uint64_t)n * (uint64_t)sizeof(Record);
    uint32_t bytes_32 = n * (uint32_t)sizeof(Record);
    std::cout << "n: " << n << std::endl;
    std::cout << "bytes_64: " << bytes_64 << std::endl;
    std::cout << "bytes_32: " << bytes_32 << std::endl;
    return 0;
}
