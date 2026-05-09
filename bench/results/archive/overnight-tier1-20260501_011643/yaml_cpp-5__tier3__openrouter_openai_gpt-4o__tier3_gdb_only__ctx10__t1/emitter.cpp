  if (m_stream.comment())
    m_stream << "\n";
  if (m_stream.col() > 0 && requireSpace)
    m_stream << " ";
  m_stream << IndentTo(indent);
}

void Emitter::PrepareIntegralStream(std::stringstream& stream) const {

  switch (m_pState->GetIntFormat()) {
    case Dec:
      stream << std::dec;
      break;
    case Hex:
      stream << "0x";
      stream << std::hex;
      break;
    case Oct:
      stream << "0";
      stream << std::oct;
      break;
    default:
      assert(false);
  }
}

void Emitter::StartedScalar() { m_pState->StartedScalar(); }

// *******************************************************************************************
// overloads of Write

StringEscaping::value GetStringEscapingStyle(const EMITTER_MANIP emitterManip) {
  switch (emitterManip) {
    case EscapeNonAscii:
      return StringEscaping::NonAscii;
    case EscapeAsJson:
      return StringEscaping::JSON;
    default:
      return StringEscaping::None;
      break;
  }
}

Emitter& Emitter::Write(const std::string& str) {
  if (!good())
    return *this;

  StringEscaping::value stringEscaping = GetStringEscapingStyle(m_pState->GetOutputCharset());

  const StringFormat::value strFormat =
      Utils::ComputeStringFormat(str, m_pState->GetStringFormat(),
                                 m_pState->CurGroupFlowType(), stringEscaping == StringEscaping::NonAscii);

  if (strFormat == StringFormat::Literal)
    m_pState->SetMapKeyFormat(YAML::LongKey, FmtScope::Local);

  PrepareNode(EmitterNodeType::Scalar);

  switch (strFormat) {
    case StringFormat::Plain:
      m_stream << str;
      break;
    case StringFormat::SingleQuoted:
      Utils::WriteSingleQuotedString(m_stream, str);
      break;
    case StringFormat::DoubleQuoted:
      Utils::WriteDoubleQuotedString(m_stream, str, stringEscaping);
      break;
    case StringFormat::Literal:
      Utils::WriteLiteralString(m_stream, str,
                                m_pState->CurIndent() + m_pState->GetIndent());
      break;
  }

  StartedScalar();

  return *this;
}

std::size_t Emitter::GetFloatPrecision() const {
  return m_pState->GetFloatPrecision();
}

std::size_t Emitter::GetDoublePrecision() const {
  return m_pState->GetDoublePrecision();
}

const char* Emitter::ComputeFullBoolName(bool b) const {
  const EMITTER_MANIP mainFmt = (m_pState->GetBoolLengthFormat() == ShortBool
                                     ? YesNoBool
                                     : m_pState->GetBoolFormat());
  const EMITTER_MANIP caseFmt = m_pState->GetBoolCaseFormat();
  switch (mainFmt) {
    case YesNoBool:
      switch (caseFmt) {
        case UpperCase:
          return b ? "YES" : "NO";
        case CamelCase:
          return b ? "Yes" : "No";
        case LowerCase:
          return b ? "yes" : "no";
