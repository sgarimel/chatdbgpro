        // if the library says 0 is invalid
        // => it is assumed that parameter is an in parameter (TODO: this is a bad heuristic)
        if (!addressOf && settings && settings->library.isnullargbad(tok, 1+argnr))
            return false;
        // possible pass-by-reference => inconclusive
        if (possiblyPassedByReference) {
            if (inconclusive != nullptr)
                *inconclusive = true;
            return false;
        }
        // Safe guess: Assume that parameter is changed by function call
        return true;
    }

    const Variable *arg = tok->function()->getArgumentVar(argnr);

    if (addressOf || (indirect > 0 && arg && arg->isPointer())) {
        if (!(arg && arg->isConst()))
            return true;
        // If const is applied to the pointer, then the value can still be modified
        if (arg && Token::simpleMatch(arg->typeEndToken(), "* const"))
            return true;
    }

    return arg && !arg->isConst() && arg->isReference();
}

bool isVariableChanged(const Token *tok, int indirect, const Settings *settings, bool cpp, int depth)
{
    if (!tok)
        return false;
    const Token *tok2 = tok;
    while (Token::simpleMatch(tok2->astParent(), "*") || (Token::simpleMatch(tok2->astParent(), ".") && !Token::simpleMatch(tok2->astParent()->astParent(), "(")) ||
           (Token::simpleMatch(tok2->astParent(), "[") && tok2 == tok2->astParent()->astOperand1()))
        tok2 = tok2->astParent();

    while (Token::simpleMatch(tok2->astParent(), "?") || (Token::simpleMatch(tok2->astParent(), ":") && Token::simpleMatch(tok2->astParent()->astParent(), "?")))
        tok2 = tok2->astParent();

    if (Token::Match(tok2->astParent(), "++|--"))
        return true;

    if (tok2->astParent() && tok2->astParent()->isAssignmentOp()) {
        if (tok2 == tok2->astParent()->astOperand1())
            return true;
        // Check if assigning to a non-const lvalue
        const Variable * var = getLHSVariable(tok2->astParent());
        if (var && var->isReference() && !var->isConst() && var->nameToken() && var->nameToken()->next() == tok2->astParent()) {
            if (!var->isLocal() || isVariableChanged(var, settings, cpp, depth - 1))
                return true;
        }
    }

    if (isLikelyStreamRead(cpp, tok->previous()))
        return true;

    if (isLikelyStream(cpp, tok2))
        return true;

    // Member function call
    if (tok->variable() && Token::Match(tok2->astParent(), ". %name%") && isFunctionCall(tok2->astParent()->next()) && tok2->astParent()->astOperand1() == tok2) {
        const Variable * var = tok->variable();
        bool isConst = var && var->isConst();
        if (!isConst) {
            const ValueType * valueType = var->valueType();
            isConst = (valueType && valueType->pointer == 1 && valueType->constness == 1);
        }

        const Token *ftok = tok->tokAt(2);
        const Function * fun = ftok->function();
        if (!isConst && (!fun || !fun->isConst()))
            return true;
        else
            return false;
    }

    const Token *ftok = tok2;
    while (ftok && (!Token::Match(ftok, "[({]") || ftok->isCast()))
        ftok = ftok->astParent();

    if (ftok && Token::Match(ftok->link(), ")|} !!{")) {
        const Token * ptok = tok2;
        while (Token::Match(ptok->astParent(), ".|::|["))
            ptok = ptok->astParent();
        bool inconclusive = false;
        bool isChanged = isVariableChangedByFunctionCall(ptok, indirect, settings, &inconclusive);
        isChanged |= inconclusive;
        if (isChanged)
            return true;
    }

    const Token *parent = tok2->astParent();
    while (Token::Match(parent, ".|::"))
        parent = parent->astParent();
    if (parent && parent->tokType() == Token::eIncDecOp)
        return true;

    if (Token::simpleMatch(tok2->astParent(), ":") && tok2->astParent()->astParent() && Token::simpleMatch(tok2->astParent()->astParent()->previous(), "for (")) {
        const Token * varTok = tok2->astParent()->previous();
        if (!varTok)
            return false;
