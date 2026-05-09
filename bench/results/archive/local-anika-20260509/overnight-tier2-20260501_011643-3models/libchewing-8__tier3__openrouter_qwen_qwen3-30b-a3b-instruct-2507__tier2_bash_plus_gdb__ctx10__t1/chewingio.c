
CHEWING_API int chewing_handle_ShiftSpace( ChewingContext *ctx )
{
	ChewingData *pgdata = ctx->data;
	ChewingOutput *pgo = ctx->output;
	int keystrokeRtn = KEYSTROKE_ABSORB;

	if ( ! pgdata->bSelect ) {
		CheckAndResetRange( pgdata );
	}
	CallPhrasing( pgdata, 0 );
	MakeOutputWithRtn( pgo, pgdata, keystrokeRtn );
	return 0;
}

CHEWING_API int chewing_handle_Numlock( ChewingContext *ctx, int key )
{
	ChewingData *pgdata = ctx->data;
	ChewingOutput *pgo = ctx->output;
	int rtn, QuickCommit = 0;
	int keystrokeRtn = KEYSTROKE_ABSORB;

	if ( ! pgdata->bSelect ) {
		/* If we're not selecting words, we should send out numeric
		 * characters at once.
		 */
		if ( pgdata->chiSymbolBufLen == 0 ) {
			QuickCommit = 1;
		}
		rtn = SymbolInput( key, pgdata );
		/* copied from chewing_handle_Default */
		if ( rtn == SYMBOL_KEY_ERROR ) {
			keystrokeRtn = KEYSTROKE_IGNORE ;
		}
		else if ( QuickCommit ) {
			pgo->commitStr[ 0 ] = pgdata->chiSymbolBuf[ 0 ];
			pgo->nCommitStr = 1;
			pgdata->chiSymbolBufLen = 0;
			pgdata->chiSymbolCursor = 0;
			keystrokeRtn = KEYSTROKE_COMMIT;
		}
		else {	/* Not quick commit */
			CallPhrasing( pgdata, 0 );
			if( ReleaseChiSymbolBuf( pgdata, pgo ) != 0 )
				keystrokeRtn = KEYSTROKE_COMMIT;
		}
	}
	else {
		/* Otherwise, if we are selecting words, we use numeric keys
		 * as selkey
		 * and submit the words.
		 */
		int num = -1;
		if ( key > '0' && key < '9' )
			num = key - '1';
		else if ( key == '0' )
			num = 9;
		DoSelect( pgdata, num );
	}
	CallPhrasing( pgdata, 0 );
	if ( ReleaseChiSymbolBuf( pgdata, pgo ) != 0 )
		keystrokeRtn = KEYSTROKE_COMMIT;
	MakeOutputWithRtn( pgo, pgdata, keystrokeRtn );
	return 0;
}

CHEWING_API unsigned short *chewing_get_phoneSeq( ChewingContext *ctx )
{
	uint16_t *seq;
	seq = ALC( uint16_t, ctx->data->nPhoneSeq );
	if ( seq )
		memcpy( seq, ctx->data->phoneSeq, sizeof(uint16_t)*ctx->data->nPhoneSeq );
	return seq;
}

CHEWING_API int chewing_get_phoneSeqLen( ChewingContext *ctx )
{
	return ctx->data->nPhoneSeq;
}

CHEWING_API void chewing_set_logger( ChewingContext *ctx,
	void (*logger)( void *data, int level, const char *fmt, ... ),
	void *data )
{
	if ( !logger ) {
		logger = NullLogger;
		data = 0;
	}
	ctx->data->logger = logger;
	ctx->data->loggerData = data;
}
