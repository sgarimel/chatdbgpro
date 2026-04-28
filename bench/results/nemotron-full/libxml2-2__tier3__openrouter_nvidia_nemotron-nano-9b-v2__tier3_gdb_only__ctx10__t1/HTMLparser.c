
static const xmlChar *
htmlParseHTMLName_nonInvasive(htmlParserCtxtPtr ctxt) {
    int i = 0;
    xmlChar loc[HTML_PARSER_BUFFER_SIZE];

    if (!IS_ASCII_LETTER(NXT(1)) && (NXT(1) != '_') &&
        (NXT(1) != ':')) return(NULL);

    while ((i < HTML_PARSER_BUFFER_SIZE) &&
           ((IS_ASCII_LETTER(NXT(1+i))) || (IS_ASCII_DIGIT(NXT(1+i))) ||
	   (NXT(1+i) == ':') || (NXT(1+i) == '-') || (NXT(1+i) == '_'))) {
	if ((NXT(1+i) >= 'A') && (NXT(1+i) <= 'Z')) loc[i] = NXT(1+i) + 0x20;
        else loc[i] = NXT(1+i);
	i++;
    }

    return(xmlDictLookup(ctxt->dict, loc, i));
}


/**
 * htmlParseName:
 * @ctxt:  an HTML parser context
 *
 * parse an HTML name, this routine is case sensitive.
 *
 * Returns the Name parsed or NULL
 */

static const xmlChar *
htmlParseName(htmlParserCtxtPtr ctxt) {
    const xmlChar *in;
    const xmlChar *ret;
    int count = 0;

    GROW;

    /*
     * Accelerator for simple ASCII names
     */
    in = ctxt->input->cur;
    if (((*in >= 0x61) && (*in <= 0x7A)) ||
	((*in >= 0x41) && (*in <= 0x5A)) ||
	(*in == '_') || (*in == ':')) {
	in++;
	while (((*in >= 0x61) && (*in <= 0x7A)) ||
	       ((*in >= 0x41) && (*in <= 0x5A)) ||
	       ((*in >= 0x30) && (*in <= 0x39)) ||
	       (*in == '_') || (*in == '-') ||
	       (*in == ':') || (*in == '.'))
	    in++;


	if ((*in > 0) && (*in < 0x80)) {
	    count = in - ctxt->input->cur;
	    ret = xmlDictLookup(ctxt->dict, ctxt->input->cur, count);
	    ctxt->input->cur = in;
	    ctxt->nbChars += count;
	    ctxt->input->col += count;
	    return(ret);
	}
    }
    return(htmlParseNameComplex(ctxt));
}

static const xmlChar *
htmlParseNameComplex(xmlParserCtxtPtr ctxt) {
    int len = 0, l;
    int c;
    int count = 0;

    /*
     * Handler for more complex cases
     */
    GROW;
    c = CUR_CHAR(l);
    if ((c == ' ') || (c == '>') || (c == '/') || /* accelerators */
	(!IS_LETTER(c) && (c != '_') &&
         (c != ':'))) {
	return(NULL);
    }

    while ((c != ' ') && (c != '>') && (c != '/') && /* test bigname.xml */
	   ((IS_LETTER(c)) || (IS_DIGIT(c)) ||
            (c == '.') || (c == '-') ||
	    (c == '_') || (c == ':') ||
	    (IS_COMBINING(c)) ||
	    (IS_EXTENDER(c)))) {
	if (count++ > 100) {
	    count = 0;
	    GROW;
	}
	len += l;
	NEXTL(l);
	c = CUR_CHAR(l);
    }


    return(xmlDictLookup(ctxt->dict, ctxt->input->cur - len, len));
}
