  if (c.is_traceable(*this)) {
    TraceOpeName vis;
    const_cast<Ope &>(*this).accept(vis);
    c.trace_enter(vis.name, s, n, sv, dt);
    auto len = parse_core(s, n, sv, c, dt);
    c.trace_leave(vis.name, s, n, sv, dt, len);
    return len;
  }
  return parse_core(s, n, sv, c, dt);
}

inline size_t Dictionary::parse_core(const char *s, size_t n,
                                     SemanticValues & /*sv*/, Context &c,
                                     any & /*dt*/) const {
  auto len = trie_.match(s, n);
  if (len > 0) { return len; }
  c.set_error_pos(s);
  return static_cast<size_t>(-1);
}

inline size_t LiteralString::parse_core(const char *s, size_t n,
                                        SemanticValues &sv, Context &c,
                                        any &dt) const {
  return parse_literal(s, n, sv, c, dt, lit_, init_is_word_, is_word_,
                       ignore_case_);
}

inline size_t TokenBoundary::parse_core(const char *s, size_t n,
                                        SemanticValues &sv, Context &c,
                                        any &dt) const {
  c.in_token = true;
  auto se = make_scope_exit([&]() { c.in_token = false; });
  auto len = ope_->parse(s, n, sv, c, dt);
  if (success(len)) {
    sv.tokens.emplace_back(std::make_pair(s, len));

    if (c.whitespaceOpe) {
      auto l = c.whitespaceOpe->parse(s + len, n - len, sv, c, dt);
      if (fail(l)) { return static_cast<size_t>(-1); }
      len += l;
    }
  }
  return len;
}

inline size_t Holder::parse_core(const char *s, size_t n, SemanticValues &sv,
                                 Context &c, any &dt) const {
  if (!ope_) {
    throw std::logic_error("Uninitialized definition ope was used...");
  }

  // Macro reference
  // TODO: need packrat support
  if (outer_->is_macro) { return ope_->parse(s, n, sv, c, dt); }

  size_t len;
  any val;

  c.packrat(s, outer_->id, len, val, [&](any &a_val) {
    if (outer_->enter) { outer_->enter(s, n, dt); }

    auto se2 = make_scope_exit([&]() {
      c.pop();

      if (outer_->leave) { outer_->leave(s, n, len, a_val, dt); }
    });

    auto &chldsv = c.push();

    c.rule_stack.push_back(outer_);
    len = ope_->parse(s, n, chldsv, c, dt);
    c.rule_stack.pop_back();

    // Invoke action
    if (success(len)) {
      chldsv.s_ = s;
      chldsv.n_ = len;
      chldsv.name_ = outer_->name;

      if (!IsPrioritizedChoice::check(*ope_)) {
        chldsv.choice_count_ = 0;
        chldsv.choice_ = 0;
      }

      try {
        a_val = reduce(chldsv, dt);
      } catch (const parse_error &e) {
        if (e.what()) {
          if (c.message_pos < s) {
            c.message_pos = s;
            c.message = e.what();
          }
        }
        len = static_cast<size_t>(-1);
      }
    }
  });

  if (success(len)) {
    if (!outer_->ignoreSemanticValue) {
      sv.emplace_back(std::move(val));
