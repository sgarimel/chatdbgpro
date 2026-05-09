        }
#endif
        return writeMethod;
    } // TiffParserWorker::encode

    TiffComponent::AutoPtr TiffParserWorker::parse(
        const byte*              pData,
              uint32_t           size,
              uint32_t           root,
              TiffHeaderBase*    pHeader
    )
    {
        if (pData == 0 || size == 0) return TiffComponent::AutoPtr(0);
        if (!pHeader->read(pData, size) || pHeader->offset() >= size) {
            throw Error(kerNotAnImage, "TIFF");
        }
        TiffComponent::AutoPtr rootDir = TiffCreator::create(root, ifdIdNotSet);
        if (0 != rootDir.get()) {
            rootDir->setStart(pData + pHeader->offset());
            TiffRwState state(pHeader->byteOrder(), 0);
            TiffReader reader(pData, size, rootDir.get(), state);
            rootDir->accept(reader);
            reader.postProcess();
        }
        return rootDir;

    } // TiffParserWorker::parse

    void TiffParserWorker::findPrimaryGroups(PrimaryGroups& primaryGroups, TiffComponent* pSourceDir)
    {
        if (0 == pSourceDir)
            return;

        const IfdId imageGroups[] = {
            ifd0Id,
            ifd1Id,
            ifd2Id,
            ifd3Id,
            subImage1Id,
            subImage2Id,
            subImage3Id,
            subImage4Id,
            subImage5Id,
            subImage6Id,
            subImage7Id,
            subImage8Id,
            subImage9Id
        };

        for (unsigned int i = 0; i < EXV_COUNTOF(imageGroups); ++i) {
            TiffFinder finder(0x00fe, imageGroups[i]);
            pSourceDir->accept(finder);
            TiffEntryBase* te = dynamic_cast<TiffEntryBase*>(finder.result());
            if (   te
                && te->pValue()->typeId() == unsignedLong
                && te->pValue()->count() == 1
                && (te->pValue()->toLong() & 1) == 0) {
                primaryGroups.push_back(te->group());
            }
        }

    } // TiffParserWorker::findPrimaryGroups

    TiffHeaderBase::TiffHeaderBase(uint16_t  tag,
                                   uint32_t  size,
                                   ByteOrder byteOrder,
                                   uint32_t  offset)
        : tag_(tag),
          size_(size),
          byteOrder_(byteOrder),
          offset_(offset)
    {
    }

    TiffHeaderBase::~TiffHeaderBase()
    {
    }

    bool TiffHeaderBase::read(const byte* pData, uint32_t size)
    {
        if (!pData || size < 8) return false;

        if (pData[0] == 'I' && pData[0] == pData[1]) {
            byteOrder_ = littleEndian;
        }
        else if (pData[0] == 'M' && pData[0] == pData[1]) {
            byteOrder_ = bigEndian;
        }
        else {
            return false;
        }
        if (tag_ != getUShort(pData + 2, byteOrder_)) return false;
        offset_ = getULong(pData + 4, byteOrder_);

        return true;
    } // TiffHeaderBase::read

    DataBuf TiffHeaderBase::write() const
    {
        DataBuf buf(8);
        switch (byteOrder_) {
