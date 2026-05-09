            parameterValueNumericAsSI(EPSG_CODE_PARAMETER_Y_AXIS_TRANSLATION);
        double z =
            parameterValueNumericAsSI(EPSG_CODE_PARAMETER_Z_AXIS_TRANSLATION);
        double da = parameterValueNumericAsSI(
            EPSG_CODE_PARAMETER_SEMI_MAJOR_AXIS_DIFFERENCE);
        double df = parameterValueNumericAsSI(
            EPSG_CODE_PARAMETER_FLATTENING_DIFFERENCE);

        auto sourceCRSGeog =
            dynamic_cast<const crs::GeographicCRS *>(sourceCRS().get());
        if (!sourceCRSGeog) {
            throw io::FormattingException(
                "Can apply Molodensky only to GeographicCRS");
        }

        auto targetCRSGeog =
            dynamic_cast<const crs::GeographicCRS *>(targetCRS().get());
        if (!targetCRSGeog) {
            throw io::FormattingException(
                "Can apply Molodensky only to GeographicCRS");
        }

        formatter->startInversion();
        sourceCRSGeog->_exportToPROJString(formatter);
        formatter->stopInversion();

        formatter->addStep("molodensky");
        sourceCRSGeog->ellipsoid()->_exportToPROJString(formatter);
        formatter->addParam("dx", x);
        formatter->addParam("dy", y);
        formatter->addParam("dz", z);
        formatter->addParam("da", da);
        formatter->addParam("df", df);

        if (ci_find(methodName, "Abridged") != std::string::npos ||
            methodEPSGCode == EPSG_CODE_METHOD_ABRIDGED_MOLODENSKY) {
            formatter->addParam("abridged");
        }

        targetCRSGeog->_exportToPROJString(formatter);

        return;
    }

    if (methodEPSGCode == EPSG_CODE_METHOD_GEOGRAPHIC2D_OFFSETS) {
        double offsetLat =
            parameterValueNumeric(EPSG_CODE_PARAMETER_LATITUDE_OFFSET,
                                  common::UnitOfMeasure::ARC_SECOND);
        double offsetLong =
            parameterValueNumeric(EPSG_CODE_PARAMETER_LONGITUDE_OFFSET,
                                  common::UnitOfMeasure::ARC_SECOND);

        auto sourceCRSGeog =
            dynamic_cast<const crs::GeographicCRS *>(sourceCRS().get());
        if (!sourceCRSGeog) {
            throw io::FormattingException(
                "Can apply Geographic 2D offsets only to GeographicCRS");
        }

        auto targetCRSGeog =
            dynamic_cast<const crs::GeographicCRS *>(targetCRS().get());
        if (!targetCRSGeog) {
            throw io::FormattingException(
                "Can apply Geographic 2D offsets only to GeographicCRS");
        }

        formatter->startInversion();
        sourceCRSGeog->addAngularUnitConvertAndAxisSwap(formatter);
        formatter->stopInversion();

        if (offsetLat != 0.0 || offsetLong != 0.0) {
            formatter->addStep("geogoffset");
            formatter->addParam("dlat", offsetLat);
            formatter->addParam("dlon", offsetLong);
        }

        targetCRSGeog->addAngularUnitConvertAndAxisSwap(formatter);

        return;
    }

    if (methodEPSGCode == EPSG_CODE_METHOD_GEOGRAPHIC3D_OFFSETS) {
        double offsetLat =
            parameterValueNumeric(EPSG_CODE_PARAMETER_LATITUDE_OFFSET,
                                  common::UnitOfMeasure::ARC_SECOND);
        double offsetLong =
            parameterValueNumeric(EPSG_CODE_PARAMETER_LONGITUDE_OFFSET,
                                  common::UnitOfMeasure::ARC_SECOND);
        double offsetHeight =
            parameterValueNumericAsSI(EPSG_CODE_PARAMETER_VERTICAL_OFFSET);

        auto sourceCRSGeog =
            dynamic_cast<const crs::GeographicCRS *>(sourceCRS().get());
        if (!sourceCRSGeog) {
            throw io::FormattingException(
                "Can apply Geographic 3D offsets only to GeographicCRS");
        }

        auto targetCRSGeog =
            dynamic_cast<const crs::GeographicCRS *>(targetCRS().get());
        if (!targetCRSGeog) {
