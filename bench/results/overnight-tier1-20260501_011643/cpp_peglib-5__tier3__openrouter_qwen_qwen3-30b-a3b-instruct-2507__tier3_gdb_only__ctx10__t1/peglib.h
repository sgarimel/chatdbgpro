inline void LiteralString::accept(Visitor& v) { v.visit(*this); }
inline void CharacterClass::accept(Visitor& v) { v.visit(*this); }
inline void Character::accept(Visitor& v) { v.visit(*this); }
inline void AnyCharacter::accept(Visitor& v) { v.visit(*this); }
inline void CaptureScope::accept(Visitor& v) { v.visit(*this); }
inline void Capture::accept(Visitor& v) { v.visit(*this); }
inline void TokenBoundary::accept(Visitor& v) { v.visit(*this); }
inline void Ignore::accept(Visitor& v) { v.visit(*this); }
inline void User::accept(Visitor& v) { v.visit(*this); }
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
        for (auto arg: ope.args_) {
            arg->accept(*this);
        }
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
}

inline void LinkReferences::visit(Reference& ope) {
    if (grammar_.count(ope.name_)) {
        auto& rule = grammar_.at(ope.name_);
        ope.rule_ = &rule;
    } else {
        for (size_t i = 0; i < params_.size(); i++) {
            const auto& param = params_[i];
            if (param == ope.name_) {
                ope.iarg_ = i;
                break;
            }
        }
    }
    for (auto arg: ope.args_) {
        arg->accept(*this);
    }
}

inline void FindReference::visit(Reference& ope) {
    for (size_t i = 0; i < args_.size(); i++) {
