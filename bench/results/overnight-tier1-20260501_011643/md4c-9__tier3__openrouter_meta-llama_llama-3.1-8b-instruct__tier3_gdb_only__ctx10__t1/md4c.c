        /* Check for "brother" container. I.e. whether we are another list item
         * in already started list. */
        if(n_parents < ctx->n_containers  &&  n_brothers + n_children == 0) {
            OFF tmp;

            if(md_is_container_mark(ctx, line->indent, off, &tmp, &container)  &&
               md_is_container_compatible(&ctx->containers[n_parents], &container))
            {
                pivot_line = &md_dummy_blank_line;

                off = tmp;

                total_indent += container.contents_indent - container.mark_indent;
                line->indent = md_line_indentation(ctx, total_indent, off, &off);
                total_indent += line->indent;
                line->beg = off;

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

                ctx->containers[n_parents].mark_indent = container.mark_indent;
                ctx->containers[n_parents].contents_indent = container.contents_indent;

                n_brothers++;
                continue;
            }
        }

        /* Check for indented code.
         * Note indented code block cannot interrupt a paragraph. */
        if(line->indent >= ctx->code_indent_offset  &&
            (pivot_line->type == MD_LINE_BLANK || pivot_line->type == MD_LINE_INDENTEDCODE))
        {
            line->type = MD_LINE_INDENTEDCODE;
            MD_ASSERT(line->indent >= ctx->code_indent_offset);
            line->indent -= ctx->code_indent_offset;
            line->data = 0;
            break;
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
                continue;
            }
        }

        /* Check whether we are table continuation. */
        if(pivot_line->type == MD_LINE_TABLE  &&  md_is_table_row(ctx, off, &off)  &&
           n_parents == ctx->n_containers)
        {
            line->type = MD_LINE_TABLE;
            break;
        }

        /* Check for ATX header. */
        if(line->indent < ctx->code_indent_offset  &&  CH(off) == _T('#')) {
