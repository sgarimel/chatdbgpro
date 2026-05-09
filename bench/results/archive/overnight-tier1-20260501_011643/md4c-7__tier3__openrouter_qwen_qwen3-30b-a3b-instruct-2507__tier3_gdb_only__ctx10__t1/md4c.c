
static void
md_analyze_emph(MD_CTX* ctx, int mark_index)
{
    MD_MARK* mark = &ctx->marks[mark_index];
    MD_MARKCHAIN* chain = md_mark_chain(ctx, mark_index);

    /* If we can be a closer, try to resolve with the preceding opener. */
    if(mark->flags & MD_MARK_POTENTIAL_CLOSER) {
        MD_MARK* opener = NULL;
        int opener_index;

        if(mark->ch == _T('*')) {
            MD_MARKCHAIN* opener_chains[6];
            int i, n_opener_chains;
            unsigned flags = mark->flags;

            /* Apply the "rule of three". */
            n_opener_chains = 0;
            opener_chains[n_opener_chains++] = &ASTERISK_OPENERS_intraword_mod3_0;
            if((flags & MD_MARK_EMPH_MOD3_MASK) != MD_MARK_EMPH_MOD3_2)
                opener_chains[n_opener_chains++] = &ASTERISK_OPENERS_intraword_mod3_1;
            if((flags & MD_MARK_EMPH_MOD3_MASK) != MD_MARK_EMPH_MOD3_1)
                opener_chains[n_opener_chains++] = &ASTERISK_OPENERS_intraword_mod3_2;
            opener_chains[n_opener_chains++] = &ASTERISK_OPENERS_extraword_mod3_0;
            if(!(flags & MD_MARK_EMPH_INTRAWORD)  ||  (flags & MD_MARK_EMPH_MOD3_MASK) != MD_MARK_EMPH_MOD3_2)
                opener_chains[n_opener_chains++] = &ASTERISK_OPENERS_extraword_mod3_1;
            if(!(flags & MD_MARK_EMPH_INTRAWORD)  ||  (flags & MD_MARK_EMPH_MOD3_MASK) != MD_MARK_EMPH_MOD3_1)
                opener_chains[n_opener_chains++] = &ASTERISK_OPENERS_extraword_mod3_2;

            /* Opener is the most recent mark from the allowed chains. */
            for(i = 0; i < n_opener_chains; i++) {
                if(opener_chains[i]->tail >= 0) {
                    int tmp_index = opener_chains[i]->tail;
                    MD_MARK* tmp_mark = &ctx->marks[tmp_index];
                    if(opener == NULL  ||  tmp_mark->end > opener->end) {
                        opener_index = tmp_index;
                        opener = tmp_mark;
                    }
                }
            }
        } else {
            /* Simple emph. mark */
            if(chain->tail >= 0) {
                opener_index = chain->tail;
                opener = &ctx->marks[opener_index];
            }
        }

        /* Resolve, if we have found matching opener. */
        if(opener != NULL) {
            SZ opener_size = opener->end - opener->beg;
            SZ closer_size = mark->end - mark->beg;
            MD_MARKCHAIN* opener_chain = md_mark_chain(ctx, mark_index);

            if(opener_size > closer_size) {
                opener_index = md_split_emph_mark(ctx, opener_index, closer_size);
                md_mark_chain_append(ctx, opener_chain, opener_index);
            } else if(opener_size < closer_size) {
                md_split_emph_mark(ctx, mark_index, closer_size - opener_size);
            }

            md_rollback(ctx, opener_index, mark_index, MD_ROLLBACK_CROSSING);
            md_resolve_range(ctx, opener_chain, opener_index, mark_index);
            return;
        }
    }

    /* If we could not resolve as closer, we may be yet be an opener. */
    if(mark->flags & MD_MARK_POTENTIAL_OPENER)
        md_mark_chain_append(ctx, chain, mark_index);
}

static void
md_analyze_tilde(MD_CTX* ctx, int mark_index)
{
    MD_MARK* mark = &ctx->marks[mark_index];
    MD_MARKCHAIN* chain = md_mark_chain(ctx, mark_index);

    /* We attempt to be Github Flavored Markdown compatible here. GFM accepts
     * only tildes sequences of length 1 and 2, and the length of the opener
     * and closer has to match. */

    if((mark->flags & MD_MARK_POTENTIAL_CLOSER)  &&  chain->head >= 0) {
        int opener_index = chain->head;

        md_rollback(ctx, opener_index, mark_index, MD_ROLLBACK_CROSSING);
        md_resolve_range(ctx, chain, opener_index, mark_index);
        return;
    }

    if(mark->flags & MD_MARK_POTENTIAL_OPENER)
        md_mark_chain_append(ctx, chain, mark_index);
}

static void
md_analyze_dollar(MD_CTX* ctx, int mark_index)
{
    /* This should mimic the way inline equations work in LaTeX, so there
     * can only ever be one item in the chain (i.e. the dollars can't be
     * nested). This is basically the same as the md_analyze_tilde function,
