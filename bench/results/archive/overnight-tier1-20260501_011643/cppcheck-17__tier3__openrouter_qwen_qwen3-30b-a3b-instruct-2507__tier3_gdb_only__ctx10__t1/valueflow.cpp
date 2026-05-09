    if (minValue && minValue->isImpossible() && minValue->bound == ValueFlow::Value::Bound::Upper) {
        if (minValue->intvalue >= x)
            result = minValue;
    }
    return result;
}

static const ValueFlow::Value* proveNotEqual(const std::list<ValueFlow::Value>& values, MathLib::bigint x)
{
    const ValueFlow::Value* result = nullptr;
    for (const ValueFlow::Value& value : values) {
        if (value.valueType != ValueFlow::Value::INT)
            continue;
        if (result && !isInBounds(value, result->intvalue))
            continue;
        if (value.isImpossible()) {
            if (value.intvalue == x)
                return &value;
            if (!isInBounds(value, x))
                continue;
            result = &value;
        } else {
            if (value.intvalue == x)
                return nullptr;
            if (!isInBounds(value, x))
                continue;
            result = nullptr;
        }
    }
    return result;
}

static void valueFlowInferCondition(TokenList* tokenlist,
                                    const Settings* settings)
{
    for (Token* tok = tokenlist->front(); tok; tok = tok->next()) {
        if (!tok->astParent())
            continue;
        if (tok->hasKnownValue())
            continue;
        if (tok->variable() && (Token::Match(tok->astParent(), "?|&&|!|%oror%") ||
                                Token::Match(tok->astParent()->previous(), "if|while ("))) {
            const ValueFlow::Value* result = proveNotEqual(tok->values(), 0);
            if (!result)
                continue;
            ValueFlow::Value value = *result;
            value.intvalue = 1;
            value.bound = ValueFlow::Value::Bound::Point;
            value.setKnown();
            setTokenValue(tok, value, settings);
        } else if (tok->isComparisonOp()) {
            MathLib::bigint val = 0;
            const Token* varTok = nullptr;
            if (tok->astOperand1()->hasKnownIntValue()) {
                val = tok->astOperand1()->values().front().intvalue;
                varTok = tok->astOperand2();
            } else if (tok->astOperand2()->hasKnownIntValue()) {
                val = tok->astOperand2()->values().front().intvalue;
                varTok = tok->astOperand1();
            }
            if (!varTok)
                continue;
            if (varTok->hasKnownIntValue())
                continue;
            if (varTok->values().empty())
                continue;
            const ValueFlow::Value* result = nullptr;
            bool known = false;
            if (Token::Match(tok, "==|!=")) {
                result = proveNotEqual(varTok->values(), val);
                known = tok->str() == "!=";
            } else if (Token::Match(tok, "<|>=")) {
                result = proveLessThan(varTok->values(), val);
                known = tok->str() == "<";
                if (!result && !isSaturated(val)) {
                    result = proveGreaterThan(varTok->values(), val - 1);
                    known = tok->str() == ">=";
                }
            } else if (Token::Match(tok, ">|<=")) {
                result = proveGreaterThan(varTok->values(), val);
                known = tok->str() == ">";
                if (!result && !isSaturated(val)) {
                    result = proveLessThan(varTok->values(), val + 1);
                    known = tok->str() == "<=";
                }
            }
            if (!result)
                continue;
            ValueFlow::Value value = *result;
            value.intvalue = known;
            value.bound = ValueFlow::Value::Bound::Point;
            value.setKnown();
            setTokenValue(tok, value, settings);
        }
    }
}

static bool valueFlowForLoop1(const Token *tok, int * const varid, MathLib::bigint * const num1, MathLib::bigint * const num2, MathLib::bigint * const numAfter)
{
    tok = tok->tokAt(2);
    if (!Token::Match(tok, "%type%| %var% ="))
