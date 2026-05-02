
                copyStringFromPreeditBuf(pgdata, cursor, newPhraseLen, addWordSeq, sizeof(addWordSeq));

                phraseState = UserUpdatePhrase(pgdata, addPhoneSeq, addWordSeq);
                SetUpdatePhraseMsg(pgdata, addWordSeq, newPhraseLen, phraseState);

                /* Clear the breakpoint between the New Phrase */
                for (i = 1; i < newPhraseLen; i++)
                    pgdata->bUserArrBrkpt[cursor + i] = 0;
            }
        }
    } else {
        if (newPhraseLen >= 1 && cursor - newPhraseLen >= 0) {
            if (NoSymbolBetween(pgdata, cursor - newPhraseLen, cursor)) {
                /* Manually add phrase to the user phrase database. */
                memcpy(addPhoneSeq, &pgdata->phoneSeq[cursor - newPhraseLen], sizeof(uint16_t) * newPhraseLen);
                addPhoneSeq[newPhraseLen] = 0;

                copyStringFromPreeditBuf(pgdata, cursor - newPhraseLen, newPhraseLen, addWordSeq, sizeof(addWordSeq));

                phraseState = UserUpdatePhrase(pgdata, addPhoneSeq, addWordSeq);
                SetUpdatePhraseMsg(pgdata, addWordSeq, newPhraseLen, phraseState);

                /* Clear the breakpoint between the New Phrase */
                for (i = 1; i < newPhraseLen; i++)
                    pgdata->bUserArrBrkpt[cursor - newPhraseLen + i] = 0;
            }
        }
    }
    CallPhrasing(pgdata, 0);
    MakeOutputWithRtn(pgo, pgdata, keystrokeRtn);
    MakeOutputAddMsgAndCleanInterval(pgo, pgdata);
    return 0;
}

CHEWING_API int chewing_handle_ShiftSpace(ChewingContext *ctx)
{
    ChewingData *pgdata;
    ChewingOutput *pgo;
    int keystrokeRtn = KEYSTROKE_ABSORB;

    if (!ctx) {
        return -1;
    }
    pgdata = ctx->data;
    pgo = ctx->output;

    LOG_API("");

    if (!pgdata->bSelect) {
        CheckAndResetRange(pgdata);
    }


    CallPhrasing(pgdata, 0);
    MakeOutputWithRtn(pgo, pgdata, keystrokeRtn);
    return 0;
}

CHEWING_API int chewing_handle_Numlock(ChewingContext *ctx, int key)
{
    ChewingData *pgdata;
    ChewingOutput *pgo;
    int keystrokeRtn = KEYSTROKE_ABSORB;
    int rtn;
    int QuickCommit = 0;

    if (!ctx) {
        return -1;
    }
    pgdata = ctx->data;
    pgo = ctx->output;

    LOG_API("");

    if (!pgdata->bSelect) {
        /* If we're not selecting words, we should send out numeric
         * characters at once.
         */
        if (pgdata->chiSymbolBufLen == 0) {
            QuickCommit = 1;
        }
        rtn = SymbolInput(key, pgdata);
        /* copied from chewing_handle_Default */
        if (rtn == SYMBOL_KEY_ERROR) {
            keystrokeRtn = KEYSTROKE_IGNORE;
        } else if (QuickCommit) {
            WriteChiSymbolToCommitBuf(pgdata, pgo, 1);
            pgdata->chiSymbolBufLen = 0;
            pgdata->chiSymbolCursor = 0;
            keystrokeRtn = KEYSTROKE_COMMIT;
        } else {                /* Not quick commit */
            CallPhrasing(pgdata, 0);
            if (ReleaseChiSymbolBuf(pgdata, pgo) != 0)
                keystrokeRtn = KEYSTROKE_COMMIT;
        }
    } else {
        /* Otherwise, if we are selecting words, we use numeric keys
         * as selkey
         * and submit the words.
         */
