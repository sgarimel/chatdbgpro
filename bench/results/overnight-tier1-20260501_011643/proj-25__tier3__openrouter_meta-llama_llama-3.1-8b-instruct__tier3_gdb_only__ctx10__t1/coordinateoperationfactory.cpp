    }

    // There might be better things to do, but for now just ignore the
    // transformation of the bound CRS
    res = createOperations(boundSrc->baseCRS(), targetCRS, context);
}
//! @endcond

// ---------------------------------------------------------------------------

/** \brief Find a list of CoordinateOperation from sourceCRS to targetCRS.
 *
 * The operations are sorted with the most relevant ones first: by
 * descending
 * area (intersection of the transformation area with the area of interest,
 * or intersection of the transformation with the area of use of the CRS),
 * and
 * by increasing accuracy. Operations with unknown accuracy are sorted last,
 * whatever their area.
 *
 * When one of the source or target CRS has a vertical component but not the
 * other one, the one that has no vertical component is automatically promoted
 * to a 3D version, where its vertical axis is the ellipsoidal height in metres,
 * using the ellipsoid of the base geodetic CRS.
 *
 * @param sourceCRS source CRS.
 * @param targetCRS target CRS.
 * @param context Search context.
 * @return a list
 */
std::vector<CoordinateOperationNNPtr>
CoordinateOperationFactory::createOperations(
    const crs::CRSNNPtr &sourceCRS, const crs::CRSNNPtr &targetCRS,
    const CoordinateOperationContextNNPtr &context) const {

#ifdef TRACE_CREATE_OPERATIONS
    ENTER_FUNCTION();
#endif
    // Look if we are called on CRS that have a link to a 'canonical'
    // BoundCRS
    // If so, use that one as input
    const auto &srcBoundCRS = sourceCRS->canonicalBoundCRS();
    const auto &targetBoundCRS = targetCRS->canonicalBoundCRS();
    auto l_sourceCRS = srcBoundCRS ? NN_NO_CHECK(srcBoundCRS) : sourceCRS;
    auto l_targetCRS = targetBoundCRS ? NN_NO_CHECK(targetBoundCRS) : targetCRS;
    const auto &authFactory = context->getAuthorityFactory();

    metadata::ExtentPtr sourceCRSExtent;
    auto l_resolvedSourceCRS =
        crs::CRS::getResolvedCRS(l_sourceCRS, authFactory, sourceCRSExtent);
    metadata::ExtentPtr targetCRSExtent;
    auto l_resolvedTargetCRS =
        crs::CRS::getResolvedCRS(l_targetCRS, authFactory, targetCRSExtent);
    Private::Context contextPrivate(sourceCRSExtent, targetCRSExtent, context);

    if (context->getSourceAndTargetCRSExtentUse() ==
        CoordinateOperationContext::SourceTargetCRSExtentUse::INTERSECTION) {
        if (sourceCRSExtent && targetCRSExtent &&
            !sourceCRSExtent->intersects(NN_NO_CHECK(targetCRSExtent))) {
            return std::vector<CoordinateOperationNNPtr>();
        }
    }

    return filterAndSort(Private::createOperations(l_resolvedSourceCRS,
                                                   l_resolvedTargetCRS,
                                                   contextPrivate),
                         context, sourceCRSExtent, targetCRSExtent);
}

// ---------------------------------------------------------------------------

/** \brief Instantiate a CoordinateOperationFactory.
 */
CoordinateOperationFactoryNNPtr CoordinateOperationFactory::create() {
    return NN_NO_CHECK(
        CoordinateOperationFactory::make_unique<CoordinateOperationFactory>());
}

// ---------------------------------------------------------------------------

} // namespace operation

namespace crs {
// ---------------------------------------------------------------------------

//! @cond Doxygen_Suppress

crs::CRSNNPtr CRS::getResolvedCRS(const crs::CRSNNPtr &crs,
                                  const io::AuthorityFactoryPtr &authFactory,
                                  metadata::ExtentPtr &extentOut) {
    const auto &ids = crs->identifiers();
    const auto &name = crs->nameStr();

    bool approxExtent;
    extentOut = operation::getExtentPossiblySynthetized(crs, approxExtent);

    // We try to "identify" the provided CRS with the ones of the database,
    // but in a more restricted way that what identify() does.
    // If we get a match from id in priority, and from name as a fallback, and
    // that they are equivalent to the input CRS, then use the identified CRS.
    // Even if they aren't equivalent, we update extentOut with the one of the
