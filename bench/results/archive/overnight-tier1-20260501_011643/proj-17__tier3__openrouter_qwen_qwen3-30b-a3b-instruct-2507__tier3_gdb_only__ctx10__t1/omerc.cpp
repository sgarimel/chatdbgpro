    Sp = .5 * (Qp - 1. / Qp);
    Tp = .5 * (Qp + 1. / Qp);
    Vp = sin(Q->BrA * u);
    Up = (Vp * Q->cosgam + Sp * Q->singam) / Tp;
    if (fabs(fabs(Up) - 1.) < EPS) {
        lp.lam = 0.;
        lp.phi = Up < 0. ? -M_HALFPI : M_HALFPI;
    } else {
        lp.phi = Q->E / sqrt((1. + Up) / (1. - Up));
        if ((lp.phi = pj_phi2(P->ctx, pow(lp.phi, 1. / Q->B), P->e)) == HUGE_VAL) {
            proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
            return lp;
        }
        lp.lam = - Q->rB * atan2((Sp * Q->cosgam -
            Vp * Q->singam), cos(Q->BrA * u));
    }
    return lp;
}


PJ *PROJECTION(omerc) {
    double con, com, cosph0, D, F, H, L, sinph0, p, J, gamma=0,
        gamma0, lamc=0, lam1=0, lam2=0, phi1=0, phi2=0, alpha_c=0;
    int alp, gam, no_off = 0;

    struct pj_opaque *Q = static_cast<struct pj_opaque*>(pj_calloc (1, sizeof (struct pj_opaque)));
    if (nullptr==Q)
        return pj_default_destructor (P, ENOMEM);
    P->opaque = Q;

    Q->no_rot = pj_param(P->ctx, P->params, "bno_rot").i;
        if ((alp = pj_param(P->ctx, P->params, "talpha").i) != 0)
            alpha_c = pj_param(P->ctx, P->params, "ralpha").f;
        if ((gam = pj_param(P->ctx, P->params, "tgamma").i) != 0)
            gamma = pj_param(P->ctx, P->params, "rgamma").f;
    if (alp || gam) {
        lamc    = pj_param(P->ctx, P->params, "rlonc").f;
        no_off =
                    /* For libproj4 compatibility */
                    pj_param(P->ctx, P->params, "tno_off").i
                    /* for backward compatibility */
                    || pj_param(P->ctx, P->params, "tno_uoff").i;
        if( no_off )
        {
            /* Mark the parameter as used, so that the pj_get_def() return them */
            pj_param(P->ctx, P->params, "sno_uoff");
            pj_param(P->ctx, P->params, "sno_off");
        }
    } else {
        lam1 = pj_param(P->ctx, P->params, "rlon_1").f;
        phi1 = pj_param(P->ctx, P->params, "rlat_1").f;
        lam2 = pj_param(P->ctx, P->params, "rlon_2").f;
        phi2 = pj_param(P->ctx, P->params, "rlat_2").f;
        if (fabs(phi1 - phi2) <= TOL ||
            (con = fabs(phi1)) <= TOL ||
            fabs(con - M_HALFPI) <= TOL ||
            fabs(fabs(P->phi0) - M_HALFPI) <= TOL ||
            fabs(fabs(phi2) - M_HALFPI) <= TOL)
                return pj_default_destructor(P, PJD_ERR_LAT_0_OR_ALPHA_EQ_90);
    }
    com = sqrt(P->one_es);
    if (fabs(P->phi0) > EPS) {
        sinph0 = sin(P->phi0);
        cosph0 = cos(P->phi0);
        con = 1. - P->es * sinph0 * sinph0;
        Q->B = cosph0 * cosph0;
        Q->B = sqrt(1. + P->es * Q->B * Q->B / P->one_es);
        Q->A = Q->B * P->k0 * com / con;
        D = Q->B * com / (cosph0 * sqrt(con));
        if ((F = D * D - 1.) <= 0.)
            F = 0.;
        else {
            F = sqrt(F);
            if (P->phi0 < 0.)
                F = -F;
        }
        Q->E = F += D;
        Q->E *= pow(pj_tsfn(P->phi0, sinph0, P->e), Q->B);
    } else {
        Q->B = 1. / com;
        Q->A = P->k0;
        Q->E = D = F = 1.;
    }
    if (alp || gam) {
        if (alp) {
            gamma0 = aasin(P->ctx, sin(alpha_c) / D);
            if (!gam)
                gamma = alpha_c;
        } else
            alpha_c = aasin(P->ctx, D*sin(gamma0 = gamma));
        if( fabs(fabs(P->phi0) - M_HALFPI) <= TOL ) {
            return pj_default_destructor(P, PJD_ERR_LAT_0_OR_ALPHA_EQ_90);
        }
        P->lam0 = lamc - aasin(P->ctx, .5 * (F - 1. / F) *
           tan(gamma0)) / Q->B;
    } else {
        H = pow(pj_tsfn(phi1, sin(phi1), P->e), Q->B);
        L = pow(pj_tsfn(phi2, sin(phi2), P->e), Q->B);
        F = Q->E / H;
        p = (L - H) / (L + H);
        if( p == 0 ) {
