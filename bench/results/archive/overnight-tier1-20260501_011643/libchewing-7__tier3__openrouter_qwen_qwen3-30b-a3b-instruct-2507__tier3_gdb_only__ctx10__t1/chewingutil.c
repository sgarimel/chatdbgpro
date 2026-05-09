            sizeof(pgdata->preeditBuf[0]) * (pgdata->chiSymbolBufLen - pgdata->chiSymbolCursor));
    /* "0" means Chinese word */
    pgdata->preeditBuf[pgdata->chiSymbolCursor].category = CHEWING_CHINESE;
    pgdata->chiSymbolBufLen++;
    pgdata->chiSymbolCursor++;

    return 0;
}

static void ShowChewingData(ChewingData *pgdata)
{
    int i;

    DEBUG_OUT("nPhoneSeq : %d\n" "phoneSeq  : ", pgdata->nPhoneSeq);
    for (i = 0; i < pgdata->nPhoneSeq; i++)
        DEBUG_OUT("%hu ", pgdata->phoneSeq[i]);
    DEBUG_OUT("[cursor : %d]\n"
              "nSelect : %d\n" "selectStr       selectInterval\n", PhoneSeqCursor(pgdata), pgdata->nSelect);
    for (i = 0; i < pgdata->nSelect; i++) {
        DEBUG_OUT("  %14s%4d%4d\n", pgdata->selectStr[i], pgdata->selectInterval[i].from, pgdata->selectInterval[i].to);
    }

    DEBUG_OUT("bUserArrCnnct : ");
    for (i = 0; i <= pgdata->nPhoneSeq; i++)
        DEBUG_OUT("%d ", pgdata->bUserArrCnnct[i]);
    DEBUG_OUT("\n");

    DEBUG_OUT("bUserArrBrkpt : ");
    for (i = 0; i <= pgdata->nPhoneSeq; i++)
        DEBUG_OUT("%d ", pgdata->bUserArrBrkpt[i]);
    DEBUG_OUT("\n");

    DEBUG_OUT("bArrBrkpt     : ");
    for (i = 0; i <= pgdata->nPhoneSeq; i++)
        DEBUG_OUT("%d ", pgdata->bArrBrkpt[i]);
    DEBUG_OUT("\n");

    DEBUG_OUT("bChiSym : %d , bSelect : %d\n", pgdata->bChiSym, pgdata->bSelect);
}

int CallPhrasing(ChewingData *pgdata, int all_phrasing)
{
    /* set "bSymbolArrBrkpt" && "bArrBrkpt" */
    int i, ch_count = 0;

    memcpy(pgdata->bArrBrkpt, pgdata->bUserArrBrkpt, (MAX_PHONE_SEQ_LEN + 1) * sizeof(int));
    memset(pgdata->bSymbolArrBrkpt, 0, (MAX_PHONE_SEQ_LEN + 1) * sizeof(int));

    for (i = 0; i < pgdata->chiSymbolBufLen; i++) {
        if (ChewingIsChiAt(i, pgdata))
            ch_count++;
        else {
            pgdata->bArrBrkpt[ch_count] = 1;
            pgdata->bSymbolArrBrkpt[ch_count] = 1;
        }
    }

    /* kill select interval */
    for (i = 0; i < pgdata->nPhoneSeq; i++) {
        if (pgdata->bArrBrkpt[i]) {
            ChewingKillSelectIntervalAcross(i, pgdata);
        }
    }

    ShowChewingData(pgdata);

    /* then phrasing */
    Phrasing(pgdata, all_phrasing);

    /* and then make prefer interval */
    MakePreferInterval(pgdata);

    return 0;
}


static void Union(int set1, int set2, int parent[])
{
    if (set1 != set2)
        parent[max(set1, set2)] = min(set1, set2);
}

static int SameSet(int set1, int set2, int parent[])
{
    while (parent[set1] != 0) {
        set1 = parent[set1];
    }
    while (parent[set2] != 0) {
        set2 = parent[set2];
    }
    return (set1 == set2);
}

/* make prefer interval from phrOut->dispInterval */
static void MakePreferInterval(ChewingData *pgdata)
{
    int i, j, set_no;
    int belong_set[MAX_PHONE_SEQ_LEN + 1];
    int parent[MAX_PHONE_SEQ_LEN + 1];

    memset(belong_set, 0, sizeof(int) * (MAX_PHONE_SEQ_LEN + 1));
