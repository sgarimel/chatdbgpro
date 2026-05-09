#include <iostream>
#include <cstdint>

struct Record {
    uint64_t id;
    uint64_t score;
    uint64_t payload[6];
};

int main() {
    uint32_t n = 70000000u;
    uint32_t size = sizeof(Record);
    uint64_t bytes = (uint64_t)n * (uint64_t)size;
    std::cout << "n: " << n << std::endl;
    std::cout << "sizeof(Record): " << size << std::endl;
    std::cout << "bytes (uint32_t): " << (uint32_t)(n * size) << std::endl;
    std::cout << "bytes (uint64_t): " << bytes << std::endl;
    return 0;
}
