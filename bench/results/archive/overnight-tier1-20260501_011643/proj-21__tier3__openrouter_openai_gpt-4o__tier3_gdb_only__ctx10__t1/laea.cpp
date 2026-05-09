    lp.phi = 2. * asin(lp.phi);
    if (Q->mode == OBLIQ || Q->mode == EQUIT) {
        sinz = sin(lp.phi);
        cosz = cos(lp.phi);
    }
    switch (Q->mode) {
    case EQUIT:
        lp.phi = fabs(rh) <= EPS10 ? 0. : asin(xy.y * sinz / rh);
        xy.x *= sinz;
        xy.y = cosz * rh;
        break;
    case OBLIQ:
        lp.phi = fabs(rh) <= EPS10 ? P->phi0 :
           asin(cosz * Q->sinb1 + xy.y * sinz * Q->cosb1 / rh);
        xy.x *= sinz * Q->cosb1;
        xy.y = (cosz - sin(lp.phi) * Q->sinb1) * rh;
        break;
    case N_POLE:
        xy.y = -xy.y;
        lp.phi = M_HALFPI - lp.phi;
        break;
    case S_POLE:
        lp.phi -= M_HALFPI;
        break;
    }
    lp.lam = (xy.y == 0. && (Q->mode == EQUIT || Q->mode == OBLIQ)) ?
        0. : atan2(xy.x, xy.y);
    return (lp);
}


static PJ *destructor (PJ *P, int errlev) {
    if (nullptr==P)
        return nullptr;

    if (nullptr==P->opaque)
        return pj_default_destructor (P, errlev);

    pj_dealloc (static_cast<struct pj_opaque*>(P->opaque)->apa);

    return pj_default_destructor(P, errlev);
}


PJ *PROJECTION(laea) {
    double t;
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(pj_calloc (1, sizeof (struct pj_opaque)));
    if (nullptr==Q)
        return pj_default_destructor (P, ENOMEM);
    P->opaque = Q;
    P->destructor = destructor;

    t = fabs(P->phi0);
    if (fabs(t - M_HALFPI) < EPS10)
        Q->mode = P->phi0 < 0. ? S_POLE : N_POLE;
    else if (fabs(t) < EPS10)
        Q->mode = EQUIT;
    else
        Q->mode = OBLIQ;
    if (P->es != 0.0) {
        double sinphi;

        P->e = sqrt(P->es);
        Q->qp = pj_qsfn(1., P->e, P->one_es);
        Q->mmf = .5 / (1. - P->es);
        Q->apa = pj_authset(P->es);
        if (nullptr==Q->apa)
            return destructor(P, ENOMEM);
        switch (Q->mode) {
        case N_POLE:
        case S_POLE:
            Q->dd = 1.;
            break;
        case EQUIT:
            Q->dd = 1. / (Q->rq = sqrt(.5 * Q->qp));
            Q->xmf = 1.;
            Q->ymf = .5 * Q->qp;
            break;
        case OBLIQ:
            Q->rq = sqrt(.5 * Q->qp);
            sinphi = sin(P->phi0);
            Q->sinb1 = pj_qsfn(sinphi, P->e, P->one_es) / Q->qp;
            Q->cosb1 = sqrt(1. - Q->sinb1 * Q->sinb1);
            Q->dd = cos(P->phi0) / (sqrt(1. - P->es * sinphi * sinphi) *
               Q->rq * Q->cosb1);
            Q->ymf = (Q->xmf = Q->rq) / Q->dd;
            Q->xmf *= Q->dd;
            break;
        }
        P->inv = e_inverse;
        P->fwd = e_forward;
    } else {
        if (Q->mode == OBLIQ) {
            Q->sinb1 = sin(P->phi0);
            Q->cosb1 = cos(P->phi0);
        }
        P->inv = s_inverse;
        P->fwd = s_forward;
    }

    return P;
