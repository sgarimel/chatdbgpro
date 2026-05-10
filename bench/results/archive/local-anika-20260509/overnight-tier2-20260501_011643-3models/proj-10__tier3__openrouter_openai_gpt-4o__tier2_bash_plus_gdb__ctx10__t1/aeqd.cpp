    coslam = cos(lp.lam);
    cosphi = cos(lp.phi);
    sinphi = sin(lp.phi);
    switch (Q->mode) {
    case N_POLE:
        coslam = - coslam;
        /*-fallthrough*/
    case S_POLE:
        xy.x = (rho = fabs(Q->Mp - pj_mlfn(lp.phi, sinphi, cosphi, Q->en))) *
            sin(lp.lam);
        xy.y = rho * coslam;
        break;
    case EQUIT:
    case OBLIQ:
        if (fabs(lp.lam) < EPS10 && fabs(lp.phi - P->phi0) < EPS10) {
            xy.x = xy.y = 0.;
            break;
        }

        phi1 = P->phi0 / DEG_TO_RAD; lam1 = P->lam0 / DEG_TO_RAD;
        phi2 = lp.phi / DEG_TO_RAD;  lam2 = (lp.lam+P->lam0) / DEG_TO_RAD;

        geod_inverse(&Q->g, phi1, lam1, phi2, lam2, &s12, &azi1, &azi2);
        azi1 *= DEG_TO_RAD;
        xy.x = s12 * sin(azi1) / P->a;
        xy.y = s12 * cos(azi1) / P->a;
        break;
    }
    return xy;
}


static PJ_XY aeqd_s_forward (PJ_LP lp, PJ *P) {           /* Spheroidal, forward */
    PJ_XY xy = {0.0,0.0};
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(P->opaque);
    double  coslam, cosphi, sinphi;

    sinphi = sin(lp.phi);
    cosphi = cos(lp.phi);
    coslam = cos(lp.lam);
    switch (Q->mode) {
    case EQUIT:
        xy.y = cosphi * coslam;
        goto oblcon;
    case OBLIQ:
        xy.y = Q->sinph0 * sinphi + Q->cosph0 * cosphi * coslam;
oblcon:
        if (fabs(fabs(xy.y) - 1.) < TOL)
            if (xy.y < 0.) {
                proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
                return xy;
            }
            else
                xy.x = xy.y = 0.;
        else {
            xy.y = acos(xy.y);
            xy.y /= sin(xy.y);
            xy.x = xy.y * cosphi * sin(lp.lam);
            xy.y *= (Q->mode == EQUIT) ? sinphi :
                Q->cosph0 * sinphi - Q->sinph0 * cosphi * coslam;
        }
        break;
    case N_POLE:
        lp.phi = -lp.phi;
        coslam = -coslam;
        /*-fallthrough*/
    case S_POLE:
        if (fabs(lp.phi - M_HALFPI) < EPS10) {
            proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
            return xy;
        }
        xy.x = (xy.y = (M_HALFPI + lp.phi)) * sin(lp.lam);
        xy.y *= coslam;
        break;
    }
    return xy;
}


static PJ_LP e_guam_inv(PJ_XY xy, PJ *P) { /* Guam elliptical */
    PJ_LP lp = {0.0,0.0};
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(P->opaque);
    double x2, t = 0.0;
    int i;

    x2 = 0.5 * xy.x * xy.x;
    lp.phi = P->phi0;
    for (i = 0; i < 3; ++i) {
        t = P->e * sin(lp.phi);
        lp.phi = pj_inv_mlfn(P->ctx, Q->M1 + xy.y -
            x2 * tan(lp.phi) * (t = sqrt(1. - t * t)), P->es, Q->en);
    }
    lp.lam = xy.x * t / cos(lp.phi);
    return lp;
}


static PJ_LP aeqd_e_inverse (PJ_XY xy, PJ *P) {          /* Ellipsoidal, inverse */
    PJ_LP lp = {0.0,0.0};
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(P->opaque);
    double c;
