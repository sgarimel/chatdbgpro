    EF   exit_function;
    bool execute_on_destruction;
};

template <typename EF>
auto make_scope_exit(EF&& exit_function) -> scope_exit<EF> {
    return scope_exit<typename std::remove_reference<EF>::type>(std::forward<EF>(exit_function));
}

/*-----------------------------------------------------------------------------
 *  PEG
 *---------------------------------------------------------------------------*/

/*
* Line information utility function
*/
inline std::pair<size_t, size_t> line_info(const char* start, const char* cur) {
    auto p = start;
    auto col_ptr = p;
    auto no = 1;

    while (p < cur) {
        if (*p == '\n') {
            no++;
            col_ptr = p + 1;
        }
        p++;
    }

    auto col = p - col_ptr + 1;

    return std::make_pair(no, col);
}

/*
* Semantic values
*/
struct SemanticValues : protected std::vector<any>
{
    // Input text
    const char* path;
    const char* ss;

    // Matched string
    const char* c_str() const { return s_; }
    size_t      length() const { return n_; }

    std::string str() const {
        return std::string(s_, n_);
    }

    // Line number and column at which the matched string is
    std::pair<size_t, size_t> line_info() const {
    }

    // Choice number (0 based index)
    size_t      choice() const { return choice_; }

    // Tokens
    std::vector<std::pair<const char*, size_t>> tokens;

    std::string token(size_t id = 0) const {
        if (!tokens.empty()) {
            assert(id < tokens.size());
            const auto& tok = tokens[id];
            return std::string(tok.first, tok.second);
        }
        return std::string(s_, n_);
    }

    // Transform the semantic value vector to another vector
    template <typename T>
    auto transform(size_t beg = 0, size_t end = static_cast<size_t>(-1)) const -> vector<T> {
        return this->transform(beg, end, [](const any& v) { return v.get<T>(); });
    }

    SemanticValues() : s_(nullptr), n_(0), choice_(0) {}

    using std::vector<any>::iterator;
    using std::vector<any>::const_iterator;
    using std::vector<any>::size;
    using std::vector<any>::empty;
    using std::vector<any>::assign;
    using std::vector<any>::begin;
    using std::vector<any>::end;
    using std::vector<any>::rbegin;
    using std::vector<any>::rend;
    using std::vector<any>::operator[];
    using std::vector<any>::at;
    using std::vector<any>::resize;
    using std::vector<any>::front;
    using std::vector<any>::back;
    using std::vector<any>::push_back;
    using std::vector<any>::pop_back;
    using std::vector<any>::insert;
    using std::vector<any>::erase;
    using std::vector<any>::clear;
    using std::vector<any>::swap;
    using std::vector<any>::emplace;
    using std::vector<any>::emplace_back;

