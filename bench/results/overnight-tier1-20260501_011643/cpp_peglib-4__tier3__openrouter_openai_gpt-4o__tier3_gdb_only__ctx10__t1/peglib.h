}

inline void DetectLeftRecursion::visit(Reference& ope) {
    if (ope.name_ == name_) {
        error_s = ope.s_;
    } else if (!refs_.count(ope.name_)) {
        refs_.insert(ope.name_);
        if (ope.rule_) {
            ope.rule_->accept(*this);
            if (done_ == false) {
                return;
            }
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
    // Check if the reference is a macro parameter
    auto found_param = false;
    for (size_t i = 0; i < params_.size(); i++) {
        const auto& param = params_[i];
        if (param == ope.name_) {
            ope.iarg_ = i;
            found_param = true;
            break;
        }
    }

    // Check if the reference is a definition rule
    if (grammar_.count(ope.name_)) {
        auto& rule = grammar_.at(ope.name_);
        ope.rule_ = &rule;
    }

    for (auto arg: ope.args_) {
        arg->accept(*this);
    }
}

inline void FindReference::visit(Reference& ope) {
    for (size_t i = 0; i < args_.size(); i++) {
        const auto& name = params_[i];
        if (name == ope.name_) {
            found_ope = args_[i];
            return;
        }
    }
    found_ope = ope.shared_from_this();
}

/*-----------------------------------------------------------------------------
 *  PEG parser generator
 *---------------------------------------------------------------------------*/

typedef std::unordered_map<std::string, std::shared_ptr<Ope>> Rules;
typedef std::function<void (size_t, size_t, const std::string&)> Log;

class ParserGenerator
{
public:
    static std::shared_ptr<Grammar> parse(
        const char*  s,
        size_t       n,
        const Rules& rules,
        std::string& start,
        Log          log)
    {
        return get_instance().perform_core(s, n, rules, start, log);
    }

     static std::shared_ptr<Grammar> parse(
        const char*  s,
        size_t       n,
        std::string& start,
        Log          log)
    {
        Rules dummy;
