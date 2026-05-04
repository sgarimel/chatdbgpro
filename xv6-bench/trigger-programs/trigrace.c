// Trigger for bug4: stress the allocator from multiple processes
// to expose the missing-lock race condition.
// With SMP=2 and no lock on kalloc/kfree, concurrent allocations
// will corrupt the freelist and eventually panic or corrupt memory.
#include "kernel/types.h"
#include "user/user.h"

void
alloc_stress(void)
{
  // Repeatedly allocate and free via sbrk
  for(int i = 0; i < 50; i++){
    char *p = sbrk(4096);
    if(p == (char*)-1){
      printf("sbrk failed at iter %d\n", i);
      break;
    }
    // Touch the page to force allocation
    *p = 'X';
    // Free it back
    sbrk(-4096);
  }
}

int
main(int argc, char *argv[])
{
  printf("trigrace: starting race condition stress test\n");

  // Fork multiple children to run allocations concurrently
  for(int c = 0; c < 4; c++){
    int pid = fork();
    if(pid < 0){
      printf("trigrace: fork failed\n");
      break;
    }
    if(pid == 0){
      // Child: hammer the allocator
      alloc_stress();
      exit(0);
    }
  }

  // Parent also hammers
  alloc_stress();

  // Wait for all children
  for(int c = 0; c < 4; c++){
    wait(0);
  }

  printf("trigrace: done (if you see this, race didn't crash)\n");
  exit(0);
}
