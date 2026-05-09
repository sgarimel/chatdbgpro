    if (!Token::Match(first->link(), "] (|{"))
        return nullptr;
    if (first->astOperand1() != first->link()->next())
        return nullptr;
    const Token * tok = first;

    if (tok->astOperand1() && tok->astOperand1()->str() == "(")
        tok = tok->astOperand1();
    if (tok->astOperand1() && tok->astOperand1()->str() == "{")
        return tok->astOperand1()->link();
    return nullptr;
}

const Token* findLambdaEndToken(const Token* first)
{
    return findLambdaEndTokenGeneric(first);
}
Token* findLambdaEndToken(Token* first)
{
    return findLambdaEndTokenGeneric(first);
}

bool isLikelyStream(bool cpp, const Token *stream)
{
    if (!cpp)
        return false;

    if (!stream)
        return false;

    if (!Token::Match(stream->astParent(), "&|<<|>>") || !stream->astParent()->isBinaryOp())
        return false;

    if (stream->astParent()->astOperand1() != stream)
        return false;

    return !astIsIntegral(stream, false);
}

bool isLikelyStreamRead(bool cpp, const Token *op)
{
    if (!cpp)
        return false;

    if (!Token::Match(op, "&|>>") || !op->isBinaryOp())
        return false;

    if (!Token::Match(op->astOperand2(), "%name%|.|*|[") && op->str() != op->astOperand2()->str())
        return false;

    const Token *parent = op;
    while (parent->astParent() && parent->astParent()->str() == op->str())
        parent = parent->astParent();
    if (parent->astParent() && !Token::Match(parent->astParent(), "%oror%|&&|(|,|!"))
        return false;
    if (op->str() == "&" && parent->astParent())
        return false;
    if (!parent->astOperand1() || !parent->astOperand2())
        return false;
    return (!parent->astOperand1()->valueType() || !parent->astOperand1()->valueType()->isIntegral());
}

bool isCPPCast(const Token* tok)
{
    return tok && Token::simpleMatch(tok->previous(), "> (") && tok->astOperand2() && tok->astOperand1() && tok->astOperand1()->str().find("_cast") != std::string::npos;
}

bool isConstVarExpression(const Token *tok, const char* skipMatch)
{
    if (!tok)
        return false;
    if (skipMatch && Token::Match(tok, skipMatch))
        return false;
    if (Token::simpleMatch(tok->previous(), "sizeof ("))
        return true;
    if (Token::Match(tok->previous(), "%name% (")) {
        if (Token::simpleMatch(tok->astOperand1(), ".") && !isConstVarExpression(tok->astOperand1(), skipMatch))
            return false;
        std::vector<const Token *> args = getArguments(tok);
        return std::all_of(args.begin(), args.end(), [&](const Token* t) {
            return isConstVarExpression(t, skipMatch);
        });
    }
    if (isCPPCast(tok)) {
        return isConstVarExpression(tok->astOperand2(), skipMatch);
    }
    if (Token::Match(tok, "( %type%"))
        return isConstVarExpression(tok->astOperand1(), skipMatch);
    if (tok->str() == "::" && tok->hasKnownValue())
        return isConstVarExpression(tok->astOperand2(), skipMatch);
    if (Token::Match(tok, "%cop%|[|.")) {
        if (tok->astOperand1() && !isConstVarExpression(tok->astOperand1(), skipMatch))
            return false;
        if (tok->astOperand2() && !isConstVarExpression(tok->astOperand2(), skipMatch))
            return false;
        return true;
    }
    if (Token::Match(tok, "%bool%|%num%|%str%|%char%|nullptr|NULL"))
        return true;
    if (tok->isEnumerator())
        return true;
