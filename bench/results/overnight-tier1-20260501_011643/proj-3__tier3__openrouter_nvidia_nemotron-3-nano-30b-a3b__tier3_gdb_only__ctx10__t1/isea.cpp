    quad = isea_ptdd(tri, &v);
    quad = isea_dddi(g, quad, &v, di);
    return quad;
}

/* q2di to seqnum */

static long isea_disn(struct isea_dgg *g, int quad, struct isea_pt *di) {
    long             sidelength;
    long             sn, height;
    long             hexes;

    if (quad == 0) {
        g->serial = 1;
        return g->serial;
    }
    /* hexes in a quad */
    hexes = lround(pow(static_cast<double>(g->aperture), static_cast<double>(g->resolution)));
    if (quad == 11) {
        g->serial = 1 + 10 * hexes + 1;
        return g->serial;
    }
    if (g->aperture == 3 && g->resolution % 2 == 1) {
        height = lround(floor((pow(g->aperture, (g->resolution - 1) / 2.0))));
        sn = ((long)di->x) * height;
        sn += ((long)di->y) / height;
        sn += (quad - 1) * hexes;
        sn += 2;
    } else {
        sidelength = lround((pow(g->aperture, g->resolution / 2.0)));
        sn = lround(floor(((quad - 1) * hexes + sidelength * di->x + di->y + 2)));
    }

    g->serial = sn;
    return sn;
}

/* TODO just encode the quad in the d or i coordinate
 * quad is 0-11, which can be four bits.
 * d' = d << 4 + q, d = d' >> 4, q = d' & 0xf
 */
/* convert a q2di to global hex coord */
static int isea_hex(struct isea_dgg *g, int tri,
                    struct isea_pt *pt, struct isea_pt *hex) {
    struct isea_pt v;
#ifdef FIXME
    long sidelength;
    long d, i, x, y;
#endif
    int quad;

    quad = isea_ptdi(g, tri, pt, &v);

    hex->x = ((int)v.x << 4) + quad;
    hex->y = v.y;

    return 1;
#ifdef FIXME
    d = lround(floor(v.x));
    i = lround(floor(v.y));

    /* Aperture 3 odd resolutions */
    if (g->aperture == 3 && g->resolution % 2 != 0) {
        long offset = lround((pow(3.0, g->resolution - 1) + 0.5));

        d += offset * ((g->quad-1) % 5);
        i += offset * ((g->quad-1) % 5);

        if (quad == 0) {
            d = 0;
            i = offset;
        } else if (quad == 11) {
            d = 2 * offset;
            i = 0;
        } else if (quad > 5) {
            d += offset;
        }

        x = (2*d - i) /3;
        y = (2*i - d) /3;

        hex->x = x + offset / 3;
        hex->y = y + 2 * offset / 3;
        return 1;
    }

    /* aperture 3 even resolutions and aperture 4 */
    sidelength = lround((pow(g->aperture, g->resolution / 2.0)));
    if (g->quad == 0) {
        hex->x = 0;
        hex->y = sidelength;
    } else if (g->quad == 11) {
        hex->x = sidelength * 2;
        hex->y = 0;
    } else {
        hex->x = d + sidelength * ((g->quad-1) % 5);
        if (g->quad > 5) hex->x += sidelength;
        hex->y = i + sidelength * ((g->quad-1) % 5);
    }

    return 1;
