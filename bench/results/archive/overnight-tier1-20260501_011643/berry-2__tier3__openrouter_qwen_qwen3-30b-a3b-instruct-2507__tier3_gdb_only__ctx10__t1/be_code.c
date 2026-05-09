        exp2anyreg(finfo, e);
        break;
    }
}

/* Apply binary operator `op` to e1 and e2, result in e1 */
void be_code_binop(bfuncinfo *finfo, int op, bexpdesc *e1, bexpdesc *e2, int dst)
{
    switch (op) {
    case OptAnd:
        var2anyreg(finfo, e2);
        be_code_conjump(finfo, &e2->f, e1->f);
        *e1 = *e2;
        break;
    case OptOr:
        var2anyreg(finfo, e2);
        be_code_conjump(finfo, &e2->t, e1->t);
        *e1 = *e2;
        break;
    case OptAdd: case OptSub: case OptMul: case OptDiv:
    case OptMod: case OptLT: case OptLE: case OptEQ:
    case OptNE: case OptGT: case OptGE: case OptConnect:
    case OptBitAnd: case OptBitOr: case OptBitXor:
    case OptShiftL: case OptShiftR:
        binaryexp(finfo, (bopcode)(op - OptAdd), e1, e2, dst);
        break;
    default: break;
    }
}

/* Apply unary operator and return register number */
/* If input is register, change in place or allocate new register */
static void unaryexp(bfuncinfo *finfo, bopcode op, bexpdesc *e)
{
    int src = exp2anyreg(finfo, e);
    int dst = e->type == ETREG ? src : be_code_allocregs(finfo, 1);
    codeABC(finfo, op, dst, src, 0);
    e->type = ETREG;
    e->v.idx = dst;
}

/* Apply not to conditional expression */
/* If literal compute the value */
/* Or invert t/f subexpressions */
static void code_not(bfuncinfo *finfo, bexpdesc *e)
{
    switch (e->type) {
    case ETINT: e->v.i = e->v.i == 0; break;
    case ETREAL: e->v.i = e->v.r == cast(breal, 0); break;
    case ETNIL: e->v.i = 1; break;
    case ETBOOL: e->v.i = !e->v.i; break;
    case ETSTRING: e->v.i = 0; break;
    default: {
        int temp = e->t;
        e->t = e->f;
        e->f = temp;
        e->not = NOT_EXPR | (e->not ^ NOT_MASK);
        return;
    }
    }
    e->type = ETBOOL;
}

/* Negative value of literal or emit NEG opcode */
static int code_neg(bfuncinfo *finfo, bexpdesc *e)
{
    switch (e->type) {
    case ETINT: e->v.i = -e->v.i; break;
    case ETREAL: e->v.r = -e->v.r; break;
    case ETNIL: case ETBOOL: case ETSTRING:
        return 1; /* error */
    default:
        unaryexp(finfo, OP_NEG, e);
    }
    return 0;
}

/* Bit flip of literal or emit FLIP opcode */
static int code_flip(bfuncinfo *finfo, bexpdesc *e)
{
    switch (e->type) {
    case ETINT: e->v.i = ~e->v.i; break;
    case ETREAL: case ETNIL: case ETBOOL: case ETSTRING:
        return 2; /* error */
    default:
        unaryexp(finfo, OP_FLIP, e);
    }
    return 0;
}

/* Apply unary operator: not, neg or bitflip */
int be_code_unop(bfuncinfo *finfo, int op, bexpdesc *e)
{
    switch (op) {
    case OptNot:
        code_not(finfo, e); break;
    case OptFlip: /* do nothing */
        return code_flip(finfo, e);
    case OptSub:
        return code_neg(finfo, e);
    default:
