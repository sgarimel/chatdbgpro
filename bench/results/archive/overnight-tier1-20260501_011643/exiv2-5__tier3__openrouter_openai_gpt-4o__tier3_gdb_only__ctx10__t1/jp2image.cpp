                        DataBuf rawIptc = IptcParser::encode(iptcData_);
                        if (rawIptc.size_ > 0)
                        {
                            DataBuf boxData(8 + 16 + rawIptc.size_);
                            ul2Data(boxDataSize, boxData.size_, Exiv2::bigEndian);
                            ul2Data(boxUUIDtype, kJp2BoxTypeUuid, Exiv2::bigEndian);
                            memcpy(boxData.pData_,          boxDataSize,    4);
                            memcpy(boxData.pData_ + 4,      boxUUIDtype,    4);
                            memcpy(boxData.pData_ + 8,      kJp2UuidIptc,   16);
                            memcpy(boxData.pData_ + 8 + 16, rawIptc.pData_, rawIptc.size_);

#ifdef EXIV2_DEBUG_MESSAGES
                            std::cout << "Exiv2::Jp2Image::doWriteMetadata: Write box with Iptc metadata (length: "
                                      << boxData.size_ << std::endl;
#endif
                            if (outIo.write(boxData.pData_, boxData.size_) != boxData.size_) throw Error(kerImageWriteFailed);
                        }
                    }

                    if (writeXmpFromPacket() == false)
                    {
                        if (XmpParser::encode(xmpPacket_, xmpData_) > 1)
                        {
#ifndef SUPPRESS_WARNINGS
                            EXV_ERROR << "Failed to encode XMP metadata." << std::endl;
#endif
                        }
                    }
                    if (xmpPacket_.size() > 0)
                    {
                        // Update Xmp data to a new UUID box

                        DataBuf xmp(reinterpret_cast<const byte*>(xmpPacket_.data()), static_cast<long>(xmpPacket_.size()));
                        DataBuf boxData(8 + 16 + xmp.size_);
                        ul2Data(boxDataSize, boxData.size_, Exiv2::bigEndian);
                        ul2Data(boxUUIDtype, kJp2BoxTypeUuid, Exiv2::bigEndian);
                        memcpy(boxData.pData_,          boxDataSize,  4);
                        memcpy(boxData.pData_ + 4,      boxUUIDtype,  4);
                        memcpy(boxData.pData_ + 8,      kJp2UuidXmp,  16);
                        memcpy(boxData.pData_ + 8 + 16, xmp.pData_,   xmp.size_);

#ifdef EXIV2_DEBUG_MESSAGES
                        std::cout << "Exiv2::Jp2Image::doWriteMetadata: Write box with XMP metadata (length: "
                                  << boxData.size_ << ")" << std::endl;
#endif
                        if (outIo.write(boxData.pData_, boxData.size_) != boxData.size_) throw Error(kerImageWriteFailed);
                    }

                    break;
                }

                case kJp2BoxTypeUuid:
                {
                    if(memcmp(boxBuf.pData_ + 8, kJp2UuidExif, 16) == 0)
                    {
#ifdef EXIV2_DEBUG_MESSAGES
                        std::cout << "Exiv2::Jp2Image::doWriteMetadata: strip Exif Uuid box" << std::endl;
#endif
                    }
                    else if(memcmp(boxBuf.pData_ + 8, kJp2UuidIptc, 16) == 0)
                    {
#ifdef EXIV2_DEBUG_MESSAGES
                        std::cout << "Exiv2::Jp2Image::doWriteMetadata: strip Iptc Uuid box" << std::endl;
#endif
                    }
                    else if(memcmp(boxBuf.pData_ + 8, kJp2UuidXmp,  16) == 0)
                    {
#ifdef EXIV2_DEBUG_MESSAGES
                        std::cout << "Exiv2::Jp2Image::doWriteMetadata: strip Xmp Uuid box" << std::endl;
#endif
                    }
                    else
                    {
#ifdef EXIV2_DEBUG_MESSAGES
                        std::cout << "Exiv2::Jp2Image::doWriteMetadata: write Uuid box (length: " << box.length << ")" << std::endl;
#endif
                        if (outIo.write(boxBuf.pData_, boxBuf.size_) != boxBuf.size_) throw Error(kerImageWriteFailed);
                    }
                    break;
                }

                default:
                {
#ifdef EXIV2_DEBUG_MESSAGES
                    std::cout << "Exiv2::Jp2Image::doWriteMetadata: write box (length: " << box.length << ")" << std::endl;
#endif
                    if (outIo.write(boxBuf.pData_, boxBuf.size_) != boxBuf.size_) throw Error(kerImageWriteFailed);

                    break;
                }
            }
        }

#ifdef EXIV2_DEBUG_MESSAGES
        std::cout << "Exiv2::Jp2Image::doWriteMetadata: EOF" << std::endl;
#endif

    } // Jp2Image::doWriteMetadata

    // *************************************************************************
    // free functions
