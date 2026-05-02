            if(is_link) {
                if(delim != NULL) {
                    if(delim->end < closer->beg) {
                        opener->end = delim->beg;
                    } else {
                        /* The pipe is just before the closer: [[foo|]] */
                        closer->beg = delim->beg;
                        delim = NULL;
                    }
                }

                opener->beg = next_opener->beg;
                opener->next = closer_index;
                opener->flags |= MD_MARK_OPENER | MD_MARK_RESOLVED;

                closer->end = next_closer->end;
                closer->prev = opener_index;
                closer->flags |= MD_MARK_CLOSER | MD_MARK_RESOLVED;

                last_link_beg = opener->beg;
                last_link_end = closer->end;

                if(delim != NULL) {
                    delim->flags |= MD_MARK_RESOLVED;
                    md_rollback(ctx, opener_index, delim_index, MD_ROLLBACK_ALL);
                    md_analyze_link_contents(ctx, lines, n_lines, opener_index+1, closer_index);
                } else {
                    md_rollback(ctx, opener_index, closer_index, MD_ROLLBACK_ALL);
                }

                opener_index = next_opener->prev;
                continue;
            }
        }

        if(next_opener != NULL  &&  next_opener->beg == closer->end) {
            if(next_closer->beg > closer->end + 1) {
                /* Might be full reference link. */
                is_link = md_is_link_reference(ctx, lines, n_lines, next_opener->beg, next_closer->end, &attr);
            } else {
                /* Might be shortcut reference link. */
                is_link = md_is_link_reference(ctx, lines, n_lines, opener->beg, closer->end, &attr);
            }

            if(is_link < 0)
                return -1;

            if(is_link) {
                /* Eat the 2nd "[...]". */
                closer->end = next_closer->end;

                /* Do not analyze the label as a standalone link in the next
                 * iteration. */
            }
        } else {
            if(closer->end < ctx->size  &&  CH(closer->end) == _T('(')) {
                /* Might be inline link. */
                OFF inline_link_end = UINT_MAX;

                is_link = md_is_inline_link_spec(ctx, lines, n_lines, closer->end, &inline_link_end, &attr);
                if(is_link < 0)
                    return -1;

                /* Check the closing ')' is not inside an already resolved range
                 * (i.e. a range with a higher priority), e.g. a code span. */
                if(is_link) {
                    int i = closer_index + 1;

                    while(i < ctx->n_marks) {
                        MD_MARK* mark = &ctx->marks[i];

                        if(mark->beg >= inline_link_end)
                            break;
                        if((mark->flags & (MD_MARK_OPENER | MD_MARK_RESOLVED)) == (MD_MARK_OPENER | MD_MARK_RESOLVED)) {
                            if(ctx->marks[mark->next].beg >= inline_link_end) {
                                /* Cancel the link status. */
                                if(attr.title_needs_free)
                                    free(attr.title);
                                is_link = FALSE;
                                break;
                            }

                            i = mark->next + 1;
                        } else {
                            i++;
                        }
                    }
                }

                if(is_link) {
                    /* Eat the "(...)" */
                    closer->end = inline_link_end;
                }
            }

            if(!is_link) {
                /* Might be collapsed reference link. */
                is_link = md_is_link_reference(ctx, lines, n_lines, opener->beg, closer->end, &attr);
                if(is_link < 0)
                    return -1;
            }
