        });
        return std::make_pair(checkThen, checkElse);
    }

    bool update(Token* tok) {
        Analyzer::Action action = analyzer->analyze(tok, Analyzer::Direction::Reverse);
        if (!action.isNone())
            analyzer->update(tok, action, Analyzer::Direction::Reverse);
        if (action.isInconclusive() && !analyzer->lowerToInconclusive())
            return false;
        if (action.isInvalid())
            return false;
        return true;
    }

    bool updateRecursive(Token* start) {
        bool continueB = true;
        visitAstNodes(start, [&](Token* tok) {
            continueB &= update(tok);
            if (continueB)
                return ChildrenToVisit::op1_and_op2;
            else
                return ChildrenToVisit::done;
        });
        return continueB;
    }

    Analyzer::Action analyzeRecursive(const Token* start) {
        Analyzer::Action result = Analyzer::Action::None;
        visitAstNodes(start, [&](const Token* tok) {
            result |= analyzer->analyze(tok, Analyzer::Direction::Reverse);
            if (result.isModified())
                return ChildrenToVisit::done;
            return ChildrenToVisit::op1_and_op2;
        });
        return result;
    }

    Analyzer::Action analyzeRange(const Token* start, const Token* end) {
        Analyzer::Action result = Analyzer::Action::None;
        for (const Token* tok = start; tok && tok != end; tok = tok->next()) {
            Analyzer::Action action = analyzer->analyze(tok, Analyzer::Direction::Reverse);
            if (action.isModified())
                return action;
            result |= action;
        }
        return result;
    }

    Token* isDeadCode(Token* tok) {
        int opSide = 0;
        for (; tok && tok->astParent(); tok = tok->astParent()) {
            Token* parent = tok->astParent();
            if (tok != parent->astOperand2())
                continue;
            if (Token::simpleMatch(parent, ":")) {
                if (astIsLHS(tok))
                    opSide = 1;
                else if (astIsRHS(tok))
                    opSide = 2;
                else
                    opSide = 0;
            }
            if (!Token::Match(parent, "%oror%|&&|?"))
                continue;
            Token* condTok = parent->astOperand1();
            if (!condTok)
                continue;
            bool checkThen, checkElse;
            std::tie(checkThen, checkElse) = evalCond(condTok);

            if (!checkThen && !checkElse) {
                Analyzer::Action action = analyzeRecursive(condTok);
                if (action.isRead() || action.isModified())
                    return parent;
            }

            if (parent->str() == "?") {
                if (!checkElse && opSide == 1)
                    return parent;
                if (!checkThen && opSide == 2)
                    return parent;
            }
            if (!checkThen && parent->str() == "&&")
                return parent;
            if (!checkElse && parent->str() == "||")
                return parent;
        }
        return nullptr;
    }

    void traverse(Token* start, const Token* end = nullptr) {
        if (start == end)
            return;
        for (Token* tok = start->previous(); tok != end; tok = tok->previous()) {
            if (tok == start || (tok->str() == "{" && (tok->scope()->type == Scope::ScopeType::eFunction ||
                                 tok->scope()->type == Scope::ScopeType::eLambda))) {
                break;
            }
            if (Token::Match(tok, "return|break|continue"))
                break;
