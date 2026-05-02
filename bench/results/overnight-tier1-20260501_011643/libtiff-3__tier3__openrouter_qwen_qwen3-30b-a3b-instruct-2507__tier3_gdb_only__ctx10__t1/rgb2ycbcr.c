static	int tiffcvt(TIFF* in, TIFF* out);
static	void usage(int code);
static	void setupLumaTables(void);

#ifdef DPP_ENABLE_GCOV
#include <signal.h>
static struct sigaction dpp_gcov_sigaction;
static struct sigaction dpp_orig_sigaction;
void dpp_sighandler(int signum) {
	__gcov_flush();
	sigaction(sigaction, &dpp_orig_sigaction, NULL);
	raise(signum);
	exit(1);
}
#endif
int
main(int argc, char* argv[])
  {
#ifdef DPP_ENABLE_GCOV
	  {
		  dpp_gcov_sigaction.sa_handler = dpp_sighandler;
		  sigemptyset(&dpp_gcov_sigaction.sa_mask);
		  dpp_gcov_sigaction.sa_flags = 0;
		  sigaction(SIGSEGV, &dpp_gcov_sigaction, &dpp_orig_sigaction);
		  sigaction(SIGFPE, &dpp_gcov_sigaction, &dpp_orig_sigaction);
		  sigaction(SIGABRT, &dpp_gcov_sigaction, &dpp_orig_sigaction);
	  }
#endif
	TIFF *in, *out;
	int c;
#if !HAVE_DECL_OPTARG
	extern int optind;
	extern char *optarg;
#endif

	while ((c = getopt(argc, argv, "c:h:r:v:z")) != -1)
		switch (c) {
		case 'c':
			if (streq(optarg, "none"))
			    compression = COMPRESSION_NONE;
			else if (streq(optarg, "packbits"))
			    compression = COMPRESSION_PACKBITS;
			else if (streq(optarg, "lzw"))
			    compression = COMPRESSION_LZW;
			else if (streq(optarg, "jpeg"))
			    compression = COMPRESSION_JPEG;
			else if (streq(optarg, "zip"))
			    compression = COMPRESSION_ADOBE_DEFLATE;
			else
			    usage(-1);
			break;
		case 'h':
			horizSubSampling = atoi(optarg);
			break;
		case 'v':
			vertSubSampling = atoi(optarg);
            if( vertSubSampling != 1 && vertSubSampling != 2 && vertSubSampling != 4 )
                usage(-1);
			break;
		case 'r':
			rowsperstrip = atoi(optarg);
			break;
		case 'z':	/* CCIR Rec 601-1 w/ headroom/footroom */
			refBlackWhite[0] = 16.;
			refBlackWhite[1] = 235.;
			refBlackWhite[2] = 128.;
			refBlackWhite[3] = 240.;
			refBlackWhite[4] = 128.;
			refBlackWhite[5] = 240.;
			break;
		case '?':
			usage(0);
			/*NOTREACHED*/
		}
	if (argc - optind < 2)
		usage(-1);
	out = TIFFOpen(argv[argc-1], "w");
	if (out == NULL)
		return (-2);
	setupLumaTables();
	for (; optind < argc-1; optind++) {
		in = TIFFOpen(argv[optind], "r");
		if (in != NULL) {
			do {
				if (!tiffcvt(in, out) ||
				    !TIFFWriteDirectory(out)) {
					(void) TIFFClose(out);
					return (1);
				}
			} while (TIFFReadDirectory(in));
			(void) TIFFClose(in);
		}
	}
	(void) TIFFClose(out);
	return (0);
}

float	*lumaRed;
float	*lumaGreen;
float	*lumaBlue;
float	D1, D2;
