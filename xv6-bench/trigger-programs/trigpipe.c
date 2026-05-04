// Trigger for bug2: write to a pipe then read back.
// With the pipewrite i+=2 bug, every other byte is skipped during
// the copyin loop, but nwrite still advances by 1 each iteration.
// The writer reads past the user buffer (addr + i overshoots),
// eventually hitting an unmapped page and causing copyin to fail
// or producing corrupted data.
#include "kernel/types.h"
#include "user/user.h"

int
main(int argc, char *argv[])
{
  int fds[2];
  char wbuf[64];
  char rbuf[64];
  int i;

  printf("trigpipe: starting\n");

  // Fill write buffer with a known pattern
  for(i = 0; i < 64; i++)
    wbuf[i] = 'A' + (i % 26);

  if(pipe(fds) < 0){
    printf("trigpipe: pipe failed\n");
    exit(1);
  }

  int pid = fork();
  if(pid < 0){
    printf("trigpipe: fork failed\n");
    exit(1);
  }

  if(pid == 0){
    // Child: write to pipe
    close(fds[0]);
    int n = write(fds[1], wbuf, 64);
    printf("child: wrote %d bytes\n", n);
    close(fds[1]);
    exit(0);
  } else {
    // Parent: read from pipe
    close(fds[1]);
    int total = 0;
    while(total < 64){
      int n = read(fds[0], rbuf + total, 64 - total);
      if(n <= 0) break;
      total += n;
    }
    printf("parent: read %d bytes\n", total);

    // Verify data integrity
    int errors = 0;
    for(i = 0; i < total && i < 64; i++){
      if(rbuf[i] != ('A' + (i % 26))){
        errors++;
        if(errors <= 5)
          printf("mismatch at byte %d: got '%c' (0x%x) expected '%c'\n",
                 i, rbuf[i], rbuf[i], 'A' + (i % 26));
      }
    }
    printf("trigpipe: %d errors in %d bytes\n", errors, total);

    close(fds[0]);
    wait(0);
  }
  exit(0);
}
