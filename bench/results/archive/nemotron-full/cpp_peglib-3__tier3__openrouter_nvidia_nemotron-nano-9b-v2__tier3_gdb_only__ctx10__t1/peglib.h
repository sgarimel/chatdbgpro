      return r.ret && r.len == n;
    }
    return false;
  }

  template <typename T>
  bool parse(const char *s, T &val, const char *path = nullptr) const {
    auto n = strlen(s);
    return parse_n(s, n, val, path);
  }

  template <typename T>
  bool parse_n(const char *s, size_t n, any &dt, T &val,
               const char *path = nullptr) const {
    if (grammar_ != nullptr) {
      const auto &rule = (*grammar_)[start_];
      auto r = rule.parse_and_get_value(s, n, dt, val, path);
      output_log(s, n, r);
      return r.ret && r.len == n;
    }
    return false;
  }

  template <typename T>
  bool parse(const char *s, any &dt, T &val,
             const char * /*path*/ = nullptr) const {
    auto n = strlen(s);
    return parse_n(s, n, dt, val);
  }

  Definition &operator[](const char *s) { return (*grammar_)[s]; }

  const Definition &operator[](const char *s) const { return (*grammar_)[s]; }

  std::vector<std::string> get_rule_names() {
    std::vector<std::string> rules;
    rules.reserve(grammar_->size());
    for (auto const &r : *grammar_) {
      rules.emplace_back(r.first);
    }
    return rules;
  }

  void enable_packrat_parsing() {
    if (grammar_ != nullptr) {
      auto &rule = (*grammar_)[start_];
      rule.enablePackratParsing = true;
    }
  }

  template <typename T = Ast> parser &enable_ast() {
    for (auto &x : *grammar_) {
      auto &rule = x.second;
      if (!rule.action) { add_ast_action(rule); }
    }
    return *this;
  }

  void enable_trace(TracerEnter tracer_enter, TracerLeave tracer_leave) {
    if (grammar_ != nullptr) {
      auto &rule = (*grammar_)[start_];
      rule.tracer_enter = tracer_enter;
      rule.tracer_leave = tracer_leave;
    }
  }

  Log log;

private:
  void output_log(const char *s, size_t n, const Definition::Result &r) const {
    if (log) {
      if (!r.ret) {
        if (r.message_pos) {
          auto line = line_info(s, r.message_pos);
          log(line.first, line.second, r.message);
        } else {
          auto line = line_info(s, r.error_pos);
          log(line.first, line.second, "syntax error");
        }
      } else if (r.len != n) {
        auto line = line_info(s, s + r.len);
        log(line.first, line.second, "syntax error");
      }
    }
  }

  std::shared_ptr<Grammar> grammar_;
  std::string start_;
};

} // namespace peg

#endif

// vim: et ts=2 sw=2 cin cino={1s ff=unix
