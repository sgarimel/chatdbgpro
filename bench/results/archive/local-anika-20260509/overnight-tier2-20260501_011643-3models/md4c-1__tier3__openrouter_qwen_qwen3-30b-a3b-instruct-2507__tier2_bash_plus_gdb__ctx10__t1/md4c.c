        (pivot_line->type == MD_LINE_BLANK || pivot_line->type == MD_LINE_INDENTEDCODE))
    {
        line->type = MD_LINE_INDENTEDCODE;
        MD_ASSERT(line->indent >= ctx->code_indent_offset);
        line->indent -= ctx->code_indent_offset;
        line->data = 0;
        goto done;
    }

    /* Check for start of a new container block. */
    if(line->indent < ctx->code_indent_offset  &&
       md_is_container_mark(ctx, line->indent, off, &off, &container))
    {
        if(pivot_line->type == MD_LINE_TEXT  &&  n_parents == ctx->n_containers  &&
                    (off >= ctx->size || ISNEWLINE(off)))
        {
            /* Noop. List mark followed by a blank line cannot interrupt a paragraph. */
        } else if(pivot_line->type == MD_LINE_TEXT  &&  n_parents == ctx->n_containers  &&
                    (container.ch == _T('.') || container.ch == _T(')'))  &&  container.start != 1)
        {
            /* Noop. Ordered list cannot interrupt a paragraph unless the start index is 1. */
        } else {
            total_indent += container.contents_indent - container.mark_indent;
            line->indent = md_line_indentation(ctx, total_indent, off, &off);
            total_indent += line->indent;

            line->beg = off;
            line->data = container.ch;

            /* Some of the following whitespace actually still belongs to the mark. */
            if(off >= ctx->size || ISNEWLINE(off)) {
                container.contents_indent++;
            } else if(line->indent <= ctx->code_indent_offset) {
                container.contents_indent += line->indent;
                line->indent = 0;
            } else {
                container.contents_indent += 1;
                line->indent--;
            }

            if(n_brothers + n_children == 0)
                pivot_line = &md_dummy_blank_line;

            if(n_children == 0)
                MD_CHECK(md_leave_child_containers(ctx, n_parents + n_brothers));

            n_children++;
            MD_CHECK(md_push_container(ctx, &container));
            goto redo;
        }
    }

    /* Check whether we are table continuation. */
    if(pivot_line->type == MD_LINE_TABLE  &&  md_is_table_row(ctx, off, &off))
    {
        line->type = MD_LINE_TABLE;
        goto done;
    }

    /* Check for ATX header. */
    if(line->indent < ctx->code_indent_offset  &&  CH(off) == _T('#')) {
        unsigned level;

        if(md_is_atxheader_line(ctx, off, &line->beg, &off, &level)) {
            line->type = MD_LINE_ATXHEADER;
            line->data = level;
            goto done;
        }
    }

    /* Check whether we are starting code fence. */
    if(CH(off) == _T('`') || CH(off) == _T('~')) {
        if(md_is_opening_code_fence(ctx, off, &off)) {
            line->type = MD_LINE_FENCEDCODE;
            line->data = 1;
            goto done;
        }
    }

    /* Check for start of raw HTML block. */
    if(CH(off) == _T('<')  &&  !(ctx->r.flags & MD_FLAG_NOHTMLBLOCKS))
    {
        ctx->html_block_type = md_is_html_block_start_condition(ctx, off);

        /* HTML block type 7 cannot interrupt paragraph. */
        if(ctx->html_block_type == 7  &&  pivot_line->type == MD_LINE_TEXT)
            ctx->html_block_type = 0;

        if(ctx->html_block_type > 0) {
            /* The line itself also may immediately close the block. */
            if(md_is_html_block_end_condition(ctx, off, &off) == ctx->html_block_type) {
                /* Make sure this is the last line of the block. */
                ctx->html_block_type = 0;
            }

            line->type = MD_LINE_HTML;
            goto done;
        }
    }

    /* Check for table underline. */
