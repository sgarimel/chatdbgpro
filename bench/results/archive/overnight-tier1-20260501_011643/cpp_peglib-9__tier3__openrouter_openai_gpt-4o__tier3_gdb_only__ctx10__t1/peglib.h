        ignoreSemanticValue = true;
        return *this;
    }

    void accept(Ope::Visitor& v) {
        holder_->accept(v);
    }

    std::string                    name;
    size_t                         id;
    Action                         action;
    std::function<void (any& dt)>  before;
    std::function<void (any& dt)>  after;
    std::function<std::string ()>  error_message;
    bool                           ignoreSemanticValue;
    bool                           enablePackratParsing;
    bool                           is_token;

private:
    friend class DefinitionReference;

    Definition& operator=(const Definition& rhs);
    Definition& operator=(Definition&& rhs);

    Result parse_core(const char* s, size_t n, SemanticValues& sv, any& dt, const char* path) const {
        AssignIDToDefinition assignId;
        holder_->accept(assignId);

        Context cxt(path, s, n, assignId.ids.size(), enablePackratParsing);
        auto len = holder_->parse(s, n, sv, cxt, dt);
        return Result{ success(len), len, cxt.error_pos, cxt.message_pos, cxt.message };
    }

    std::shared_ptr<Holder> holder_;
};

/*
 * Implementations
 */

inline size_t Holder::parse(const char* s, size_t n, SemanticValues& sv, Context& c, any& dt) const {
    if (!ope_) {
        throw std::logic_error("Uninitialized definition ope was used...");
    }

    size_t      len;
    any         val;
    const char* token_boundary_s = s;
    size_t      token_boundary_n = n;

    c.packrat(s, outer_->id, len, val, [&](any& val) {
        auto& chldsv = c.push();

        const auto& rule = *ope_;
        len = rule.parse(s, n, chldsv, c, dt);

        token_boundary_n = len;

        // Invoke action
        if (success(len)) {
            if (chldsv.s) {
                token_boundary_s = chldsv.s;
                token_boundary_n = chldsv.n;
            } else {
                chldsv.s = s;
                chldsv.n = len;
            }

            try {
                val = reduce(chldsv, dt);
            } catch (const parse_error& e) {
                if (e.what()) {
                    c.message_pos = s;
                    c.message = e.what();
                }
                len = -1;
            }
        }

        c.pop();
    });

    if (success(len) && !outer_->ignoreSemanticValue) {
        sv.emplace_back(val, outer_->name.c_str(), token_boundary_s, token_boundary_n);
    }

    if (fail(len) && outer_->error_message && !c.message_pos) {
        c.message_pos = s;
        c.message = outer_->error_message();
    }

    return len;
}

inline any Holder::reduce(const SemanticValues& sv, any& dt) const {
    if (outer_->action) {
        return outer_->action(sv, dt);
    } else if (sv.empty()) {
        return any();
    } else {
        return sv.front().val;
