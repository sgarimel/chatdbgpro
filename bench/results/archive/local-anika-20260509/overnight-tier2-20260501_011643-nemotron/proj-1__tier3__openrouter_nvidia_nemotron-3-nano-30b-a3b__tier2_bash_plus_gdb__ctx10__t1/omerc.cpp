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
        P->lam0 = lamc - aasin(P->ctx, .5 * (F - 1. / F) *
           tan(gamma0)) / Q->B;
    } else {
        H = pow(pj_tsfn(phi1, sin(phi1), P->e), Q->B);
        L = pow(pj_tsfn(phi2, sin(phi2), P->e), Q->B);
        F = Q->E / H;
        p = (L - H) / (L + H);
        J = Q->E * Q->E;
        J = (J - L * H) / (J + L * H);
        if ((con = lam1 - lam2) < -M_PI)
            lam2 -= M_TWOPI;
        else if (con > M_PI)
            lam2 += M_TWOPI;
        P->lam0 = adjlon(.5 * (lam1 + lam2) - atan(
           J * tan(.5 * Q->B * (lam1 - lam2)) / p) / Q->B);
        gamma0 = atan(2. * sin(Q->B * adjlon(lam1 - P->lam0)) /
           (F - 1. / F));
        gamma = alpha_c = aasin(P->ctx, D * sin(gamma0));
    }
    Q->singam = sin(gamma0);
    Q->cosgam = cos(gamma0);
    Q->sinrot = sin(gamma);
    Q->cosrot = cos(gamma);
    Q->BrA = 1. / (Q->ArB = Q->A * (Q->rB = 1. / Q->B));
    Q->AB = Q->A * Q->B;
    if (no_off)
        Q->u_0 = 0;
    else {
        Q->u_0 = fabs(Q->ArB * atan(sqrt(D * D - 1.) / cos(alpha_c)));
        if (P->phi0 < 0.)
            Q->u_0 = - Q->u_0;
    }
    F = 0.5 * gamma0;
    Q->v_pole_n = Q->ArB * log(tan(M_FORTPI - F));
    Q->v_pole_s = Q->ArB * log(tan(M_FORTPI + F));
    P->inv = e_inverse;
    P->fwd = e_forward;

    return P;
}
