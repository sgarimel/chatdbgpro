            "Exif.Photo.SensitivityType"
        };

        // Find the first ISO value which is not "0"
        const int cnt = EXV_COUNTOF(keys);
        ExifData::const_iterator md = ed.end();
        long iso_val = -1;
        for (int idx = 0; idx < cnt; ) {
            md = findMetadatum(ed, keys + idx, cnt - idx);
            if (md == ed.end()) break;
            std::ostringstream os;
            md->write(os, &ed);
            bool ok = false;
            iso_val = parseLong(os.str(), ok);
            if (ok && iso_val > 0) break;
            while (strcmp(keys[idx++], md->key().c_str()) != 0 && idx < cnt) {}
            md = ed.end();
        }

        // there is either a possible ISO "overflow" or no legacy
        // ISO tag at all. Check for SensitivityType tag and the referenced
        // ISO value (see EXIF 2.3 Annex G)
        long iso_tmp_val = -1;
        while (iso_tmp_val == -1 && (iso_val == 65535 || md == ed.end())) {
            ExifData::const_iterator md_st = findMetadatum(ed, sensitivityType, 1);
            // no SensitivityType? exit with existing data
            if (md_st == ed.end())
                break;
            // otherwise pick up actual value and grab value accordingly
            std::ostringstream os;
            md_st->write(os, &ed);
            bool ok = false;
            const long st_val = parseLong(os.str(), ok);
            // SensivityType out of range or cannot be parsed properly
            if (!ok || st_val < 1 || st_val > 7)
                break;
            // pick up list of ISO tags, and check for at least one of
            // them available.
            const SensKeyNameList *sensKeys = &sensitivityKey[st_val - 1];
            md_st = ed.end();
            for (int idx = 0; idx < sensKeys->count; md_st = ed.end()) {
                md_st = findMetadatum(ed, const_cast<const char**>(sensKeys->keys), sensKeys->count);
                if (md_st == ed.end())
                    break;
                std::ostringstream os_iso;
                md_st->write(os_iso, &ed);
                ok = false;
                iso_tmp_val = parseLong(os_iso.str(), ok);
                // something wrong with the value
                if (ok || iso_tmp_val > 0) {
                    md = md_st;
                    break;
                }
                while (strcmp(sensKeys->keys[idx++], md_st->key().c_str()) != 0 && idx < cnt) {}
            }
            break;
        }

        return md;
    }

    ExifData::const_iterator flashBias(const ExifData& ed)
    {
        static const char* keys[] = {
            "Exif.CanonSi.FlashBias",
            "Exif.Panasonic.FlashBias",
            "Exif.Olympus.FlashBias",
            "Exif.OlympusCs.FlashExposureComp",
            "Exif.Minolta.FlashExposureComp",
            "Exif.SonyMinolta.FlashExposureComp",
            "Exif.Sony1.FlashExposureComp",
            "Exif.Sony2.FlashExposureComp"
        };
        return findMetadatum(ed, keys, EXV_COUNTOF(keys));
    }

    ExifData::const_iterator exposureMode(const ExifData& ed)
    {
        static const char* keys[] = {
            "Exif.Photo.ExposureProgram",
            "Exif.Image.ExposureProgram",
            "Exif.CanonCs.ExposureProgram",
            "Exif.MinoltaCs7D.ExposureMode",
            "Exif.MinoltaCs5D.ExposureMode",
            "Exif.MinoltaCsNew.ExposureMode",
            "Exif.MinoltaCsOld.ExposureMode",
            "Exif.Sony1MltCsA100.ExposureMode",
            "Exif.Sony1Cs.ExposureProgram",
            "Exif.Sony2Cs.ExposureProgram",
            "Exif.Sigma.ExposureMode"
        };
        return findMetadatum(ed, keys, EXV_COUNTOF(keys));
    }

    ExifData::const_iterator sceneMode(const ExifData& ed)
    {
        static const char* keys[] = {
            "Exif.CanonCs.EasyMode",
            "Exif.Fujifilm.PictureMode",
            "Exif.MinoltaCsNew.SubjectProgram",
            "Exif.MinoltaCsOld.SubjectProgram",
