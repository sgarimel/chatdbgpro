    }
    return lp;
}


PJ *PROJECTION(lcc) {
    double cosphi, sinphi;
    int secant;
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(pj_calloc(1, sizeof (struct pj_opaque)));

    if (nullptr == Q)
        return pj_default_destructor(P, ENOMEM);
    P->opaque = Q;

    Q->phi1 = pj_param(P->ctx, P->params, "rlat_1").f;
    if (pj_param(P->ctx, P->params, "tlat_2").i)
        Q->phi2 = pj_param(P->ctx, P->params, "rlat_2").f;
    else {
        Q->phi2 = Q->phi1;
        if (!pj_param(P->ctx, P->params, "tlat_0").i)
            P->phi0 = Q->phi1;
    }
    if (fabs(Q->phi1 + Q->phi2) < EPS10)
        return pj_default_destructor(P, PJD_ERR_CONIC_LAT_EQUAL);

    Q->n = sinphi = sin(Q->phi1);
    cosphi = cos(Q->phi1);
    secant = fabs(Q->phi1 - Q->phi2) >= EPS10;
    if (P->es != 0.) {
        double ml1, m1;

        m1 = pj_msfn(sinphi, cosphi, P->es);
        ml1 = pj_tsfn(Q->phi1, sinphi, P->e);
        if( ml1 == 0 ) {
            return pj_default_destructor(P, PJD_ERR_LAT_1_OR_2_ZERO_OR_90);
        }
        if (secant) { /* secant cone */
            sinphi = sin(Q->phi2);
            Q->n = log(m1 / pj_msfn(sinphi, cos(Q->phi2), P->es));
            if (Q->n == 0) {
                // Not quite, but es is very close to 1...
                return pj_default_destructor(P, PJD_ERR_INVALID_ECCENTRICITY);
            }
            const double ml2 = pj_tsfn(Q->phi2, sinphi, P->e);
            if( ml2 == 0 ) {
                return pj_default_destructor(P, PJD_ERR_LAT_1_OR_2_ZERO_OR_90);
            }
            Q->n /= log(ml1 / ml2);
        }
        Q->c = (Q->rho0 = m1 * pow(ml1, -Q->n) / Q->n);
        Q->rho0 *= (fabs(fabs(P->phi0) - M_HALFPI) < EPS10) ? 0. :
            pow(pj_tsfn(P->phi0, sin(P->phi0), P->e), Q->n);
    } else {
        if (secant)
            Q->n = log(cosphi / cos(Q->phi2)) /
               log(tan(M_FORTPI + .5 * Q->phi2) /
               tan(M_FORTPI + .5 * Q->phi1));
        Q->c = cosphi * pow(tan(M_FORTPI + .5 * Q->phi1), Q->n) / Q->n;
        Q->rho0 = (fabs(fabs(P->phi0) - M_HALFPI) < EPS10) ? 0. :
            Q->c * pow(tan(M_FORTPI + .5 * P->phi0), -Q->n);
    }

    P->inv = e_inverse;
    P->fwd = e_forward;

    return P;
}
