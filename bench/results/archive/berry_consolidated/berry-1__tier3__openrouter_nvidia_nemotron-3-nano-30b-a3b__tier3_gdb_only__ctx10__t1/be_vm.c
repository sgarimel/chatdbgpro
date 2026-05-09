        opcase(CONNECT): {
            bvalue *a = RKB(), *b = RKC();
            if (var_isint(a) && var_isint(b)) {
                make_range(vm, *RKB(), *RKC());
            } else if (var_isstr(a)) {
                connect_str(vm, var_tostr(a), b);
            } else if (var_isinstance(a)) {
                object_binop(vm, "..", *RKB(), *RKC());
            } else {
                binop_error(vm, "..", RKB(), RKC());
            }
            reg = vm->reg;
            *RA() = *vm->top; /* copy result to R(A) */
            dispatch();
        }
        opcase(AND): {
            bitwise_block(&);
            dispatch();
        }
        opcase(OR): {
            bitwise_block(|);
            dispatch();
        }
        opcase(XOR): {
            bitwise_block(^);
            dispatch();
        }
        opcase(SHL): {
            bitwise_block(<<);
            dispatch();
        }
        opcase(SHR): {
            bitwise_block(>>);
            dispatch();
        }
        opcase(NEG): {
            bvalue *dst = RA(), *a = RKB();
            if (var_isint(a)) {
                var_setint(dst, -a->v.i);
            } else if (var_isreal(a)) {
                var_setreal(dst, -a->v.r);
            } else if (var_isinstance(a)) {
                ins_unop(vm, "-*", *RKB());
                reg = vm->reg;
                *RA() = *vm->top; /* copy result to dst */
            } else {
                unop_error(vm, "-", a);
            }
            dispatch();
        }
        opcase(FLIP): {
            bvalue *dst = RA(), *a = RKB();
            if (var_isint(a)) {
                var_setint(dst, -a->v.i);
            } else if (var_isinstance(a)) {
                ins_unop(vm, "~", *RKB());
                reg = vm->reg;
                *RA() = *vm->top; /* copy result to dst */
            } else {
                unop_error(vm, "~", a);
            }
            dispatch();
        }
        opcase(JMP): {
            vm->ip += IGET_sBx(ins);
            dispatch();
        }
        opcase(JMPT): {
            if (be_value2bool(vm, RA())) {
                vm->ip += IGET_sBx(ins);
            }
            dispatch();
        }
        opcase(JMPF): {
            if (!be_value2bool(vm, RA())) {
                vm->ip += IGET_sBx(ins);
            }
            dispatch();
        }
        opcase(CLOSURE): {
            bvalue *dst;
            bproto *p = clos->proto->ptab[IGET_Bx(ins)];
            bclosure *cl = be_newclosure(vm, p->nupvals);
            cl->proto = p;
            reg = vm->reg;
            dst = RA();
            var_setclosure(dst, cl);
            be_initupvals(vm, cl);
            dispatch();
        }
        opcase(CLASS): {
            bclass *c = var_toobj(ktab + IGET_Bx(ins));
            be_class_upvalue_init(vm, c);
            dispatch();
        }
        opcase(GETMBR): {
            bvalue *a = RA(), *b = RKB(), *c = RKC();
            if (var_isinstance(b) && var_isstr(c)) {
                obj_attribute(vm, b, var_tostr(c), a);
                reg = vm->reg;
            } else if (var_isclass(b) && var_isstr(c)) {
