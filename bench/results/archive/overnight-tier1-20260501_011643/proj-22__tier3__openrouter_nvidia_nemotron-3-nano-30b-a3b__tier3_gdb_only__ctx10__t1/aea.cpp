                if ((lp.phi = phi1_(lp.phi, P->e, P->one_es)) == HUGE_VAL) {
                    proj_errno_set(P, PJD_ERR_TOLERANCE_CONDITION);
                    return lp;
                }
            } else
                lp.phi = lp.phi < 0. ? -M_HALFPI : M_HALFPI;
        } else if (fabs(lp.phi = (Q->c - lp.phi * lp.phi) / Q->n2) <= 1.)
            lp.phi = asin(lp.phi);
        else
            lp.phi = lp.phi < 0. ? -M_HALFPI : M_HALFPI;
        lp.lam = atan2(xy.x, xy.y) / Q->n;
    } else {
        lp.lam = 0.;
        lp.phi = Q->n > 0. ? M_HALFPI : - M_HALFPI;
    }
    return lp;
}



static PJ *setup(PJ *P) {
    double cosphi, sinphi;
    int secant;
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(P->opaque);

    P->inv = e_inverse;
    P->fwd = e_forward;

    if (fabs(Q->phi1) > M_HALFPI || fabs(Q->phi2) > M_HALFPI)
        return destructor(P, PJD_ERR_LAT_LARGER_THAN_90);
    if (fabs(Q->phi1 + Q->phi2) < EPS10)
        return destructor(P, PJD_ERR_CONIC_LAT_EQUAL);
    Q->n = sinphi = sin(Q->phi1);
    cosphi = cos(Q->phi1);
    secant = fabs(Q->phi1 - Q->phi2) >= EPS10;
    if( (Q->ellips = (P->es > 0.))) {
        double ml1, m1;

        if (!(Q->en = pj_enfn(P->es)))
            return destructor(P, 0);
        m1 = pj_msfn(sinphi, cosphi, P->es);
        ml1 = pj_qsfn(sinphi, P->e, P->one_es);
        if (secant) { /* secant cone */
            double ml2, m2;

            sinphi = sin(Q->phi2);
            cosphi = cos(Q->phi2);
            m2 = pj_msfn(sinphi, cosphi, P->es);
            ml2 = pj_qsfn(sinphi, P->e, P->one_es);
            if (ml2 == ml1)
                return destructor(P, 0);

            Q->n = (m1 * m1 - m2 * m2) / (ml2 - ml1);
        }
        Q->ec = 1. - .5 * P->one_es * log((1. - P->e) /
            (1. + P->e)) / P->e;
        Q->c = m1 * m1 + Q->n * ml1;
        Q->dd = 1. / Q->n;
        Q->rho0 = Q->dd * sqrt(Q->c - Q->n * pj_qsfn(sin(P->phi0),
            P->e, P->one_es));
    } else {
        if (secant) Q->n = .5 * (Q->n + sin(Q->phi2));
        Q->n2 = Q->n + Q->n;
        Q->c = cosphi * cosphi + Q->n2 * sinphi;
        Q->dd = 1. / Q->n;
        Q->rho0 = Q->dd * sqrt(Q->c - Q->n2 * sin(P->phi0));
    }

    return P;
}


PJ *PROJECTION(aea) {
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(pj_calloc (1, sizeof (struct pj_opaque)));
    if (nullptr==Q)
        return pj_default_destructor (P, ENOMEM);
    P->opaque = Q;
    P->destructor = destructor;

    Q->phi1 = pj_param(P->ctx, P->params, "rlat_1").f;
    Q->phi2 = pj_param(P->ctx, P->params, "rlat_2").f;
    return setup(P);
}


PJ *PROJECTION(leac) {
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(pj_calloc (1, sizeof (struct pj_opaque)));
    if (nullptr==Q)
        return pj_default_destructor (P, ENOMEM);
    P->opaque = Q;
    P->destructor = destructor;

    Q->phi2 = pj_param(P->ctx, P->params, "rlat_1").f;
    Q->phi1 = pj_param(P->ctx, P->params, "bsouth").i ? - M_HALFPI: M_HALFPI;
    return setup(P);
}

