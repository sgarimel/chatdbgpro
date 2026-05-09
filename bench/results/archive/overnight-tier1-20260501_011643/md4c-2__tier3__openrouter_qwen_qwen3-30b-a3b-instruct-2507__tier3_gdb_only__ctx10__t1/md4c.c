                    } else {
                        MD_LEAVE_SPAN(MD_SPAN_CODE, NULL);
                        text_type = MD_TEXT_NORMAL;
                    }
                    break;

                case '_':
                case '*':       /* Emphasis, strong emphasis. */
                    if(mark->flags & MD_MARK_OPENER) {
                        if((mark->end - off) % 2) {
                            MD_ENTER_SPAN(MD_SPAN_EM, NULL);
                            off++;
                        }
                        while(off + 1 < mark->end) {
                            MD_ENTER_SPAN(MD_SPAN_STRONG, NULL);
                            off += 2;
                        }
                    } else {
                        while(off + 1 < mark->end) {
                            MD_LEAVE_SPAN(MD_SPAN_STRONG, NULL);
                            off += 2;
                        }
                        if((mark->end - off) % 2) {
                            MD_LEAVE_SPAN(MD_SPAN_EM, NULL);
                            off++;
                        }
                    }
                    break;

                case '~':
                    if(mark->flags & MD_MARK_OPENER)
                        MD_ENTER_SPAN(MD_SPAN_DEL, NULL);
                    else
                        MD_LEAVE_SPAN(MD_SPAN_DEL, NULL);
                    break;

                case '[':       /* Link, image. */
                case '!':
                case ']':
                {
                    const MD_MARK* opener = (mark->ch != ']' ? mark : &ctx->marks[mark->prev]);
                    const MD_MARK* dest_mark = opener+1;
                    const MD_MARK* title_mark = opener+2;

                    MD_ASSERT(dest_mark->ch == 'D');
                    MD_ASSERT(title_mark->ch == 'D');

                    MD_CHECK(md_enter_leave_span_a(ctx, (mark->ch != ']'),
                                (opener->ch == '!' ? MD_SPAN_IMG : MD_SPAN_A),
                                STR(dest_mark->beg), dest_mark->end - dest_mark->beg, FALSE,
                                md_mark_get_ptr(ctx, title_mark - ctx->marks), title_mark->prev));

                    /* link/image closer may span multiple lines. */

                    break;
                }

                case '<':
                case '>':       /* Autolink or raw HTML. */
                    if(!(mark->flags & MD_MARK_AUTOLINK)) {
                        /* Raw HTML. */
                        if(mark->flags & MD_MARK_OPENER)
                            text_type = MD_TEXT_HTML;
                        else
                            text_type = MD_TEXT_NORMAL;
                        break;
                    }
                    /* Pass through, if auto-link. */

                case '@':       /* Permissive e-mail autolink. */
                case ':':       /* Permissive URL autolink. */
                case '.':       /* Permissive WWW autolink. */
                {
                    const MD_MARK* opener = ((mark->flags & MD_MARK_OPENER) ? mark : &ctx->marks[mark->prev]);
                    const MD_MARK* closer = &ctx->marks[opener->next];
                    const CHAR* dest = STR(opener->end);
                    SZ dest_size = closer->beg - opener->end;

                    if(opener->ch == '@' || opener->ch == '.') {
                        dest_size += 7;
                        MD_TEMP_BUFFER(dest_size * sizeof(CHAR));
                        memcpy(ctx->buffer,
                                (opener->ch == '@' ? _T("mailto:") : _T("http://")),
                                7 * sizeof(CHAR));
                        memcpy(ctx->buffer + 7, dest, (dest_size-7) * sizeof(CHAR));
                        dest = ctx->buffer;
                    }

                    MD_CHECK(md_enter_leave_span_a(ctx, (mark->flags & MD_MARK_OPENER),
                                MD_SPAN_A, dest, dest_size, TRUE, NULL, 0));
                    break;
                }

                case '&':       /* Entity. */
                    MD_TEXT(MD_TEXT_ENTITY, STR(mark->beg), mark->end - mark->beg);
                    break;

                case '\0':
                    MD_TEXT(MD_TEXT_NULLCHAR, _T(""), 1);
                    break;
            }
