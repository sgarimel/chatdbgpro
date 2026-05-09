// ***************************************************************** -*- C++ -*-
/*
 * Copyright (C) 2004-2018 Exiv2 authors
 * This program is part of the Exiv2 distribution.
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, 5th Floor, Boston, MA 02110-1301 USA.
 */
/*
  File:    pngimage.cpp
 */
// *****************************************************************************
// included header files
#include "config.h"

#ifdef   EXV_HAVE_LIBZ
#include "pngchunk_int.hpp"
#include "pngimage.hpp"
#include "jpgimage.hpp"
#include "tiffimage.hpp"
#include "image.hpp"
#include "image_int.hpp"
#include "basicio.hpp"
#include "error.hpp"
#include "futils.hpp"
#include "types.hpp"

// + standard includes
#include <string>
#include <iterator>
#include <cstring>
#include <iostream>
#include <cassert>

#include <zlib.h>     // To uncompress IccProfiles
// Signature from front of PNG file
const unsigned char pngSignature[8] = { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };

const unsigned char pngBlank[] = { 0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,0x00,0x00,0x00,0x0d,0x49,0x48,0x44,0x52,
                                   0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x02,0x00,0x00,0x00,0x90,0x77,0x53,
                                   0xde,0x00,0x00,0x00,0x01,0x73,0x52,0x47,0x42,0x00,0xae,0xce,0x1c,0xe9,0x00,0x00,
                                   0x00,0x09,0x70,0x48,0x59,0x73,0x00,0x00,0x0b,0x13,0x00,0x00,0x0b,0x13,0x01,0x00,
                                   0x9a,0x9c,0x18,0x00,0x00,0x00,0x0c,0x49,0x44,0x41,0x54,0x08,0xd7,0x63,0xf8,0xff,
                                   0xff,0x3f,0x00,0x05,0xfe,0x02,0xfe,0xdc,0xcc,0x59,0xe7,0x00,0x00,0x00,0x00,0x49,
                                   0x45,0x4e,0x44,0xae,0x42,0x60,0x82
                                 };

namespace
{
    inline bool compare(const char* str, const Exiv2::DataBuf& buf, size_t length)
    {
        // str & length should compile time constants => only running this in DEBUG mode is ok
        assert(strlen(str) <= length);
        return memcmp(str, buf.pData_, std::min(static_cast<long>(length), buf.size_)) == 0;
    }
}  // namespace

// *****************************************************************************
// class member definitions
namespace Exiv2 {

    using namespace Internal;

    PngImage::PngImage(BasicIo::AutoPtr io, bool create)
            : Image(ImageType::png, mdExif | mdIptc | mdXmp | mdComment, io)
    {
        if (create)
        {
            if (io_->open() == 0)
            {
#ifdef DEBUG
                std::cerr << "Exiv2::PngImage:: Creating PNG image to memory\n";
