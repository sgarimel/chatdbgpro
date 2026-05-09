        bool utf8 = true;

        for (pos = begin(); pos != end(); ++pos) {
            std::string value = pos->toString();
            if (pos->value().ok()) {
                int seqCount = 0;
                std::string::iterator i;
                for (i = value.begin(); i != value.end(); ++i) {
                    char c = *i;
                    if (seqCount) {
                        if ((c & 0xc0) != 0x80) {
                            utf8 = false;
                            break;
                        }
                        --seqCount;
                    }
                    else {
                        if (c & 0x80) ascii = false;
                        else continue; // ascii character

                        if      ((c & 0xe0) == 0xc0) seqCount = 1;
                        else if ((c & 0xf0) == 0xe0) seqCount = 2;
                        else if ((c & 0xf8) == 0xf0) seqCount = 3;
                        else if ((c & 0xfc) == 0xf8) seqCount = 4;
                        else if ((c & 0xfe) == 0xfc) seqCount = 5;
                        else {
                            utf8 = false;
                            break;
                        }
                    }
                }
                if (seqCount) utf8 = false; // unterminated seq
                if (!utf8) break;
            }
        }

        if (ascii) return "ASCII";
        if (utf8) return "UTF-8";
        return NULL;
    }

    const byte IptcParser::marker_ = 0x1C;          // Dataset marker

    int IptcParser::decode(
              IptcData& iptcData,
        const byte*     pData,
              uint32_t  size
    )
    {
#ifdef DEBUG
        std::cerr << "IptcParser::decode, size = " << size << "\n";
#endif
        const byte* pRead = pData;
        iptcData.clear();

        uint16_t record = 0;
        uint16_t dataSet = 0;
        uint32_t sizeData = 0;
        byte extTest = 0;

        while (pRead + 3 < pData + size) {
            // First byte should be a marker. If it isn't, scan forward and skip
            // the chunk bytes present in some images. This deviates from the
            // standard, which advises to treat such cases as errors.
            if (*pRead++ != marker_) continue;
            record = *pRead++;
            dataSet = *pRead++;

            extTest = *pRead;
            if (extTest & 0x80) {
                // extended dataset
                uint16_t sizeOfSize = (getUShort(pRead, bigEndian) & 0x7FFF);
                if (sizeOfSize > 4) return 5;
                pRead += 2;
                sizeData = 0;
                for (; sizeOfSize > 0; --sizeOfSize) {
                    sizeData |= *pRead++ << (8 *(sizeOfSize-1));
                }
            }
            else {
                // standard dataset
                sizeData = getUShort(pRead, bigEndian);
                pRead += 2;
            }
            if (pRead + sizeData <= pData + size) {
                int rc = 0;
                if ((rc = readData(iptcData, dataSet, record, pRead, sizeData)) != 0) {
#ifndef SUPPRESS_WARNINGS
                    EXV_WARNING << "Failed to read IPTC dataset "
                                << IptcKey(dataSet, record)
                                << " (rc = " << rc << "); skipped.\n";
#endif
                }
            }
#ifndef SUPPRESS_WARNINGS
            else {
                EXV_WARNING << "IPTC dataset " << IptcKey(dataSet, record)
                            << " has invalid size " << sizeData << "; skipped.\n";
            }
#endif
            pRead += sizeData;
