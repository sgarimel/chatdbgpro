            if (tok->previous()->str() == "=")
                tok = tok->link();
            else
                ++indentLevel;
        } else if (tok->str() == "}") {
            --indentLevel;
            if (indentLevel == 0) {
                executablescope = false;
                continue;
            }
        } else if (Token::Match(tok, "(|["))
            tok = tok->link();

        if (Token::Match(tok, "[;{}:] case")) {
            while (nullptr != (tok = tok->next())) {
                if (Token::Match(tok, "(|[")) {
                    tok = tok->link();
                } else if (tok->str() == "?") {
                    Token *tok1 = skipTernaryOp(tok);
                    if (!tok1) {
                        syntaxError(tok);
                    }
                    tok = tok1;
                }
                if (Token::Match(tok->next(),"[:{};]"))
                    break;
            }
            if (!tok)
                break;
            if (tok->str() != "case" && tok->next() && tok->next()->str() == ":") {
                tok = tok->next();
                if (!tok->next())
                    syntaxError(tok);
                if (tok->next()->str() != ";" && tok->next()->str() != "case")
                    tok->insertToken(";");
                else
                    tok = tok->previous();
            } else {
                syntaxError(tok);
            }
        } else if (Token::Match(tok, "[;{}] %name% : !!;")) {
            if (!cpp || !Token::Match(tok->next(), "class|struct|enum")) {
                tok = tok->tokAt(2);
                tok->insertToken(";");
            }
        }
    }
}


void Tokenizer::simplifyCaseRange()
{
    for (Token* tok = list.front(); tok; tok = tok->next()) {
        if (Token::Match(tok, "case %num% ... %num% :")) {
            const MathLib::bigint start = MathLib::toLongNumber(tok->strAt(1));
            MathLib::bigint end = MathLib::toLongNumber(tok->strAt(3));
            end = std::min(start + 50, end); // Simplify it 50 times at maximum
            if (start < end) {
                tok = tok->tokAt(2);
                tok->str(":");
                tok->insertToken("case");
                for (MathLib::bigint i = end-1; i > start; i--) {
                    tok->insertToken(":");
                    tok->insertToken(MathLib::toString(i));
                    tok->insertToken("case");
                }
            }
        } else if (Token::Match(tok, "case %char% ... %char% :")) {
            const char start = tok->strAt(1)[1];
            const char end = tok->strAt(3)[1];
            if (start < end) {
                tok = tok->tokAt(2);
                tok->str(":");
                tok->insertToken("case");
                for (char i = end - 1; i > start; i--) {
                    tok->insertToken(":");
                    if (i == '\\') {
                        tok->insertToken(std::string("\'\\") + i + '\'');
                    } else {
                        tok->insertToken(std::string(1, '\'') + i + '\'');
                    }
                    tok->insertToken("case");
                }
            }
        }
    }
}

void Tokenizer::calculateScopes()
{
    for (auto *tok = list.front(); tok; tok = tok->next())
        tok->scopeInfo(nullptr);

    std::string nextScopeNameAddition;
    std::shared_ptr<ScopeInfo2> primaryScope = std::make_shared<ScopeInfo2>("", nullptr);
    list.front()->scopeInfo(primaryScope);

    for (Token* tok = list.front(); tok; tok = tok->next()) {
        if (tok == list.front() || !tok->scopeInfo()) {
            if (tok != list.front())
                tok->scopeInfo(tok->previous()->scopeInfo());
