    return false;
}

static bool isContainerSize(const Token* tok)
{
    if (!Token::Match(tok, "%var% . %name% ("))
        return false;
    if (!astIsContainer(tok))
        return false;
    if (tok->valueType()->container && tok->valueType()->container->getYield(tok->strAt(2)) == Library::Container::Yield::SIZE)
        return true;
    if (Token::Match(tok->tokAt(2), "size|length ( )"))
        return true;
    return false;
}

static bool isContainerEmpty(const Token* tok)
{
    if (!Token::Match(tok, "%var% . %name% ("))
        return false;
    if (!astIsContainer(tok))
        return false;
    if (tok->valueType()->container && tok->valueType()->container->getYield(tok->strAt(2)) == Library::Container::Yield::EMPTY)
        return true;
    if (Token::simpleMatch(tok->tokAt(2), "empty ( )"))
        return true;
    return false;
}
static bool isContainerSizeChanged(const Token *tok, int depth=20);

static bool isContainerSizeChanged(nonneg int varId, const Token *start, const Token *end, int depth = 20);

static bool isContainerSizeChangedByFunction(const Token *tok, int depth = 20)
{
    if (!tok->valueType() || !tok->valueType()->container)
        return false;
    // If we are accessing an element then we are not changing the container size
    if (Token::Match(tok, "%name% . %name% (")) {
        Library::Container::Yield yield = tok->valueType()->container->getYield(tok->strAt(2));
        if (yield != Library::Container::Yield::NO_YIELD)
            return false;
    }
    if (Token::simpleMatch(tok->astParent(), "["))
        return false;

    // address of variable
    const bool addressOf = tok->valueType()->pointer || (tok->astParent() && tok->astParent()->isUnaryOp("&"));

    int narg;
    const Token * ftok = getTokenArgumentFunction(tok, narg);
    if (!ftok)
        return false; // not a function => variable not changed
    const Function * fun = ftok->function();
    if (fun) {
        const Variable *arg = fun->getArgumentVar(narg);
        if (arg) {
            if (!arg->isReference() && !addressOf)
                return false;
            if (!addressOf && arg->isConst())
                return false;
            if (arg->valueType() && arg->valueType()->constness == 1)
                return false;
            const Scope * scope = fun->functionScope;
            if (scope) {
                // Argument not used
                if (!arg->nameToken())
                    return false;
                if (depth > 0)
                    return isContainerSizeChanged(arg->declarationId(), scope->bodyStart, scope->bodyEnd, depth - 1);
            }
            // Don't know => Safe guess
            return true;
        }
    }

    bool inconclusive = false;
    const bool isChanged = isVariableChangedByFunctionCall(tok, 0, nullptr, &inconclusive);
    return (isChanged || inconclusive);
}

static void valueFlowContainerReverse(Token *tok, nonneg int containerId, const ValueFlow::Value &value, const Settings *settings)
{
    while (nullptr != (tok = tok->previous())) {
        if (Token::Match(tok, "[{}]"))
            break;
        if (Token::Match(tok, "return|break|continue"))
            break;
        if (tok->varId() != containerId)
            continue;
        if (Token::Match(tok, "%name% ="))
            break;
        if (isContainerSizeChangedByFunction(tok))
            break;
        if (!tok->valueType() || !tok->valueType()->container)
            break;
        if (Token::Match(tok, "%name% . %name% (") && tok->valueType()->container->getAction(tok->strAt(2)) != Library::Container::Action::NO_ACTION)
            break;
        if (!hasContainerSizeGuard(tok, containerId))
            setTokenValue(tok, value, settings);
    }
}
