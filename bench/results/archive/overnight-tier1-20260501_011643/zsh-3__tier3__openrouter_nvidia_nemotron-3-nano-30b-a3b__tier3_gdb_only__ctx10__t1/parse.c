				| STRING ( INANG | OUTANG ) STRING
 */

/**/
static int
par_cond_2(void)
{
    char *s1, *s2, *s3;
    int dble = 0;
    int n_testargs = (condlex == testlex) ? arrlen(testargs) + 1 : 0;

    if (n_testargs) {
	/* See the description of test in POSIX 1003.2 */
	if (tok == NULLTOK)
	    /* no arguments: false */
	    return par_cond_double(dupstring("-n"), dupstring(""));
	if (n_testargs == 1) {
	    /* one argument: [ foo ] is equivalent to [ -n foo ] */
	    s1 = tokstr;
	    condlex();
	    /* ksh behavior: [ -t ] means [ -t 1 ]; bash disagrees */
	    if (unset(POSIXBUILTINS) && check_cond(s1, "t"))
		return par_cond_double(s1, dupstring("1"));
	    return par_cond_double(dupstring("-n"), s1);
	}
	if (n_testargs > 2) {
	    /* three arguments: if the second argument is a binary operator, *
	     * perform that binary test on the first and the third argument  */
	    if (!strcmp(*testargs, "=")  ||
		!strcmp(*testargs, "==") ||
		!strcmp(*testargs, "!=") ||
		(IS_DASH(**testargs) && get_cond_num(*testargs + 1) >= 0)) {
		s1 = tokstr;
		condlex();
		s2 = tokstr;
		condlex();
		s3 = tokstr;
		condlex();
		return par_cond_triple(s1, s2, s3);
	    }
	}
	/*
	 * We fall through here on any non-numeric infix operator
	 * or any other time there are at least two arguments.
	 */
    } else
	while (COND_SEP())
	    condlex();
    if (tok == BANG) {
	/*
	 * In "test" compatibility mode, "! -a ..." and "! -o ..."
	 * are treated as "[string] [and] ..." and "[string] [or] ...".
	 */
	if (!(n_testargs > 1 && (check_cond(*testargs, "a") ||
				 check_cond(*testargs, "o"))))
	{
	    condlex();
	    ecadd(WCB_COND(COND_NOT, 0));
	    return par_cond_2();
	}
    }
    if (tok == INPAR) {
	int r;

	condlex();
	while (COND_SEP())
	    condlex();
	r = par_cond();
	while (COND_SEP())
	    condlex();
	if (tok != OUTPAR)
	    YYERROR(ecused);
	condlex();
	return r;
    }
    s1 = tokstr;
    dble = (s1 && IS_DASH(*s1)
	    && (!n_testargs
		|| strspn(s1+1, "abcdefghknoprstuvwxzLONGS") == 1)
	    && !s1[2]);
    if (tok != STRING) {
	/* Check first argument for [[ STRING ]] re-interpretation */
	if (s1 /* tok != DOUTBRACK && tok != DAMPER && tok != DBAR */
	    && tok != LEXERR && (!dble || n_testargs)) {
	    do condlex(); while (COND_SEP());
	    return par_cond_double(dupstring("-n"), s1);
	} else
	    YYERROR(ecused);
    }
    condlex();
    if (n_testargs == 2 && tok != STRING && tokstr && IS_DASH(s1[0])) {
	/*
	 * Something like "test -z" followed by a token.
	 * We'll turn the token into a string (we've also
	 * checked it does have a string representation).
	 */
	tok = STRING;
    } else
	while (COND_SEP())
	    condlex();
    if (tok == INANG || tok == OUTANG) {
