) {
/**************************************************************************************

    Transform a series of coordinates, where the individual coordinate dimension
    may be represented by an array that is either

        1. fully populated
        2. a null pointer and/or a length of zero, which will be treated as a
           fully populated array of zeroes
        3. of length one, i.e. a constant, which will be treated as a fully
           populated array of that constant value

    The strides, sx, sy, sz, st, represent the step length, in bytes, between
    consecutive elements of the corresponding array. This makes it possible for
    proj_transform to handle transformation of a large class of application
    specific data structures, without necessarily understanding the data structure
    format, as in:

        typedef struct {double x, y; int quality_level; char surveyor_name[134];} XYQS;
        XYQS survey[345];
        double height = 23.45;
        PJ *P = {...};
        size_t stride = sizeof (XYQS);
        ...
        proj_transform (
            P, PJ_INV, sizeof(XYQS),
            &(survey[0].x), stride, 345,  (*  We have 345 eastings  *)
            &(survey[0].y), stride, 345,  (*  ...and 345 northings. *)
            &height, 1,                   (*  The height is the constant  23.45 m *)
            0, 0                          (*  and the time is the constant 0.00 s *)
        );

    This is similar to the inner workings of the pj_transform function, but the
    stride functionality has been generalized to work for any size of basic unit,
    not just a fixed number of doubles.

    In most cases, the stride will be identical for x, y,z, and t, since they will
    typically be either individual arrays (stride = sizeof(double)), or strided
    views into an array of application specific data structures (stride = sizeof (...)).

    But in order to support cases where x, y, z, and t come from heterogeneous
    sources, individual strides, sx, sy, sz, st, are used.

    Caveat: Since proj_transform does its work *in place*, this means that even the
    supposedly constants (i.e. length 1 arrays) will return from the call in altered
    state. Hence, remember to reinitialize between repeated calls.

    Return value: Number of transformations completed.

**************************************************************************************/
    PJ_COORD coord = {{0,0,0,0}};
    size_t i, nmin;
    double null_broadcast = 0;

    if (nullptr==P)
        return 0;

    if (P->inverted)
        direction = opposite_direction(direction);

    /* ignore lengths of null arrays */
    if (nullptr==x) nx = 0;
    if (nullptr==y) ny = 0;
    if (nullptr==z) nz = 0;
    if (nullptr==t) nt = 0;

    /* and make the nullities point to some real world memory for broadcasting nulls */
    if (0==nx) x = &null_broadcast;
    if (0==ny) y = &null_broadcast;
    if (0==nz) z = &null_broadcast;
    if (0==nt) t = &null_broadcast;

    /* nothing to do? */
    if (0==nx+ny+nz+nt)
        return 0;

    /* arrays of length 1 are constants, which we broadcast along the longer arrays */
    /* so we need to find the length of the shortest non-unity array to figure out  */
    /* how many coordinate pairs we must transform */
    nmin = (nx > 1)? nx: (ny > 1)? ny: (nz > 1)? nz: (nt > 1)? nt: 1;
    if ((nx > 1) && (nx < nmin))  nmin = nx;
    if ((ny > 1) && (ny < nmin))  nmin = ny;
    if ((nz > 1) && (nz < nmin))  nmin = nz;
    if ((nt > 1) && (nt < nmin))  nmin = nt;

    /* Check validity of direction flag */
    switch (direction) {
        case PJ_FWD:
        case PJ_INV:
            break;
        case PJ_IDENT:
            return nmin;
        default:
            proj_errno_set (P, EINVAL);
            return 0;
    }

    /* Arrays of length==0 are broadcast as the constant 0               */
    /* Arrays of length==1 are broadcast as their single value           */
    /* Arrays of length >1 are iterated over (for the first nmin values) */
    /* The slightly convolved incremental indexing is used due           */
