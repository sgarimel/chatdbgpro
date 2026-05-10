    // Assignments;
    // * Is this LHS in assignment
    // * Passing address in RHS to pointer variable
    {
        const Token *tok = derefValue ? derefValue : valueExpr;
        if (Token::simpleMatch(tok->astParent(), "=")) {
            if (astIsLhs(tok))
                return nullptr;
            if (alloc != NO_ALLOC && astIsRhs(valueExpr))
                return nullptr;
        }
    }

    // Initialize reference variable
    if (Token::Match((derefValue ? derefValue : vartok)->astParent(), "(|=") && astIsRhs(derefValue ? derefValue : vartok)) {
        const Token *rhstok = derefValue ? derefValue : vartok;
        const Token *lhstok = rhstok->astParent()->astOperand1();
        const Variable *lhsvar = lhstok->variable();
        if (lhsvar && lhsvar->isReference() && lhsvar->nameToken() == lhstok)
            return nullptr;
    }

    // LHS in range for loop:
    if (Token::simpleMatch(valueExpr->astParent(), ":") &&
        astIsLhs(valueExpr) &&
        valueExpr->astParent()->astParent() &&
        Token::simpleMatch(valueExpr->astParent()->astParent()->previous(), "for ("))
        return nullptr;

    // Stream read/write
    // FIXME this code is a hack!!
    if (mTokenizer->isCPP() && Token::Match(valueExpr->astParent(), "<<|>>")) {
        if (isLikelyStreamRead(mTokenizer->isCPP(), vartok->previous()))
            return nullptr;

        if (valueExpr->valueType() && valueExpr->valueType()->type == ValueType::Type::VOID)
            return nullptr;

        // overloaded << operator to initialize variable?
        if (Token::simpleMatch(valueExpr->astParent(), "<<") && !valueExpr->astParent()->astParent()) {
            if (astIsLhs(valueExpr))
                return nullptr;
            const Token *lhs = valueExpr->astParent()->astOperand1();
            if (Token::simpleMatch(lhs, "<<"))
                return valueExpr;
            if (Token::simpleMatch(lhs->previous(), "std ::"))
                return valueExpr;
            const Variable *var = lhs->variable();
            if (var && (var->typeStartToken()->isStandardType() || var->typeStartToken()->isEnumType() || Token::simpleMatch(var->typeStartToken(), "std ::")))
                return valueExpr;
            return nullptr;
        }
    }

    if (mTokenizer->isCPP() && Token::simpleMatch(valueExpr->astParent(), "&") && !valueExpr->astParent()->astParent() && astIsRhs(valueExpr) && Token::Match(valueExpr->astSibling(), "%type%"))
        return nullptr;

    return derefValue ? derefValue : valueExpr;
}

/***
 * Is function parameter "used" so a "usage of uninitialized variable" can
 * be written? If parameter is passed "by value" then it is "used". If it
 * is passed "by reference" then it is not necessarily "used".
 * @return  -1 => unknown   0 => not used   1 => used
 */
int CheckUninitVar::isFunctionParUsage(const Token *vartok, bool pointer, Alloc alloc, int indirect) const
{
    bool unknown = false;
    const Token *parent = getAstParentSkipPossibleCastAndAddressOf(vartok, &unknown);
    if (unknown || !Token::Match(parent, "[(,]"))
        return -1;

    // locate start parentheses in function call..
    int argumentNumber = 0;
    const Token *start = vartok;
    while (start && !Token::Match(start, "[;{}(]")) {
        if (start->str() == ")")
            start = start->link();
        else if (start->str() == ",")
            ++argumentNumber;
        start = start->previous();
    }
    if (!start)
        return -1;

    if (Token::simpleMatch(start->link(), ") {") && Token::Match(start->previous(), "if|for|while|switch"))
        return (!pointer || alloc == NO_ALLOC);

    // is this a function call?
    if (Token::Match(start->previous(), "%name% (")) {
        const bool address(vartok->previous()->str() == "&");
        const bool array(vartok->variable() && vartok->variable()->isArray());
        // check how function handle uninitialized data arguments..
        const Function *func = start->previous()->function();
        if (func) {
            const Variable *arg = func->getArgumentVar(argumentNumber);
            if (arg) {
                const Token *argStart = arg->typeStartToken();
                if (!address && !array && Token::Match(argStart, "%type% %name%| [,)]"))
                    return 1;
