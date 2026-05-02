		    snprintf((char *)out, sizeof(out), "#x%X", value);
		else
		    snprintf((char *)out, sizeof(out), "#%d", value);
		if ((ctxt->sax != NULL) && (ctxt->sax->reference != NULL) &&
		    (!ctxt->disableSAX))
		    ctxt->sax->reference(ctxt->userData, out);
	    }
	} else {
	    /*
	     * Just encode the value in UTF-8
	     */
	    COPY_BUF(0 ,out, i, value);
	    out[i] = 0;
	    if ((ctxt->sax != NULL) && (ctxt->sax->characters != NULL) &&
		(!ctxt->disableSAX))
		ctxt->sax->characters(ctxt->userData, out, i);
	}
	return;
    }

    /*
     * We are seeing an entity reference
     */
    ent = xmlParseEntityRef(ctxt);
    if (ent == NULL) return;
    if (!ctxt->wellFormed)
	return;
    was_checked = ent->checked;

    /* special case of predefined entities */
    if ((ent->name == NULL) ||
        (ent->etype == XML_INTERNAL_PREDEFINED_ENTITY)) {
	val = ent->content;
	if (val == NULL) return;
	/*
	 * inline the entity.
	 */
	if ((ctxt->sax != NULL) && (ctxt->sax->characters != NULL) &&
	    (!ctxt->disableSAX))
	    ctxt->sax->characters(ctxt->userData, val, xmlStrlen(val));
	return;
    }

    /*
     * The first reference to the entity trigger a parsing phase
     * where the ent->children is filled with the result from
     * the parsing.
     * Note: external parsed entities will not be loaded, it is not
     * required for a non-validating parser, unless the parsing option
     * of validating, or substituting entities were given. Doing so is
     * far more secure as the parser will only process data coming from
     * the document entity by default.
     */
    if (ent->checked == 0) {
	unsigned long oldnbent = ctxt->nbentities;

	/*
	 * This is a bit hackish but this seems the best
	 * way to make sure both SAX and DOM entity support
	 * behaves okay.
	 */
	void *user_data;
	if (ctxt->userData == ctxt)
	    user_data = NULL;
	else
	    user_data = ctxt->userData;

	/*
	 * Check that this entity is well formed
	 * 4.3.2: An internal general parsed entity is well-formed
	 * if its replacement text matches the production labeled
	 * content.
	 */
	if (ent->etype == XML_INTERNAL_GENERAL_ENTITY) {
	    ctxt->depth++;
	    ret = xmlParseBalancedChunkMemoryInternal(ctxt, ent->content,
	                                              user_data, &list);
	    ctxt->depth--;

	} else if (ent->etype == XML_EXTERNAL_GENERAL_PARSED_ENTITY) {
	    ctxt->depth++;
	    ret = xmlParseExternalEntityPrivate(ctxt->myDoc, ctxt, ctxt->sax,
	                                   user_data, ctxt->depth, ent->URI,
					   ent->ExternalID, &list);
	    ctxt->depth--;
	} else {
	    ret = XML_ERR_ENTITY_PE_INTERNAL;
	    xmlErrMsgStr(ctxt, XML_ERR_INTERNAL_ERROR,
			 "invalid entity type found\n", NULL);
	}

	/*
	 * Store the number of entities needing parsing for this entity
	 * content and do checkings
	 */
	ent->checked = ctxt->nbentities - oldnbent;
	if (ret == XML_ERR_ENTITY_LOOP) {
	    xmlFatalErr(ctxt, XML_ERR_ENTITY_LOOP, NULL);
	    xmlFreeNodeList(list);
	    return;
	}
