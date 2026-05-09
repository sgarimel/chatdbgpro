	        xmlFree((xmlChar *) atts[i]);
    }

    return(localname);

base_changed:
    /*
     * the attribute strings are valid iif the base didn't changed
     */
    if (attval != 0) {
	for (i = 3,j = 0; j < nratts;i += 5,j++)
	    if ((ctxt->attallocs[j] != 0) && (atts[i] != NULL))
	        xmlFree((xmlChar *) atts[i]);
    }

    /*
     * We can't switch from one entity to another in the middle
     * of a start tag
     */
    if (inputNr != ctxt->inputNr) {
        xmlFatalErrMsg(ctxt, XML_ERR_ENTITY_BOUNDARY,
		    "Start tag doesn't start and stop in the same entity\n");
	return(NULL);
    }

    ctxt->input->cur = ctxt->input->base + cur;
    ctxt->input->line = oldline;
    ctxt->input->col = oldcol;
    if (ctxt->wellFormed == 1) {
	goto reparse;
    }
    return(NULL);
}

/**
 * xmlParseEndTag2:
 * @ctxt:  an XML parser context
 * @line:  line of the start tag
 * @nsNr:  number of namespaces on the start tag
 *
 * parse an end of tag
 *
 * [42] ETag ::= '</' Name S? '>'
 *
 * With namespace
 *
 * [NS 9] ETag ::= '</' QName S? '>'
 */

static void
xmlParseEndTag2(xmlParserCtxtPtr ctxt, const xmlChar *prefix,
                const xmlChar *URI, int line, int nsNr, int tlen) {
    const xmlChar *name;

    GROW;
    if ((RAW != '<') || (NXT(1) != '/')) {
	xmlFatalErr(ctxt, XML_ERR_LTSLASH_REQUIRED, NULL);
	return;
    }
    SKIP(2);

    if ((tlen > 0) && (xmlStrncmp(ctxt->input->cur, ctxt->name, tlen) == 0)) {
             if (ctxt->input->cur[tlen] == '>') {
	    ctxt->input->cur += tlen + 1;
	    ctxt->input->col += tlen + 1;
	    goto done;
	}
	ctxt->input->cur += tlen;
	ctxt->input->col += tlen;
	name = (xmlChar*)1;
    } else {
	if (prefix == NULL)
	    name = xmlParseNameAndCompare(ctxt, ctxt->name);
	else
	    name = xmlParseQNameAndCompare(ctxt, ctxt->name, prefix);
    }

    /*
     * We should definitely be at the ending "S? '>'" part
     */
    GROW;
    if (ctxt->instate == XML_PARSER_EOF)
        return;
    SKIP_BLANKS;
    if ((!IS_BYTE_CHAR(RAW)) || (RAW != '>')) {
	xmlFatalErr(ctxt, XML_ERR_GT_REQUIRED, NULL);
    } else
	NEXT1;

    /*
     * [ WFC: Element Type Match ]
     * The Name in an element's end-tag must match the element type in the
     * start-tag.
     *
     */
    if (name != (xmlChar*)1) {
        if (name == NULL) name = BAD_CAST "unparseable";
        if ((line == 0) && (ctxt->node != NULL))
            line = ctxt->node->line;
        xmlFatalErrMsgStrIntStr(ctxt, XML_ERR_TAG_NAME_MISMATCH,
		     "Opening and ending tag mismatch: %s line %d and %s\n",
