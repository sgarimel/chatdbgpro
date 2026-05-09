  PrepareNode(m_pState->NextGroupType(GroupType::Seq));

  m_pState->StartedGroup(GroupType::Seq);
}

// EmitEndSeq
void Emitter::EmitEndSeq() {
  if (!good())
    return;
  FlowType::value originalType = m_pState->CurGroupFlowType();

  if (m_pState->CurGroupChildCount() == 0)
    m_pState->ForceFlow();

  if (m_pState->CurGroupFlowType() == FlowType::Flow) {
    if (m_stream.comment())
      m_stream << "\n";
    m_stream << IndentTo(m_pState->CurIndent());
    if (originalType == FlowType::Block) {
      m_stream << "[";
    } else {
      if (m_pState->CurGroupChildCount() == 0 && !m_pState->HasBegunNode())
        m_stream << "[";
    }
    m_stream << "]";
  }

  m_pState->EndedGroup(GroupType::Seq);
}

// EmitBeginMap
void Emitter::EmitBeginMap() {
  if (!good())
    return;

  PrepareNode(m_pState->NextGroupType(GroupType::Map));

  m_pState->StartedGroup(GroupType::Map);
}

// EmitEndMap
void Emitter::EmitEndMap() {
  if (!good())
    return;
  FlowType::value originalType = m_pState->CurGroupFlowType();

  if (m_pState->CurGroupChildCount() == 0)
    m_pState->ForceFlow();

  if (m_pState->CurGroupFlowType() == FlowType::Flow) {
    if (m_stream.comment())
      m_stream << "\n";
    m_stream << IndentTo(m_pState->CurIndent());
    if (m_pState->CurGroupChildCount() == 0)
      m_stream << "{";
    m_stream << "}";
  }

  m_pState->EndedGroup(GroupType::Map);
}

// EmitNewline
void Emitter::EmitNewline() {
  if (!good())
    return;

  PrepareNode(EmitterNodeType::NoType);
  m_stream << "\n";
  m_pState->SetNonContent();
}

bool Emitter::CanEmitNewline() const { return true; }

// Put the stream in a state so we can simply write the next node
// E.g., if we're in a sequence, write the "- "
void Emitter::PrepareNode(EmitterNodeType::value child) {
  switch (m_pState->CurGroupNodeType()) {
    case EmitterNodeType::NoType:
      PrepareTopNode(child);
      break;
    case EmitterNodeType::FlowSeq:
      FlowSeqPrepareNode(child);
      break;
    case EmitterNodeType::BlockSeq:
      BlockSeqPrepareNode(child);
      break;
    case EmitterNodeType::FlowMap:
      FlowMapPrepareNode(child);
      break;
    case EmitterNodeType::BlockMap:
      BlockMapPrepareNode(child);
      break;
    case EmitterNodeType::Property:
    case EmitterNodeType::Scalar:
      assert(false);
      break;
  }
}

void Emitter::PrepareTopNode(EmitterNodeType::value child) {
  if (child == EmitterNodeType::NoType)
