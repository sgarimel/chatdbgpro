
    if (authorityFactory) {

        const bool unsignificantName = thisName.empty() ||
                                       ci_equal(thisName, "unknown") ||
                                       ci_equal(thisName, "unnamed");
        bool foundEquivalentName = false;

        if (hasCodeCompatibleOfAuthorityFactory(this, authorityFactory)) {
            // If the CRS has already an id, check in the database for the
            // official object, and verify that they are equivalent.
            for (const auto &id : identifiers()) {
                if (hasCodeCompatibleOfAuthorityFactory(id, authorityFactory)) {
                    try {
                        auto crs = io::AuthorityFactory::create(
                                       authorityFactory->databaseContext(),
                                       *id->codeSpace())
                                       ->createProjectedCRS(id->code());
                        bool match = _isEquivalentTo(
                            crs.get(), util::IComparable::Criterion::
                                           EQUIVALENT_EXCEPT_AXIS_ORDER_GEOGCRS,
                            dbContext);
                        res.emplace_back(crs, match ? 100 : 25);
                        return res;
                    } catch (const std::exception &) {
                    }
                }
            }
        } else if (!unsignificantName) {
            for (int ipass = 0; ipass < 2; ipass++) {
                const bool approximateMatch = ipass == 1;
                auto objects = authorityFactory->createObjectsFromName(
                    thisName, {io::AuthorityFactory::ObjectType::PROJECTED_CRS},
                    approximateMatch);
                for (const auto &obj : objects) {
                    auto crs = util::nn_dynamic_pointer_cast<ProjectedCRS>(obj);
                    assert(crs);
                    auto crsNN = NN_NO_CHECK(crs);
                    const bool eqName = metadata::Identifier::isEquivalentName(
                        thisName.c_str(), crs->nameStr().c_str());
                    foundEquivalentName |= eqName;
                    if (_isEquivalentTo(
                            crs.get(), util::IComparable::Criterion::
                                           EQUIVALENT_EXCEPT_AXIS_ORDER_GEOGCRS,
                            dbContext)) {
                        if (crs->nameStr() == thisName) {
                            res.clear();
                            res.emplace_back(crsNN, 100);
                            return res;
                        }
                        res.emplace_back(crsNN, eqName ? 90 : 70);
                    } else if (crs->nameStr() == thisName &&
                               CRS::getPrivate()->implicitCS_ &&
                               l_baseCRS->_isEquivalentTo(
                                   crs->baseCRS().get(),
                                   util::IComparable::Criterion::
                                       EQUIVALENT_EXCEPT_AXIS_ORDER_GEOGCRS,
                                   dbContext) &&
                               derivingConversionRef()->_isEquivalentTo(
                                   crs->derivingConversionRef().get(),
                                   util::IComparable::Criterion::EQUIVALENT,
                                   dbContext) &&
                               objects.size() == 1) {
                        res.clear();
                        res.emplace_back(crsNN, 100);
                        return res;
                    } else {
                        res.emplace_back(crsNN, 25);
                    }
                }
                if (!res.empty()) {
                    break;
                }
            }
        }

        const auto lambdaSort = [&thisName](const Pair &a, const Pair &b) {
            // First consider confidence
            if (a.second > b.second) {
                return true;
            }
            if (a.second < b.second) {
                return false;
            }

            // Then consider exact name matching
            const auto &aName(a.first->nameStr());
            const auto &bName(b.first->nameStr());
            if (aName == thisName && bName != thisName) {
                return true;
            }
            if (bName == thisName && aName != thisName) {
                return false;
            }

            // Arbitrary final sorting criterion
            return aName < bName;
        };

        // Sort results
        res.sort(lambdaSort);
