		    aval = hmkarray(NULL);
		} else {
		    val = dupstring("");
		}
	    }
	}
	if (vunset) {
	    if (vunset > 0 && unset(UNSET)) {
		*idend = '\0';
		zerr("%s: parameter not set", idbeg);
		return NULL;
	    }
	    val = dupstring("");
	}
    } else {			/* no ${...=...} or anything, but possible modifiers. */
	/*
	 * Handler ${+...}.  TODO: strange, why do we handle this only
	 * if there isn't a trailing modifier?  Why don't we do this
	 * e.g. when we handle the ${(t)...} flag?
	 */
colonsubscript:
	if (chkset) {
	    val = dupstring(vunset ? "0" : "1");
	    isarr = 0;
	} else if (vunset) {
	    if (vunset > 0 && unset(UNSET)) {
		*idend = '\0';
		zerr("%s: parameter not set", idbeg);
		return NULL;
	    }
	    val = dupstring("");
	}
	if (colf && inbrace) {
	    /*
	     * Look for ${PARAM:OFFSET} or ${PARAM:OFFSET:LENGTH}.
	     * This must appear before modifiers.  For compatibility
	     * with bash we perform both standard string substitutions
	     * and math eval.
	     */
	    char *check_offset2;
	    char *check_offset = check_colon_subscript(s, &check_offset2);
	    if (check_offset) {
		zlong offset = mathevali(check_offset);
		zlong length = 0;
		int length_set = 0;
		int offset_hack_argzero = 0;
		if (errflag)
		    return NULL;
		if ((*check_offset2 && *check_offset2 != ':')) {
		    zerr("invalid subscript: %s", check_offset);
		    return NULL;
		}
		if (*check_offset2) {
		    check_offset = check_colon_subscript(check_offset2 + 1,
							 &check_offset2);
		    if (*check_offset2 && *check_offset2 != ':') {
			zerr("invalid length: %s", check_offset);
			return NULL;
		    }
		    if (check_offset) {
			length = mathevali(check_offset);
			length_set = 1;
			if (errflag)
			    return NULL;
		    }
		}
		if (isarr) {
		    int alen, count;
		    char **srcptr, **dstptr, **newarr;

		    if (horrible_offset_hack) {
			/*
			 * As part of the 'orrible hoffset 'ack,
			 * (what hare you? Han 'orrible hoffset 'ack,
			 * sergeant major), if we are given a ksh/bash/POSIX
			 * style positional parameter array which includes
			 * offset 0, we use $0.
			 */
			if (offset == 0) {
			    offset_hack_argzero = 1;
			} else if (offset > 0) {
			    offset--;
			}
		    }

		    alen = arrlen(aval);
		    if (offset < 0) {
			offset += alen;
			if (offset < 0)
			    offset = 0;
		    }
		    if (offset_hack_argzero)
			alen++;
		    if (length_set) {
			if (length < 0)
			    length += alen - offset;
			if (length < 0) {
			    zerr("substring expression: %d < %d",
			         (int)(length + offset), (int)offset);
			    return NULL;
			}
