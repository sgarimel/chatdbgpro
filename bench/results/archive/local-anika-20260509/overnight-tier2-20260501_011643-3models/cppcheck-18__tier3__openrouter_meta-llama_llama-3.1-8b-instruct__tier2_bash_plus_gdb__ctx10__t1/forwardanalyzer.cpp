
    std::pair<bool, bool> evalCond(const Token* tok) {
        std::vector<int> result = analyzer->evaluate(tok);
        bool checkThen = std::any_of(result.begin(), result.end(), [](int x) {
            return x;
        });
        bool checkElse = std::any_of(result.begin(), result.end(), [](int x) {
            return !x;
        });
        return std::make_pair(checkThen, checkElse);
    }

    template<class T, REQUIRES("T must be a Token class", std::is_convertible<T*, const Token*>)>
    Progress traverseTok(T* tok, std::function<Progress(T*)> f, bool traverseUnknown, T** out = nullptr) {
        if (Token::Match(tok, "asm|goto|continue|setjmp|longjmp"))
            return Progress::Break;
        else if (Token::Match(tok, "return|throw") || isEscapeFunction(tok, &settings->library)) {
            traverseRecursive(tok->astOperand1(), f, traverseUnknown);
            traverseRecursive(tok->astOperand2(), f, traverseUnknown);
            return Progress::Break;
        } else if (isUnevaluated(tok)) {
            if (out)
                *out = tok->link();
            return Progress::Skip;
        } else if (tok->astOperand1() && tok->astOperand2() && Token::Match(tok, "?|&&|%oror%")) {
            if (traverseConditional(tok, f, traverseUnknown) == Progress::Break)
                return Progress::Break;
            if (out)
                *out = nextAfterAstRightmostLeaf(tok);
            return Progress::Skip;
            // Skip lambdas
        } else if (T* lambdaEndToken = findLambdaEndToken(tok)) {
            if (checkScope(lambdaEndToken).isModified())
                return Progress::Break;
            if (out)
                *out = lambdaEndToken->next();
            // Skip class scope
        } else if (tok->str() == "{" && tok->scope() && tok->scope()->isClassOrStruct()) {
            if (out)
                *out = tok->link();
        } else {
            if (f(tok) == Progress::Break)
                return Progress::Break;
        }
        return Progress::Continue;
    }

    template<class T, REQUIRES("T must be a Token class", std::is_convertible<T*, const Token*>)>
    Progress traverseRecursive(T* tok, std::function<Progress(T*)> f, bool traverseUnknown, unsigned int recursion=0) {
        if (!tok)
            return Progress::Continue;
        if (recursion > 10000)
            return Progress::Skip;
        // Evaluate RHS of assignment before LHS
        if (tok->astOperand1() && traverseRecursive(tok->astOperand1(), f, traverseUnknown, recursion+1) == Progress::Break)
            return Progress::Break;
        Progress p = traverseTok(tok, f, traverseUnknown);
        if (p == Progress::Break)
            return Progress::Break;
        if (p == Progress::Continue && tok->astOperand2() && traverseRecursive(tok->astOperand2(), f, traverseUnknown, recursion+1) == Progress::Break)
            return Progress::Break;
        return Progress::Continue;
    }

    template<class T, class F, REQUIRES("T must be a Token class", std::is_convertible<T*, const Token*>)>
    Progress traverseConditional(T* tok, F f, bool traverseUnknown) {
        if (Token::Match(tok, "?|&&|%oror%") && tok->astOperand1() && tok->astOperand2()) {
            T* condTok = tok->astOperand1();
            T* childTok = tok->astOperand2();
            bool checkThen, checkElse;
            std::tie(checkThen, checkElse) = evalCond(condTok);
            if (!checkThen && !checkElse) {
                // Stop if the value is conditional
                if (!traverseUnknown && analyzer->isConditional())
                    return Progress::Break;
                checkThen = true;
                checkElse = true;
            }
            if (childTok->str() == ":") {
                if (checkThen && traverseRecursive(childTok->astOperand1(), f, traverseUnknown) == Progress::Break)
                    return Progress::Break;
                if (checkElse && traverseRecursive(childTok->astOperand2(), f, traverseUnknown) == Progress::Break)
                    return Progress::Break;
            } else {
                if (!checkThen && tok->str() == "&&")
                    return Progress::Continue;
                if (!checkElse && tok->str() == "||")
                    return Progress::Continue;
                if (traverseRecursive(childTok, f, traverseUnknown) == Progress::Break)
                    return Progress::Break;
            }
        }
        return Progress::Continue;
    }

    Progress update(Token* tok) {
        ForwardAnalyzer::Action action = analyzer->analyze(tok);
        if (!action.isNone())
            analyzer->update(tok, action);
        if (action.isInconclusive() && !analyzer->lowerToInconclusive())
            return Progress::Break;
