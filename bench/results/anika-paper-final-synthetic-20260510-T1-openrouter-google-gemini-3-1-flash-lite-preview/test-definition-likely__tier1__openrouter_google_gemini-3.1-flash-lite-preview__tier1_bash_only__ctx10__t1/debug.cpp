#include <iostream>

static int* p = nullptr;

struct Bob
{
  int ****data;
};
struct Adam
{
  Bob *b1;
  Bob *b2;
};

int main()
{
  int x = 42;
  p = &x;
  int **p2 = &p;
  int ***p3 = &p2;
  int ****p4 = &p3;

  Bob bob1 = {p4};
  Bob bob2 = {p4};
  Adam adam1 = {&bob1, &bob2};

  std::cout << "p: " << p << std::endl;
  std::cout << "*p: " << *p << std::endl;
  std::cout << "**p2: " << **p2 << std::endl;
  std::cout << "***p3: " << ***p3 << std::endl;
  std::cout << "****p4: " << ****p4 << std::endl;
  
  int n = ****adam1.b1->data;
  std::cout << "n: " << n << std::endl;
  return 0;
}
