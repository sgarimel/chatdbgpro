#include <iostream>

float fact(float n) {
  float x = 1.0;
  for (float i = 1.0; i <= n; i++) {
    x *= i;
  }
  return x;
}

int main() {
  std::cout << fact(5) << std::endl;
  return 0;
}
