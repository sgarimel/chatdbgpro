    bool nextMoreIndented = Exp::Blank().Matches(INPUT);
    if (params.fold == FOLD_BLOCK && foldedNewlineCount == 0 && nextEmptyLine)
      foldedNewlineStartedMoreIndented = moreIndented;

    // for block scalars, we always start with a newline, so we should ignore it
    // (not fold or keep)
    if (pastOpeningBreak) {
      switch (params.fold) {
        case DONT_FOLD:
          scalar += "\n";
          break;
        case FOLD_BLOCK:
          if (!emptyLine && !nextEmptyLine && !moreIndented &&
              !nextMoreIndented && INPUT.column() >= params.indent) {
            scalar += " ";
          } else if (nextEmptyLine) {
            foldedNewlineCount++;
          } else {
            scalar += "\n";
          }

          if (!nextEmptyLine && foldedNewlineCount > 0) {
            scalar += std::string(foldedNewlineCount - 1, '\n');
            if (foldedNewlineStartedMoreIndented ||
                nextMoreIndented | !foundNonEmptyLine) {
              scalar += "\n";
            }
            foldedNewlineCount = 0;
          }
          break;
        case FOLD_FLOW:
          if (nextEmptyLine) {
            scalar += "\n";
          } else if (!emptyLine && !escapedNewline) {
            scalar += " ";
          }
          break;
      }
    }

    emptyLine = nextEmptyLine;
    moreIndented = nextMoreIndented;
    pastOpeningBreak = true;

    // are we done via indentation?
    if (!emptyLine && INPUT.column() < params.indent) {
      params.leadingSpaces = true;
      break;
    }
  }

  // post-processing
  if (params.trimTrailingSpaces) {
    std::size_t pos = scalar.find_last_not_of(' ');
    if (lastEscapedChar != std::string::npos) {
      if (pos < lastEscapedChar || pos == std::string::npos) {
        pos = lastEscapedChar;
      }
    }
    if (pos < scalar.size()) {
      scalar.erase(pos + 1);
    }
  }

  switch (params.chomp) {
    case CLIP: {
      std::size_t pos = scalar.find_last_not_of('\n');
      if (lastEscapedChar != std::string::npos) {
        if (pos < lastEscapedChar || pos == std::string::npos) {
          pos = lastEscapedChar;
        }
      }
      if (pos == std::string::npos) {
        scalar.erase();
      } else if (pos + 1 < scalar.size()) {
        scalar.erase(pos + 2);
      }
    } break;
    case STRIP: {
      std::size_t pos = scalar.find_last_not_of('\n');
      if (lastEscapedChar != std::string::npos) {
        if (pos < lastEscapedChar || pos == std::string::npos) {
          pos = lastEscapedChar;
        }
      }
      if (pos == std::string::npos) {
        scalar.erase();
      } else if (pos < scalar.size()) {
        scalar.erase(pos + 1);
      }
    } break;
    default:
      break;
  }

  return scalar;
}
}  // namespace YAML
