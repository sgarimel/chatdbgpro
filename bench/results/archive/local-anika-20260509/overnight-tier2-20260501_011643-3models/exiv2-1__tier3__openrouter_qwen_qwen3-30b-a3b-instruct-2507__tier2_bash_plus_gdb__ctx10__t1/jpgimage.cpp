            std::string nm[256];
            nm[0xd8] = "SOI";
            nm[0xd9] = "EOI";
            nm[0xda] = "SOS";
            nm[0xdb] = "DQT";
            nm[0xdd] = "DRI";
            nm[0xfe] = "COM";

            // 0xe0 .. 0xef are APPn
            // 0xc0 .. 0xcf are SOFn (except 4)
            nm[0xc4] = "DHT";
            for (int i = 0; i <= 15; i++) {
                char MN[16];
                snprintf(MN, sizeof(MN), "APP%d", i);
                nm[0xe0 + i] = MN;
                if (i != 4) {
                    snprintf(MN, sizeof(MN), "SOF%d", i);
                    nm[0xc0 + i] = MN;
                }
            }

            // which markers have a length field?
            bool mHasLength[256];
            for (int i = 0; i < 256; i++)
                mHasLength[i] = (i >= sof0_ && i <= sof15_) || (i >= app0_ && i <= (app0_ | 0x0F)) ||
                                (i == dht_ || i == dqt_ || i == dri_ || i == com_ || i == sos_);

            // Container for the signature
            bool bExtXMP = false;
            long bufRead = 0;
            const long bufMinSize = 36;
            DataBuf buf(bufMinSize);

            // Read section marker
            int marker = advanceToMarker();
            if (marker < 0)
                throw Error(kerNotAJpeg);

            bool done = false;
            bool first = true;
            while (!done) {
                // print marker bytes
                if (first && bPrint) {
                    out << "STRUCTURE OF JPEG FILE: " << io_->path() << std::endl;
                    out << " address | marker       |  length | data" << std::endl;
                    REPORT_MARKER;
                }
                first = false;
                bool bLF = bPrint;

                // Read size and signature
                std::memset(buf.pData_, 0x0, buf.size_);
                bufRead = io_->read(buf.pData_, bufMinSize);
                if (io_->error())
                    throw Error(kerFailedToReadImageData);
                if (bufRead != bufMinSize) exit(1);
                const uint16_t size = mHasLength[marker] ? getUShort(buf.pData_, bigEndian) : 0;
                if (bPrint && mHasLength[marker])
                    out << Internal::stringFormat(" | %7d ", size);

                // print signature for APPn
                if (marker >= app0_ && marker <= (app0_ | 0x0F)) {
                    // http://www.adobe.com/content/dam/Adobe/en/devnet/xmp/pdfs/XMPSpecificationPart3.pdf p75
                    const std::string signature =
                        string_from_unterminated(reinterpret_cast<const char*>(buf.pData_ + 2), buf.size_ - 2);

                    // 728 rmills@rmillsmbp:~/gnu/exiv2/ttt $ exiv2 -pS test/data/exiv2-bug922.jpg
                    // STRUCTURE OF JPEG FILE: test/data/exiv2-bug922.jpg
                    // address | marker     | length  | data
                    //       0 | 0xd8 SOI   |       0
                    //       2 | 0xe1 APP1  |     911 | Exif..MM.*.......%.........#....
                    //     915 | 0xe1 APP1  |     870 | http://ns.adobe.com/xap/1.0/.<x:
                    //    1787 | 0xe1 APP1  |   65460 | http://ns.adobe.com/xmp/extensio
                    if (option == kpsXMP && signature.rfind("http://ns.adobe.com/x", 0) == 0) {
                        // extract XMP
                        if (size > 0) {
                            io_->seek(-bufRead, BasicIo::cur);
                            std::vector<byte> xmp(size + 1);
                            io_->read(&xmp[0], size);
                            int start = 0;

                            // http://wwwimages.adobe.com/content/dam/Adobe/en/devnet/xmp/pdfs/XMPSpecificationPart3.pdf
                            // if we find HasExtendedXMP, set the flag and ignore this block
                            // the first extended block is a copy of the Standard block.
                            // a robust implementation allows extended blocks to be out of sequence
                            // we could implement out of sequence with a dictionary of sequence/offset
                            // and dumping the XMP in a post read operation similar to kpsIptcErase
                            // for the moment, dumping 'on the fly' is working fine
                            if (!bExtXMP) {
                                while (xmp.at(start)) {
                                    start++;
                                }
                                start++;
                                const std::string xmp_from_start = string_from_unterminated(
                                    reinterpret_cast<const char*>(&xmp.at(start)), size - start);
                                if (xmp_from_start.find("HasExtendedXMP", start) != std::string::npos) {
                                    start = size;  // ignore this packet, we'll get on the next time around
                                    bExtXMP = true;
                                }
                            } else {
                                start = 2 + 35 + 32 + 4 + 4;  // Adobe Spec, p19
