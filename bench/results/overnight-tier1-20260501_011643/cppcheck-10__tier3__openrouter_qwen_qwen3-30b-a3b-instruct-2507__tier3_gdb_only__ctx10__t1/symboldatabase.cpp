{
    *this = var;
    mScope = scope;
}

Variable::Variable(const Variable &var)
    : mValueType(nullptr)
{
    *this = var;
}

Variable::~Variable()
{
    delete mValueType;
}

Variable& Variable::operator=(const Variable &var)
{
    if (this == &var)
        return *this;

    mNameToken = var.mNameToken;
    mTypeStartToken = var.mTypeStartToken;
    mTypeEndToken = var.mTypeEndToken;
    mIndex = var.mIndex;
    mAccess = var.mAccess;
    mFlags = var.mFlags;
    mType = var.mType;
    mScope = var.mScope;
    mDimensions = var.mDimensions;
    delete mValueType;
    if (var.mValueType)
        mValueType = new ValueType(*var.mValueType);
    else
        mValueType = nullptr;

    return *this;
}

bool Variable::isPointerArray() const
{
    return isArray() && nameToken() && nameToken()->previous() && (nameToken()->previous()->str() == "*");
}

bool Variable::isUnsigned() const
{
    return mValueType ? (mValueType->sign == ValueType::Sign::UNSIGNED) : mTypeStartToken->isUnsigned();
}

const Token * Variable::declEndToken() const
{
    Token const * declEnd = typeStartToken();
    while (declEnd && !Token::Match(declEnd, "[;,)={]")) {
        if (declEnd->link() && Token::Match(declEnd,"(|["))
            declEnd = declEnd->link();
        declEnd = declEnd->next();
    }
    return declEnd;
}

void Variable::evaluate(const Settings* settings)
{
    // Is there initialization in variable declaration
    const Token *initTok = mNameToken ? mNameToken->next() : nullptr;
    while (initTok && initTok->str() == "[")
        initTok = initTok->link()->next();
    if (Token::Match(initTok, "=|{") || (initTok && initTok->isSplittedVarDeclEq()))
        setFlag(fIsInit, true);

    if (!settings)
        return;

    const Library * const lib = &settings->library;

    if (mNameToken)
        setFlag(fIsArray, arrayDimensions(settings));

    if (mTypeStartToken)
        setValueType(ValueType::parseDecl(mTypeStartToken,settings));

    const Token* tok = mTypeStartToken;
    while (tok && tok->previous() && tok->previous()->isName())
        tok = tok->previous();
    const Token* end = mTypeEndToken;
    if (end)
        end = end->next();
    while (tok != end) {
        if (tok->str() == "static")
            setFlag(fIsStatic, true);
        else if (tok->str() == "extern")
            setFlag(fIsExtern, true);
        else if (tok->str() == "volatile" || Token::simpleMatch(tok, "std :: atomic <"))
            setFlag(fIsVolatile, true);
        else if (tok->str() == "mutable")
            setFlag(fIsMutable, true);
        else if (tok->str() == "const")
            setFlag(fIsConst, true);
        else if (tok->str() == "constexpr") {
            setFlag(fIsConst, true);
            setFlag(fIsStatic, true);
        } else if (tok->str() == "*") {
