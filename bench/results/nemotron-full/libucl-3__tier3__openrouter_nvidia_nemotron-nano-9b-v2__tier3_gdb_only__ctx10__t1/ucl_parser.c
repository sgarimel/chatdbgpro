		ucl_object_t *elt)
{
	ucl_object_t *nobj;

	if ((parser->flags & UCL_PARSER_NO_IMPLICIT_ARRAYS) == 0) {
		/* Implicit array */
		top->flags |= UCL_OBJECT_MULTIVALUE;
		DL_APPEND (top, elt);
	}
	else {
		if ((top->flags & UCL_OBJECT_MULTIVALUE) != 0) {
			/* Just add to the explicit array */
			ucl_array_append (top, elt);
		}
		else {
			/* Convert to an array */
			ucl_hash_delete (cont, top);
			nobj = ucl_object_typed_new (UCL_ARRAY);
			nobj->key = top->key;
			nobj->keylen = top->keylen;
			nobj->flags |= UCL_OBJECT_MULTIVALUE;
			ucl_array_append (nobj, top);
			ucl_array_append (nobj, elt);
			ucl_hash_insert (cont, nobj, nobj->key, nobj->keylen);
		}
	}
}

/**
 * Parse a key in an object
 * @param parser
 * @param chunk
 * @return true if a key has been parsed
 */
static bool
ucl_parse_key (struct ucl_parser *parser, struct ucl_chunk *chunk, bool *next_key, bool *end_of_object)
{
	const unsigned char *p, *c = NULL, *end, *t;
	const char *key = NULL;
	bool got_quote = false, got_eq = false, got_semicolon = false,
			need_unescape = false, ucl_escape = false, var_expand = false,
			got_content = false, got_sep = false;
	ucl_object_t *nobj, *tobj;
	ucl_hash_t *container;
	ssize_t keylen;

	p = chunk->pos;

	if (*p == '.') {
		/* It is macro actually */
		ucl_chunk_skipc (chunk, p);
		parser->prev_state = parser->state;
		parser->state = UCL_STATE_MACRO_NAME;
		return true;
	}
	while (p < chunk->end) {
		/*
		 * A key must start with alpha, number, '/' or '_' and end with space character
		 */
		if (c == NULL) {
			if (chunk->remain >= 2 && ucl_lex_is_comment (p[0], p[1])) {
				if (!ucl_skip_comments (parser)) {
					return false;
				}
				p = chunk->pos;
			}
			else if (ucl_test_character (*p, UCL_CHARACTER_WHITESPACE_UNSAFE)) {
				ucl_chunk_skipc (chunk, p);
			}
			else if (ucl_test_character (*p, UCL_CHARACTER_KEY_START)) {
				/* The first symbol */
				c = p;
				ucl_chunk_skipc (chunk, p);
				got_content = true;
			}
			else if (*p == '"') {
				/* JSON style key */
				c = p + 1;
				got_quote = true;
				got_content = true;
				ucl_chunk_skipc (chunk, p);
			}
			else if (*p == '}') {
				/* We have actually end of an object */
				*end_of_object = true;
				return true;
			}
			else if (*p == '.') {
				ucl_chunk_skipc (chunk, p);
				parser->prev_state = parser->state;
				parser->state = UCL_STATE_MACRO_NAME;
				return true;
			}
			else {
				/* Invalid identifier */
				ucl_set_err (parser, UCL_ESYNTAX, "key must begin with a letter",
						&parser->err);
				return false;
			}
		}
		else {
