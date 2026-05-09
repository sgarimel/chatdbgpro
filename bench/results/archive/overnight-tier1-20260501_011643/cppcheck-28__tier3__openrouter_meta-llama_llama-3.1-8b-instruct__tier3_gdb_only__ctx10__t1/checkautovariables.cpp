        // Return reference from function
        if (returnRef && Token::simpleMatch(tok->astParent(), "return")) {
            for (const LifetimeToken& lt : getLifetimeTokens(tok, true)) {
                if (!printInconclusive && lt.inconclusive)
                    continue;
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
                   !tok->variable()->isArgument()) {
            ErrorPath errorPath;
            const Variable *var = getLifetimeVariable(tok, errorPath);
            if (var && isInScope(var->nameToken(), tok->scope())) {
                errorDanglingReference(tok, var, errorPath);
                continue;
            }
            // Reference to temporary
        } else if (tok->variable() && (tok->variable()->isReference() || tok->variable()->isRValueReference())) {
            for (const LifetimeToken& lt : getLifetimeTokens(getParentLifetime(tok))) {
                if (!printInconclusive && lt.inconclusive)
                    continue;
                const Token * tokvalue = lt.token;
                if (isDeadTemporary(mTokenizer->isCPP(), tokvalue, tok, &mSettings->library)) {
                    errorDanglingTempReference(tok, lt.errorPath, lt.inconclusive);
                    break;
                }
            }

        }
        for (const ValueFlow::Value& val:tok->values()) {
            if (!val.isLocalLifetimeValue() && !val.isSubFunctionLifetimeValue())
                continue;
            if (!printInconclusive && val.isInconclusive())
                continue;
            const bool escape = Token::Match(tok->astParent(), "return|throw");
            for (const LifetimeToken& lt : getLifetimeTokens(getParentLifetime(val.tokvalue), escape)) {
                const Token * tokvalue = lt.token;
                if (val.isLocalLifetimeValue()) {
                    if (escape) {
                        if (getPointerDepth(tok) < getPointerDepth(tokvalue))
                            continue;
                        if (!isLifetimeBorrowed(tok, mSettings))
                            continue;
                        if ((tokvalue->variable() && !isEscapedReference(tokvalue->variable()) &&
                             isInScope(tokvalue->variable()->nameToken(), scope)) ||
                            isDeadTemporary(mTokenizer->isCPP(), tokvalue, tok, &mSettings->library)) {
                            errorReturnDanglingLifetime(tok, &val);
                            break;
                        }
                    } else if (tokvalue->variable() && isDeadScope(tokvalue->variable()->nameToken(), tok->scope())) {
                        errorInvalidLifetime(tok, &val);
                        break;
                    } else if (!tokvalue->variable() &&
                               isDeadTemporary(mTokenizer->isCPP(), tokvalue, tok, &mSettings->library)) {
                        errorDanglingTemporaryLifetime(tok, &val);
                        break;
                    }
                }
                if (tokvalue->variable() && (isInScope(tokvalue->variable()->nameToken(), tok->scope()) ||
                                             (val.isSubFunctionLifetimeValue() && isDanglingSubFunction(tokvalue, tok)))) {
                    const Variable * var = nullptr;
                    const Token * tok2 = tok;
                    if (Token::simpleMatch(tok->astParent(), "=")) {
                        if (tok->astParent()->astOperand2() == tok) {
                            var = getLHSVariable(tok->astParent());
                            tok2 = tok->astParent()->astOperand1();
                        }
                    } else if (tok->variable() && tok->variable()->declarationId() == tok->varId()) {
                        var = tok->variable();
                    }
                    if (!isLifetimeBorrowed(tok, mSettings))
                        continue;
                    if (var && !var->isLocal() && !var->isArgument() && !isVariableChanged(tok->next(), tok->scope()->bodyEnd, var->declarationId(), var->isGlobal(), mSettings, mTokenizer->isCPP())) {
                        errorDanglngLifetime(tok2, &val);
                        break;
                    }
                }
            }
        }
        const Token *lambdaEndToken = findLambdaEndToken(tok);
        if (lambdaEndToken) {
            checkVarLifetimeScope(lambdaEndToken->link(), lambdaEndToken);
            tok = lambdaEndToken;
        }
        if (tok->str() == "{" && tok->scope()) {
            // Check functions in local classes
            if (tok->scope()->type == Scope::eClass ||
                tok->scope()->type == Scope::eStruct ||
                tok->scope()->type == Scope::eUnion) {
                for (const Function& f:tok->scope()->functionList) {
                    if (f.functionScope)
