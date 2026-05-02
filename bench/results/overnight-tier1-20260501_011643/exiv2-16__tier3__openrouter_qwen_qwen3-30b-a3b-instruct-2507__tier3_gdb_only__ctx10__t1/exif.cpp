
// *****************************************************************************
// class member definitions
namespace Exiv2 {

    using namespace Internal;

    /*!
      @brief Set the value of \em exifDatum to \em value. If the object already
             has a value, it is replaced. Otherwise a new ValueType\<T\> value
             is created and set to \em value.

      This is a helper function, called from Exifdatum members. It is meant to
      be used with T = (u)int16_t, (u)int32_t or (U)Rational. Do not use directly.
    */
    template<typename T>
    Exiv2::Exifdatum& setValue(Exiv2::Exifdatum& exifDatum, const T& value)
    {
        auto v = std::unique_ptr<Exiv2::ValueType<T> >(new Exiv2::ValueType<T>);
        v->value_.push_back(value);
        exifDatum.value_ = std::move(v);
        return exifDatum;
    }

    Exifdatum::Exifdatum(const ExifKey& key, const Value* pValue)
        : key_(key.clone())
    {
        if (pValue) value_ = pValue->clone();
    }

    Exifdatum::Exifdatum(const Exifdatum& rhs)
        : Metadatum(rhs)
    {
        if (rhs.key_.get() != nullptr)
            key_ = rhs.key_->clone();  // deep copy
        if (rhs.value_.get() != nullptr)
            value_ = rhs.value_->clone();  // deep copy
    }

    std::ostream& Exifdatum::write(std::ostream& os, const ExifData* pMetadata) const
    {
        if (value().count() == 0) return os;

        PrintFct       fct = printValue;
        const TagInfo* ti  = Internal::tagInfo(tag(), static_cast<IfdId>(ifdId()));
        // be careful with comments (User.Photo.UserComment, GPSAreaInfo etc).
        if ( ti ) {
            fct = ti->printFct_;
            if ( ti->typeId_ == comment ) {
              os << value().toString();
              fct = nullptr;
            }
        }
        if ( fct ) fct(os, value(), pMetadata);
        return os;
    }

    const Value& Exifdatum::value() const
    {
        if (value_.get() == nullptr)
            throw Error(kerValueNotSet);
        return *value_;
    }

    Exifdatum& Exifdatum::operator=(const Exifdatum& rhs)
    {
        if (this == &rhs) return *this;
        Metadatum::operator=(rhs);

        key_.reset();
        if (rhs.key_.get() != nullptr)
            key_ = rhs.key_->clone();  // deep copy

        value_.reset();
        if (rhs.value_.get() != nullptr)
            value_ = rhs.value_->clone();  // deep copy

        return *this;
    } // Exifdatum::operator=

    Exifdatum& Exifdatum::operator=(const std::string& value)
    {
        setValue(value);
        return *this;
    }

    Exifdatum& Exifdatum::operator=(const uint16_t& value)
    {
        return Exiv2::setValue(*this, value);
    }

    Exifdatum& Exifdatum::operator=(const uint32_t& value)
    {
        return Exiv2::setValue(*this, value);
    }

    Exifdatum& Exifdatum::operator=(const URational& value)
    {
        return Exiv2::setValue(*this, value);
    }

