    return;

  if (!m_pState->HasBegunContent()) {
    if (childCount > 0) {
      m_stream << "\n";
    }
    if (m_stream.comment()) {
      m_stream << "\n";
    }
    m_stream << IndentTo(curIndent);
    m_stream << "?";
  }

  switch (child) {
    case EmitterNodeType::NoType:
      break;
    case EmitterNodeType::Property:
    case EmitterNodeType::Scalar:
    case EmitterNodeType::FlowSeq:
    case EmitterNodeType::FlowMap:
      SpaceOrIndentTo(true, curIndent + 1);
      break;
    case EmitterNodeType::BlockSeq:
    case EmitterNodeType::BlockMap:
      if (m_pState->HasBegunContent())
        m_stream << "\n";
      break;
  }
}

void Emitter::BlockMapPrepareLongKeyValue(EmitterNodeType::value child) {
  const std::size_t curIndent = m_pState->CurIndent();

  if (child == EmitterNodeType::NoType)
    return;

  if (!m_pState->HasBegunContent()) {
    m_stream << "\n";
    m_stream << IndentTo(curIndent);
    m_stream << ":";
  }

  switch (child) {
    case EmitterNodeType::NoType:
      break;
    case EmitterNodeType::Property:
    case EmitterNodeType::Scalar:
    case EmitterNodeType::FlowSeq:
    case EmitterNodeType::FlowMap:
      SpaceOrIndentTo(true, curIndent + 1);
      break;
    case EmitterNodeType::BlockSeq:
    case EmitterNodeType::BlockMap:
      SpaceOrIndentTo(true, curIndent + 1);
      break;
  }
}

void Emitter::BlockMapPrepareSimpleKey(EmitterNodeType::value child) {
  const std::size_t curIndent = m_pState->CurIndent();
  const std::size_t childCount = m_pState->CurGroupChildCount();

  if (child == EmitterNodeType::NoType)
    return;

  if (!m_pState->HasBegunNode()) {
    if (childCount > 0) {
      m_stream << "\n";
    }
  }

  switch (child) {
    case EmitterNodeType::NoType:
      break;
    case EmitterNodeType::Property:
    case EmitterNodeType::Scalar:
    case EmitterNodeType::FlowSeq:
    case EmitterNodeType::FlowMap:
      SpaceOrIndentTo(m_pState->HasBegunContent(), curIndent);
      break;
    case EmitterNodeType::BlockSeq:
    case EmitterNodeType::BlockMap:
      break;
  }
}

void Emitter::BlockMapPrepareSimpleKeyValue(EmitterNodeType::value child) {
  const std::size_t curIndent = m_pState->CurIndent();
  const std::size_t nextIndent = curIndent + m_pState->CurGroupIndent();

  if (!m_pState->HasBegunNode()) {
    m_stream << ":";
  }

  switch (child) {
    case EmitterNodeType::NoType:
      break;
    case EmitterNodeType::Property:
    case EmitterNodeType::Scalar:
    case EmitterNodeType::FlowSeq:
    case EmitterNodeType::FlowMap:
