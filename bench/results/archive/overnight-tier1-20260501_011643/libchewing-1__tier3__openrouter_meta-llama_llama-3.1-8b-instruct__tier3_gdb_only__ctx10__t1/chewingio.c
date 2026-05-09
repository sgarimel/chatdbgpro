
    if (!ctx) {
        return -1;
    }
    pgdata = ctx->data;

    LOG_API("bEasySymbolInput = %d", ctx->data->config.bEasySymbolInput);

    return ctx->data->config.bEasySymbolInput;
}

CHEWING_API void chewing_set_phraseChoiceRearward(ChewingContext *ctx, int mode)
{
    ChewingData *pgdata;

    if (!ctx) {
        return;
    }
    pgdata = ctx->data;

    LOG_API("mode = %d", mode);

    if (mode == 0 || mode == 1)
        ctx->data->config.bPhraseChoiceRearward = mode;
}

CHEWING_API int chewing_get_phraseChoiceRearward(const ChewingContext *ctx)
{
    const ChewingData *pgdata;

    if (!ctx) {
        return -1;
    }
    pgdata = ctx->data;

    LOG_API("bPhraseChoiceRearward = %d", ctx->data->config.bPhraseChoiceRearward);

    return ctx->data->config.bPhraseChoiceRearward;
}

CHEWING_API void chewing_set_ChiEngMode(ChewingContext *ctx, int mode)
{
    ChewingData *pgdata;

    if (!ctx) {
        return;
    }
    pgdata = ctx->data;

    LOG_API("mode = %d", mode);

    if (mode == CHINESE_MODE || mode == SYMBOL_MODE) {
        // remove all data inside buffer as switching mode.
        BopomofoRemoveAll(&(ctx->data->bopomofoData));
        MakeOutputWithRtn(ctx->output, ctx->data, KEYSTROKE_ABSORB);
        ctx->data->bChiSym = mode;
    }
}

CHEWING_API int chewing_get_ChiEngMode(const ChewingContext *ctx)
{
    const ChewingData *pgdata;

    if (!ctx) {
        return -1;
    }
    pgdata = ctx->data;

    LOG_API("bChiSym = %d", ctx->data->bChiSym);

    return ctx->data->bChiSym;
}

CHEWING_API void chewing_set_ShapeMode(ChewingContext *ctx, int mode)
{
    ChewingData *pgdata;

    if (!ctx) {
        return;
    }
    pgdata = ctx->data;

    LOG_API("mode = %d", mode);

    if (mode == HALFSHAPE_MODE || mode == FULLSHAPE_MODE)
        ctx->data->bFullShape = mode;
}

CHEWING_API int chewing_get_ShapeMode(const ChewingContext *ctx)
{
    const ChewingData *pgdata;

    if (!ctx) {
        return -1;
    }
    pgdata = ctx->data;

    LOG_API("ctx->data->bFullShape = %d", ctx->data->bFullShape);

    return ctx->data->bFullShape;
}
