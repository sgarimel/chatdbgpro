            std::memset(buf.pData_, 0x0, buf.size_);
            if (cc) std::memcpy(buf.pData_ + 8, cc->pData() + 8, cc->size() - 8);
            if (edX != edEnd && edX->size() == 4) {
                edX->copy(buf.pData_, pHead->byteOrder());
            }
            if (edY != edEnd && edY->size() == 4) {
                edY->copy(buf.pData_ + 4, pHead->byteOrder());
            }
            int32_t d = 0;
            if (edO != edEnd && edO->count() > 0 && edO->typeId() == unsignedShort) {
                d = RotationMap::degrees(static_cast<uint16_t>(edO->toLong()));
            }
            l2Data(buf.pData_ + 12, d, pHead->byteOrder());
            pHead->add(pCrwMapping->crwTagId_, pCrwMapping->crwDir_, buf);
        }
        else {
            pHead->remove(pCrwMapping->crwTagId_, pCrwMapping->crwDir_);
        }
    } // CrwMap::encode0x1810

    void CrwMap::encode0x2008(const Image&      image,
                              const CrwMapping* pCrwMapping,
                                    CiffHeader* pHead)
    {
        assert(pCrwMapping != 0);
        assert(pHead != 0);

        ExifThumbC exifThumb(image.exifData());
        DataBuf buf = exifThumb.copy();
        if (buf.size_ != 0) {
            pHead->add(pCrwMapping->crwTagId_, pCrwMapping->crwDir_, buf);
        }
        else {
            pHead->remove(pCrwMapping->crwTagId_, pCrwMapping->crwDir_);
        }
    } // CrwMap::encode0x2008

    // *************************************************************************
    // free functions
    DataBuf packIfdId(const ExifData& exifData,
                            IfdId     ifdId,
                            ByteOrder byteOrder)
    {
        const uint16_t size = 1024;
        DataBuf buf(size);
        std::memset(buf.pData_, 0x0, buf.size_);

        uint16_t len = 0;
        const ExifData::const_iterator b = exifData.begin();
        const ExifData::const_iterator e = exifData.end();
        for (ExifData::const_iterator i = b; i != e; ++i) {
            if (i->ifdId() != ifdId) continue;
            const uint16_t s = i->tag()*2 + static_cast<uint16_t>(i->size());
            assert(s <= size);
            if (len < s) len = s;
            i->copy(buf.pData_ + i->tag()*2, byteOrder);
            
        }
        // Round the size to make it even.
        buf.size_ = len + len%2;
        return buf;
    }

}}                                       // namespace Internal, Exiv2
