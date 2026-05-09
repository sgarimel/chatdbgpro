    return false;
}

static bool isInScope(const Token * tok, const Scope * scope)
{
    if (!tok)
        return false;
    if (!scope)
        return false;
    const Variable * var = tok->variable();
    if (var && (var->isGlobal() || var->isStatic() || var->isExtern()))
        return false;
    if (tok->scope() && tok->scope()->isNestedIn(scope))
        return true;
    if (!var)
        return false;
    if (var->isArgument() && !var->isReference()) {
        const Scope * tokScope = tok->scope();
        if (!tokScope)
            return false;
        for (const Scope * argScope:tokScope->nestedList) {
            if (argScope && argScope->isNestedIn(scope))
                return true;
        }
    }
    return false;
}

static bool isDeadScope(const Token * tok, const Scope * scope)
{
    if (!tok)
        return false;
    if (!scope)
        return false;
    const Variable * var = tok->variable();
    if (var && (!var->isLocal() || var->isStatic() || var->isExtern()))
        return false;
    if (tok->scope() && tok->scope()->bodyEnd != scope->bodyEnd && precedes(tok->scope()->bodyEnd, scope->bodyEnd))
        return true;
    return false;
}

static int getPointerDepth(const Token *tok)
{
    if (!tok)
        return 0;
    return tok->valueType() ? tok->valueType()->pointer : 0;
}

static bool isDeadTemporary(bool cpp, const Token* tok, const Token* expr, const Library* library)
{
    if (!isTemporary(cpp, tok, library))
        return false;
    if (expr && !precedes(nextAfterAstRightmostLeaf(tok->astTop()), nextAfterAstRightmostLeaf(expr->astTop())))
        return false;
    return true;
}

static bool isEscapedReference(const Variable* var)
{
    if (!var)
        return false;
    if (!var->isReference())
        return false;
    if (!var->declEndToken())
        return false;
    if (!Token::simpleMatch(var->declEndToken(), "="))
        return false;
    const Token* vartok = var->declEndToken()->astOperand2();
    return !isTemporary(true, vartok, nullptr, false);
}

void CheckAutoVariables::checkVarLifetimeScope(const Token * start, const Token * end)
{
    if (!start)
        return;
    const Scope * scope = start->scope();
    if (!scope)
        return;
    // If the scope is not set correctly then skip checking it
    if (scope->bodyStart != start)
        return;
    bool returnRef = Function::returnsReference(scope->function);
    for (const Token *tok = start; tok && tok != end; tok = tok->next()) {
        // Return reference from function
        if (returnRef && Token::simpleMatch(tok->astParent(), "return")) {
            for (const LifetimeToken& lt : getLifetimeTokens(tok)) {
                const Variable* var = lt.token->variable();
                if (var && !var->isGlobal() && !var->isStatic() && !var->isReference() && !var->isRValueReference() &&
                    isInScope(var->nameToken(), tok->scope())) {
                    errorReturnReference(tok, lt.errorPath, lt.inconclusive);
                    break;
                } else if (isDeadTemporary(mTokenizer->isCPP(), lt.token, nullptr, &mSettings->library)) {
                    errorReturnTempReference(tok, lt.errorPath, lt.inconclusive);
                    break;
                }
            }
            // Assign reference to non-local variable
        } else if (Token::Match(tok->previous(), "&|&& %var% =") && tok->astParent() == tok->next() &&
                   tok->variable() && tok->variable()->nameToken() == tok &&
                   tok->variable()->declarationId() == tok->varId() && tok->variable()->isStatic() &&
