	if (status == BZ_OK || status == BZ_STREAM_END)
		return 0;

	error_printf(_("Failed to uncompress bzip2 stream (%d)\n"), status);
	return -1;
}

static void bzip2_exit(wget_decompressor *dc)
{
	BZ2_bzDecompressEnd(&dc->bz_strm);
}
#endif // WITH_BZIP2

static int identity(wget_decompressor *dc, const char *src, size_t srclen)
{
	if (dc->sink)
		dc->sink(dc->context, src, srclen);

	return 0;
}

wget_decompressor *wget_decompress_open(
	wget_content_encoding encoding,
	wget_decompressor_sink_fn *sink,
	void *context)
{
	int rc = 0;
	wget_decompressor *dc = wget_calloc(1, sizeof(wget_decompressor));

	if (!dc)
		return NULL;

	if (encoding == wget_content_encoding_gzip) {
#ifdef WITH_ZLIB
		if ((rc = gzip_init(&dc->z_strm)) == 0) {
			dc->decompress = gzip_decompress;
			dc->exit = gzip_exit;
		}
#endif
	} else if (encoding == wget_content_encoding_deflate) {
#ifdef WITH_ZLIB
		if ((rc = deflate_init(&dc->z_strm)) == 0) {
			dc->decompress = gzip_decompress;
			dc->exit = gzip_exit;
		}
#endif
	} else if (encoding == wget_content_encoding_bzip2) {
#ifdef WITH_BZIP2
		if ((rc = bzip2_init(&dc->bz_strm)) == 0) {
			dc->decompress = bzip2_decompress;
			dc->exit = bzip2_exit;
		}
#endif
	} else if (encoding == wget_content_encoding_lzma) {
#ifdef WITH_LZMA
		if ((rc = lzma_init(&dc->lzma_strm)) == 0) {
			dc->decompress = lzma_decompress;
			dc->exit = lzma_exit;
		}
#endif
	} else if (encoding == wget_content_encoding_brotli) {
#ifdef WITH_BROTLIDEC
		if ((rc = brotli_init(&dc->brotli_strm)) == 0) {
			dc->decompress = brotli_decompress;
			dc->exit = brotli_exit;
		}
#endif
	} else if (encoding == wget_content_encoding_zstd) {
#ifdef WITH_ZSTD
		if ((rc = zstd_init(&dc->zstd_strm)) == 0) {
			dc->decompress = zstd_decompress;
			dc->exit = zstd_exit;
		}
#endif
	} else if (encoding == wget_content_encoding_lzip) {
#ifdef WITH_LZIP
		if ((rc = lzip_init(&dc->lzip_strm)) == 0) {
			dc->decompress = lzip_decompress;
			dc->exit = lzip_exit;
		}
#endif
	}

	if (!dc->decompress) {
		// identity
		debug_printf("Falling back to Content-Encoding 'identity'\n");
		dc->decompress = identity;
	}

	if (rc) {
		xfree(dc);
		return NULL;
	}

	dc->encoding = encoding;
	dc->sink = sink;
	dc->context = context;
	return dc;
}

void wget_decompress_close(wget_decompressor *dc)
