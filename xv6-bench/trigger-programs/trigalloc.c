// Trigger for bug3: allocate memory via sbrk repeatedly.
// With the kalloc freelist-not-advancing bug, the same physical
// page is returned for every allocation. Two different virtual
// pages map to the same physical page, causing memory corruption.
// Writing to one allocation silently overwrites the other, and
// the kernel eventually panics when page table structures collide.
#include "kernel/types.h"
#include "user/user.h"

int
main(int argc, char *argv[])
{
  printf("trigalloc: starting\n");

  // Allocate two separate pages via sbrk
  char *p1 = sbrk(4096);
  char *p2 = sbrk(4096);

  if(p1 == (char*)-1 || p2 == (char*)-1){
    printf("trigalloc: sbrk failed\n");
    exit(1);
  }

  printf("trigalloc: p1=%p p2=%p\n", p1, p2);

  // Write distinct patterns
  memset(p1, 'A', 4096);
  memset(p2, 'B', 4096);

  // Check p1 — if bug is present, p2's write clobbered p1
  int errors = 0;
  for(int i = 0; i < 4096; i++){
    if(p1[i] != 'A'){
      errors++;
      if(errors <= 3)
        printf("CORRUPTION at p1[%d]: got 0x%x, expected 0x41\n", i, p1[i]);
    }
  }

  if(errors > 0)
    printf("trigalloc: FAIL — %d bytes corrupted (same page aliased)\n", errors);
  else
    printf("trigalloc: PASS — memory is distinct\n");

  // Fork to stress the allocator further — this often panics
  // because page table pages also get the same physical page
  int pid = fork();
  if(pid < 0){
    printf("trigalloc: fork failed (expected with this bug)\n");
    exit(1);
  }
  if(pid == 0){
    // Child: try to use memory
    memset(p1, 'C', 4096);
    printf("child: wrote to p1\n");
    exit(0);
  } else {
    wait(0);
    printf("trigalloc: done\n");
  }
  exit(0);
}
