    if (i==len)
        return 0;

    /* Store definition */
    P->def_spherification = pj_strdup(par->param);
    par->used = 1;

    switch (i) {

    /* R_A - a sphere with same area as ellipsoid */
    case 0:
        P->a *= 1. - P->es * (SIXTH + P->es * (RA4 + P->es * RA6));
        break;

    /* R_V - a sphere with same volume as ellipsoid */
    case 1:
        P->a *= 1. - P->es * (SIXTH + P->es * (RV4 + P->es * RV6));
        break;

    /* R_a - a sphere with R = the arithmetic mean of the ellipsoid */
    case 2:
        P->a = (P->a + P->b) / 2;
        break;

    /* R_g - a sphere with R = the geometric mean of the ellipsoid */
    case 3:
        P->a = sqrt (P->a * P->b);
        break;

    /* R_h - a sphere with R = the harmonic mean of the ellipsoid */
    case 4:
        if (P->a + P->b == 0)
            return proj_errno_set (P, PJD_ERR_TOLERANCE_CONDITION);
        P->a = (2*P->a * P->b) / (P->a + P->b);
        break;

    /* R_lat_a - a sphere with R = the arithmetic mean of the ellipsoid at given latitude */
    case 5:
    /* R_lat_g - a sphere with R = the geometric  mean of the ellipsoid at given latitude */
    case 6:
        v = pj_param_value (par);
        t = proj_dmstor (v, &endp);
        if (fabs (t) > M_HALFPI)
            return proj_errno_set (P, PJD_ERR_REF_RAD_LARGER_THAN_90);
        t = sin (t);
        t = 1 - P->es * t * t;
        if (i==5)   /* arithmetic */
            P->a *= (1. - P->es + t) / (2 * t * sqrt(t));
        else        /* geometric */
            P->a *= sqrt (1 - P->es) / t;
        break;
    }


    /* Clean up the ellipsoidal parameters to reflect the sphere */
    P->es = P->e = P->f = 0;
    P->rf = HUGE_VAL;
    P->b = P->a;
    pj_calc_ellipsoid_params (P, P->a, 0);

    return 0;
}


/* locate parameter in list */
static paralist *pj_get_param (paralist *list, const char *key) {
    size_t l = strlen(key);
	while (list && !(0==strncmp(list->param, key, l) && (0==list->param[l] || list->param[l] == '=') ) )
		list = list->next;
	return list;
}


static char *pj_param_value (paralist *list) {
    char *key, *value;
    if (nullptr==list)
        return nullptr;

    key = list->param;
    value = strchr (key, '=');

    /* a flag (i.e. a key without value) has its own name (key) as value */
    return value? value + 1: key;
}


static const PJ_ELLPS *pj_find_ellps (const char *name) {
    int i;
    const char *s;
    const PJ_ELLPS *ellps;

    if (nullptr==name)
        return nullptr;

    ellps = proj_list_ellps();

    /* Search through internal ellipsoid list for name */
    for (i = 0; (s = ellps[i].id) && strcmp(name, s) ; ++i);
    if (nullptr==s)
        return nullptr;
    return ellps + i;
