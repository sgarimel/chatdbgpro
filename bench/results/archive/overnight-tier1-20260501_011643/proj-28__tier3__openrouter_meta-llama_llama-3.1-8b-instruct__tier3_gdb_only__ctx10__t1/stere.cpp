
static double ssfn_ (double phit, double sinphi, double eccen) {
    sinphi *= eccen;
    return (tan (.5 * (M_HALFPI + phit)) *
       pow ((1. - sinphi) / (1. + sinphi), .5 * eccen));
}


static PJ_XY stere_e_forward (PJ_LP lp, PJ *P) {          /* Ellipsoidal, forward */
    PJ_XY xy = {0.0,0.0};
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(P->opaque);
    double coslam, sinlam, sinX = 0.0, cosX = 0.0, A = 0.0, sinphi;

    coslam = cos (lp.lam);
    sinlam = sin (lp.lam);
    sinphi = sin (lp.phi);
    if (Q->mode == OBLIQ || Q->mode == EQUIT) {
        const double X = 2. * atan(ssfn_(lp.phi, sinphi, P->e)) - M_HALFPI;
        sinX = sin (X);
        cosX = cos (X);
    }

    switch (Q->mode) {
    case OBLIQ: {
        const double denom = Q->cosX1 * (1. + Q->sinX1 * sinX +
           Q->cosX1 * cosX * coslam);
        if( denom == 0 ) {
            proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
            return proj_coord_error().xy;
        }
        A = Q->akm1 / denom;
        xy.y = A * (Q->cosX1 * sinX - Q->sinX1 * cosX * coslam);
        xy.x = A * cosX;
        break;
    }

    case EQUIT:
        /* avoid zero division */
        if (1. + cosX * coslam == 0.0) {
            xy.y = HUGE_VAL;
        } else {
            A = Q->akm1 / (1. + cosX * coslam);
            xy.y = A * sinX;
        }
        xy.x = A * cosX;
        break;

    case S_POLE:
        lp.phi = -lp.phi;
        coslam = - coslam;
        sinphi = -sinphi;
        /*-fallthrough*/
    case N_POLE:
        xy.x = Q->akm1 * pj_tsfn (lp.phi, sinphi, P->e);
        xy.y = - xy.x * coslam;
        break;
    }

    xy.x = xy.x * sinlam;
    return xy;
}


static PJ_XY stere_s_forward (PJ_LP lp, PJ *P) {           /* Spheroidal, forward */
    PJ_XY xy = {0.0,0.0};
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(P->opaque);
    double  sinphi, cosphi, coslam, sinlam;

    sinphi = sin(lp.phi);
    cosphi = cos(lp.phi);
    coslam = cos(lp.lam);
    sinlam = sin(lp.lam);

    switch (Q->mode) {
    case EQUIT:
        xy.y = 1. + cosphi * coslam;
        goto oblcon;
    case OBLIQ:
        xy.y = 1. + sinph0 * sinphi + cosph0 * cosphi * coslam;
oblcon:
        if (xy.y <= EPS10) {
            proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
            return xy;
        }
        xy.y = Q->akm1 / xy.y;
        xy.x = xy.y * cosphi * sinlam;
        xy.y *= (Q->mode == EQUIT) ? sinphi :
           cosph0 * sinphi - sinph0 * cosphi * coslam;
        break;
    case N_POLE:
        coslam = - coslam;
        lp.phi = - lp.phi;
        /*-fallthrough*/
    case S_POLE:
        if (fabs (lp.phi - M_HALFPI) < TOL) {
            proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
            return xy;
        }
        xy.y = Q->akm1 * tan (M_FORTPI + .5 * lp.phi);
        xy.x = sinlam * xy.y;
        xy.y *= coslam;
