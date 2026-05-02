                    if (!tok->valueType())
                        continue;
                    bool check = false;
                    switch (tok->valueType()->type) {
                    case ValueType::Type::UNKNOWN_TYPE:
                    case ValueType::Type::NONSTD:
                    case ValueType::Type::RECORD:
                        check = tok->valueType()->typeScope && !tok->valueType()->typeScope->getDestructor();
                        break;
                    case ValueType::Type::CONTAINER:
                    case ValueType::Type::ITERATOR:
                    case ValueType::Type::VOID:
                    case ValueType::Type::BOOL:
                    case ValueType::Type::CHAR:
                    case ValueType::Type::SHORT:
                    case ValueType::Type::WCHAR_T:
                    case ValueType::Type::INT:
                    case ValueType::Type::LONG:
                    case ValueType::Type::LONGLONG:
                    case ValueType::Type::UNKNOWN_INT:
                    case ValueType::Type::FLOAT:
                    case ValueType::Type::DOUBLE:
                    case ValueType::Type::LONGDOUBLE:
                        check = true;
                        break;
                    };
                    if (!check)
                        continue;
                }
                tok = tok->next();
            }
            if (tok->astParent() && tok->str() != "(") {
                const Token *parent = tok->astParent();
                while (Token::Match(parent, "%oror%|%comp%|!|&&"))
                    parent = parent->astParent();
                if (!parent)
                    continue;
                if (!Token::simpleMatch(parent->previous(), "if ("))
                    continue;
            }
            // Do not warn about assignment with NULL
            if (FwdAnalysis::isNullOperand(tok->astOperand2()))
                continue;

            if (!tok->astOperand1())
                continue;

            const Token *iteratorToken = tok->astOperand1();
            while (Token::Match(iteratorToken, "[.*]"))
                iteratorToken = iteratorToken->astOperand1();
            if (iteratorToken && iteratorToken->variable() && iteratorToken->variable()->typeEndToken()->str().find("iterator") != std::string::npos)
                continue;


            const Variable *op1Var = tok->astOperand1() ? tok->astOperand1()->variable() : nullptr;
            if (op1Var && op1Var->isReference() && op1Var->nameToken() != tok->astOperand1())
                // todo: check references
                continue;

            if (op1Var && op1Var->isStatic())
                // todo: check static variables
                continue;

            if (op1Var && op1Var->nameToken()->isAttributeUnused())
                continue;

            // Is there a redundant assignment?
            const Token *start = tok->findExpressionStartEndTokens().second->next();

            const Token *expr = varDecl ? varDecl : tok->astOperand1();

            FwdAnalysis fwdAnalysis(mTokenizer->isCPP(), mSettings->library);
            if (fwdAnalysis.unusedValue(expr, start, scope->bodyEnd))
                // warn
                unreadVariableError(tok, expr->expressionString(), false);
        }

        // varId, usage {read, write, modified}
        Variables variables;

        checkFunctionVariableUsage_iterateScopes(scope, variables);


        // Check usage of all variables in the current scope..
        for (std::map<unsigned int, Variables::VariableUsage>::const_iterator it = variables.varUsage().begin();
             it != variables.varUsage().end();
             ++it) {
            const Variables::VariableUsage &usage = it->second;

            // variable has been marked as unused so ignore it
            if (usage._var->nameToken()->isAttributeUnused() || usage._var->nameToken()->isAttributeUsed())
                continue;

            // skip things that are only partially implemented to prevent false positives
            if (usage.mType == Variables::pointerPointer ||
                usage.mType == Variables::pointerArray ||
                usage.mType == Variables::referenceArray)
                continue;

            const std::string &varname = usage._var->name();
            const Variable* var = symbolDatabase->getVariableFromVarId(it->first);
