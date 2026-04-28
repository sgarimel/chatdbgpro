        // there will be no more strings because there are no more AST to split,
        // which means that this is the chain's tail.
        if (remainder_re_ast == NULL)
          new_string->flags |= STRING_FLAGS_CHAIN_PART |
                               STRING_FLAGS_CHAIN_TAIL;
      }

      yr_re_ast_destroy(re_ast);
      re_ast = remainder_re_ast;
    }
  }
  else  // not a STRING_FLAGS_HEXADECIMAL or STRING_FLAGS_REGEXP or
        // STRING_FLAGS_BASE64 or STRING_FLAGS_BASE64_WIDE
  {
    result = _yr_parser_write_string(
        identifier,
        modifier,
        compiler,
        str,
        NULL,
        string_ref,
        &min_atom_quality,
        &current_rule->num_atoms);

    if (result != ERROR_SUCCESS)
      goto _exit;
  }

  if (min_atom_quality < compiler->atoms_config.quality_warning_threshold)
  {
    yywarning(yyscanner, "%s is slowing down scanning", identifier);
  }

_exit:

  if (re_ast != NULL)
    yr_re_ast_destroy(re_ast);

  if (remainder_re_ast != NULL)
    yr_re_ast_destroy(remainder_re_ast);

  return result;
}


int yr_parser_reduce_rule_declaration_phase_1(
    yyscan_t yyscanner,
    int32_t flags,
    const char* identifier,
    YR_ARENA_REF* rule_ref)
{
  YR_FIXUP *fixup;
  YR_COMPILER* compiler = yyget_extra(yyscanner);
  compiler->current_rule_idx = compiler->next_rule_idx;
  compiler->next_rule_idx++;

  YR_NAMESPACE* ns = (YR_NAMESPACE*) yr_arena_get_ptr(
      compiler->arena,
      YR_NAMESPACES_TABLE,
      compiler->current_namespace_idx * sizeof(struct YR_NAMESPACE));

  if (yr_hash_table_lookup_uint32(
          compiler->rules_table,
          identifier,
          ns->name) != UINT32_MAX ||
      yr_hash_table_lookup(
          compiler->objects_table,
          identifier,
          NULL) != NULL)
  {
    // A rule or variable with the same identifier already exists, return the
    // appropriate error.

    yr_compiler_set_error_extra_info(compiler, identifier)
    return ERROR_DUPLICATED_IDENTIFIER;
  }

  FAIL_ON_ERROR(yr_arena_allocate_struct(
      compiler->arena,
      YR_RULES_TABLE,
      sizeof(YR_RULE),
      rule_ref,
      offsetof(YR_RULE, identifier),
      offsetof(YR_RULE, tags),
      offsetof(YR_RULE, strings),
      offsetof(YR_RULE, metas),
      offsetof(YR_RULE, ns),
      EOL));

  YR_RULE* rule = (YR_RULE*) yr_arena_ref_to_ptr(compiler->arena, rule_ref);

  YR_ARENA_REF ref;

  FAIL_ON_ERROR(yr_arena_write_string(
      compiler->arena,
      YR_SZ_POOL,
      identifier,
      &ref));

  rule->identifier = (const char*) yr_arena_ref_to_ptr(compiler->arena, &ref);
  rule->flags = flags;
