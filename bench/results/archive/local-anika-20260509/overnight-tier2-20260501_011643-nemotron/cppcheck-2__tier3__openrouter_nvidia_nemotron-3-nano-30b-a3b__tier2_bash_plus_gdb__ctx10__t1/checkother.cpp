                    const std::string strDim = MathLib::toString(dim);
                    checkPipeParameterSizeError(varTok,varTok->str(), strDim);
                }
            }
        }
    }
}

void CheckOther::checkPipeParameterSizeError(const Token *tok, const std::string &strVarName, const std::string &strDim)
{
    reportError(tok, Severity::error,
                "wrongPipeParameterSize",
                "$symbol:" + strVarName + "\n"
                "Buffer '$symbol' must have size of 2 integers if used as parameter of pipe().\n"
                "The pipe()/pipe2() system command takes an argument, which is an array of exactly two integers.\n"
                "The variable '$symbol' is an array of size " + strDim + ", which does not match.", CWE686, false);
}

//---------------------------------------------------------------------------
// Detect redundant assignments: x = 0; x = 4;
//---------------------------------------------------------------------------

void CheckOther::checkRedundantAssignment()
{
    if (!mSettings->isEnabled(Settings::STYLE))
        return;
    const SymbolDatabase* symbolDatabase = mTokenizer->getSymbolDatabase();
    for (const Scope *scope : symbolDatabase->functionScopes) {
        if (!scope->bodyStart)
            continue;
        for (const Token* tok = scope->bodyStart->next(); tok != scope->bodyEnd; tok = tok->next()) {
            if (Token::simpleMatch(tok, "] ("))
                // todo: handle lambdas
                break;
            if (Token::simpleMatch(tok, "try {"))
                // todo: check try blocks
                tok = tok->linkAt(1);
            if ((tok->isAssignmentOp() || Token::Match(tok, "++|--")) && tok->astOperand1()) {
                if (tok->astParent())
                    continue;

                // Do not warn about redundant initialization when rhs is trivial
                // TODO : do not simplify the variable declarations
                bool isInitialization = false;
                if (Token::Match(tok->tokAt(-3), "%var% ; %var% =") && tok->previous()->variable() && tok->previous()->variable()->nameToken() == tok->tokAt(-3) && tok->tokAt(-3)->linenr() == tok->previous()->linenr()) {
                    isInitialization = true;
                    bool trivial = true;
                    visitAstNodes(tok->astOperand2(),
                    [&](const Token *rhs) {
                        if (Token::simpleMatch(rhs, "{ 0 }"))
                            return ChildrenToVisit::none;
                        if (Token::Match(rhs, "%str%|%num%|%name%") && !rhs->varId())
                            return ChildrenToVisit::none;
                        if (rhs->isCast())
                            return ChildrenToVisit::op2;
                        trivial = false;
                        return ChildrenToVisit::done;
                    });
                    if (trivial)
                        continue;
                }

                // Do not warn about assignment with 0 / NULL
                if (Token::simpleMatch(tok->astOperand2(), "0") || FwdAnalysis::isNullOperand(tok->astOperand2()))
                    continue;

                if (tok->astOperand1()->variable() && tok->astOperand1()->variable()->isReference())
                    // todo: check references
                    continue;

                if (tok->astOperand1()->variable() && tok->astOperand1()->variable()->isStatic())
                    // todo: check static variables
                    continue;

                // If there is a custom assignment operator => this is inconclusive
                bool inconclusive = false;
                if (mTokenizer->isCPP() && tok->astOperand1()->valueType() && tok->astOperand1()->valueType()->typeScope) {
                    const std::string op = "operator" + tok->str();
                    for (const Function &f : tok->astOperand1()->valueType()->typeScope->functionList) {
                        if (f.name() == op) {
                            inconclusive = true;
                            break;
                        }
                    }
                }
                if (inconclusive && !mSettings->inconclusive)
                    continue;

                FwdAnalysis fwdAnalysis(mTokenizer->isCPP(), mSettings->library);
                if (fwdAnalysis.hasOperand(tok->astOperand2(), tok->astOperand1()))
                    continue;

                // Is there a redundant assignment?
                const Token *start;
                if (tok->isAssignmentOp())
                    start = tok->next();
                else
                    start = tok->findExpressionStartEndTokens().second->next();

                // Get next assignment..
                const Token *nextAssign = fwdAnalysis.reassign(tok->astOperand1(), start, scope->bodyEnd);
