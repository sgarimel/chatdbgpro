        std::ios::fmtflags f( os.flags() );
        os << prefix
           << _("Header, offset") << " = 0x" << std::setw(8) << std::setfill('0')
           << std::hex << std::right << offset_ << "\n";
        if (pRootDir_) pRootDir_->print(os, byteOrder_, prefix);
        os.flags(f);
    } // CiffHeader::print

    void CiffComponent::print(std::ostream&      os,
                              ByteOrder          byteOrder,
                              const std::string& prefix) const
    {
        doPrint(os, byteOrder, prefix);
    }

    void CiffComponent::doPrint(std::ostream&      os,
                                ByteOrder          byteOrder,
                                const std::string& prefix) const
    {
        os << prefix
           << _("tag") << " = 0x" << std::setw(4) << std::setfill('0')
           << std::hex << std::right << tagId()
           << ", " << _("dir") << " = 0x" << std::setw(4) << std::setfill('0')
           << std::hex << std::right << dir()
           << ", " << _("type") << " = " << TypeInfo::typeName(typeId())
           << ", " << _("size") << " = " << std::dec << size_
           << ", " << _("offset") << " = " << offset_ << "\n";

        Value::AutoPtr value;
        if (typeId() != directory) {
            value = Value::create(typeId());
            value->read(pData_, size_, byteOrder);
            if (value->size() < 100) {
                os << prefix << *value << "\n";
            }
        }
    } // CiffComponent::doPrint

    void CiffDirectory::doPrint(std::ostream&      os,
                                ByteOrder          byteOrder,
                                const std::string& prefix) const
    {
        CiffComponent::doPrint(os, byteOrder, prefix);
        Components::const_iterator b = components_.begin();
        Components::const_iterator e = components_.end();
        for (Components::const_iterator i = b; i != e; ++i) {
            (*i)->print(os, byteOrder, prefix + "   ");
        }
    } // CiffDirectory::doPrint

    void CiffComponent::setValue(DataBuf buf)
    {
        if (isAllocated_) {
            delete pData_;
            pData_ = 0;
            size_ = 0;
        }
        isAllocated_ = true;
        std::pair<byte *, long> p = buf.release();
        pData_ = p.first;
        size_  = p.second;
        if (size_ > 8 && dataLocation() == directoryData) {
            tag_ &= 0x3fff;
        }
    } // CiffComponent::setValue

    TypeId CiffComponent::typeId(uint16_t tag)
    {
        TypeId ti = invalidTypeId;
        switch (tag & 0x3800) {
        case 0x0000: ti = unsignedByte; break;
        case 0x0800: ti = asciiString; break;
        case 0x1000: ti = unsignedShort; break;
        case 0x1800: ti = unsignedLong; break;
        case 0x2000: ti = undefined; break;
        case 0x2800: // fallthrough
        case 0x3000: ti = directory; break;
        }
        return ti;
    } // CiffComponent::typeId

    DataLocId CiffComponent::dataLocation(uint16_t tag)
    {
        switch (tag & 0xc000) {
        case 0x0000: return valueData;
        case 0x4000: return directoryData;
        default: throw Error(kerCorruptedMetadata);
        }
    } // CiffComponent::dataLocation

    /*!
      @brief Finds \em crwTagId in directory \em crwDir, returning a pointer to
             the component or 0 if not found.

     */
    CiffComponent* CiffHeader::findComponent(uint16_t crwTagId,
                                             uint16_t crwDir) const
    {
        if (pRootDir_ == 0) return 0;
        return pRootDir_->findComponent(crwTagId, crwDir);
    } // CiffHeader::findComponent
