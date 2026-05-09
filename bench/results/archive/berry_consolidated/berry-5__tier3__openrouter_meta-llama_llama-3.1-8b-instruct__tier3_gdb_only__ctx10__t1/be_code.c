                return i;
            }
            break;
        default:
            break;
        }
    }
    return -1;
}

static int exp2const(bfuncinfo *finfo, bexpdesc *e)
{
    int idx = findconst(finfo, e);
    if (idx == -1) {
        bvalue k;
        switch (e->type) {
        case ETINT:
            k.type = BE_INT;
            k.v.i = e->v.i;
            break;
        case ETREAL:
            k.type = BE_REAL;
            k.v.r = e->v.r;
            break;
        case ETSTRING:
            k.type = BE_STRING;
            k.v.s = e->v.s;
            break;
        default:
            break;
        }
        idx = newconst(finfo, &k);
    }
    if (idx < 256) {
        e->type = ETCONST;
        e->v.idx = setK(idx);
    } else { /* index value is too large */
        e->type = ETREG;
        e->v.idx = be_code_allocregs(finfo, 1);
        codeABx(finfo, OP_LDCONST, e->v.idx, idx);
    }
    return e->v.idx;
}

static void free_suffix(bfuncinfo *finfo, bexpdesc *e)
{
    int idx = e->v.ss.idx;
    int nlocal = be_list_count(finfo->local);
    /* release suffix register */
    if (!isK(idx) && idx >= nlocal) {
        be_code_freeregs(finfo, 1);
    }
    /* release object register */
    if (e->v.ss.tt == ETREG && (int)e->v.ss.obj >= nlocal) {
        be_code_freeregs(finfo, 1);
    }
}

static int code_suffix(bfuncinfo *finfo, bopcode op, bexpdesc *e, int dst)
{
    free_suffix(finfo, e); /* free temporary registers */
    if (dst > finfo->freereg) {
        dst = finfo->freereg;
    }
    codeABC(finfo, op, dst, e->v.ss.obj, e->v.ss.idx);
    return dst;
}

/* idx: the proto index in proto_table
 * dst: the destination register
 **/
static void code_closure(bfuncinfo *finfo, int idx, int dst)
{
    codeABx(finfo, OP_CLOSURE, dst, idx); /* load closure to register */
}

static bbool constint(bfuncinfo *finfo, bint i)
{
    /* cache common numbers */
    if ((i < IsBx_MIN || i > IsBx_MAX) ||
        (i >= 0 && i <= 3 && be_vector_count(&finfo->kvec) < 256)) {
        return btrue;
    }
    return bfalse;
}

static int var2reg(bfuncinfo *finfo, bexpdesc *e, int dst)
{
    be_assert(e != NULL);
    switch (e->type) {
    case ETINT:
        if (constint(finfo, e->v.i)) {
            return exp2const(finfo, e);
        } else {
            codeABx(finfo, OP_LDINT, dst, var_toidx(e) + IsBx_MAX);
        }
        break;
    case ETBOOL:
        code_bool(finfo, dst, e->v.i != 0, 0);
        break;
    case ETNIL:
