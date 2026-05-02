	return true;
}

/**
 * Handle the main states of rcl parser
 * @param parser parser structure
 * @param data the pointer to the beginning of a chunk
 * @param len the length of a chunk
 * @return true if chunk has been parsed and false in case of error
 */
static bool
ucl_state_machine (struct ucl_parser *parser)
{
	ucl_object_t *obj;
	struct ucl_chunk *chunk = parser->chunks;
	const unsigned char *p, *c = NULL, *macro_start = NULL;
	unsigned char *macro_escaped;
	size_t macro_len = 0;
	struct ucl_macro *macro = NULL;
	bool next_key = false, end_of_object = false;

	if (parser->top_obj == NULL) {
		if (*chunk->pos == '[') {
			obj = ucl_add_parser_stack (NULL, parser, true, 0);
		}
		else {
			obj = ucl_add_parser_stack (NULL, parser, false, 0);
		}
		if (obj == NULL) {
			return false;
		}
		parser->top_obj = obj;
		parser->cur_obj = obj;
		parser->state = UCL_STATE_INIT;
	}

	p = chunk->pos;
	while (chunk->pos < chunk->end) {
		switch (parser->state) {
		case UCL_STATE_INIT:
			/*
			 * At the init state we can either go to the parse array or object
			 * if we got [ or { correspondingly or can just treat new data as
			 * a key of newly created object
			 */
			obj = parser->cur_obj;
			if (!ucl_skip_comments (parser)) {
				parser->prev_state = parser->state;
				parser->state = UCL_STATE_ERROR;
				return false;
			}
			else {
				/* Skip any spaces */
				p = chunk->pos;
				if (*p == '[') {
					parser->state = UCL_STATE_VALUE;
					ucl_chunk_skipc (chunk, p);
				}
				else {
					parser->state = UCL_STATE_KEY;
					if (*p == '{') {
						ucl_chunk_skipc (chunk, p);
					}
				}
			}
			break;
		case UCL_STATE_KEY:
			/* Skip any spaces */
			while (p < chunk->end && ucl_test_character (*p, UCL_CHARACTER_WHITESPACE_UNSAFE)) {
				ucl_chunk_skipc (chunk, p);
			}
			if (*p == '}') {
				/* We have the end of an object */
				parser->state = UCL_STATE_AFTER_VALUE;
				continue;
			}
			if (parser->stack == NULL) {
				/* No objects are on stack, but we want to parse a key */
				ucl_set_err (chunk, UCL_ESYNTAX, "top object is finished but the parser "
						"expects a key", &parser->err);
				parser->prev_state = parser->state;
				parser->state = UCL_STATE_ERROR;
				return false;
			}
			if (!ucl_parse_key (parser, chunk, &next_key, &end_of_object)) {
				parser->prev_state = parser->state;
				parser->state = UCL_STATE_ERROR;
				return false;
			}
			if (end_of_object) {
				p = chunk->pos;
				parser->state = UCL_STATE_AFTER_VALUE;
				continue;
			}
			else if (parser->state != UCL_STATE_MACRO_NAME) {
				if (next_key && parser->stack->obj->type == UCL_OBJECT) {
					/* Parse more keys and nest objects accordingly */
					obj = ucl_add_parser_stack (parser->cur_obj, parser, false,
							parser->stack->level + 1);
					if (obj == NULL) {
						return false;
