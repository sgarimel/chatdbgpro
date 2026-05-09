	static void ucl_emit_ ##type## _end_object (struct ucl_emitter_context *ctx,	\
		const ucl_object_t *obj) {	\
		ucl_emitter_common_end_object (ctx, obj, (compact));	\
	}	\
	static void ucl_emit_ ##type## _end_array (struct ucl_emitter_context *ctx,	\
		const ucl_object_t *obj) {	\
		ucl_emitter_common_end_array (ctx, obj, (compact));	\
	}

UCL_EMIT_TYPE_IMPL(json, false)
UCL_EMIT_TYPE_IMPL(json_compact, true)
UCL_EMIT_TYPE_IMPL(config, false)
UCL_EMIT_TYPE_IMPL(yaml, false)

static void
ucl_emit_msgpack_elt (struct ucl_emitter_context *ctx,
		const ucl_object_t *obj, bool first, bool print_key)
{
	ucl_object_iter_t it;
	struct ucl_object_userdata *ud;
	const char *ud_out;
	const ucl_object_t *cur, *celt;

	switch (obj->type) {
	case UCL_INT:
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);
		ucl_emitter_print_int_msgpack (ctx, ucl_object_toint (obj));
		break;

	case UCL_FLOAT:
	case UCL_TIME:
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);
		ucl_emitter_print_double_msgpack (ctx, ucl_object_todouble (obj));
		break;

	case UCL_BOOLEAN:
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);
		ucl_emitter_print_bool_msgpack (ctx, ucl_object_toboolean (obj));
		break;

	case UCL_STRING:
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);
		ucl_emitter_print_string_msgpack (ctx, obj->value.sv, obj->len);
		break;

	case UCL_NULL:
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);
		ucl_emitter_print_null_msgpack (ctx);
		break;

	case UCL_OBJECT:
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);
		ucl_emit_msgpack_start_obj (ctx, obj, print_key);
		it = ucl_object_iterate_new (obj);

		while ((cur = ucl_object_iterate_safe (it, true)) != NULL) {
			LL_FOREACH (cur, celt) {
				ucl_emit_msgpack_elt (ctx, celt, false, true);
				/* XXX:
				 * in msgpack the length of objects is encoded within a single elt
				 * so in case of multi-value keys we are using merely the first
				 * element ignoring others
				 */
			}
		}

		ucl_object_iterate_free (it);
		break;

	case UCL_ARRAY:
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);
		ucl_emit_msgpack_start_array (ctx, obj, print_key);
		it = ucl_object_iterate_new (obj);

		while ((cur = ucl_object_iterate_safe (it, true)) != NULL) {
			ucl_emit_msgpack_elt (ctx, cur, false, false);
		}

		ucl_object_iterate_free (it);
		break;

	case UCL_USERDATA:
		ud = (struct ucl_object_userdata *)obj;
		ucl_emitter_print_key_msgpack (print_key, ctx, obj);

		if (ud->emitter) {
			ud_out = ud->emitter (obj->value.ud);
			if (ud_out == NULL) {
				ud_out = "null";
			}
		}
		ucl_emitter_print_string_msgpack (ctx, obj->value.sv, obj->len);
		break;
	}
}

static void
ucl_emit_msgpack_start_obj (struct ucl_emitter_context *ctx,
		const ucl_object_t *obj, bool print_key)
{
	ucl_emitter_print_object_msgpack (ctx, obj->len);
