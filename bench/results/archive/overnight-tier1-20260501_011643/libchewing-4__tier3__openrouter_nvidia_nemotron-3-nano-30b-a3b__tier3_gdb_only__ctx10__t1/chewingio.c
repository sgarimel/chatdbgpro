	CheckAndResetRange( pgdata );

	if ( ! ChewingIsEntering( pgdata ) ) {
		keystrokeRtn = KEYSTROKE_IGNORE;
	}

	if ( ! pgdata->bSelect ) {
		if ( ZuinIsEntering( &( pgdata->zuinData ) ) ) {
			ZuinRemoveLast( &( pgdata->zuinData ) );
		}
		else if ( pgdata->chiSymbolCursor > 0 ) {
			ChewingKillChar(
				pgdata,
				pgdata->chiSymbolCursor - 1,
				DECREASE_CURSOR );
		}
		CallPhrasing( pgdata, 0 );
	}
	else if ( pgdata->bSelect ) {
		chewing_cand_close( ctx );
	}

	MakeOutputWithRtn( pgo, pgdata, keystrokeRtn );
	return 0;
}

CHEWING_API int chewing_handle_Up( ChewingContext *ctx )
{
	ChewingData *pgdata;
	ChewingOutput *pgo;
	int keystrokeRtn = KEYSTROKE_ABSORB;
	int key_buf_cursor;

	if ( !ctx ) {
		return -1;
	}
	pgdata = ctx->data;
	pgo = ctx->output;

	LOG_API();

	CheckAndResetRange( pgdata );

	if ( ! ChewingIsEntering( pgdata ) ) {
		keystrokeRtn = KEYSTROKE_IGNORE;
	}

	key_buf_cursor = pgdata->chiSymbolCursor;
	// FIXME: when pgdata->chiSymbolBufLen == 0, key_buf_cursor will be -1.
	if ( pgdata->chiSymbolCursor == pgdata->chiSymbolBufLen )
		key_buf_cursor--;

	/* close candidate list, compared to Down key to open candidate list. */
	if ( ! pgdata->symbolKeyBuf[ key_buf_cursor ] ) {
		if ( pgdata->bSelect ) {
			ChoiceEndChoice( pgdata );
		}
	}

	MakeOutputWithRtn( pgo, pgdata, keystrokeRtn );
	return 0;
}

CHEWING_API int chewing_handle_Down( ChewingContext *ctx )
{
	ChewingData *pgdata;
	ChewingOutput *pgo;
	int toSelect = 0;
	int keystrokeRtn = KEYSTROKE_ABSORB;
	int key_buf_cursor;

	if ( !ctx ) {
		return -1;
	}
	pgdata = ctx->data;
	pgo = ctx->output;

	LOG_API();

	CheckAndResetRange( pgdata );

	if ( ! ChewingIsEntering( pgdata ) ) {
		keystrokeRtn = KEYSTROKE_IGNORE;
	}

	key_buf_cursor = pgdata->chiSymbolCursor;
	if ( pgdata->chiSymbolCursor == pgdata->chiSymbolBufLen && key_buf_cursor > 0 )
		key_buf_cursor--;

	/* see if to select */
	if ( ChewingIsChiAt( key_buf_cursor, pgdata ) )
			toSelect = 1;

	chooseCandidate( ctx, toSelect, key_buf_cursor );

	MakeOutputWithRtn( pgo, pgdata, keystrokeRtn );
	return 0;
}

/* Add phrase in Hanin Style */
CHEWING_API int chewing_handle_ShiftLeft( ChewingContext *ctx )
