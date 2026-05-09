                valueIdx += sv;
            }
            uint32_t sd = (*i)->sizeData();
            sd += sd & 1;                   // Align data to word boundary
            dataIdx += sd;
        }
        assert(idx == sizeDir + sizeValue);

        // 3rd: Write data - may contain offsets too (eg sub-IFD)
        dataIdx = sizeDir + sizeValue;
        idx += writeData(ioWrapper, byteOrder, offset, dataIdx, imageIdx);

        // 4th: Write next-IFD
        if (pNext_ && sizeNext) {
            idx += pNext_->write(ioWrapper, byteOrder, offset + idx, uint32_t(-1), uint32_t(-1), imageIdx);
        }

        // 5th, at the root directory level only: write image data
        if (isRootDir) {
            idx += writeImage(ioWrapper, byteOrder);
        }

        return idx;
    } // TiffDirectory::doWrite

    uint32_t TiffDirectory::writeDirEntry(IoWrapper&     ioWrapper,
                                          ByteOrder      byteOrder,
                                          int32_t        offset,
                                          TiffComponent* pTiffComponent,
                                          uint32_t       valueIdx,
                                          uint32_t       dataIdx,
                                          uint32_t&      imageIdx) const
    {
        assert(pTiffComponent);
        TiffEntryBase* pDirEntry = dynamic_cast<TiffEntryBase*>(pTiffComponent);
        assert(pDirEntry);
        byte buf[8];
        us2Data(buf,     pDirEntry->tag(),      byteOrder);
        us2Data(buf + 2, pDirEntry->tiffType(), byteOrder);
        ul2Data(buf + 4, pDirEntry->count(),    byteOrder);
        ioWrapper.write(buf, 8);
        if (pDirEntry->size() > 4) {
            pDirEntry->setOffset(offset + static_cast<int32_t>(valueIdx));
            l2Data(buf, pDirEntry->offset(), byteOrder);
            ioWrapper.write(buf, 4);
        }
        else {
            const uint32_t len = pDirEntry->write(ioWrapper,
                                                  byteOrder,
                                                  offset,
                                                  valueIdx,
                                                  dataIdx,
                                                  imageIdx);
            assert(len <= 4);
            if (len < 4) {
                memset(buf, 0x0, 4);
                ioWrapper.write(buf, 4 - len);
            }
        }
        return 12;
    } // TiffDirectory::writeDirEntry

    uint32_t TiffEntryBase::doWrite(IoWrapper& ioWrapper,
                                    ByteOrder byteOrder,
                                    int32_t   /*offset*/,
                                    uint32_t  /*valueIdx*/,
                                    uint32_t  /*dataIdx*/,
                                    uint32_t& /*imageIdx*/)
    {
        if (!pValue_) return 0;

        DataBuf buf(pValue_->size());
        pValue_->copy(buf.pData_, byteOrder);
        ioWrapper.write(buf.pData_, buf.size_);
        return buf.size_;
    } // TiffEntryBase::doWrite

    uint32_t TiffEntryBase::writeOffset(byte*     buf,
                                        int32_t   offset,
                                        TiffType  tiffType,
                                        ByteOrder byteOrder)
    {
        uint32_t rc = 0;
        switch(tiffType) {
        case ttUnsignedShort:
        case ttSignedShort:
            if (static_cast<uint32_t>(offset) > 0xffff) throw Error(kerOffsetOutOfRange);
            rc = s2Data(buf, static_cast<int16_t>(offset), byteOrder);
            break;
        case ttUnsignedLong:
        case ttSignedLong:
            rc = l2Data(buf, static_cast<int32_t>(offset), byteOrder);
            break;
        default:
            throw Error(kerUnsupportedDataAreaOffsetType);
            break;
        }
        return rc;
    } // TiffEntryBase::writeOffset

    uint32_t TiffDataEntry::doWrite(IoWrapper& ioWrapper,
