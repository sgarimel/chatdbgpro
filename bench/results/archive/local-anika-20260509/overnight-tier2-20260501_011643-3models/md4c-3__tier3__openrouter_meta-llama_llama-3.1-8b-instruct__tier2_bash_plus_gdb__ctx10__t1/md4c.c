    }

    return 0;
}

/* Analyze whether the mark '&' starts a HTML entity.
 * If so, update its flags as well as flags of corresponding closer ';'. */
static void
md_analyze_entity(MD_CTX* ctx, int mark_index)
{
    MD_MARK* opener = &ctx->marks[mark_index];
    MD_MARK* closer;
    OFF off;

    /* Cannot be entity if there is no closer as the next mark.
     * (Any other mark between would mean strange character which cannot be
     * part of the entity.
     *
     * So we can do all the work on '&' and do not call this later for the
     * closing mark ';'.
     */
    if(mark_index + 1 >= ctx->n_marks)
        return;
    closer = &ctx->marks[mark_index+1];
    if(closer->ch != ';')
        return;

    if(md_is_entity(ctx, opener->beg, closer->end, &off)) {
        MD_ASSERT(off == closer->end);

        md_resolve_range(ctx, NULL, mark_index, mark_index+1);
        opener->end = closer->end;
    }
}

static void
md_analyze_table_cell_boundary(MD_CTX* ctx, int mark_index)
{
    MD_MARK* mark = &ctx->marks[mark_index];
    mark->flags |= MD_MARK_RESOLVED;

    md_mark_chain_append(ctx, &TABLECELLBOUNDARIES, mark_index);
    ctx->n_table_cell_boundaries++;
}

/* Split a longer mark into two. The new mark takes the given count of
 * characters. May only be called if an adequate number of dummy 'D' marks
 * follows.
 */
static int
md_split_simple_pairing_mark(MD_CTX* ctx, int mark_index, SZ n)
{
    MD_MARK* mark = &ctx->marks[mark_index];
    int new_mark_index = mark_index + (mark->end - mark->beg - 1);
    MD_MARK* dummy = &ctx->marks[new_mark_index];

    MD_ASSERT(mark->end - mark->beg > n);
    MD_ASSERT(dummy->ch == 'D');

    memcpy(dummy, mark, sizeof(MD_MARK));
    mark->end -= n;
    dummy->beg = mark->end;

    return new_mark_index;
}

static void
md_analyze_simple_pairing_mark(MD_CTX* ctx, MD_MARKCHAIN* chain, int mark_index,
                               int apply_rule_of_three)
{
    MD_MARK* mark = &ctx->marks[mark_index];

    /* If we can be a closer, try to resolve with the preceding opener. */
    if((mark->flags & MD_MARK_POTENTIAL_CLOSER)  &&  chain->tail >= 0) {
        int opener_index = chain->tail;
        MD_MARK* opener = &ctx->marks[opener_index];
        SZ opener_size = opener->end - opener->beg;
        SZ closer_size = mark->end - mark->beg;

        /* Apply the "rule of three". */
        if(apply_rule_of_three) {
            while((mark->flags & MD_MARK_EMPH_INTRAWORD) || (opener->flags & MD_MARK_EMPH_INTRAWORD)) {
                SZ opener_orig_size_modulo3;

                switch(opener->flags & MD_MARK_EMPH_MODULO3_MASK) {
                    case MD_MARK_EMPH_MODULO3_0:    opener_orig_size_modulo3 = 0; break;
                    case MD_MARK_EMPH_MODULO3_1:    opener_orig_size_modulo3 = 1; break;
                    case MD_MARK_EMPH_MODULO3_2:    opener_orig_size_modulo3 = 2; break;
                    default:                        MD_UNREACHABLE(); break;
                }

                if((opener_orig_size_modulo3 + closer_size) % 3 != 0) {
                    /* This opener is suitable. */
                    break;
                }

                if(opener->prev >= 0) {
                    /* Try previous opener. */
                    opener_index = opener->prev;
                    opener = &ctx->marks[opener_index];
                    opener_size = opener->end - opener->beg;
