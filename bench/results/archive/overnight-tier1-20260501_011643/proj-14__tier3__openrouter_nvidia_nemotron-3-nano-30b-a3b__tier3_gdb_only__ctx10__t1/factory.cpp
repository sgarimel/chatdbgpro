                    res.emplace_back(
                        TableType("helmert_transformation", std::string()));
                    res.emplace_back(
                        TableType("grid_transformation", std::string()));
                    res.emplace_back(
                        TableType("other_transformation", std::string()));
                    res.emplace_back(
                        TableType("concatenated_operation", std::string()));
                    break;
                case ObjectType::CONVERSION:
                    res.emplace_back(TableType("conversion", std::string()));
                    break;
                case ObjectType::TRANSFORMATION:
                    res.emplace_back(
                        TableType("helmert_transformation", std::string()));
                    res.emplace_back(
                        TableType("grid_transformation", std::string()));
                    res.emplace_back(
                        TableType("other_transformation", std::string()));
                    break;
                case ObjectType::CONCATENATED_OPERATION:
                    res.emplace_back(
                        TableType("concatenated_operation", std::string()));
                    break;
                }
            }
        }
        return res;
    };

    const auto listTableNameType = getTableAndTypeConstraints();
    bool first = true;
    ListOfParams params;
    for (const auto &tableNameTypePair : listTableNameType) {
        if (!first) {
            sql += " UNION ";
        }
        first = false;
        sql += "SELECT '";
        sql += tableNameTypePair.first;
        sql += "' AS table_name, auth_name, code, name, deprecated, "
               "0 AS is_alias FROM ";
        sql += tableNameTypePair.first;
        sql += " WHERE 1 = 1 ";
        if (!tableNameTypePair.second.empty()) {
            sql += "AND type = '";
            sql += tableNameTypePair.second;
            sql += "' ";
        }
        if (deprecated) {
            sql += "AND deprecated = 1 ";
        }
        if (!approximateMatch) {
            sql += "AND name LIKE ? ";
            params.push_back(searchedNameWithoutDeprecated);
        }
        if (d->hasAuthorityRestriction()) {
            sql += "AND auth_name = ? ";
            params.emplace_back(d->authority());
        }

        sql += " UNION SELECT '";
        sql += tableNameTypePair.first;
        sql += "' AS table_name, "
               "ov.auth_name AS auth_name, "
               "ov.code AS code, a.alt_name AS name, "
               "ov.deprecated AS deprecated, 1 as is_alias FROM ";
        sql += tableNameTypePair.first;
        sql += " ov "
               "JOIN alias_name a ON "
               "ov.auth_name = a.auth_name AND ov.code = a.code WHERE "
               "a.table_name = '";
        sql += tableNameTypePair.first;
        sql += "' ";
        if (!tableNameTypePair.second.empty()) {
            sql += "AND ov.type = '";
            sql += tableNameTypePair.second;
            sql += "' ";
        }
        if (deprecated) {
            sql += "AND ov.deprecated = 1 ";
        }
        if (!approximateMatch) {
            sql += "AND a.alt_name LIKE ? ";
            params.push_back(searchedNameWithoutDeprecated);
        }
        if (d->hasAuthorityRestriction()) {
            sql += "AND ov.auth_name = ? ";
            params.emplace_back(d->authority());
        }
    }

    sql += ") ORDER BY deprecated, is_alias, length(name), name";
    if (limitResultCount > 0 &&
        limitResultCount <
            static_cast<size_t>(std::numeric_limits<int>::max()) &&
        !approximateMatch) {
        sql += " LIMIT ";
        sql += toString(static_cast<int>(limitResultCount));
    }

