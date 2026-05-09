    return rule_->holder_;
}

inline size_t BackReference::parse(const char* s, size_t n, SemanticValues& sv, Context& c, any& dt) const {
    c.trace("BackReference", s, n, sv, dt);
    auto it = c.capture_scope_stack.rbegin();
    while (it != c.capture_scope_stack.rend()) {
        const auto& captures = *it;
        if (captures.find(name_) != captures.end()) {
            const auto& lit = captures.at(name_);
            auto init_is_word = false;
            auto is_word = false;
            return parse_literal(s, n, sv, c, dt, lit, init_is_word, is_word);
        }
        ++it;
    }
    throw std::runtime_error("Invalid back reference...");
}

inline void Sequence::accept(Visitor& v) { v.visit(*this); }
inline void PrioritizedChoice::accept(Visitor& v) { v.visit(*this); }
inline void ZeroOrMore::accept(Visitor& v) { v.visit(*this); }
inline void OneOrMore::accept(Visitor& v) { v.visit(*this); }
inline void Option::accept(Visitor& v) { v.visit(*this); }
inline void AndPredicate::accept(Visitor& v) { v.visit(*this); }
inline void NotPredicate::accept(Visitor& v) { v.visit(*this); }
inline void LiteralString::accept(Visitor& v) { v.visit(*this); }
inline void CharacterClass::accept(Visitor& v) { v.visit(*this); }
inline void Character::accept(Visitor& v) { v.visit(*this); }
inline void AnyCharacter::accept(Visitor& v) { v.visit(*this); }
inline void CaptureScope::accept(Visitor& v) { v.visit(*this); }
inline void Capture::accept(Visitor& v) { v.visit(*this); }
inline void TokenBoundary::accept(Visitor& v) { v.visit(*this); }
inline void Ignore::accept(Visitor& v) { v.visit(*this); }
inline void WeakHolder::accept(Visitor& v) { v.visit(*this); }
inline void Holder::accept(Visitor& v) { v.visit(*this); }
inline void Reference::accept(Visitor& v) { v.visit(*this); }
inline void Whitespace::accept(Visitor& v) { v.visit(*this); }
inline void BackReference::accept(Visitor& v) { v.visit(*this); }

inline void AssignIDToDefinition::visit(Holder& ope) {
    auto p = static_cast<void*>(ope.outer_);
    if (ids.count(p)) {
        return;
    }
    auto id = ids.size();
    ids[p] = id;
    ope.outer_->id = id;
    ope.ope_->accept(*this);
}

inline void AssignIDToDefinition::visit(Reference& ope) {
    if (ope.rule_) {
        ope.rule_->accept(*this);
    }
}

inline void TokenChecker::visit(Reference& ope) {
    if (ope.is_macro_) {
        ope.rule_->accept(*this);
        for (auto arg: ope.args_) {
            arg->accept(*this);
        }
    } else {
        has_rule_ = true;
    }
}

inline void DetectLeftRecursion::visit(Reference& ope) {
    if (ope.name_ == name_) {
        error_s = ope.s_;
    } else if (!refs_.count(ope.name_)) {
        refs_.insert(ope.name_);
        if (ope.rule_) {
            ope.rule_->accept(*this);
        }
    }
    done_ = true;
}

inline void ReferenceChecker::visit(Reference& ope) {
    auto it = std::find(params_.begin(), params_.end(), ope.name_);
    if (it != params_.end()) {
        return;
    }

    if (!grammar_.count(ope.name_)) {
        error_s[ope.name_] = ope.s_;
        error_message[ope.name_] = "'" + ope.name_ + "' is not defined.";
    } else {
        const auto& rule = grammar_.at(ope.name_);
        if (rule.is_macro) {
            if (!ope.is_macro_ || ope.args_.size() != rule.params.size()) {
                error_s[ope.name_] = ope.s_;
                error_message[ope.name_] = "incorrect number of arguments.";
            }
        } else if (ope.is_macro_) {
            error_s[ope.name_] = ope.s_;
            error_message[ope.name_] = "'" + ope.name_ + "' is not macro.";
        }
    }
