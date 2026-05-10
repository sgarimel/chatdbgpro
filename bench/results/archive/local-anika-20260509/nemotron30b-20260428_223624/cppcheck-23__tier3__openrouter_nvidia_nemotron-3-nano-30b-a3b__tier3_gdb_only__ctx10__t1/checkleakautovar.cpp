                // Check if its a pointer to a function
                const Token * dtok = Token::findmatch(deleterToken, "& %name%", endDeleterToken);
                if (dtok) {
                    af = mSettings->library.getDeallocFuncInfo(dtok->tokAt(1));
                } else {
                    const Token * tscopeStart = nullptr;
                    const Token * tscopeEnd = nullptr;
                    // If the deleter is a lambda, check if it calls the dealloc function
                    if (deleterToken->str() == "[" &&
                        Token::simpleMatch(deleterToken->link(), "] (") &&
                        // TODO: Check for mutable keyword
                        Token::simpleMatch(deleterToken->link()->linkAt(1), ") {")) {
                        tscopeStart = deleterToken->link()->linkAt(1)->tokAt(1);
                        tscopeEnd = tscopeStart->link();
                        // If the deleter is a class, check if class calls the dealloc function
                    } else if ((dtok = Token::findmatch(deleterToken, "%type%", endDeleterToken)) && dtok->type()) {
                        const Scope * tscope = dtok->type()->classScope;
                        if (tscope) {
                            tscopeStart = tscope->bodyStart;
                            tscopeEnd = tscope->bodyEnd;
                        }
                    }

                    if (tscopeStart && tscopeEnd) {
                        for (const Token *tok2 = tscopeStart; tok2 != tscopeEnd; tok2 = tok2->next()) {
                            af = mSettings->library.getDeallocFuncInfo(tok2);
                            if (af)
                                break;
                        }
                    }
                }
            }

            const Token * vtok = typeEndTok->tokAt(3);
            const VarInfo::AllocInfo allocation(af ? af->groupId : (arrayDelete ? NEW_ARRAY : NEW), VarInfo::OWNED, ftok);
            changeAllocStatus(varInfo, allocation, vtok, vtok);
        }
    }
}


const Token * CheckLeakAutoVar::checkTokenInsideExpression(const Token * const tok, VarInfo *varInfo)
{
    // Deallocation and then dereferencing pointer..
    if (tok->varId() > 0) {
        // TODO : Write a separate checker for this that uses valueFlowForward.
        const std::map<int, VarInfo::AllocInfo>::const_iterator var = varInfo->alloctype.find(tok->varId());
        if (var != varInfo->alloctype.end()) {
            bool unknown = false;
            if (var->second.status == VarInfo::DEALLOC && CheckNullPointer::isPointerDeRef(tok, unknown, mSettings) && !unknown) {
                deallocUseError(tok, tok->str());
            } else if (Token::simpleMatch(tok->tokAt(-2), "= &")) {
                varInfo->erase(tok->varId());
            } else if (Token::Match(tok->previous(), "= %var% [;,)]")) {
                varInfo->erase(tok->varId());
            }
        } else if (Token::Match(tok->previous(), "& %name% = %var% ;")) {
            varInfo->referenced.insert(tok->tokAt(2)->varId());
        }
    }

    // check for function call
    const Token * const openingPar = isFunctionCall(tok);
    if (openingPar) {
        const Library::AllocFunc* allocFunc = mSettings->library.getDeallocFuncInfo(tok);
        VarInfo::AllocInfo alloc(allocFunc ? allocFunc->groupId : 0, VarInfo::DEALLOC, tok);
        if (alloc.type == 0)
            alloc.status = VarInfo::NOALLOC;
        functionCall(tok, openingPar, varInfo, alloc, nullptr);
        return openingPar->link();
    }

    return nullptr;
}


void CheckLeakAutoVar::changeAllocStatusIfRealloc(std::map<int, VarInfo::AllocInfo> &alloctype, const Token *fTok, const Token *retTok)
{
    const Library::AllocFunc* f = mSettings->library.getReallocFuncInfo(fTok);
    if (f && f->arg == -1 && f->reallocArg > 0 && f->reallocArg <= numberOfArguments(fTok)) {
        const Token* argTok = getArguments(fTok).at(f->reallocArg - 1);
        VarInfo::AllocInfo& argAlloc = alloctype[argTok->varId()];
        VarInfo::AllocInfo& retAlloc = alloctype[retTok->varId()];
        if (argAlloc.type != 0 && argAlloc.type != f->groupId)
            mismatchError(fTok, argAlloc.allocTok, argTok->str());
        argAlloc.status = VarInfo::DEALLOC;
        argAlloc.allocTok = fTok;
        retAlloc.type = f->groupId;
        retAlloc.status = VarInfo::ALLOC;
        retAlloc.allocTok = fTok;
    }
}


void CheckLeakAutoVar::changeAllocStatus(VarInfo *varInfo, const VarInfo::AllocInfo& allocation, const Token* tok, const Token* arg)
{
    std::map<int, VarInfo::AllocInfo> &alloctype = varInfo->alloctype;
    const std::map<int, VarInfo::AllocInfo>::iterator var = alloctype.find(arg->varId());
    if (var != alloctype.end()) {
        if (allocation.status == VarInfo::NOALLOC) {
            // possible usage
