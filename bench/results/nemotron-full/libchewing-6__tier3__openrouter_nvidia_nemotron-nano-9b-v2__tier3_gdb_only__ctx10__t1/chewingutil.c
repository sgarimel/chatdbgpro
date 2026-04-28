			}
		}
		return i;
	}

	i = FindIntervalFrom( 0, pgdata->preferInterval, pgdata->nPrefer );
	if ( i >= 0 ) {
		return ( pgdata->preferInterval[ i ].to - pgdata->preferInterval[ i ].from );
	}

	return 1;
}

static void KillFromLeft( ChewingData *pgdata, int nKill )
{
	int i;

	for ( i = 0; i < nKill; i++ )
		ChewingKillChar( pgdata, 0, DECREASE_CURSOR );
}

void CleanAllBuf( ChewingData *pgdata )
{
	/* 1 */
	pgdata->nPhoneSeq = 0 ;
	memset( pgdata->phoneSeq, 0, sizeof( pgdata->phoneSeq ) );
	/* 2 */
	pgdata->chiSymbolBufLen = 0;
	memset( pgdata->chiSymbolBuf, 0, sizeof( pgdata->chiSymbolBuf ) );
	/* 3 */
	memset( pgdata->bUserArrBrkpt, 0, sizeof( pgdata->bUserArrBrkpt ) );
	/* 4 */
	pgdata->nSelect = 0;
	/* 5 */
	pgdata->chiSymbolCursor = 0;
	/* 6 */
	memset( pgdata->bUserArrCnnct, 0, sizeof( pgdata->bUserArrCnnct ) );

	pgdata->phrOut.nNumCut = 0;

	memset( pgdata->symbolKeyBuf, 0, sizeof( pgdata->symbolKeyBuf ) );

	pgdata->nPrefer = 0;
}

int ReleaseChiSymbolBuf( ChewingData *pgdata, ChewingOutput *pgo )
{
	int throwEnd;
	uint16_t bufPhoneSeq[ MAX_PHONE_SEQ_LEN + 1 ];
	char bufWordSeq[ MAX_PHONE_SEQ_LEN * MAX_UTF8_SIZE + 1 ];

	throwEnd = CountReleaseNum( pgdata );

	pgo->nCommitStr = throwEnd;
	if ( throwEnd ) {
		/*
		 * count how many chinese words in "chiSymbolBuf[ 0 .. (throwEnd - 1)]"
		 * And release from "chiSymbolBuf" && "phoneSeq"
		 */
		WriteChiSymbolToBuf( pgo->commitStr, throwEnd, pgdata );

		/* Add to userphrase */
		memcpy( bufPhoneSeq, pgdata->phoneSeq, sizeof( uint16_t ) * throwEnd );
		bufPhoneSeq[ throwEnd ] = (uint16_t) 0;
		ueStrNCpy( bufWordSeq, pgdata->phrOut.chiBuf, throwEnd, 1 );
		UserUpdatePhrase( pgdata, bufPhoneSeq, bufWordSeq );

		KillFromLeft( pgdata, throwEnd );
	}
	return throwEnd;
}

static int ChewingIsBreakPoint( int cursor, ChewingData *pgdata )
{
	static const char * const break_word[] = {
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
	char buf[ MAX_UTF8_SIZE + 1 ];
	int i = 0, symbols = 0;
	for ( i = 0; i < cursor; i++ )
