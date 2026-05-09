// ---------------------------------------------------------------------------

PrimeMeridianNNPtr JSONParser::buildPrimeMeridian(const json &j) {
    if (!j.contains("longitude")) {
        throw ParsingException("Missing \"longitude\" key");
    }
    auto longitude = j["longitude"];
    if (longitude.is_number()) {
        return PrimeMeridian::create(
            buildProperties(j),
            Angle(longitude.get<double>(), UnitOfMeasure::DEGREE));
    } else if (longitude.is_object()) {
        return PrimeMeridian::create(buildProperties(j),
                                     Angle(getMeasure(longitude)));
    }
    throw ParsingException("Unexpected type for value of \"longitude\"");
}

// ---------------------------------------------------------------------------

EllipsoidNNPtr JSONParser::buildEllipsoid(const json &j) {
    if (j.contains("semi_major_axis")) {
        auto semiMajorAxis = getLength(j, "semi_major_axis");
        const auto celestialBody(
            Ellipsoid::guessBodyName(dbContext_, semiMajorAxis.getSIValue()));
        if (j.contains("semi_minor_axis")) {
            return Ellipsoid::createTwoAxis(buildProperties(j), semiMajorAxis,
                                            getLength(j, "semi_minor_axis"),
                                            celestialBody);
        } else if (j.contains("inverse_flattening")) {
            return Ellipsoid::createFlattenedSphere(
                buildProperties(j), semiMajorAxis,
                Scale(getNumber(j, "inverse_flattening")), celestialBody);
        } else {
            throw ParsingException(
                "Missing semi_minor_axis or inverse_flattening");
        }
    } else if (j.contains("radius")) {
        auto radius = getLength(j, "radius");
        const auto celestialBody(
            Ellipsoid::guessBodyName(dbContext_, radius.getSIValue()));
        return Ellipsoid::createSphere(buildProperties(j), radius,
                                       celestialBody);
    }
    throw ParsingException("Missing semi_major_axis or radius");
}

// ---------------------------------------------------------------------------

static BaseObjectNNPtr createFromUserInput(const std::string &text,
                                           const DatabaseContextPtr &dbContext,
                                           bool usePROJ4InitRules,
                                           PJ_CONTEXT *ctx) {

    if (!text.empty() && text[0] == '{') {
        json j;
        try {
            j = json::parse(text);
        } catch (const std::exception &e) {
            throw ParsingException(e.what());
        }
        return JSONParser().attachDatabaseContext(dbContext).create(j);
    }

    if (!ci_starts_with(text, "step proj=") &&
        !ci_starts_with(text, "step +proj=")) {
        for (const auto &wktConstant : WKTConstants::constants()) {
            if (ci_starts_with(text, wktConstant)) {
                for (auto wkt = text.c_str() + wktConstant.size(); *wkt != '\0';
                     ++wkt) {
                    if (isspace(static_cast<unsigned char>(*wkt)))
                        continue;
                    if (*wkt == '[') {
                        return WKTParser()
                            .attachDatabaseContext(dbContext)
                            .setStrict(false)
                            .createFromWKT(text);
                    }
                    break;
                }
            }
        }
    }

    const char *textWithoutPlusPrefix = text.c_str();
    if (textWithoutPlusPrefix[0] == '+')
        textWithoutPlusPrefix++;

    if (strncmp(textWithoutPlusPrefix, "proj=", strlen("proj=")) == 0 ||
        text.find(" +proj=") != std::string::npos ||
        text.find(" proj=") != std::string::npos ||
        strncmp(textWithoutPlusPrefix, "init=", strlen("init=")) == 0 ||
        text.find(" +init=") != std::string::npos ||
        text.find(" init=") != std::string::npos ||
        strncmp(textWithoutPlusPrefix, "title=", strlen("title=")) == 0) {
        return PROJStringParser()
            .attachDatabaseContext(dbContext)
            .attachContext(ctx)
            .setUsePROJ4InitRules(ctx != nullptr
                                      ? (proj_context_get_use_proj4_init_rules(
                                             ctx, false) == TRUE)
