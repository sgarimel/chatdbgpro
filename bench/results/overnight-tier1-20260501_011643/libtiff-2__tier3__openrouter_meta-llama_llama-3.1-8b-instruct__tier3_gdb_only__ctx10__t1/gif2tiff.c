    interleaved = buf[8] & 0x40;
    if (width == 0UL || height == 0UL || (width > 2000000000UL / height)) {
        fprintf(stderr, "Invalid value of width or height\n");
        return(0);
    }
    if (local == 0 && global == 0) {
        fprintf(stderr, "no colormap present for image\n");
        return (0);
    }
    raster_size=width*height;
    if ((raster_size/width) == height) {
        raster_size += EXTRAFUDGE;  /* Add elbow room */
    } else {
        raster_size=0;
    }
    if ((raster = (unsigned char*) _TIFFmalloc(raster_size)) == NULL) {
        fprintf(stderr, "not enough memory for image\n");
        return (0);
    }
    if (local) {
        localbits = (buf[8] & 0x7) + 1;

        fprintf(stderr, "   local colors: %d\n", 1<<localbits);

        if (fread(localmap, 3, ((size_t)1)<<localbits, infile) !=
            ((size_t)1)<<localbits) {
            fprintf(stderr, "short read from file %s (%s)\n",
                    filename, strerror(errno));
            return (0);
        }
        initcolors(localmap, 1<<localbits);
    } else if (global) {
        initcolors(globalmap, 1<<globalbits);
    }
    if ((status = readraster()))
	rasterize(interleaved, mode);
    _TIFFfree(raster);
    return status;
}

/*
 * 	readextension -
 *		Read a GIF extension block (and do nothing with it).
 *
 */
int
readextension(void)
{
    int count;
    char buf[255];
    int status = 1;

    (void) getc(infile);
    while ((count = getc(infile)) && count <= 255)
        if (fread(buf, 1, count, infile) != (size_t) count) {
            fprintf(stderr, "short read from file %s (%s)\n",
                    filename, strerror(errno));
            status = 0;
            break;
        }
    return status;
}

/*
 * 	readraster -
 *		Decode a raster image
 *
 */
int
readraster(void)
{
    unsigned char *fill = raster;
    unsigned char buf[255];
    register int bits=0;
    register unsigned long datum=0;
    register unsigned char *ch;
    register int count, code;
    int status = 1;

    datasize = getc(infile);
    if (datasize > 12)
	return 0;
    clear = 1 << datasize;
    eoi = clear + 1;
    avail = clear + 2;
    oldcode = -1;
    codesize = datasize + 1;
    codemask = (1 << codesize) - 1;
    for (code = 0; code < clear; code++) {
	prefix[code] = 0;
	suffix[code] = code;
    }
    stackp = stack;
    for (count = getc(infile); count > 0 && count <= 255; count = getc(infile)) {
	if (fread(buf,1,count,infile) != (size_t)count) {
            fprintf(stderr, "short read from file %s (%s)\n",
                    filename, strerror(errno));
            return 0;
        }
	for (ch=buf; count-- > 0; ch++) {
	    datum += (unsigned long) *ch << bits;
