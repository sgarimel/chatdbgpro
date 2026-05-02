{
    const Token *lastStatement = nullptr;
    while ((tok = tok->previous()) != nullptr) {
        if (tok->str() == "{")
            return lastStatement ? lastStatement : tok->next();
        if (tok->str() == "}") {
            for (const Token *prev = tok->link()->previous(); prev && prev->scope() == tok->scope() && !Token::Match(prev, "[;{}]"); prev = prev->previous()) {
                if (prev->isKeyword() && Token::Match(prev, "return|throw"))
                    return nullptr;
                if (prev->str() == "goto" && !isForwardJump(prev))
                    return nullptr;
            }
            if (tok->scope()->type == Scope::ScopeType::eSwitch) {
                // find reachable break / !default
                bool hasDefault = false;
                bool reachable = false;
                for (const Token *switchToken = tok->link(); switchToken != tok; switchToken = switchToken->next()) {
                    if (reachable && Token::simpleMatch(switchToken, "break ;"))
                        return switchToken;
                    if (switchToken->isKeyword() && Token::Match(switchToken, "return|throw"))
                        reachable = false;
                    if (Token::Match(switchToken, "%name% (") && library.isnoreturn(switchToken))
                        reachable = false;
                    if (Token::Match(switchToken, "case|default"))
                        reachable = true;
                    if (Token::simpleMatch(switchToken, "default :"))
                        hasDefault = true;
                    else if (switchToken->str() == "{" && switchToken->scope()->isLoopScope())
                        switchToken = switchToken->link();
                }
                if (!hasDefault)
                    return tok->link();
            } else if (tok->scope()->type == Scope::ScopeType::eIf) {
                const Token *condition = tok->scope()->classDef->next()->astOperand2();
                if (condition && condition->hasKnownIntValue() && condition->getKnownIntValue() == 1)
                    return checkMissingReturnScope(tok, library);
                return tok;
            } else if (tok->scope()->type == Scope::ScopeType::eElse) {
                const Token *errorToken = checkMissingReturnScope(tok, library);
                if (errorToken)
                    return errorToken;
                tok = tok->link();
                if (Token::simpleMatch(tok->tokAt(-2), "} else {"))
                    return checkMissingReturnScope(tok->tokAt(-2), library);
                return tok;
            }
            // FIXME
            return nullptr;
        }
        if (tok->isKeyword() && Token::Match(tok, "return|throw"))
            return nullptr;
        if (tok->str() == "goto" && !isForwardJump(tok))
            return nullptr;
        if (Token::Match(tok, "%name% (") && library.isnoreturn(tok))
            return nullptr;
        if (Token::Match(tok, "[;{}] %name% :"))
            return tok;
        if (Token::Match(tok, "; !!}") && !lastStatement)
            lastStatement = tok->next();
    }
    return nullptr;
}

void CheckFunctions::missingReturnError(const Token* tok)
{
    reportError(tok, Severity::error, "missingReturn",
                "Found a exit path from function with non-void return type that has missing return statement", CWE758, Certainty::normal);
}
//---------------------------------------------------------------------------
// Detect passing wrong values to <cmath> functions like atan(0, x);
//---------------------------------------------------------------------------
void CheckFunctions::checkMathFunctions()
{
    const bool styleC99 = mSettings->severity.isEnabled(Severity::style) && mSettings->standards.c != Standards::C89 && mSettings->standards.cpp != Standards::CPP03;
    const bool printWarnings = mSettings->severity.isEnabled(Severity::warning);

    const SymbolDatabase *symbolDatabase = mTokenizer->getSymbolDatabase();
    for (const Scope *scope : symbolDatabase->functionScopes) {
        for (const Token* tok = scope->bodyStart->next(); tok != scope->bodyEnd; tok = tok->next()) {
            if (tok->varId())
                continue;
            if (printWarnings && Token::Match(tok, "%name% ( !!)")) {
                if (tok->strAt(-1) != "."
                    && Token::Match(tok, "log|logf|logl|log10|log10f|log10l|log2|log2f|log2l ( %num% )")) {
                    const std::string& number = tok->strAt(2);
                    if ((MathLib::isInt(number) && MathLib::toLongNumber(number) <= 0) ||
                        (MathLib::isFloat(number) && MathLib::toDoubleNumber(number) <= 0.))
                        mathfunctionCallWarning(tok);
                } else if (Token::Match(tok, "log1p|log1pf|log1pl ( %num% )")) {
                    const std::string& number = tok->strAt(2);
                    if ((MathLib::isInt(number) && MathLib::toLongNumber(number) <= -1) ||
                        (MathLib::isFloat(number) && MathLib::toDoubleNumber(number) <= -1.))
                        mathfunctionCallWarning(tok);
                }
                // atan2 ( x , y): x and y can not be zero, because this is mathematically not defined
                else if (Token::Match(tok, "atan2|atan2f|atan2l ( %num% , %num% )")) {
                    if (MathLib::isNullValue(tok->strAt(2)) && MathLib::isNullValue(tok->strAt(4)))
                        mathfunctionCallWarning(tok, 2);
                }
                // fmod ( x , y) If y is zero, then either a range error will occur or the function will return zero (implementation-defined).
                else if (Token::Match(tok, "fmod|fmodf|fmodl (")) {
