
    void CiffComponent::doRead(const byte* pData,
                               uint32_t    size,
                               uint32_t    start,
                               ByteOrder   byteOrder)
    {
        if (size < 10) throw Error(kerNotACrwImage);
        tag_ = getUShort(pData + start, byteOrder);

        DataLocId dl = dataLocation();
        assert(dl == directoryData || dl == valueData);

        if (dl == valueData) {
            size_   = getULong(pData + start + 2, byteOrder);
            offset_ = getULong(pData + start + 6, byteOrder);
        }
        if ( size_ > size || offset_ > size ) throw Error(kerOffsetOutOfRange); // #889
        if (dl == directoryData) {
            size_ = 8;
            offset_ = start + 2;
        }
        pData_ = pData + offset_;
#ifdef DEBUG
        std::cout << "  Entry for tag 0x"
                  << std::hex << tagId() << " (0x" << tag()
                  << "), " << std::dec << size_
                  << " Bytes, Offset is " << offset_ << "\n";
#endif

    } // CiffComponent::doRead

    void CiffDirectory::doRead(const byte* pData,
                               uint32_t    size,
                               uint32_t    start,
                               ByteOrder   byteOrder)
    {
        CiffComponent::doRead(pData, size, start, byteOrder);
#ifdef DEBUG
        std::cout << "Reading directory 0x" << std::hex << tag() << "\n";
#endif
        readDirectory(pData + offset(), this->size(), byteOrder);
#ifdef DEBUG
        std::cout << "<---- 0x" << std::hex << tag() << "\n";
#endif
    } // CiffDirectory::doRead

    void CiffDirectory::readDirectory(const byte* pData,
                                      uint32_t    size,
                                      ByteOrder   byteOrder)
    {
        if (size < 4)
            throw Error(kerCorruptedMetadata);
        uint32_t o = getULong(pData + size - 4, byteOrder);
        if ( o+2 > size )
            throw Error(kerCorruptedMetadata);
        uint16_t count = getUShort(pData + o, byteOrder);
#ifdef DEBUG
        std::cout << "Directory at offset " << std::dec << o
                  <<", " << count << " entries \n";
#endif
        o += 2;
        if ( (o + (count * 10)) > size )
            throw Error(kerCorruptedMetadata);

        for (uint16_t i = 0; i < count; ++i) {
            uint16_t tag = getUShort(pData + o, byteOrder);
            CiffComponent::AutoPtr m;
            switch (CiffComponent::typeId(tag)) {
            case directory: m = CiffComponent::AutoPtr(new CiffDirectory); break;
            default: m = CiffComponent::AutoPtr(new CiffEntry); break;
            }
            m->setDir(this->tag());
            m->read(pData, size, o, byteOrder);
            add(m);
            o += 10;
        }
    }  // CiffDirectory::readDirectory

    void CiffHeader::decode(Image& image) const
    {
        // Nothing to decode from the header itself, just add correct byte order
        if (pRootDir_) pRootDir_->decode(image, byteOrder_);
    } // CiffHeader::decode

    void CiffComponent::decode(Image& image, ByteOrder byteOrder) const
    {
        doDecode(image, byteOrder);
    }

    void CiffEntry::doDecode(Image& image, ByteOrder byteOrder) const
    {
        CrwMap::decode(*this, image, byteOrder);
    } // CiffEntry::doDecode

    void CiffDirectory::doDecode(Image& image, ByteOrder byteOrder) const
    {
        Components::const_iterator b = components_.begin();
        Components::const_iterator e = components_.end();
        for (Components::const_iterator i = b; i != e; ++i) {
            (*i)->decode(image, byteOrder);
        }
