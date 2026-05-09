	if ( throwEnd ) {
		/*
		 * count how many chinese words in "chiSymbolBuf[ 0 .. (throwEnd - 1)]"
		 * And release from "chiSymbolBuf" && "phoneSeq"
		 */
		WriteChiSymbolToCommitBuf( pgdata, pgo, throwEnd );
		KillFromLeft( pgdata, throwEnd );
	}
	return throwEnd;
}

static int ChewingIsBreakPoint( int cursor, ChewingData *pgdata )
{
	static const char * const BREAK_WORD[] = {
		"\xE6\x98\xAF", "\xE7\x9A\x84", "\xE4\xBA\x86", "\xE4\xB8\x8D",
		/* 是              的              了              不 */
		"\xE4\xB9\x9F", "\xE8\x80\x8C", "\xE4\xBD\xA0", "\xE6\x88\x91",
		/* 也              而              你              我 */
		"\xE4\xBB\x96", "\xE8\x88\x87", "\xE5\xAE\x83", "\xE5\xA5\xB9",
		/* 他              與              它              她 */
		"\xE5\x85\xB6", "\xE5\xB0\xB1", "\xE5\x92\x8C", "\xE6\x88\x96",
		/* 其              就              和              或 */
		"\xE5\x80\x91", "\xE6\x80\xA7", "\xE5\x93\xA1", "\xE5\xAD\x90",
		/* 們              性              員              子 */
		"\xE4\xB8\x8A", "\xE4\xB8\x8B", "\xE4\xB8\xAD", "\xE5\x85\xA7",
		/* 上              下              中              內 */
		"\xE5\xA4\x96", "\xE5\x8C\x96", "\xE8\x80\x85", "\xE5\xAE\xB6",
		/* 外              化              者              家 */
		"\xE5\x85\x92", "\xE5\xB9\xB4", "\xE6\x9C\x88", "\xE6\x97\xA5",
		/* 兒              年              月              日 */
		"\xE6\x99\x82", "\xE5\x88\x86", "\xE7\xA7\x92", "\xE8\xA1\x97",
		/* 時              分              秒              街 */
		"\xE8\xB7\xAF", "\xE6\x9D\x91",
		/* 路              村 */
		"\xE5\x9C\xA8",
		/* 在 */
	};
	int i;

	if ( ! ChewingIsChiAt( cursor, pgdata ) )
		return 1;

	for ( i = 0; i < ARRAY_SIZE( BREAK_WORD ); ++i )
		if ( ! strcmp( pgdata->preeditBuf[ cursor ].char_, BREAK_WORD[ i ]) )
			return 1;

	return 0;
}

void AutoLearnPhrase( ChewingData *pgdata )
{
	uint16_t bufPhoneSeq[ MAX_PHONE_SEQ_LEN + 1 ];
	char bufWordSeq[ MAX_PHONE_SEQ_LEN * MAX_UTF8_SIZE + 1 ] = { 0 };
	int i, from, len;
	int bufWordLen;
	int prev_pos = 0;
	int pending = 0;

	for ( i = 0; i < pgdata->nPrefer; i++ ) {
		from = pgdata->preferInterval[ i ].from;
		len = pgdata->preferInterval[i].to - from;
		if ( len == 1 && ! ChewingIsBreakPoint( from, pgdata ) ) {
			memcpy( bufPhoneSeq + prev_pos, &pgdata->phoneSeq[ from ], sizeof( uint16_t ) * len );
			bufPhoneSeq[ prev_pos + len ] = (uint16_t) 0;

			bufWordLen = strlen( bufWordSeq );
			copyStringFromPreeditBuf( pgdata, from, len,
				bufWordSeq + bufWordLen, sizeof( bufWordSeq ) - bufWordLen );
			prev_pos += len;
			pending = 1;
		}
		else {
			if ( pending ) {
				UserUpdatePhrase( pgdata, bufPhoneSeq, bufWordSeq );
				prev_pos = 0;
				pending = 0;
			}
			memcpy( bufPhoneSeq, &pgdata->phoneSeq[ from ], sizeof( uint16_t ) * len );
			bufPhoneSeq[ len ] = (uint16_t) 0;
			copyStringFromPreeditBuf( pgdata, from, len, bufWordSeq, sizeof( bufWordSeq ) );
			UserUpdatePhrase( pgdata, bufPhoneSeq, bufWordSeq );
		}
	}
	if ( pending ) {
		UserUpdatePhrase( pgdata, bufPhoneSeq, bufWordSeq );
		prev_pos = 0;
		pending = 0;
	}
}

int AddChi( uint16_t phone, uint16_t phoneAlt, ChewingData *pgdata )
{
	int i;
	int cursor = PhoneSeqCursor( pgdata );

	/* shift the selectInterval */
	for ( i = 0; i < pgdata->nSelect; i++ ) {
		if ( pgdata->selectInterval[ i ].from >= cursor ) {
			pgdata->selectInterval[ i ].from++;
			pgdata->selectInterval[ i ].to++;
		}
