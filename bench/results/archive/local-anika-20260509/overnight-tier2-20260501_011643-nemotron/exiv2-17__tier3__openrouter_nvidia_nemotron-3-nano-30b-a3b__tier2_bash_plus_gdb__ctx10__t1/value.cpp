        return "";
    }

    long LangAltValue::toLong(long /*n*/) const
    {
        ok_ = false;
        return 0;
    }

    float LangAltValue::toFloat(long /*n*/) const
    {
        ok_ = false;
        return 0.0F;
    }

    Rational LangAltValue::toRational(long /*n*/) const
    {
        ok_ = false;
        return {0, 0};
    }

    LangAltValue* LangAltValue::clone_() const
    {
        return new LangAltValue(*this);
    }

    DateValue::DateValue()
        : Value(date)
    {
    }

    DateValue::DateValue(int year, int month, int day)
        : Value(date)
    {
        date_.year = year;
        date_.month = month;
        date_.day = day;
    }

    int DateValue::read(const byte* buf, long len, ByteOrder /*byteOrder*/)
    {
        // Hard coded to read Iptc style dates
        if (len != 8) {
#ifndef SUPPRESS_WARNINGS
            EXV_WARNING << Error(kerUnsupportedDateFormat) << "\n";
#endif
            return 1;
        }
        // Make the buffer a 0 terminated C-string for sscanf
        char b[] = { 0, 0, 0, 0, 0, 0, 0, 0, 0 };
        std::memcpy(b, reinterpret_cast<const char*>(buf), 8);
        int scanned = sscanf(b, "%4d%2d%2d",
                             &date_.year, &date_.month, &date_.day);
        if (scanned != 3){
#ifndef SUPPRESS_WARNINGS
            EXV_WARNING << Error(kerUnsupportedDateFormat) << "\n";
#endif
            return 1;
        }
        return 0;
    }

    int DateValue::read(const std::string& buf)
    {
        // Hard coded to read Iptc style dates
        if (buf.length() < 8) {
#ifndef SUPPRESS_WARNINGS
            EXV_WARNING << Error(kerUnsupportedDateFormat) << "\n";
#endif
            return 1;
        }
        int scanned = sscanf(buf.c_str(), "%4d-%d-%d",
                             &date_.year, &date_.month, &date_.day);
        if (scanned != 3){
#ifndef SUPPRESS_WARNINGS
            EXV_WARNING << Error(kerUnsupportedDateFormat) << "\n";
#endif
            return 1;
        }
        return 0;
    }

    void DateValue::setDate(const Date& src)
    {
        date_.year = src.year;
        date_.month = src.month;
        date_.day = src.day;
    }

    long DateValue::copy(byte* buf, ByteOrder /*byteOrder*/) const
    {
        // sprintf wants to add the null terminator, so use oversized buffer
        char temp[9];

        int wrote = sprintf(temp, "%04d%02d%02d", date_.year, date_.month, date_.day);
        assert(wrote == 8);
        std::memcpy(buf, temp, wrote);
        return wrote;
    }

    const DateValue::Date& DateValue::getDate() const
