 */
// Note: 'parse_error' exception class should be be used in sematic action
// handlers to reject the rule.
struct parse_error {
  parse_error() = default;
  parse_error(const char *s) : s_(s) {}
  const char *what() const { return s_.empty() ? nullptr : s_.c_str(); }

private:
  std::string s_;
};

/*
 * Result
 */
inline bool success(size_t len) { return len != static_cast<size_t>(-1); }

inline bool fail(size_t len) { return len == static_cast<size_t>(-1); }

/*
 * Context
 */
class Context;
class Ope;
class Definition;

typedef std::function<void(const char *name, const char *s, size_t n,
                           const SemanticValues &sv, const Context &c,
                           const any &dt)>
    TracerEnter;

typedef std::function<void(const char *name, const char *s, size_t n,
                           const SemanticValues &sv, const Context &c,
                           const any &dt, size_t)>
    TracerLeave;

class Context {
public:
  const char *path;
  const char *s;
  const size_t l;
  std::vector<size_t> source_line_index;

  const char *error_pos = nullptr;
  const char *message_pos = nullptr;
  std::string message; // TODO: should be `int`.

  std::vector<std::shared_ptr<SemanticValues>> value_stack;
  size_t value_stack_size = 0;

  std::vector<Definition *> rule_stack;
  std::vector<std::vector<std::shared_ptr<Ope>>> args_stack;

  bool in_token = false;

  std::shared_ptr<Ope> whitespaceOpe;
  bool in_whitespace = false;

  std::shared_ptr<Ope> wordOpe;

  std::vector<std::map<std::string, std::string>> capture_scope_stack;
  size_t capture_scope_stack_size = 0;

  const size_t def_count;
  const bool enablePackratParsing;
  std::vector<bool> cache_registered;
  std::vector<bool> cache_success;

  std::map<std::pair<size_t, size_t>, std::tuple<size_t, any>> cache_values;

  TracerEnter tracer_enter;
  TracerLeave tracer_leave;

  Context(const char *a_path, const char *a_s, size_t a_l, size_t a_def_count,
          std::shared_ptr<Ope> a_whitespaceOpe, std::shared_ptr<Ope> a_wordOpe,
          bool a_enablePackratParsing, TracerEnter a_tracer_enter,
          TracerLeave a_tracer_leave)
      : path(a_path), s(a_s), l(a_l), whitespaceOpe(a_whitespaceOpe),
        wordOpe(a_wordOpe), def_count(a_def_count),
        enablePackratParsing(a_enablePackratParsing),
        cache_registered(enablePackratParsing ? def_count * (l + 1) : 0),
        cache_success(enablePackratParsing ? def_count * (l + 1) : 0),
        tracer_enter(a_tracer_enter), tracer_leave(a_tracer_leave) {

    for (size_t pos = 0; pos < l; pos++) {
      if (s[pos] == '\n') { source_line_index.push_back(pos); }
    }
    source_line_index.push_back(l);

    args_stack.resize(1);

    push_capture_scope();
  }

  ~Context() { assert(!value_stack_size); }

  Context(const Context &) = delete;
  Context(Context &&) = delete;
  Context operator=(const Context &) = delete;

  template <typename T>
