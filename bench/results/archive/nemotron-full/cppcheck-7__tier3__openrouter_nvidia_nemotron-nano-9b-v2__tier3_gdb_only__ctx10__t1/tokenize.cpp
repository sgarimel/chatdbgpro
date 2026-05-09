                }
            }

            if (removeUnusedTemplates || (isIncluded && removeUnusedIncludedTemplates)) {
                if (Token::Match(tok->next(), "template < %name%")) {
                    const Token *tok2 = tok->tokAt(3);
                    while (Token::Match(tok2, "%name% %name% [,=>]") || Token::Match(tok2, "typename ... %name% [,>]")) {
                        if (Token::simpleMatch(tok2, "typename ..."))
                            tok2 = tok2->tokAt(3);
                        else
                            tok2 = tok2->tokAt(2);
                        if (Token::Match(tok2, "= %name% [,>]"))
                            tok2 = tok2->tokAt(2);
                        if (tok2->str() == ",")
                            tok2 = tok2->next();
                    }
                    if (Token::Match(tok2, "> class|struct %name% [;:{]") && keep.find(tok2->strAt(2)) == keep.end()) {
                        const Token *endToken = tok2->tokAt(3);
                        if (endToken->str() == ":") {
                            endToken = endToken->next();
                            while (Token::Match(endToken, "%name%|,"))
                                endToken = endToken->next();
                        }
                        if (endToken && endToken->str() == "{")
                            endToken = endToken->link()->next();
                        if (endToken && endToken->str() == ";")
                            Token::eraseTokens(tok, endToken);
                    } else if (Token::Match(tok2, "> %type% %name% (") && Token::simpleMatch(tok2->linkAt(3), ") {") && keep.find(tok2->strAt(2)) == keep.end()) {
                        const Token *endToken = tok2->linkAt(3)->linkAt(1)->next();
                        Token::eraseTokens(tok, endToken);
                    }
                }
            }
        }
    }
}

void Tokenizer::removeMacrosInGlobalScope()
{
    for (Token *tok = list.front(); tok; tok = tok->next()) {
        if (tok->str() == "(") {
            tok = tok->link();
            if (Token::Match(tok, ") %type% {") &&
                !Token::Match(tok->next(), "const|namespace|class|struct|union|noexcept|override|final|volatile"))
                tok->deleteNext();
        }

        if (Token::Match(tok, "%type%") && tok->isUpperCaseName() &&
            (!tok->previous() || Token::Match(tok->previous(), "[;{}]") || (tok->previous()->isName() && endsWith(tok->previous()->str(), ':')))) {
            const Token *tok2 = tok->next();
            if (tok2 && tok2->str() == "(")
                tok2 = tok2->link()->next();


            if (Token::Match(tok, "%name% (") && Token::Match(tok2, "%name% *|&|::|<| %name%") && !Token::Match(tok2, "namespace|class|struct|union"))
                unknownMacroError(tok);

            if (Token::Match(tok, "%type% (") && Token::Match(tok2, "%type% (") && !Token::Match(tok2, "noexcept|throw") && isFunctionHead(tok2->next(), ":;{"))
                unknownMacroError(tok);

            // remove unknown macros before namespace|class|struct|union
            if (Token::Match(tok2, "namespace|class|struct|union")) {
                // is there a "{" for?
                const Token *tok3 = tok2;
                while (tok3 && !Token::Match(tok3,"[;{}()]"))
                    tok3 = tok3->next();
                if (tok3 && tok3->str() == "{") {
                    Token::eraseTokens(tok, tok2);
                    tok->deleteThis();
                }
                continue;
            }

            // replace unknown macros before foo(
            /*
                        if (Token::Match(tok2, "%type% (") && isFunctionHead(tok2->next(), "{")) {
                            std::string typeName;
                            for (const Token* tok3 = tok; tok3 != tok2; tok3 = tok3->next())
                                typeName += tok3->str();
                            Token::eraseTokens(tok, tok2);
                            tok->str(typeName);
                        }
            */
            // remove unknown macros before foo::foo(
            if (Token::Match(tok2, "%type% :: %type%")) {
                const Token *tok3 = tok2;
                while (Token::Match(tok3, "%type% :: %type% ::"))
                    tok3 = tok3->tokAt(2);
                if (Token::Match(tok3, "%type% :: %type% (") && tok3->str() == tok3->strAt(2)) {
                    Token::eraseTokens(tok, tok2);
                    tok->deleteThis();
                }
                continue;
            }
        }

        // Skip executable scopes
        if (tok->str() == "{") {
            const Token *prev = tok->previous();
            while (prev && prev->isName())
                prev = prev->previous();
