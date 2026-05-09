                    (void)c_locale_stod(l_version);
                    formatter->add(l_version);
                } catch (const std::exception &) {
                    formatter->addQuotedString(l_version);
                }
            }
            if (authority().has_value() &&
                *(authority()->title()) != l_codeSpace) {
                formatter->startNode(WKTConstants::CITATION, false);
                formatter->addQuotedString(*(authority()->title()));
                formatter->endNode();
            }
            if (uri().has_value()) {
                formatter->startNode(WKTConstants::URI, false);
                formatter->addQuotedString(*(uri()));
                formatter->endNode();
            }
            formatter->endNode();
        } else {
            formatter->startNode(WKTConstants::AUTHORITY, false);
            formatter->addQuotedString(l_codeSpace);
            formatter->addQuotedString(l_code);
            formatter->endNode();
        }
    }
}

// ---------------------------------------------------------------------------

void Identifier::_exportToJSON(JSONFormatter *formatter) const {
    const std::string &l_code = code();
    const std::string &l_codeSpace = *codeSpace();
    if (!l_codeSpace.empty() && !l_code.empty()) {
        auto writer = formatter->writer();
        auto objContext(formatter->MakeObjectContext(nullptr, false));
        writer->AddObjKey("authority");
        writer->Add(l_codeSpace);
        writer->AddObjKey("code");
        try {
            writer->Add(std::stoi(l_code));
        } catch (const std::exception &) {
            writer->Add(l_code);
        }
    }
}

//! @endcond

// ---------------------------------------------------------------------------

//! @cond Doxygen_Suppress
static bool isIgnoredChar(char ch) {
    return ch == ' ' || ch == '_' || ch == '-' || ch == '/' || ch == '(' ||
           ch == ')' || ch == '.' || ch == '&';
}
//! @endcond

// ---------------------------------------------------------------------------

//! @cond Doxygen_Suppress
static const struct utf8_to_lower {
    const char *utf8;
    char ascii;
} map_utf8_to_lower[] = {
    {"\xc3\xa1", 'a'}, // a acute
    {"\xc3\xa4", 'a'}, // a tremma

    {"\xc4\x9b", 'e'}, // e reverse circumflex
    {"\xc3\xa8", 'e'}, // e grave
    {"\xc3\xa9", 'e'}, // e acute
    {"\xc3\xab", 'e'}, // e tremma

    {"\xc3\xad", 'i'}, // i grave

    {"\xc3\xb4", 'o'}, // o circumflex
    {"\xc3\xb6", 'o'}, // o tremma

    {"\xc3\xa7", 'c'}, // c cedilla
};

static const struct utf8_to_lower *get_ascii_replacement(const char *c_str) {
    for (const auto &pair : map_utf8_to_lower) {
        if (*c_str == pair.utf8[0] &&
            strncmp(c_str, pair.utf8, strlen(pair.utf8)) == 0) {
            return &pair;
        }
    }
    return nullptr;
}
//! @endcond

// ---------------------------------------------------------------------------

//! @cond Doxygen_Suppress
std::string Identifier::canonicalizeName(const std::string &str) {
    std::string res;
    const char *c_str = str.c_str();
    for (size_t i = 0; c_str[i] != 0; ++i) {
        const auto ch = c_str[i];
        if (ch == ' ' && c_str[i + 1] == '+' && c_str[i + 2] == ' ') {
            i += 2;
