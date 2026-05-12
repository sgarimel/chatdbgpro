#include <iostream>
int main() {
    float x = 1.0;
    for (float i = 0.0; i < 5; i++) {
        std::cout << "i: " << i << ", x: " << x << std::endl;
        x *= i;
    }
    return 0;
}
