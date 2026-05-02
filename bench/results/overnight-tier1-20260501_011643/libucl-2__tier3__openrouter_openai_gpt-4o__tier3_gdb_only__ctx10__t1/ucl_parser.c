	int obraces = 1, ebraces = 0, state = 0;
	const unsigned char *p, *c;
	size_t args_len = 0;
	struct ucl_parser_saved_state saved;

	saved.column = chunk->column;
	saved.line = chunk->line;
	saved.pos = chunk->pos;
	saved.remain = chunk->remain;
	p = chunk->pos;

	if (*p != '(' || chunk->remain < 2) {
		return NULL;
	}

	/* Set begin and start */
	ucl_chunk_skipc (chunk, p);
	c = p;

	while ((p) < (chunk)->end) {
		switch (state) {
		case 0:
			/* Parse symbols and check for '(', ')' and '"' */
			if (*p == '(') {
				obraces ++;
			}
			else if (*p == ')') {
				ebraces ++;
			}
			else if (*p == '"') {
				state = 1;
			}
			/* Check pairing */
			if (obraces == ebraces) {
				state = 99;
			}
			else {
				args_len ++;
			}
			/* Check overflow */
			if (chunk->remain == 0) {
				goto restore_chunk;
			}
			ucl_chunk_skipc (chunk, p);
			break;
		case 1:
			/* We have quote character, so skip all but quotes */
			if (*p == '"' && *(p - 1) != '\\') {
				state = 0;
			}
			if (chunk->remain == 0) {
				goto restore_chunk;
			}
			ucl_chunk_skipc (chunk, p);
			break;
		case 99:
			/*
			 * We have read the full body of arguments, so we need to parse and set
			 * object from that
			 */
			params_parser = ucl_parser_new (parser->flags);
			if (!ucl_parser_add_chunk (params_parser, c, args_len)) {
				ucl_set_err (parser, UCL_ESYNTAX, "macro arguments parsing error",
						&parser->err);
			}
			else {
				res = ucl_parser_get_object (params_parser);
			}
			ucl_parser_free (params_parser);

			return res;

			break;
		}
	}

	return res;

restore_chunk:
	chunk->column = saved.column;
	chunk->line = saved.line;
	chunk->pos = saved.pos;
	chunk->remain = saved.remain;

	return NULL;
}

#define SKIP_SPACES_COMMENTS(parser, chunk, p) do {								\
	while ((p) < (chunk)->end) {												\
		if (!ucl_test_character (*(p), UCL_CHARACTER_WHITESPACE_UNSAFE)) {		\
			if ((chunk)->remain >= 2 && ucl_lex_is_comment ((p)[0], (p)[1])) {	\
				if (!ucl_skip_comments (parser)) {								\
					return false;												\
				}																\
				p = (chunk)->pos;												\
			}																	\
			break;																\
		}																		\
		ucl_chunk_skipc (chunk, p);												\
	}																			\
} while(0)
