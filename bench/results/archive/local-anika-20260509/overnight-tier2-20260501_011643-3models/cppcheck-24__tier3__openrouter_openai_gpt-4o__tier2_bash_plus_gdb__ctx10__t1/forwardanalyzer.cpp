        return Progress::Continue;
    }

    Progress updateRange(Token* start, const Token* end) {
        for (Token* tok = start; tok && tok != end; tok = tok->next()) {
            Token* next = nullptr;

            if (tok->link()) {
                // Skip casts..
                if (tok->str() == "(" && !tok->astOperand2() && tok->isCast()) {
                    tok = tok->link();
                    continue;
                }
                // Skip template arguments..
                if (tok->str() == "<") {
                    tok = tok->link();
                    continue;
                }
            }

            // Evaluate RHS of assignment before LHS
            if (Token* assignTok = assignExpr(tok)) {
                if (updateRecursive(assignTok->astOperand2()) == Progress::Break)
                    return Progress::Break;
                if (updateRecursive(assignTok->astOperand1()) == Progress::Break)
                    return Progress::Break;
                if (update(assignTok) == Progress::Break)
                    return Progress::Break;
                tok = nextAfterAstRightmostLeaf(assignTok);
                if (!tok)
                    return Progress::Break;
            } else if (tok->str() ==  "break") {
                const Scope* scope = findBreakScope(tok->scope());
                if (!scope)
                    return Progress::Break;
                tok = skipTo(tok, scope->bodyEnd, end);
                if (!analyzer->lowerToPossible())
                    return Progress::Break;
                // TODO: Don't break, instead move to the outer scope
                if (!tok)
                    return Progress::Break;
            } else if (Token::Match(tok, "%name% :") || tok->str() == "case") {
                if (!analyzer->lowerToPossible())
                    return Progress::Break;
            } else if (tok->link() && tok->str() == "}") {
                if (Token::Match(tok->link()->previous(), ")|else {")) {
                    const bool inElse = Token::simpleMatch(tok->link()->previous(), "else {");
                    const Token* condTok = getCondTokFromEnd(tok);
                    if (!condTok)
                        return Progress::Break;
                    if (!condTok->hasKnownIntValue()) {
                        if (!analyzer->lowerToPossible())
                            return Progress::Break;
                    } else if (condTok->values().front().intvalue == !inElse) {
                        return Progress::Break;
                    }
                    analyzer->assume(condTok, !inElse, tok);
                    if (Token::simpleMatch(tok, "} else {"))
                        tok = tok->linkAt(2);
                } else if (Token::simpleMatch(tok->link()->previous(), "try {")) {
                    if (!analyzer->lowerToPossible())
                        return Progress::Break;
                } else if (Token::simpleMatch(tok->next(), "else {")) {
                    tok = tok->linkAt(2);
                }
            } else if (tok->isControlFlowKeyword() && Token::Match(tok, "if|while|for (") && Token::simpleMatch(tok->next()->link(), ") {")) {
                Token* endCond = tok->next()->link();
                Token* endBlock = endCond->next()->link();
                Token* condTok = getCondTok(tok);
                Token* initTok = getInitTok(tok);
                if (!condTok)
                    return Progress::Break;
                if (initTok && updateRecursive(initTok) == Progress::Break)
                    return Progress::Break;
                if (Token::Match(tok, "for|while (")) {
                    Token* stepTok = getStepTok(tok);
                    if (updateLoop(endBlock, condTok, initTok, stepTok) == Progress::Break)
                        return Progress::Break;
                    tok = endBlock;
                } else {
                    // Traverse condition
                    if (updateRecursive(condTok) == Progress::Break)
                        return Progress::Break;
                    // Check if condition is true or false
                    bool checkThen, checkElse;
                    std::tie(checkThen, checkElse) = evalCond(condTok);
                    ForwardAnalyzer::Action thenAction = ForwardAnalyzer::Action::None;
                    ForwardAnalyzer::Action elseAction = ForwardAnalyzer::Action::None;
                    bool hasElse = Token::simpleMatch(endBlock, "} else {");
                    bool bail = false;

                    // Traverse then block
                    bool returnThen = isEscapeScope(endBlock, true);
                    bool returnElse = false;
                    if (checkThen) {
                        if (updateRange(endCond->next(), endBlock) == Progress::Break)
                            return Progress::Break;
                    } else if (!checkElse) {
                        thenAction = checkScope(endBlock);
                        if (hasGoto(endBlock))
                            bail = true;
