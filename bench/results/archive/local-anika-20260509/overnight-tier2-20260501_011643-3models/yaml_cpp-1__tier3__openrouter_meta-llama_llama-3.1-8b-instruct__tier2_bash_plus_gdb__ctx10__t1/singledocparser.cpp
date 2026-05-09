#include <algorithm>
#include <cstdio>
#include <sstream>

#include "collectionstack.h"  // IWYU pragma: keep
#include "scanner.h"
#include "singledocparser.h"
#include "tag.h"
#include "token.h"
#include "yaml-cpp/depthguard.h"
#include "yaml-cpp/emitterstyle.h"
#include "yaml-cpp/eventhandler.h"
#include "yaml-cpp/exceptions.h"  // IWYU pragma: keep
#include "yaml-cpp/mark.h"
#include "yaml-cpp/null.h"

namespace YAML {
SingleDocParser::SingleDocParser(Scanner& scanner, const Directives& directives)
    : m_scanner(scanner),
      m_directives(directives),
      m_pCollectionStack(new CollectionStack),
      m_anchors{},
      m_curAnchor(0) {}

SingleDocParser::~SingleDocParser() = default;

// HandleDocument
// . Handles the next document
// . Throws a ParserException on error.
void SingleDocParser::HandleDocument(EventHandler& eventHandler) {
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
  if (m_scanner.empty()) {
    eventHandler.OnNull(mark, anchor);
    return;
  }

  const Token& token = m_scanner.peek();

  if (token.type == Token::PLAIN_SCALAR && IsNullString(token.value)) {
    eventHandler.OnNull(mark, anchor);
    m_scanner.pop();
    return;
  }

  // add non-specific tags
