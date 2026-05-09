        for (const Token* tok = start; tok && tok != end; tok = tok->next()) {
            ForwardAnalyzer::Action action = analyzer->analyze(tok);
            if (action.isModified() || action.isInconclusive())
                return action;
            result = action;
        }
        return result;
    }

    void forkScope(Token* endBlock, bool isModified = false) {
        if (analyzer->updateScope(endBlock, isModified)) {
            ForwardTraversal ft = *this;
            ft.updateRange(endBlock->link(), endBlock);
        }
    }

    static bool hasGoto(const Token* endBlock) {
        return Token::findsimplematch(endBlock->link(), "goto", endBlock);
    }

    bool isEscapeScope(const Token* endBlock, bool unknown = false) {
        const Token* ftok = nullptr;
        bool r = isReturnScope(endBlock, &settings->library, &ftok);
        if (!r && ftok)
            return unknown;
        return r;
    }

    enum class Status {
        None,
        Escaped,
        Modified,
        Inconclusive,
    };

    ForwardAnalyzer::Action analyzeScope(const Token* endBlock) {
        return analyzeRange(endBlock->link(), endBlock);
    }

    ForwardAnalyzer::Action checkScope(Token* endBlock) {
        ForwardAnalyzer::Action a = analyzeScope(endBlock);
        forkScope(endBlock, a.isModified());
        return a;
    }

    ForwardAnalyzer::Action checkScope(const Token* endBlock) {
        ForwardAnalyzer::Action a = analyzeScope(endBlock);
        return a;
    }

    Progress updateLoop(Token* endBlock, Token* condTok, Token* initTok = nullptr, Token* stepTok = nullptr) {
        ForwardAnalyzer::Action bodyAnalysis = analyzeScope(endBlock);
        ForwardAnalyzer::Action allAnalysis = bodyAnalysis;
        if (initTok)
            allAnalysis |= analyzeRecursive(initTok);
        if (stepTok)
            allAnalysis |= analyzeRecursive(stepTok);
        if (allAnalysis.isInconclusive()) {
            if (!analyzer->lowerToInconclusive())
                return Progress::Break;
        } else if (allAnalysis.isModified()) {
            if (!analyzer->lowerToPossible())
                return Progress::Break;
        }
        // Traverse condition after lowering
        if (condTok) {
            if (updateRecursive(condTok) == Progress::Break)
                return Progress::Break;

            bool checkThen, checkElse;
            std::tie(checkThen, checkElse) = evalCond(condTok);
            if (checkElse)
                // condition is false, we don't enter the loop
                return Progress::Break;
        }

        forkScope(endBlock, allAnalysis.isModified());
        if (bodyAnalysis.isModified()) {
            Token* writeTok = findRange(endBlock->link(), endBlock, std::mem_fn(&ForwardAnalyzer::Action::isModified));
            const Token* nextStatement = Token::findmatch(writeTok, ";|}", endBlock);
            if (!Token::Match(nextStatement, ";|} break ;"))
                return Progress::Break;
        } else {
            if (stepTok && updateRecursive(stepTok) == Progress::Break)
                return Progress::Break;
        }
        // TODO: Should we traverse the body?
        // updateRange(endBlock->link(), endBlock);
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
