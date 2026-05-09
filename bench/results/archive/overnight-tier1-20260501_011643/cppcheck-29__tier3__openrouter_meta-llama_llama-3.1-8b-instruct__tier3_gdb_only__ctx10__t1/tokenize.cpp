
    for (Token *tok = list.front(); tok; tok = tok->next()) {
        if (Token::Match(tok, "using|:: operator %op% ;")) {
            tok->next()->str("operator" + tok->strAt(2));
            tok->next()->deleteNext();
            continue;
        }

        if (tok->str() != "operator")
            continue;
        // operator op
        std::string op;
        Token *par = tok->next();
        bool done = false;
        while (!done && par) {
            done = true;
            if (par->isName()) {
                op += par->str();
                par = par->next();
                // merge namespaces eg. 'operator std :: string () const {'
                if (Token::Match(par, ":: %name%|%op%|.")) {
                    op += par->str();
                    par = par->next();
                }
                done = false;
            } else if (Token::Match(par, ".|%op%|,")) {
                // check for operator in template
                if (!(Token::Match(par, "<|>") && !op.empty())) {
                    op += par->str();
                    par = par->next();
                    done = false;
                }
            } else if (Token::simpleMatch(par, "[ ]")) {
                op += "[]";
                par = par->tokAt(2);
                done = false;
            } else if (Token::Match(par, "( *| )")) {
                // break out and simplify..
                if (operatorEnd(par->next()))
                    break;

                while (par->str() != ")") {
                    op += par->str();
                    par = par->next();
                }
                op += ")";
                par = par->next();
                done = false;
            } else if (Token::Match(par, "\"\" %name% (")) {
                op += "\"\"";
                op += par->strAt(1);
                par = par->tokAt(2);
                done = true;
            }
        }

        if (par && (Token::Match(par, "<|>") || isFunctionHead(par, "{|;"))) {
            tok->str("operator" + op);
            Token::eraseTokens(tok, par);
        }

        if (!op.empty())
            tok->isOperatorKeyword(true);
    }

    if (mSettings->debugwarnings) {
        const Token *tok = list.front();

        while ((tok = Token::findsimplematch(tok, "operator")) != nullptr) {
            reportError(tok, Severity::debug, "debug",
                        "simplifyOperatorName: found unsimplified operator name");
            tok = tok->next();
        }
    }
}

// remove unnecessary member qualification..
void Tokenizer::removeUnnecessaryQualification()
{
    if (isC())
        return;

    std::vector<Space> classInfo;
    for (Token *tok = list.front(); tok; tok = tok->next()) {
        if (Token::Match(tok, "class|struct|namespace %type% :|{") &&
            (!tok->previous() || tok->previous()->str() != "enum")) {
            Space info;
            info.isNamespace = tok->str() == "namespace";
            tok = tok->next();
            info.className = tok->str();
            tok = tok->next();
            while (tok && tok->str() != "{")
                tok = tok->next();
            if (!tok)
                return;
            info.bodyEnd = tok->link();
            classInfo.push_back(info);
        } else if (!classInfo.empty()) {
            if (tok == classInfo.back().bodyEnd)
                classInfo.pop_back();
            else if (tok->str() == classInfo.back().className &&
