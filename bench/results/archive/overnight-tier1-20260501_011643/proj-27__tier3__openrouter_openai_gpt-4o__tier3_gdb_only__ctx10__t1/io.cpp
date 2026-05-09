                    CoordinateSystemAxis::create(
                        util::PropertyMap().set(IdentifiedObject::NAME_KEY,
                                                AxisName::Westing),
                        emptyString, AxisDirection::WEST, linearUnit))
                    .as_nullable();
        } else if (methodCode ==
                       EPSG_CODE_METHOD_POLAR_STEREOGRAPHIC_VARIANT_A ||
                   methodCode ==
                       EPSG_CODE_METHOD_LAMBERT_AZIMUTHAL_EQUAL_AREA) {
            // It is likely that the ESRI definition of EPSG:32661 (UPS North) &
            // EPSG:32761 (UPS South) uses the easting-northing order, instead
            // of the EPSG northing-easting order.
            // Same for WKT1_GDAL
            const double lat0 = conversion->parameterValueNumeric(
                EPSG_CODE_PARAMETER_LATITUDE_OF_NATURAL_ORIGIN,
                common::UnitOfMeasure::DEGREE);
            if (std::fabs(lat0 - 90) < 1e-10) {
                cartesianCS =
                    CartesianCS::createNorthPoleEastingSouthNorthingSouth(
                        linearUnit)
                        .as_nullable();
            } else if (std::fabs(lat0 - -90) < 1e-10) {
                cartesianCS =
                    CartesianCS::createSouthPoleEastingNorthNorthingNorth(
                        linearUnit)
                        .as_nullable();
            }
        } else if (methodCode ==
                   EPSG_CODE_METHOD_POLAR_STEREOGRAPHIC_VARIANT_B) {
            const double lat_ts = conversion->parameterValueNumeric(
                EPSG_CODE_PARAMETER_LATITUDE_STD_PARALLEL,
                common::UnitOfMeasure::DEGREE);
            if (lat_ts > 0) {
                cartesianCS =
                    CartesianCS::createNorthPoleEastingSouthNorthingSouth(
                        linearUnit)
                        .as_nullable();
            } else if (lat_ts < 0) {
                cartesianCS =
                    CartesianCS::createSouthPoleEastingNorthNorthingNorth(
                        linearUnit)
                        .as_nullable();
            }
        } else if (methodCode ==
                   EPSG_CODE_METHOD_TRANSVERSE_MERCATOR_SOUTH_ORIENTATED) {
            cartesianCS =
                CartesianCS::createWestingSouthing(linearUnit).as_nullable();
        }
    }
    if (!cartesianCS) {
        ThrowNotExpectedCSType("Cartesian");
    }


    addExtensionProj4ToProp(nodeP, props);

    return ProjectedCRS::create(props, baseGeodCRS, conversion,
                                NN_NO_CHECK(cartesianCS));
}

// ---------------------------------------------------------------------------

void WKTParser::Private::parseDynamic(const WKTNodeNNPtr &dynamicNode,
                                      double &frameReferenceEpoch,
                                      util::optional<std::string> &modelName) {
    auto &frameEpochNode = dynamicNode->lookForChild(WKTConstants::FRAMEEPOCH);
    const auto &frameEpochChildren = frameEpochNode->GP()->children();
    if (frameEpochChildren.empty()) {
        ThrowMissing(WKTConstants::FRAMEEPOCH);
    }
    try {
        frameReferenceEpoch = asDouble(frameEpochChildren[0]);
    } catch (const std::exception &) {
        throw ParsingException("Invalid FRAMEEPOCH node");
    }
    auto &modelNode = dynamicNode->GP()->lookForChild(
        WKTConstants::MODEL, WKTConstants::VELOCITYGRID);
    const auto &modelChildren = modelNode->GP()->children();
    if (modelChildren.size() == 1) {
        modelName = stripQuotes(modelChildren[0]);
    }
}

// ---------------------------------------------------------------------------

VerticalReferenceFrameNNPtr WKTParser::Private::buildVerticalReferenceFrame(
    const WKTNodeNNPtr &node, const WKTNodeNNPtr &dynamicNode) {

    if (!isNull(dynamicNode)) {
        double frameReferenceEpoch = 0.0;
        util::optional<std::string> modelName;
        parseDynamic(dynamicNode, frameReferenceEpoch, modelName);
        return DynamicVerticalReferenceFrame::create(
            buildProperties(node), getAnchor(node),
            optional<RealizationMethod>(),
            common::Measure(frameReferenceEpoch, common::UnitOfMeasure::YEAR),
            modelName);
    }

    // WKT1 VERT_DATUM has a datum type after the datum name that we ignore.
    return VerticalReferenceFrame::create(buildProperties(node),
