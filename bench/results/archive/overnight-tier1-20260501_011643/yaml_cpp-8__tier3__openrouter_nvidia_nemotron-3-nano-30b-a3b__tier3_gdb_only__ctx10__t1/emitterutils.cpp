  return true;
}

bool WriteDoubleQuotedString(ostream_wrapper& out, const std::string& str,
                             StringEscaping::value stringEscaping) {
  out << "\"";
  int codePoint;
  for (std::string::const_iterator i = str.begin();
       GetNextCodePointAndAdvance(codePoint, i, str.end());) {
    switch (codePoint) {
      case '\"':
        out << "\\\"";
        break;
      case '\\':
        out << "\\\\";
        break;
      case '\n':
        out << "\\n";
        break;
      case '\t':
        out << "\\t";
        break;
      case '\r':
        out << "\\r";
        break;
      case '\b':
        out << "\\b";
        break;
      case '\f':
        out << "\\f";
        break;
      default:
        if (codePoint < 0x20 ||
            (codePoint >= 0x80 &&
             codePoint <= 0xA0)) {  // Control characters and non-breaking space
          WriteDoubleQuoteEscapeSequence(out, codePoint, stringEscaping);
        } else if (codePoint == 0xFEFF) {  // Byte order marks (ZWNS) should be
                                           // escaped (YAML 1.2, sec. 5.2)
          WriteDoubleQuoteEscapeSequence(out, codePoint, stringEscaping);
        } else if (stringEscaping == StringEscaping::NonAscii && codePoint > 0x7E) {
          WriteDoubleQuoteEscapeSequence(out, codePoint, stringEscaping);
        } else {
          WriteCodePoint(out, codePoint);
        }
    }
  }
  out << "\"";
  return true;
}

bool WriteLiteralString(ostream_wrapper& out, const std::string& str,
                        std::size_t indent) {
  out << "|\n";
  out << IndentTo(indent);
  int codePoint;
  for (std::string::const_iterator i = str.begin();
       GetNextCodePointAndAdvance(codePoint, i, str.end());) {
    if (codePoint == '\n') {
      out << "\n" << IndentTo(indent);
    } else {
      WriteCodePoint(out, codePoint);
    }
  }
  return true;
}

bool WriteChar(ostream_wrapper& out, char ch, StringEscaping::value stringEscapingStyle) {
  if (('a' <= ch && ch <= 'z') || ('A' <= ch && ch <= 'Z')) {
    out << ch;
  } else if (ch == '\"') {
    out << R"("\"")";
  } else if (ch == '\t') {
    out << R"("\t")";
  } else if (ch == '\n') {
    out << R"("\n")";
  } else if (ch == '\b') {
    out << R"("\b")";
  } else if (ch == '\r') {
    out << R"("\r")";
  } else if (ch == '\f') {
    out << R"("\f")";
  } else if (ch == '\\') {
    out << R"("\\")";
  } else if (0x20 <= ch && ch <= 0x7e) {
    out << "\"" << ch << "\"";
  } else {
    out << "\"";
    WriteDoubleQuoteEscapeSequence(out, ch, stringEscapingStyle);
    out << "\"";
  }
  return true;
}

bool WriteComment(ostream_wrapper& out, const std::string& str,
                  std::size_t postCommentIndent) {
  const std::size_t curIndent = out.col();
  out << "#" << Indentation(postCommentIndent);
  out.set_comment();
  int codePoint;
  for (std::string::const_iterator i = str.begin();
       GetNextCodePointAndAdvance(codePoint, i, str.end());) {
