    std::cout << std::string(indent, ' ') << nodeType;
    for (auto tok: mExtTokens)
        std::cout << " " << tok;
    std::cout << std::endl;
    for (int c = 0; c < children.size(); ++c) {
        if (children[c])
            children[c]->dumpAst(c, indent + 2);
        else
            std::cout << std::string(indent + 2, ' ') << "<<<<NULL>>>>>" << std::endl;
    }
}

void clangimport::AstNode::setLocations(TokenList *tokenList, int file, int line, int col)
{
    for (const std::string &ext: mExtTokens) {
        if (ext.compare(0,5,"<col:") == 0)
            col = std::atoi(ext.substr(5).c_str());
        else if (ext.compare(0,6,"<line:") == 0) {
            line = std::atoi(ext.substr(6).c_str());
            if (ext.find(", col:") != std::string::npos)
                col = std::atoi(ext.c_str() + ext.find(", col:") + 6);
        } else if (ext[0] == '<' && ext.find(":") != std::string::npos) {
            std::string::size_type sep1 = ext.find(":");
            std::string::size_type sep2 = ext.find(":", sep1+1);
            file = tokenList->appendFileIfNew(ext.substr(1, sep1 - 1));
            line = MathLib::toLongNumber(ext.substr(sep1+1, sep2-sep1));
        }
    }
    mFile = file;
    mLine = line;
    mCol = col;
    for (auto child: children) {
        if (child)
            child->setLocations(tokenList, file, line, col);
    }
}

Token *clangimport::AstNode::addtoken(TokenList *tokenList, const std::string &str, bool valueType)
{
    const Scope *scope = getNestedInScope(tokenList);
    tokenList->addtoken(str, mLine, mCol, mFile);
    tokenList->back()->scope(scope);
    if (valueType)
        setValueType(tokenList->back());
    return tokenList->back();
}

const ::Type * clangimport::AstNode::addTypeTokens(TokenList *tokenList, const std::string &str, const Scope *scope)
{
    if (str.find("\':\'") != std::string::npos) {
        return addTypeTokens(tokenList, str.substr(0, str.find("\':\'") + 1), scope);
    }


    std::string type;
    if (str.find(" (") != std::string::npos) {
        if (str.find("<") != std::string::npos)
            type = str.substr(1, str.find("<")) + "...>";
        else
            type = str.substr(1,str.find(" (")-1);
    } else
        type = unquote(str);

    for (const std::string &s: splitString(type))
        addtoken(tokenList, s, false);

    // Set Type
    if (!scope) {
        scope = tokenList->back() ? tokenList->back()->scope() : nullptr;
        if (!scope)
            return nullptr;
    }
    for (const Token *typeToken = tokenList->back(); Token::Match(typeToken, "&|*|%name%"); typeToken = typeToken->previous()) {
        if (!typeToken->isName())
            continue;
        const ::Type *recordType = scope->check->findVariableType(scope, typeToken);
        if (recordType) {
            const_cast<Token*>(typeToken)->type(recordType);
            return recordType;
        }
    }
    return nullptr;
}

void clangimport::AstNode::addFullScopeNameTokens(TokenList *tokenList, const Scope *recordScope)
{
    if (!recordScope)
        return;
    std::list<const Scope *> scopes;
    while (recordScope && recordScope != tokenList->back()->scope() && !recordScope->isExecutable()) {
        scopes.push_front(recordScope);
        recordScope = recordScope->nestedIn;
    }
    for (const Scope *s: scopes) {
        if (!s->className.empty()) {
            addtoken(tokenList, s->className);
            addtoken(tokenList, "::");
        }
    }
}

