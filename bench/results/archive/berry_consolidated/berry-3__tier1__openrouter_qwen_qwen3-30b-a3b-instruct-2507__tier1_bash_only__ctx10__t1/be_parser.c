        expr(parser, &e2);

        e1 = *e;        /* copy the class description */
        bexpdesc key;   /* build the member key */
        init_exp(&key, ETSTRING, 0);
        key.v.s = name;

        be_code_member(parser->finfo, &e1, &key);   /* compute member accessor */
        be_code_setvar(parser->finfo, &e1, &e2);    /* set member */
    }
}

static void classstatic_stmt(bparser *parser, bclass *c, bexpdesc *e)
{
    bstring *name;
    /* 'static' ID ['=' expr] {',' ID ['=' expr] } */
    scan_next_token(parser); /* skip 'static' */
    if (match_id(parser, name) != NULL) {
        check_class_attr(parser, c, name);
        be_member_bind(parser->vm, c, name, bfalse);
        class_static_assignment_expr(parser, e, name);

        while (match_skip(parser, OptComma)) { /* ',' */
            if (match_id(parser, name) != NULL) {
                check_class_attr(parser, c, name);
                be_member_bind(parser->vm, c, name, bfalse);
                class_static_assignment_expr(parser, e, name);
            } else {
                parser_error(parser, "class static error");
            }
        }
    } else {
        parser_error(parser, "class static error");
    }
}

static void classdef_stmt(bparser *parser, bclass *c)
{
    bexpdesc e;
    bstring *name;
    bproto *proto;
    /* 'def' ID '(' varlist ')' block 'end' */
    scan_next_token(parser); /* skip 'def' */
    name = func_name(parser, &e, 1);
    check_class_attr(parser, c, name);
    proto = funcbody(parser, name, FUNC_METHOD);
    be_method_bind(parser->vm, c, proto->name, proto);
    be_stackpop(parser->vm, 1);
}

static void class_inherit(bparser *parser, bexpdesc *e)
{
    if (next_type(parser) == OptColon) { /* ':' */
        bexpdesc e1;
        scan_next_token(parser); /* skip ':' */
        expr(parser, &e1);
        check_var(parser, &e1);
        be_code_setsuper(parser->finfo, e, &e1);
    }
}

static void class_block(bparser *parser, bclass *c, bexpdesc *e)
{
    /* { [;] } */
    while (block_follow(parser)) {
        switch (next_type(parser)) {
        case KeyVar: classvar_stmt(parser, c); break;
        case KeyStatic: classstatic_stmt(parser, c, e); break;
        case KeyDef: classdef_stmt(parser, c); break;
        case OptSemic: scan_next_token(parser); break;
        default: push_error(parser,
                "unexpected token '%s'", token2str(parser));
        }
    }
}

static void class_stmt(bparser *parser)
{
    bstring *name;
    /* 'class' ID [':' ID] class_block 'end' */
    scan_next_token(parser); /* skip 'class' */
    if (match_id(parser, name) != NULL) {
        bexpdesc e;
        bclass *c = be_newclass(parser->vm, name, NULL);
        new_var(parser, name, &e);
        be_code_class(parser->finfo, &e, c);
        class_inherit(parser, &e);
        class_block(parser, c, &e);
        be_class_compress(parser->vm, c); /* compress class size */
        match_token(parser, KeyEnd); /* skip 'end' */
    } else {
        parser_error(parser, "class name error");
    }
}

static void import_stmt(bparser *parser)
{
    bstring *name; /* variable name */
    bexpdesc m, v;
    /* 'import' (ID (['as' ID] | {',' ID}) | STRING 'as' ID ) */
    scan_next_token(parser); /* skip 'import' */
