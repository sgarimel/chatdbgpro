    if (fpRaw->read(header, sizeof(header)) != sizeof(header)) {
        pj_ctx_set_errno(ctx, PJD_ERR_FAILED_TO_LOAD_GRID);
        return nullptr;
    }

    constexpr int OFFSET_GS_TYPE = 56;
    if (memcmp(header + OFFSET_GS_TYPE, "SECONDS", 7) != 0) {
        pj_log(ctx, PJ_LOG_ERROR, "Only GS_TYPE=SECONDS is supported");
        pj_ctx_set_errno(ctx, PJD_ERR_FAILED_TO_LOAD_GRID);
        return nullptr;
    }

    const bool must_swap = (header[8] == 11) ? !IS_LSB : IS_LSB;
    constexpr int OFFSET_NUM_SUBFILES = 8 + 32;
    if (must_swap) {
        // swap_words( header+8, 4, 1 );
        // swap_words( header+8+16, 4, 1 );
        swap_words(header + OFFSET_NUM_SUBFILES, 4, 1);
        // swap_words( header+8+7*16, 8, 1 );
        // swap_words( header+8+8*16, 8, 1 );
        // swap_words( header+8+9*16, 8, 1 );
        // swap_words( header+8+10*16, 8, 1 );
    }

    /* -------------------------------------------------------------------- */
    /*      Get the subfile count out ... all we really use for now.        */
    /* -------------------------------------------------------------------- */
    unsigned int num_subfiles;
    memcpy(&num_subfiles, header + OFFSET_NUM_SUBFILES, 4);

    std::map<std::string, NTv2Grid *> mapGrids;

    /* ==================================================================== */
    /*      Step through the subfiles, creating a grid for each.            */
    /* ==================================================================== */
    for (unsigned subfile = 0; subfile < num_subfiles; subfile++) {
        // Read header
        if (fpRaw->read(header, sizeof(header)) != sizeof(header)) {
            pj_ctx_set_errno(ctx, PJD_ERR_FAILED_TO_LOAD_GRID);
            return nullptr;
        }

        if (strncmp(header, "SUB_NAME", 8) != 0) {
            pj_ctx_set_errno(ctx, PJD_ERR_FAILED_TO_LOAD_GRID);
            return nullptr;
        }

        // Byte swap interesting fields if needed.
        constexpr int OFFSET_GS_COUNT = 8 + 16 * 10;
        constexpr int OFFSET_SOUTH_LAT = 8 + 16 * 4;
        if (must_swap) {
            // 6 double values: southLat, northLat, eastLon, westLon, resLat,
            // resLon
            swap_words(header + OFFSET_SOUTH_LAT, sizeof(double), 6);
            swap_words(header + OFFSET_GS_COUNT, sizeof(int), 1);
        }

        std::string gridName;
        gridName.append(header + 8, 8);

        ExtentAndRes extent;
        extent.southLat = to_double(header + OFFSET_SOUTH_LAT) * DEG_TO_RAD /
                          3600.0; /* S_LAT */
        extent.northLat = to_double(header + OFFSET_SOUTH_LAT + 16) *
                          DEG_TO_RAD / 3600.0; /* N_LAT */
        extent.eastLon = -to_double(header + OFFSET_SOUTH_LAT + 16 * 2) *
                         DEG_TO_RAD / 3600.0; /* E_LONG */
        extent.westLon = -to_double(header + OFFSET_SOUTH_LAT + 16 * 3) *
                         DEG_TO_RAD / 3600.0; /* W_LONG */
        extent.resLat =
            to_double(header + OFFSET_SOUTH_LAT + 16 * 4) * DEG_TO_RAD / 3600.0;
        extent.resLon =
            to_double(header + OFFSET_SOUTH_LAT + 16 * 5) * DEG_TO_RAD / 3600.0;

        if (!(fabs(extent.westLon) <= 4 * M_PI &&
              fabs(extent.eastLon) <= 4 * M_PI &&
              fabs(extent.northLat) <= M_PI + 1e-5 &&
              fabs(extent.southLat) <= M_PI + 1e-5 &&
              extent.westLon < extent.eastLon &&
              extent.southLat < extent.northLat && extent.resLon > 1e-10 &&
              extent.resLat > 1e-10)) {
            pj_log(ctx, PJ_LOG_ERROR, "Inconsistent georeferencing for %s",
                   filename.c_str());
            pj_ctx_set_errno(ctx, PJD_ERR_FAILED_TO_LOAD_GRID);
            return nullptr;
        }
        const int columns = static_cast<int>(
            fabs((extent.eastLon - extent.westLon) / extent.resLon + 0.5) + 1);
        const int rows = static_cast<int>(
            fabs((extent.northLat - extent.southLat) / extent.resLat + 0.5) +
            1);

        pj_log(ctx, PJ_LOG_DEBUG_MINOR,
               "NTv2 %s %dx%d: LL=(%.9g,%.9g) UR=(%.9g,%.9g)", gridName.c_str(),
               columns, rows, extent.westLon * RAD_TO_DEG,
               extent.southLat * RAD_TO_DEG, extent.eastLon * RAD_TO_DEG,
               extent.northLat * RAD_TO_DEG);

        unsigned int gs_count;
        memcpy(&gs_count, header + OFFSET_GS_COUNT, 4);
        if (gs_count / columns != static_cast<unsigned>(rows)) {
