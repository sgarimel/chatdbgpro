#include <cstdio>
#include <vector>

int main()
{
    std::vector<int> v = {1, 2, 3, 4};
    /* Take an iterator into the vector, then push_back which may
     * reallocate. The iterator is invalidated; dereferencing it is a
     * use-after-free that AddressSanitizer flags. */
    auto it = v.begin() + 2;
    for (int i = 0; i < 1000; ++i) {
        v.push_back(i);
    }
    std::printf("element via stale iter: %d\n", *it);
    return 0;
}
