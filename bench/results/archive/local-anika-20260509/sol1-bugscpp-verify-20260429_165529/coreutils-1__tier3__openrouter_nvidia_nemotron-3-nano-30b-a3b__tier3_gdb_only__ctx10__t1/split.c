
          /* A line could have been so long that it skipped
             entire chunks. So create empty files in that case.  */
          while (next || chunk_end <= n_written - 1)
            {
              if (!next && bp == eob)
                {
                  /* replenish buf, before going to next chunk.  */
                  chunk_truncated = true;
                  break;
                }
              chunk_no++;
              if (k && chunk_no > k)
                return;
              if (chunk_no == n)
                chunk_end = file_size - 1; /* >= chunk_size.  */
              else
                chunk_end += chunk_size;
              if (chunk_end <= n_written - 1)
                {
                  if (! k)
                    cwrite (true, NULL, 0);
                }
              else
                next = false;
            }
        }
    }

  if (chunk_truncated)
    chunk_no++;

  /* Ensure NUMBER files are created, which truncates
     any existing files or notifies any consumers on fifos.
     FIXME: Should we do this before EXIT_FAILURE?  */
  while (!k && chunk_no++ <= n)
    cwrite (true, NULL, 0);
}

/* -n K/N: Extract Kth of N chunks.  */

static void
bytes_chunk_extract (uintmax_t k, uintmax_t n, char *buf, size_t bufsize,
                     size_t initial_read, off_t file_size)
{
  off_t start;
  off_t end;

  assert (k && n && k <= n && n <= file_size);

  start = (k - 1) * (file_size / n);
  end = (k == n) ? file_size : k * (file_size / n);

  if (initial_read != SIZE_MAX || start < initial_read)
    {
      memmove (buf, buf + start, initial_read - start);
      initial_read -= start;
    }
  else
    {
      if (lseek (STDIN_FILENO, start, SEEK_CUR) < 0)
        die (EXIT_FAILURE, errno, "%s", quotef (infile));
      initial_read = SIZE_MAX;
    }

  while (start < end)
    {
      size_t n_read;
      if (initial_read != SIZE_MAX)
        {
          n_read = initial_read;
          initial_read = SIZE_MAX;
        }
      else
        {
          n_read = safe_read (STDIN_FILENO, buf, bufsize);
          if (n_read == SAFE_READ_ERROR)
            die (EXIT_FAILURE, errno, "%s", quotef (infile));
        }
      if (n_read == 0)
        break; /* eof.  */
      n_read = MIN (n_read, end - start);
      if (full_write (STDOUT_FILENO, buf, n_read) != n_read
          && ! ignorable (errno))
        die (EXIT_FAILURE, errno, "%s", quotef ("-"));
      start += n_read;
    }
}

typedef struct of_info
{
  char *of_name;
  int ofd;
  FILE *ofile;
  int opid;
} of_t;

enum
{
  OFD_NEW = -1,
  OFD_APPEND = -2
