            proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
            return xy;
        }
        else xy.y = 0.;
    } else
        xy.y = acos (xy.y);

    if (lp.phi < 0.)
        xy.y = -xy.y;
    xy.y = static_cast<struct pj_opaque_approx*>(P->opaque)->esp * (xy.y - P->phi0);
    return xy;
}


static PJ_LP approx_e_inv (PJ_XY xy, PJ *P) {
    PJ_LP lp = {0.0,0.0};
    struct pj_opaque_approx *Q = static_cast<struct pj_opaque_approx*>(P->opaque);
    double n, con, cosphi, d, ds, sinphi, t;

    lp.phi = pj_inv_mlfn(P->ctx, Q->ml0 + xy.y / P->k0, P->es, Q->en);
    if (fabs(lp.phi) >= M_HALFPI) {
        lp.phi = xy.y < 0. ? -M_HALFPI : M_HALFPI;
        lp.lam = 0.;
    } else {
        sinphi = sin(lp.phi);
        cosphi = cos(lp.phi);
        t = fabs (cosphi) > 1e-10 ? sinphi/cosphi : 0.;
        n = Q->esp * cosphi * cosphi;
        d = xy.x * sqrt (con = 1. - P->es * sinphi * sinphi) / P->k0;
        con *= t;
        t *= t;
        ds = d * d;
        lp.phi -= (con * ds / (1.-P->es)) * FC2 * (1. -
            ds * FC4 * (5. + t * (3. - 9. *  n) + n * (1. - 4 * n) -
            ds * FC6 * (61. + t * (90. - 252. * n +
                45. * t) + 46. * n
           - ds * FC8 * (1385. + t * (3633. + t * (4095. + 1575. * t)) )
            )));
        lp.lam = d*(FC1 -
            ds*FC3*( 1. + 2.*t + n -
            ds*FC5*(5. + t*(28. + 24.*t + 8.*n) + 6.*n
           - ds * FC7 * (61. + t * (662. + t * (1320. + 720. * t)) )
        ))) / cosphi;
    }
    return lp;
}


static PJ_LP approx_s_inv (PJ_XY xy, PJ *P) {
    PJ_LP lp = {0.0, 0.0};
    double h, g;

    h = exp(xy.x / static_cast<struct pj_opaque_approx*>(P->opaque)->esp);
    g = .5 * (h - 1. / h);
    h = cos (P->phi0 + xy.y / static_cast<struct pj_opaque_approx*>(P->opaque)->esp);
    lp.phi = asin(sqrt((1. - h * h) / (1. + g * g)));

    /* Make sure that phi is on the correct hemisphere when false northing is used */
    if (xy.y < 0. && -lp.phi+P->phi0 < 0.0) lp.phi = -lp.phi;

    lp.lam = (g != 0.0 || h != 0.0) ? atan2 (g, h) : 0.;
    return lp;
}


static PJ *destructor_approx(PJ *P, int errlev) {
    if (nullptr==P)
        return nullptr;

    if (nullptr==P->opaque)
        return pj_default_destructor(P, errlev);

    pj_dealloc (static_cast<struct pj_opaque_approx*>(P->opaque)->en);
    return pj_default_destructor(P, errlev);
}


static PJ *setup_approx(PJ *P) {
    struct pj_opaque_approx *Q = static_cast<struct pj_opaque_approx*>(P->opaque);

    P->destructor = destructor_approx;

    if (P->es != 0.0) {
        if (!(Q->en = pj_enfn(P->es)))
            return pj_default_destructor(P, ENOMEM);

        Q->ml0 = pj_mlfn(P->phi0, sin(P->phi0), cos(P->phi0), Q->en);
        Q->esp = P->es / (1. - P->es);
        P->inv = approx_e_inv;
        P->fwd = approx_e_fwd;
    } else {
        Q->esp = P->k0;
        Q->ml0 = .5 * Q->esp;
        P->inv = approx_s_inv;
        P->fwd = approx_s_fwd;
    }
    return P;
}



