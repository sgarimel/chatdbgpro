    const SymbolDatabase *symbolDatabase = mTokenizer->getSymbolDatabase();

    std::list<const Function*> constFunctions;
    getConstFunctions(symbolDatabase, constFunctions);

    for (const Scope *scope : symbolDatabase->functionScopes) {
        for (const Token *tok = scope->bodyStart; tok != scope->bodyEnd; tok = tok->next()) {
            if (tok->str() == "=" && Token::Match(tok->astOperand1(), "%var%")) {
                const Token * endStatement = Token::findsimplematch(tok, ";");
                if (Token::Match(endStatement, "; %type% %var% ;")) {
                    endStatement = endStatement->tokAt(4);
                }
                if (Token::Match(endStatement, "%var% %assign%")) {
                    const Token * nextAssign = endStatement->tokAt(1);
                    const Token * var1 = tok->astOperand1();
                    const Token * var2 = nextAssign->astOperand1();
                    if (var1 && var2 &&
                        Token::Match(var1->previous(), ";|{|} %var%") &&
                        Token::Match(var2->previous(), ";|{|} %var%") &&
                        var2->valueType() && var1->valueType() &&
                        var2->valueType()->originalTypeName == var1->valueType()->originalTypeName &&
                        var2->valueType()->pointer == var1->valueType()->pointer &&
                        var2->valueType()->constness == var1->valueType()->constness &&
                        var2->varId() != var1->varId() && (
                            tok->astOperand2()->isArithmeticalOp() ||
                            tok->astOperand2()->str() == "." ||
                            Token::Match(tok->astOperand2()->previous(), "%name% (")
                        ) &&
                        tok->next()->tokType() != Token::eType &&
                        isSameExpression(mTokenizer->isCPP(), true, tok->next(), nextAssign->next(), mSettings->library, true, false) &&
                        isSameExpression(mTokenizer->isCPP(), true, tok->astOperand2(), nextAssign->astOperand2(), mSettings->library, true, false) &&
                        tok->astOperand2()->expressionString() == nextAssign->astOperand2()->expressionString()) {
                        bool assigned = false;
                        const Scope * varScope = var1->scope() ? var1->scope() : scope;
                        for (const Token *assignTok = Token::findsimplematch(var2, ";"); assignTok && assignTok != varScope->bodyEnd; assignTok = assignTok->next()) {
                            if (Token::Match(assignTok, "%varid% = %var%", var1->varId()) && Token::Match(assignTok, "%var% = %varid%", var2->varId())) {
                                assigned = true;
                            }
                            if (Token::Match(assignTok, "%varid% = %var%", var2->varId()) && Token::Match(assignTok, "%var% = %varid%", var1->varId())) {
                                assigned = true;
                            }
                        }
                        if (!assigned && !isUniqueExpression(tok->astOperand2()))
                            duplicateAssignExpressionError(var1, var2, false);
                        else if (mSettings->inconclusive)
                            duplicateAssignExpressionError(var1, var2, true);
                    }
                }
            }
            ErrorPath errorPath;
            if (tok->isOp() && tok->astOperand1() && !Token::Match(tok, "+|*|<<|>>|+=|*=|<<=|>>=")) {
                if (Token::Match(tok, "==|!=|-") && astIsFloat(tok->astOperand1(), true))
                    continue;
                if (isSameExpression(mTokenizer->isCPP(), true, tok->astOperand1(), tok->astOperand2(), mSettings->library, true, true, &errorPath)) {
                    if (isWithoutSideEffects(mTokenizer->isCPP(), tok->astOperand1())) {
                        const bool assignment = tok->str() == "=";
                        if (assignment && warningEnabled)
                            selfAssignmentError(tok, tok->astOperand1()->expressionString());
                        else if (styleEnabled) {
                            if (mTokenizer->isCPP() && mSettings->standards.cpp==Standards::CPP11 && tok->str() == "==") {
                                const Token* parent = tok->astParent();
                                while (parent && parent->astParent()) {
                                    parent = parent->astParent();
                                }
                                if (parent && parent->previous() && parent->previous()->str() == "static_assert") {
                                    continue;
                                }
                            }
                            duplicateExpressionError(tok->astOperand1(), tok->astOperand2(), tok, errorPath);
                        }
                    }
                } else if (tok->str() == "=" && Token::simpleMatch(tok->astOperand2(), "=") && isSameExpression(mTokenizer->isCPP(), false, tok->astOperand1(), tok->astOperand2()->astOperand1(), mSettings->library, true, false)) {
                    if (warningEnabled && isWithoutSideEffects(mTokenizer->isCPP(), tok->astOperand1())) {
                        selfAssignmentError(tok, tok->astOperand1()->expressionString());
                    }
                } else if (styleEnabled &&
                           isOppositeExpression(mTokenizer->isCPP(), tok->astOperand1(), tok->astOperand2(), mSettings->library, false, true, &errorPath) &&
                           !Token::Match(tok, "=|-|-=|/|/=") &&
                           isWithoutSideEffects(mTokenizer->isCPP(), tok->astOperand1())) {
                    oppositeExpressionError(tok, errorPath);
                } else if (!Token::Match(tok, "[-/%]")) { // These operators are not associative
                    if (styleEnabled && tok->astOperand2() && tok->str() == tok->astOperand1()->str() && isSameExpression(mTokenizer->isCPP(), true, tok->astOperand2(), tok->astOperand1()->astOperand2(), mSettings->library, true, true, &errorPath) && isWithoutSideEffects(mTokenizer->isCPP(), tok->astOperand2()))
                        duplicateExpressionError(tok->astOperand2(), tok->astOperand1()->astOperand2(), tok, errorPath);
                    else if (tok->astOperand2() && isConstExpression(tok->astOperand1(), mSettings->library, true, mTokenizer->isCPP())) {
                        const Token *ast1 = tok->astOperand1();
                        while (ast1 && tok->str() == ast1->str()) {
                            if (isSameExpression(mTokenizer->isCPP(), true, ast1->astOperand1(), tok->astOperand2(), mSettings->library, true, true, &errorPath) &&
                                isWithoutSideEffects(mTokenizer->isCPP(), ast1->astOperand1()) &&
                                isWithoutSideEffects(mTokenizer->isCPP(), ast1->astOperand2()))
                                // Probably the message should be changed to 'duplicate expressions X in condition or something like that'.
                                duplicateExpressionError(ast1->astOperand1(), tok->astOperand2(), tok, errorPath);
                            ast1 = ast1->astOperand1();
                        }
                    }
                }
            } else if (styleEnabled && tok->astOperand1() && tok->astOperand2() && tok->str() == ":" && tok->astParent() && tok->astParent()->str() == "?") {
                if (!tok->astOperand1()->values().empty() && !tok->astOperand2()->values().empty() && isEqualKnownValue(tok->astOperand1(), tok->astOperand2()))
                    duplicateValueTernaryError(tok);
                else if (isSameExpression(mTokenizer->isCPP(), true, tok->astOperand1(), tok->astOperand2(), mSettings->library, false, true, &errorPath))
                    duplicateExpressionTernaryError(tok, errorPath);
            }
