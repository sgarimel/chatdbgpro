  }

  if (!STRING_IS_ANONYMOUS(*string))
  {
    result = yr_hash_table_add(
      compiler->strings_table,
      identifier,
      NULL,
      *string);

    if (result != ERROR_SUCCESS)
      goto _exit;
  }

  if (min_atom_quality < compiler->atoms_config.quality_warning_threshold)
  {
    yywarning(
        yyscanner,
        "%s is slowing down scanning",
        (*string)->identifier);
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
    YR_RULE** rule)
{
  YR_FIXUP *fixup;
  YR_INIT_RULE_ARGS *init_rule_args;
  YR_COMPILER* compiler = yyget_extra(yyscanner);

  *rule = NULL;

  if (yr_hash_table_lookup(
        compiler->rules_table,
        identifier,
        compiler->current_namespace->name) != NULL ||
      yr_hash_table_lookup(
        compiler->objects_table,
        identifier,
        compiler->current_namespace->name) != NULL)
  {
    // A rule or variable with the same identifier already exists, return the
    // appropriate error.

    yr_compiler_set_error_extra_info(compiler, identifier);
    return ERROR_DUPLICATED_IDENTIFIER;
  }

  FAIL_ON_ERROR(yr_arena_allocate_struct(
      compiler->rules_arena,
      sizeof(YR_RULE),
      (void**) rule,
      offsetof(YR_RULE, identifier),
      offsetof(YR_RULE, tags),
      offsetof(YR_RULE, strings),
      offsetof(YR_RULE, metas),
      offsetof(YR_RULE, ns),
      EOL))

  (*rule)->g_flags = flags;
  (*rule)->ns = compiler->current_namespace;

  #ifdef PROFILING_ENABLED
  rule->time_cost = 0;
  #endif

  FAIL_ON_ERROR(yr_arena_write_string(
      compiler->sz_arena,
      identifier,
      (char**) &(*rule)->identifier));

  FAIL_ON_ERROR(yr_parser_emit(
      yyscanner,
      OP_INIT_RULE,
      NULL));

  FAIL_ON_ERROR(yr_arena_allocate_struct(
      compiler->code_arena,
      sizeof(YR_INIT_RULE_ARGS),
      (void**) &init_rule_args,
      offsetof(YR_INIT_RULE_ARGS, rule),
      offsetof(YR_INIT_RULE_ARGS, jmp_addr),
      EOL));

  init_rule_args->rule = *rule;

  // jmp_addr holds the address to jump to when we want to skip the code for
