  assert(!m_scanner.empty());  // guaranteed that there are tokens
  assert(!m_curAnchor);

  eventHandler.OnDocumentStart(m_scanner.peek().mark);

  // eat doc start
  if (m_scanner.peek().type == Token::DOC_START)
    m_scanner.pop();

  // recurse!
  HandleNode(eventHandler);

  eventHandler.OnDocumentEnd();

  // and finally eat any doc ends we see
  while (!m_scanner.empty() && m_scanner.peek().type == Token::DOC_END)
    m_scanner.pop();
}

void SingleDocParser::HandleNode(EventHandler& eventHandler) {
  // an empty node *is* a possibility
  if (m_scanner.empty()) {
    eventHandler.OnNull(m_scanner.mark(), NullAnchor);
    return;
  }

  // save location
  Mark mark = m_scanner.peek().mark;

  // special case: a value node by itself must be a map, with no header
  if (m_scanner.peek().type == Token::VALUE) {
    eventHandler.OnMapStart(mark, "?", NullAnchor, EmitterStyle::Default);
    HandleMap(eventHandler);
    eventHandler.OnMapEnd();
    return;
  }

  // special case: an alias node
  if (m_scanner.peek().type == Token::ALIAS) {
    eventHandler.OnAlias(mark, LookupAnchor(mark, m_scanner.peek().value));
    m_scanner.pop();
    return;
  }

  std::string tag;
  std::string anchor_name;
  anchor_t anchor;
  ParseProperties(tag, anchor, anchor_name);

  if (!anchor_name.empty())
    eventHandler.OnAnchor(mark, anchor_name);

  // after parsing properties, an empty node is again a possibility

  const Token& token = m_scanner.peek();

  if (token.type == Token::PLAIN_SCALAR && IsNullString(token.value)) {
    eventHandler.OnNull(mark, anchor);
    m_scanner.pop();
    return;
  }

  // add non-specific tags
  if (tag.empty())
    tag = (token.type == Token::NON_PLAIN_SCALAR ? "!" : "?");

  // now split based on what kind of node we should be
  switch (token.type) {
    case Token::PLAIN_SCALAR:
    case Token::NON_PLAIN_SCALAR:
      eventHandler.OnScalar(mark, tag, anchor, token.value);
      m_scanner.pop();
      return;
    case Token::FLOW_SEQ_START:
      eventHandler.OnSequenceStart(mark, tag, anchor, EmitterStyle::Flow);
      HandleSequence(eventHandler);
      eventHandler.OnSequenceEnd();
      return;
    case Token::BLOCK_SEQ_START:
      eventHandler.OnSequenceStart(mark, tag, anchor, EmitterStyle::Block);
      HandleSequence(eventHandler);
      eventHandler.OnSequenceEnd();
      return;
    case Token::FLOW_MAP_START:
      eventHandler.OnMapStart(mark, tag, anchor, EmitterStyle::Flow);
      HandleMap(eventHandler);
      eventHandler.OnMapEnd();
      return;
    case Token::BLOCK_MAP_START:
      eventHandler.OnMapStart(mark, tag, anchor, EmitterStyle::Block);
      HandleMap(eventHandler);
      eventHandler.OnMapEnd();
      return;
    case Token::KEY:
      // compact maps can only go in a flow sequence
      if (m_pCollectionStack->GetCurCollectionType() ==
          CollectionType::FlowSeq) {
        eventHandler.OnMapStart(mark, tag, anchor, EmitterStyle::Flow);
        HandleMap(eventHandler);
        eventHandler.OnMapEnd();
        return;
