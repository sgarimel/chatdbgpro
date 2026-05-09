 * IN NO EVENT SHALL SAM LEFFLER OR SILICON GRAPHICS BE LIABLE FOR
 * ANY SPECIAL, INCIDENTAL, INDIRECT OR CONSEQUENTIAL DAMAGES OF ANY KIND,
 * OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
 * WHETHER OR NOT ADVISED OF THE POSSIBILITY OF DAMAGE, AND ON ANY THEORY OF 
 * LIABILITY, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE 
 * OF THIS SOFTWARE.
 */

/*
 * TIFF Library.
 *
 * Strip-organized Image Support Routines.
 */
#include "tiffiop.h"

/*
 * Compute which strip a (row,sample) value is in.
 */
uint32
TIFFComputeStrip(TIFF* tif, uint32 row, uint16 sample)
{
	static const char module[] = "TIFFComputeStrip";
	TIFFDirectory *td = &tif->tif_dir;
	uint32 strip;

	strip = row / td->td_rowsperstrip;
	if (td->td_planarconfig == PLANARCONFIG_SEPARATE) {
		if (sample >= td->td_samplesperpixel) {
			TIFFErrorExt(tif->tif_clientdata, module,
			    "%lu: Sample out of range, max %lu",
			    (unsigned long) sample, (unsigned long) td->td_samplesperpixel);
			return (0);
		}
		strip += (uint32)sample*td->td_stripsperimage;
	}
	return (strip);
}

/*
 * Compute how many strips are in an image.
 */
uint32
TIFFNumberOfStrips(TIFF* tif)
{
	TIFFDirectory *td = &tif->tif_dir;
	uint32 nstrips;

    /* If the value was already computed and store in td_nstrips, then return it,
       since ChopUpSingleUncompressedStrip might have altered and resized the
       since the td_stripbytecount and td_stripoffset arrays to the new value
       after the initial affectation of td_nstrips = TIFFNumberOfStrips() in
       tif_dirread.c ~line 3612.
       See http://bugzilla.maptools.org/show_bug.cgi?id=2587 */

	nstrips = (td->td_rowsperstrip == (uint32) -1 ? 1 :
	     TIFFhowmany_32(td->td_imagelength, td->td_rowsperstrip));
	if (td->td_planarconfig == PLANARCONFIG_SEPARATE)
		nstrips = _TIFFMultiply32(tif, nstrips, (uint32)td->td_samplesperpixel,
		    "TIFFNumberOfStrips");
	return (nstrips);
}

/*
 * Compute the # bytes in a variable height, row-aligned strip.
 */
uint64
TIFFVStripSize64(TIFF* tif, uint32 nrows)
{
	static const char module[] = "TIFFVStripSize64";
	TIFFDirectory *td = &tif->tif_dir;
	if (nrows==(uint32)(-1))
		nrows=td->td_imagelength;
	if ((td->td_planarconfig==PLANARCONFIG_CONTIG)&&
	    (td->td_photometric == PHOTOMETRIC_YCBCR)&&
	    (!isUpSampled(tif)))
	{
		/*
		 * Packed YCbCr data contain one Cb+Cr for every
		 * HorizontalSampling*VerticalSampling Y values.
		 * Must also roundup width and height when calculating
		 * since images that are not a multiple of the
		 * horizontal/vertical subsampling area include
		 * YCbCr data for the extended image.
		 */
		uint16 ycbcrsubsampling[2];
		uint16 samplingblock_samples;
		uint32 samplingblocks_hor;
		uint32 samplingblocks_ver;
		uint64 samplingrow_samples;
		uint64 samplingrow_size;
		if(td->td_samplesperpixel!=3)
		{
			TIFFErrorExt(tif->tif_clientdata,module,
			    "Invalid td_samplesperpixel value");
			return 0;
		}
		TIFFGetFieldDefaulted(tif,TIFFTAG_YCBCRSUBSAMPLING,ycbcrsubsampling+0,
		    ycbcrsubsampling+1);
		if ((ycbcrsubsampling[0] != 1 && ycbcrsubsampling[0] != 2 && ycbcrsubsampling[0] != 4)
		    ||(ycbcrsubsampling[1] != 1 && ycbcrsubsampling[1] != 2 && ycbcrsubsampling[1] != 4))
		{
