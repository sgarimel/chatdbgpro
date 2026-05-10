    double x2, y2, V1, V2, V3, V4, t = 0.0, t2, ps, pe, tpe, s;
    double I7, I8, I9, I10, I11, d, Re;
    int i;

    x2 = xy.x * xy.x;
    y2 = xy.y * xy.y;
    V1 = 3. * xy.x * y2 - xy.x * x2;
    V2 = xy.y * y2 - 3. * x2 * xy.y;
    V3 = xy.x * (5. * y2 * y2 + x2 * (-10. * y2 + x2 ));
    V4 = xy.y * (5. * x2 * x2 + y2 * (-10. * x2 + y2 ));
    xy.x += - Q->Ca * V1 - Q->Cb * V2 + Q->Cc * V3 + Q->Cd * V4;
    xy.y +=   Q->Cb * V1 - Q->Ca * V2 - Q->Cd * V3 + Q->Cc * V4;
    ps = Q->p0s + xy.y / Q->kRg;
    pe = ps + P->phi0 - Q->p0s;

    for ( i = 20; i; --i) {
        V1 = Q->A * log(tan(M_FORTPI + .5 * pe));
        tpe = P->e * sin(pe);
        V2 = .5 * P->e * Q->A * log((1. + tpe)/(1. - tpe));
        t = ps - 2. * (atan(exp(V1 - V2 + Q->C)) - M_FORTPI);
        pe += t;
        if (fabs(t) < EPS)
            break;
    }

    t = P->e * sin(pe);
    t = 1. - t * t;
    Re = P->one_es / ( t * sqrt(t) );
    t = tan(ps);
    t2 = t * t;
    s = Q->kRg * Q->kRg;
    d = Re * P->k0 * Q->kRg;
    I7 = t / (2. * d);
    I8 = t * (5. + 3. * t2) / (24. * d * s);
    d = cos(ps) * Q->kRg * Q->A;
    I9 = 1. / d;
    d *= s;
    I10 = (1. + 2. * t2) / (6. * d);
    I11 = (5. + t2 * (28. + 24. * t2)) / (120. * d * s);
    x2 = xy.x * xy.x;
    lp.phi = pe + x2 * (-I7 + I8 * x2);
    lp.lam = xy.x * (I9 + x2 * (-I10 + x2 * I11));
    return lp;
}


PJ *PROJECTION(labrd) {
    double Az, sinp, R, N, t;
    struct pj_opaque *Q = static_cast<struct pj_opaque*>(pj_calloc (1, sizeof (struct pj_opaque)));
    if (nullptr==Q)
        return pj_default_destructor (P, ENOMEM);
    P->opaque = Q;


    Az = pj_param(P->ctx, P->params, "razi").f;
    sinp = sin(P->phi0);
    t = 1. - P->es * sinp * sinp;
    N = 1. / sqrt(t);
    R = P->one_es * N / t;
    Q->kRg = P->k0 * sqrt( N * R );
    Q->p0s = atan( sqrt(R / N) * tan(P->phi0) );
    Q->A = sinp / sin(Q->p0s);
    t = P->e * sinp;
    Q->C = .5 * P->e * Q->A * log((1. + t)/(1. - t)) +
          - Q->A * log( tan(M_FORTPI + .5 * P->phi0))
          + log( tan(M_FORTPI + .5 * Q->p0s));
    t = Az + Az;
    Q->Ca = (1. - cos(t)) * ( Q->Cb = 1. / (12. * Q->kRg * Q->kRg) );
    Q->Cb *= sin(t);
    Q->Cc = 3. * (Q->Ca * Q->Ca - Q->Cb * Q->Cb);
    Q->Cd = 6. * Q->Ca * Q->Cb;

    P->inv = e_inverse;
    P->fwd = e_forward;

    return P;
}
