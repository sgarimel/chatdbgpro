// Trigger for bug1: fork a child, child touches its own memory.
// With the uvmcopy PTE_U bug, child pages lack user permission,
// causing a page fault (store/load page fault in user mode).
#include "kernel/types.h"
#include "user/user.h"

int global_var = 42;

int
main(int argc, char *argv[])
{
  int pid;
  printf("trigfork: starting\n");

  pid = fork();
  if(pid < 0){
    printf("trigfork: fork failed\n");
    exit(1);
  }

  if(pid == 0){
    // Child: try to read and write our own memory
    printf("child: reading global_var = %d\n", global_var);
    global_var = 99;
    printf("child: wrote global_var = %d\n", global_var);
    exit(0);
  } else {
    int status;
    wait(&status);
    printf("trigfork: child exited\n");
  }
  exit(0);
}
