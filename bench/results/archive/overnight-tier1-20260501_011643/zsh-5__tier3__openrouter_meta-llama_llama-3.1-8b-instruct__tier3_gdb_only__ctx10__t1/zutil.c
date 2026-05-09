static void
freestypat(Stypat p, Style s, Stypat prev)
{
    if (s) {
	if (prev)
	    prev->next = p->next;
	else
	    s->pats = p->next;
    }

    freestylepatnode(p);

    if (s && !s->pats) {
	/* No patterns left, free style */
	zstyletab->removenode(zstyletab, s->node.nam);
	zsfree(s->node.nam);
	zfree(s, sizeof(*s));
    }
}

/* Pattern to match context when printing nodes */

static Patprog zstyle_contprog;

/*
 * Print a node.  Print flags as shown.
 */
enum {
    ZSLIST_NONE,
    ZSLIST_BASIC,
    ZSLIST_SYNTAX,
};

static void
printstylenode(HashNode hn, int printflags)
{
    Style s = (Style)hn;
    Stypat p;
    char **v;

    if (printflags == ZSLIST_BASIC) {
	quotedzputs(s->node.nam, stdout);
	putchar('\n');
    }

    for (p = s->pats; p; p = p->next) {
	if (zstyle_contprog && !pattry(zstyle_contprog, p->pat))
	    continue;
	if (printflags == ZSLIST_BASIC)
	    printf("%s  %s", (p->eval ? "(eval)" : "      "), p->pat);
	else {
	    printf("zstyle %s", (p->eval ? "-e " : ""));
	    quotedzputs(p->pat, stdout);
	    printf(" %s", s->node.nam);
	}
	for (v = p->vals; *v; v++) {
	    putchar(' ');
	    quotedzputs(*v, stdout);
	}
	putchar('\n');
    }
}

/*
 * Scan the list for a particular pattern, maybe adding matches to
 * the link list (heap memory).  Value to be added as
 * shown in enum
 */
static LinkList zstyle_list;
static char *zstyle_patname;

enum {
    ZSPAT_NAME,		/* Add style names for matched pattern to list */
    ZSPAT_PAT,		/* Add all patterns to list, doesn't use patname */
    ZSPAT_REMOVE,	/* Remove matched pattern, doesn't use list */
};

static void
scanpatstyles(HashNode hn, int spatflags)
{
    Style s = (Style)hn;
    Stypat p, q;
    LinkNode n;

    for (q = NULL, p = s->pats; p; q = p, p = p->next) {
	switch (spatflags) {
	case ZSPAT_NAME:
	    if (!strcmp(p->pat, zstyle_patname)) {
		addlinknode(zstyle_list, s->node.nam);
		return;
	    }
	    break;

	case ZSPAT_PAT:
	    /* Check pattern isn't already there */
	    for (n = firstnode(zstyle_list); n; incnode(n))
		if (!strcmp(p->pat, (char *) getdata(n)))
		    break;
	    if (!n)
		addlinknode(zstyle_list, p->pat);
	    break;
