                    }
                }
            }

            const Token * vtok = typeEndTok->tokAt(2);
            const VarInfo::AllocInfo sp_allocation(sp_af ? sp_af->groupId : (arrayDelete ? NEW_ARRAY : NEW), VarInfo::OWNED);
            changeAllocStatus(varInfo, sp_allocation, vtok, vtok);
        } else {
            checkTokenInsideExpression(arg, varInfo);
        }
        // TODO: check each token in argument expression (could contain multiple variables)
        argNr++;
    }
}


void CheckLeakAutoVar::leakIfAllocated(const Token *vartok,
                                       const VarInfo &varInfo)
{
    const std::map<int, VarInfo::AllocInfo> &alloctype = varInfo.alloctype;
    const std::map<int, std::string> &possibleUsage = varInfo.possibleUsage;

    const std::map<int, VarInfo::AllocInfo>::const_iterator var = alloctype.find(vartok->varId());
    if (var != alloctype.end() && var->second.status == VarInfo::ALLOC) {
        const std::map<int, std::string>::const_iterator use = possibleUsage.find(vartok->varId());
        if (use == possibleUsage.end()) {
            leakError(vartok, vartok->str(), var->second.type);
        } else {
            configurationInfo(vartok, use->second);
        }
    }
}

void CheckLeakAutoVar::ret(const Token *tok, const VarInfo &varInfo)
{
    const std::map<int, VarInfo::AllocInfo> &alloctype = varInfo.alloctype;
    const std::map<int, std::string> &possibleUsage = varInfo.possibleUsage;

    const SymbolDatabase *symbolDatabase = mTokenizer->getSymbolDatabase();
    for (std::map<int, VarInfo::AllocInfo>::const_iterator it = alloctype.begin(); it != alloctype.end(); ++it) {
        // don't warn if variable is conditionally allocated
        if (!it->second.managed() && varInfo.conditionalAlloc.find(it->first) != varInfo.conditionalAlloc.end())
            continue;

        // don't warn if there is a reference of the variable
        if (varInfo.referenced.find(it->first) != varInfo.referenced.end())
            continue;

        const int varid = it->first;
        const Variable *var = symbolDatabase->getVariableFromVarId(varid);
        if (var) {
            bool used = false;
            for (const Token *tok2 = tok; tok2; tok2 = tok2->next()) {
                if (tok2->str() == ";")
                    break;
                if (Token::Match(tok2, "return|(|{|, %varid% [});,]", varid)) {
                    used = true;
                    break;
                }
                if (Token::Match(tok2, "return|(|{|, & %varid% . %name% [});,]", varid)) {
                    used = true;
                    break;
                }
            }

            // return deallocated pointer
            if (used && it->second.status == VarInfo::DEALLOC)
                deallocReturnError(tok, var->name());

            else if (!used && !it->second.managed()) {
                const std::map<int, std::string>::const_iterator use = possibleUsage.find(varid);
                if (use == possibleUsage.end()) {
                    leakError(tok, var->name(), it->second.type);
                } else {
                    configurationInfo(tok, use->second);
                }
            }
        }
    }
}
