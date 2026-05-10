            default:
                MD_UNREACHABLE();
                break;
        }

        ctx->n_containers--;
    }

abort:
    return ret;
}

static int
md_is_container_mark(MD_CTX* ctx, unsigned indent, OFF beg, OFF* p_end, MD_CONTAINER* p_container)
{
    OFF off = beg;
    OFF max_end;

    if(indent >= ctx->code_indent_offset)
        return FALSE;

    /* Check for block quote mark. */
    if(off < ctx->size  &&  CH(off) == _T('>')) {
        off++;
        p_container->ch = _T('>');
        p_container->is_loose = FALSE;
        p_container->is_task = FALSE;
        p_container->mark_indent = indent;
        p_container->contents_indent = indent + 1;
        *p_end = off;
        return TRUE;
    }

    /* Check for list item bullet mark. */
    if(off+1 < ctx->size  &&  ISANYOF(off, _T("-+*"))  &&  (ISBLANK(off+1) || ISNEWLINE(off+1))) {
        p_container->ch = CH(off);
        p_container->is_loose = FALSE;
        p_container->is_task = FALSE;
        p_container->mark_indent = indent;
        p_container->contents_indent = indent + 1;
        *p_end = off + 1;
        return TRUE;
    }

    /* Check for ordered list item marks. */
    max_end = off + 9;
    if(max_end > ctx->size)
        max_end = ctx->size;
    p_container->start = 0;
    while(off < max_end  &&  ISDIGIT(off)) {
        p_container->start = p_container->start * 10 + CH(off) - _T('0');
        off++;
    }
    if(off+1 < ctx->size  &&
       (CH(off) == _T('.') || CH(off) == _T(')'))  &&
       (ISBLANK(off+1) || ISNEWLINE(off+1)))
    {
        p_container->ch = CH(off);
        p_container->is_loose = FALSE;
        p_container->is_task = FALSE;
        p_container->mark_indent = indent;
        p_container->contents_indent = indent + off - beg + 1;
        *p_end = off + 1;
        return TRUE;
    }

    return FALSE;
}

static unsigned
md_line_indentation(MD_CTX* ctx, unsigned total_indent, OFF beg, OFF* p_end)
{
    OFF off = beg;
    unsigned indent = total_indent;

    while(off < ctx->size  &&  ISBLANK(off)) {
        if(CH(off) == _T('\t'))
            indent = (indent + 4) & ~3;
        else
            indent++;
        off++;
    }

    *p_end = off;
    return indent - total_indent;
}

static const MD_LINE_ANALYSIS md_dummy_blank_line = { MD_LINE_BLANK, 0 };

/* Analyze type of the line and find some its properties. This serves as a
 * main input for determining type and boundaries of a block. */
static int
md_analyze_line(MD_CTX* ctx, OFF beg, OFF* p_end,
                const MD_LINE_ANALYSIS* pivot_line, MD_LINE_ANALYSIS* line)
{
    unsigned total_indent = 0;
    int n_parents = 0;
    int n_brothers = 0;
    int n_children = 0;
    MD_CONTAINER container = { 0 };
    int prev_line_has_list_loosening_effect = ctx->last_line_has_list_loosening_effect;
