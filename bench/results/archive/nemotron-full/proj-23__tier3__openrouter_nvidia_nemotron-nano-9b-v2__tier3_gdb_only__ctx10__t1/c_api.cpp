    } catch (const std::exception &e) {
        proj_log_error(ctx, __FUNCTION__, e.what());
        delete ctx->cpp_context;
        ctx->cpp_context =
            new projCppContext(ctx, osPrevDbPath.c_str(), osPrevAuxDbPaths);
        ctx->cpp_context->setAutoCloseDb(autoCloseDb);
        return false;
    }
}

// ---------------------------------------------------------------------------

/** \brief Returns the path to the database.
 *
 * The returned pointer remains valid while ctx is valid, and until
 * proj_context_set_database_path() is called.
 *
 * @param ctx PROJ context, or NULL for default context
 * @return path, or nullptr
 */
const char *proj_context_get_database_path(PJ_CONTEXT *ctx) {
    SANITIZE_CTX(ctx);
    try {
        // temporary variable must be used as getDBcontext() might create
        // ctx->cpp_context
        auto osPath(getDBcontext(ctx)->getPath());
        ctx->cpp_context->lastDbPath_ = osPath;
        ctx->cpp_context->autoCloseDbIfNeeded();
        return ctx->cpp_context->lastDbPath_.c_str();
    } catch (const std::exception &e) {
        proj_log_error(ctx, __FUNCTION__, e.what());
        return nullptr;
    }
}

// ---------------------------------------------------------------------------

/** \brief Return a metadata from the database.
 *
 * The returned pointer remains valid while ctx is valid, and until
 * proj_context_get_database_metadata() is called.
 *
 * @param ctx PROJ context, or NULL for default context
 * @param key Metadata key. Must not be NULL
 * @return value, or nullptr
 */
const char *proj_context_get_database_metadata(PJ_CONTEXT *ctx,
                                               const char *key) {
    SANITIZE_CTX(ctx);
    try {
        // temporary variable must be used as getDBcontext() might create
        // ctx->cpp_context
        auto osVal(getDBcontext(ctx)->getMetadata(key));
        ctx->cpp_context->lastDbMetadataItem_ = osVal;
        ctx->cpp_context->autoCloseDbIfNeeded();
        return ctx->cpp_context->lastDbMetadataItem_.c_str();
    } catch (const std::exception &e) {
        proj_log_error(ctx, __FUNCTION__, e.what());
        return nullptr;
    }
}

// ---------------------------------------------------------------------------

/** \brief Guess the "dialect" of the WKT string.
 *
 * @param ctx PROJ context, or NULL for default context
 * @param wkt String (must not be NULL)
 */
PJ_GUESSED_WKT_DIALECT proj_context_guess_wkt_dialect(PJ_CONTEXT *ctx,
                                                      const char *wkt) {
    (void)ctx;
    assert(wkt);
    switch (WKTParser().guessDialect(wkt)) {
    case WKTParser::WKTGuessedDialect::WKT2_2019:
        return PJ_GUESSED_WKT2_2019;
    case WKTParser::WKTGuessedDialect::WKT2_2015:
        return PJ_GUESSED_WKT2_2015;
    case WKTParser::WKTGuessedDialect::WKT1_GDAL:
        return PJ_GUESSED_WKT1_GDAL;
    case WKTParser::WKTGuessedDialect::WKT1_ESRI:
        return PJ_GUESSED_WKT1_ESRI;
    case WKTParser::WKTGuessedDialect::NOT_WKT:
        break;
    }
    return PJ_GUESSED_NOT_WKT;
}

// ---------------------------------------------------------------------------

//! @cond Doxygen_Suppress
static const char *getOptionValue(const char *option,
                                  const char *keyWithEqual) noexcept {
    if (ci_starts_with(option, keyWithEqual)) {
        return option + strlen(keyWithEqual);
    }
    return nullptr;
}
//! @endcond

// ---------------------------------------------------------------------------
