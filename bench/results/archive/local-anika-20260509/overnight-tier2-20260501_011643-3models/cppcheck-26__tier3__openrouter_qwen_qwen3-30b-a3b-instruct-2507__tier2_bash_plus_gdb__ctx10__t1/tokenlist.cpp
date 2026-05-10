                return false;
            const Token * lambdaEnd = findLambdaEndScope(tok2);
            if (lambdaEnd)
                tok2 = lambdaEnd;
        }
    }
    // There is no initialisation for example here: 'class Fred {};'
    if (!Token::simpleMatch(endtok, "} ;"))
        return true;
    const Token *prev = nameToken;
    while (Token::Match(prev, "%name%|::|:|<|>")) {
        if (Token::Match(prev, "class|struct"))
            return false;

        prev = prev->previous();
    }
    return true;
}

static bool isQualifier(const Token* tok)
{
    while (Token::Match(tok, "&|&&|*"))
        tok = tok->next();
    if (!Token::Match(tok, "{|;"))
        return false;
    return true;
}

static void compileUnaryOp(Token *&tok, AST_state& state, void (*f)(Token *&tok, AST_state& state))
{
    Token *unaryop = tok;
    if (f) {
        tok = tok->next();
        state.depth++;
        if (state.depth > AST_MAX_DEPTH)
            throw InternalError(tok, "maximum AST depth exceeded", InternalError::AST);
        if (tok)
            f(tok, state);
        state.depth--;
    }

    if (!state.op.empty()) {
        unaryop->astOperand1(state.op.top());
        state.op.pop();
    }
    state.op.push(unaryop);
}

static void compileBinOp(Token *&tok, AST_state& state, void (*f)(Token *&tok, AST_state& state))
{
    Token *binop = tok;
    if (f) {
        tok = tok->next();
        if (Token::simpleMatch(binop, ":: ~"))
            tok = tok->next();
        state.depth++;
        if (tok && state.depth <= AST_MAX_DEPTH)
            f(tok, state);
        state.depth--;
    }

    // TODO: Should we check if op is empty.
    // * Is it better to add assertion that it isn't?
    // * Write debug warning if it's empty?
    if (!state.op.empty()) {
        binop->astOperand2(state.op.top());
        state.op.pop();
    }
    if (!state.op.empty()) {
        binop->astOperand1(state.op.top());
        state.op.pop();
    }
    state.op.push(binop);
}

static void compileExpression(Token *&tok, AST_state& state);

static void compileTerm(Token *&tok, AST_state& state)
{
    if (!tok)
        return;
    if (Token::Match(tok, "L %str%|%char%"))
        tok = tok->next();
    if (state.inArrayAssignment && Token::Match(tok->previous(), "[{,] . %name%")) { // Jump over . in C style struct initialization
        state.op.push(tok);
        tok->astOperand1(tok->next());
        tok = tok->tokAt(2);
    }
    if (state.inArrayAssignment && Token::Match(tok->previous(), "[{,] [ %num%|%name% ]")) {
        state.op.push(tok);
        tok->astOperand1(tok->next());
        tok = tok->tokAt(3);
    }
    if (tok->isLiteral()) {
        state.op.push(tok);
        do {
            tok = tok->next();
        } while (Token::Match(tok, "%name%|%str%"));
    } else if (tok->isName()) {
        if (Token::Match(tok, "return|case") || (state.cpp && tok->str() == "throw")) {
            if (tok->str() == "case")
