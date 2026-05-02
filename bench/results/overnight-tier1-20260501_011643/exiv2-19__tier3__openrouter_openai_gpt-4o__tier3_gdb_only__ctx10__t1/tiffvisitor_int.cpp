                if ( object->tag() == 0x2001 && std::string(groupName(object->group())) == "Sony1" ) {
                    isize=size;
                } else {
#ifndef SUPPRESS_WARNINGS
            EXV_ERROR << "Offset of directory " << groupName(object->group())
                      << ", entry 0x" << std::setw(4)
                      << std::setfill('0') << std::hex << object->tag()
                      << " is out of bounds: "
                      << "Offset = 0x" << std::setw(8)
                      << std::setfill('0') << std::hex << offset
                      << "; truncating the entry\n";
#endif
                }
                size = 0;
        }
        if (size > 4) {
            // setting pData to pData_ + baseOffset() + offset can result in pData pointing to invalid memory,
            // as offset can be arbitrarily large
            if ((static_cast<uintptr_t>(baseOffset()) > std::numeric_limits<uintptr_t>::max() - static_cast<uintptr_t>(offset))
             || (static_cast<uintptr_t>(baseOffset() + offset) > std::numeric_limits<uintptr_t>::max() - reinterpret_cast<uintptr_t>(pData_)))
            {
                throw Error(kerCorruptedMetadata); // #562 don't throw kerArithmeticOverflow
            }
            if (pData_ + static_cast<uintptr_t>(baseOffset()) + static_cast<uintptr_t>(offset) > pLast_) {
                throw Error(kerCorruptedMetadata);
            }
            pData = const_cast<byte*>(pData_) + baseOffset() + offset;

        // check for size being invalid
            if (size > static_cast<uint32_t>(pLast_ - pData)) {
#ifndef SUPPRESS_WARNINGS
                EXV_ERROR << "Upper boundary of data for "
                          << "directory " << groupName(object->group())
                          << ", entry 0x" << std::setw(4)
                          << std::setfill('0') << std::hex << object->tag()
                          << " is out of bounds: "
                          << "Offset = 0x" << std::setw(8)
                          << std::setfill('0') << std::hex << offset
                          << ", size = " << std::dec << size
                          << ", exceeds buffer size by "
                          // cast to make MSVC happy
                          << static_cast<uint32_t>(pData + size - pLast_)
                          << " Bytes; truncating the entry\n";
#endif
                size = 0;
            }
        }
        Value::UniquePtr v = Value::create(typeId);
        enforce(v.get() != nullptr, kerCorruptedMetadata);
        if ( !isize ) {
            v->read(pData, size, byteOrder());
        } else {
            // Prevent large memory allocations: https://github.com/Exiv2/exiv2/issues/1881

            // #1143 Write a "hollow" buffer for the preview image
            //       Sadly: we don't know the exact location of the image in the source (it's near offset)
            //       And neither TiffReader nor TiffEntryBase have access to the BasicIo object being processed
            std::vector<byte> buffer(isize);
            v->read(buffer.data() ,isize, byteOrder());
        }

        object->setValue(std::move(v));
        object->setData(pData, size);
        object->setOffset(offset);
        object->setIdx(nextIdx(object->group()));

    } // TiffReader::readTiffEntry

    void TiffReader::visitBinaryArray(TiffBinaryArray* object)
    {
        assert(object != 0);

        if (!postProc_) {
            // Defer reading children until after all other components are read, but
            // since state (offset) is not set during post-processing, read entry here
            readTiffEntry(object);
            object->iniOrigDataBuf();
            postList_.push_back(object);
            return;
        }
        // Check duplicates
        TiffFinder finder(object->tag(), object->group());
        pRoot_->accept(finder);
        auto te = dynamic_cast<TiffEntryBase*>(finder.result());
        if (te && te->idx() != object->idx()) {
#ifndef SUPPRESS_WARNINGS
            EXV_WARNING << "Not decoding duplicate binary array tag 0x"
                        << std::setw(4) << std::setfill('0') << std::hex
                        << object->tag() << std::dec << ", group "
                        << groupName(object->group()) << ", idx " << object->idx()
                        << "\n";
#endif
            object->setDecoded(false);
            return;
        }

        if (object->TiffEntryBase::doSize() == 0) return;
        if (!object->initialize(pRoot_)) return;
        const ArrayCfg* cfg = object->cfg();
        if (cfg == nullptr)
            return;
