        case MD_LINE_TABLEUNDERLINE:
        default:
            MD_UNREACHABLE();
            break;
    }

    block->flags = 0;
    block->data = line->data;
    block->n_lines = 0;

    ctx->current_block = block;
    return 0;
}

/* Eat from start of current (textual) block any reference definitions and
 * remember them so we can resolve any links referring to them.
 *
 * (Reference definitions can only be at start of it as they cannot break
 * a paragraph.)
 */
static int
md_consume_link_reference_definitions(MD_CTX* ctx)
{
    MD_LINE* lines = (MD_LINE*) (ctx->current_block + 1);
    int n_lines = ctx->current_block->n_lines;
    int n = 0;

    /* Compute how many lines at the start of the block form one or more
     * reference definitions. */
    while(n < n_lines) {
        int n_link_ref_lines;

        n_link_ref_lines = md_is_link_reference_definition(ctx,
                                    lines + n, n_lines - n);
        /* Not a reference definition? */
        if(n_link_ref_lines == 0)
            break;

        /* We fail if it is the ref. def. but it could not be stored due
         * a memory allocation error. */
        if(n_link_ref_lines < 0)
            return -1;

        n += n_link_ref_lines;
    }

    /* If there was at least one reference definition, we need to remove
     * its lines from the block, or perhaps even the whole block. */
    if(n > 0) {
        if(n == n_lines) {
            /* Remove complete block. */
            ctx->n_block_bytes -= n * sizeof(MD_LINE);
            ctx->n_block_bytes -= sizeof(MD_BLOCK);
        } else {
            /* Remove just some initial lines from the block. */
            memmove(lines, lines + n, (n_lines - n) * sizeof(MD_LINE));
            ctx->current_block->n_lines -= n;
            ctx->n_block_bytes -= n * sizeof(MD_LINE);
        }
    }

    return 0;
}

static int
md_end_current_block(MD_CTX* ctx)
{
    int ret = 0;

    if(ctx->current_block == NULL)
        return ret;

    /* Check whether there is a reference definition. (We do this here instead
     * of in md_analyze_line() because reference definition can take multiple
     * lines.) */
    if(ctx->current_block->type == MD_BLOCK_P  ||
       (ctx->current_block->type == MD_BLOCK_H  &&  (ctx->current_block->flags & MD_BLOCK_SETEXT_HEADER)))
    {
        MD_LINE* lines = (MD_LINE*) (ctx->current_block + 1);
        if(CH(lines[0].beg) == _T('[')) {
            MD_CHECK(md_consume_link_reference_definitions(ctx));
            if(ctx->current_block == NULL)
                return ret;
        }
    }

    if(ctx->current_block->type == MD_BLOCK_H  &&  (ctx->current_block->flags & MD_BLOCK_SETEXT_HEADER)) {
        int n_lines = ctx->current_block->n_lines;

        if(n_lines > 1) {
            /* Get rid of the underline. */
            ctx->current_block->n_lines--;
            ctx->n_block_bytes -= sizeof(MD_LINE);
        } else {
            /* Only the underline has left after eating the ref. defs.
             * Keep the line as beginning of a new ordinary paragraph. */
            ctx->current_block->type = MD_BLOCK_P;
            return 0;
        }
    }

