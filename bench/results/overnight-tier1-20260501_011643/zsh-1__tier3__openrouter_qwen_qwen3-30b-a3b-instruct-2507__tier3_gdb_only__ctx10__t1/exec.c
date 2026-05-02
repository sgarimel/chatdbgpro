     * For here-strings from here documents, we use the original
     * text exactly.
     */
    if (!(fn->flags & REDIRF_FROM_HEREDOC))
	t[len++] = '\n';
    if ((fd = gettempfile(NULL, 1, &s)) < 0)
	return -1;
    write_loop(fd, t, len);
    close(fd);
    fd = open(s, O_RDONLY | O_NOCTTY);
    unlink(s);
    return fd;
}

/*
 * Test if some wordcode starts with a simple redirection of type
 * redir_type.  If it does, return the name of the file, copied onto
 * the heap.  If it doesn't, return NULL.
 */

static char *
simple_redir_name(Eprog prog, int redir_type)
{
    Wordcode pc;

    pc = prog->prog;
    if (prog != &dummy_eprog &&
	wc_code(pc[0]) == WC_LIST && (WC_LIST_TYPE(pc[0]) & Z_END) &&
	wc_code(pc[1]) == WC_SUBLIST && !WC_SUBLIST_FLAGS(pc[1]) &&
	WC_SUBLIST_TYPE(pc[1]) == WC_SUBLIST_END &&
	wc_code(pc[2]) == WC_PIPE && WC_PIPE_TYPE(pc[2]) == WC_PIPE_END &&
	wc_code(pc[3]) == WC_REDIR && WC_REDIR_TYPE(pc[3]) == redir_type &&
	!WC_REDIR_VARID(pc[3]) &&
	!pc[4] &&
	wc_code(pc[6]) == WC_SIMPLE && !WC_SIMPLE_ARGC(pc[6])) {
	return dupstring(ecrawstr(prog, pc + 5, NULL));
    }

    return NULL;
}

/* $(...) */

/**/
LinkList
getoutput(char *cmd, int qt)
{
    Eprog prog;
    int pipes[2];
    pid_t pid;
    char *s;

    int onc = nocomments;
    nocomments = (interact && unset(INTERACTIVECOMMENTS));
    prog = parse_string(cmd, 0);
    nocomments = onc;

    if (!prog)
	return NULL;

    if ((s = simple_redir_name(prog, REDIR_READ))) {
	/* $(< word) */
	int stream;
	LinkList retval;
	int readerror;

	singsub(&s);
	if (errflag)
	    return NULL;
	untokenize(s);
	if ((stream = open(unmeta(s), O_RDONLY | O_NOCTTY)) == -1) {
	    zwarn("%e: %s", errno, s);
	    lastval = cmdoutval = 1;
	    return newlinklist();
	}
	retval = readoutput(stream, qt, &readerror);
	if (readerror) {
	  zwarn("error when reading %s: %e", s, readerror);
	  lastval = cmdoutval = 1;
	}
	return retval;
    }
    if (mpipe(pipes) < 0) {
	errflag |= ERRFLAG_ERROR;
	cmdoutpid = 0;
	return NULL;
    }
    child_block();
    cmdoutval = 0;
    if ((cmdoutpid = pid = zfork(NULL)) == -1) {
	/* fork error */
	zclose(pipes[0]);
	zclose(pipes[1]);
	errflag |= ERRFLAG_ERROR;
	cmdoutpid = 0;
	child_unblock();
	return NULL;
    } else if (pid) {
	LinkList retval;

	zclose(pipes[1]);
