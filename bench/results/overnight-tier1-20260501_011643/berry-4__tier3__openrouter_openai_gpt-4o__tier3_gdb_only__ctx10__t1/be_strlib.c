{
    if (is_digit(*s)) {
        ++s;
    }
    if (is_digit(*s)) {
        ++s;
    }
    return s;
}

static const char* get_mode(const char *str, char *buf)
{
    const char *p = str;
    while (*p && strchr(FLAGES, *p)) { /* skip flags */
        ++p;
    }
    p = skip2dig(p); /* skip width (2 digits at most) */
    if (*p == '.') {
        p = skip2dig(++p); /* skip width (2 digits at most) */
    }
    *(buf++) = '%';
    strncpy(buf, str, p - str + 1);
    buf[p - str + 1] = '\0';
    return p;
}

static void mode_fixlen(char *mode, const char *lenmode)
{
    size_t l = strlen(mode), lm = strlen(lenmode);
    char spec = mode[l - 1];
    strcpy(mode + l - 1, lenmode);
    mode[l + lm - 1] = spec;
    mode[l + lm] = '\0';
}

static int str_format(bvm *vm)
{
    int top = be_top(vm);
    if (top > 0 && be_isstring(vm, 1)) {
        int index = 2;
        const char *format = be_tostring(vm, 1);
        pushstr(vm, "", 0);
        for (;;) {
            char mode[MAX_FORMAT_MODE];
            char buf[128];
            const char *p = strchr(format, '%');
            if (p == NULL) {
                break;
            }
            pushstr(vm, format, p - format);
            concat2(vm);
            p = get_mode(p + 1, mode);
            buf[0] = '\0';
            if (index > top) {
                be_raise(vm, "runtime_error", be_pushfstring(vm,
                    "bad argument #%d to 'format': no value", index));
            }
            switch (*p) {
            case 'd': case 'i': case 'o':
            case 'u': case 'x': case 'X':
                if (be_isint(vm, index)) {
                    mode_fixlen(mode, BE_INT_FMTLEN);
                    sprintf(buf, mode, be_toint(vm, index));
                }
                be_pushstring(vm, buf);
                break;
            case 'e': case 'E':
            case 'f': case 'g': case 'G':
                if (be_isnumber(vm, index)) {
                    sprintf(buf, mode, be_toreal(vm, index));
                }
                be_pushstring(vm, buf);
                break;
            case 'c':
                if (be_isint(vm, index)) {
                    sprintf(buf, "%c", (int)be_toint(vm, index));
                }
                be_pushstring(vm, buf);
                break;
            case 's': {
                const char *s = be_tostring(vm, index);
                int len = be_strlen(vm, 2);
                if (len > 100 && strlen(mode) == 2) {
                    be_pushvalue(vm, index);
                } else {
                    sprintf(buf, mode, s);
                    be_pushstring(vm, buf);
                }
                break;
            }
            default: /* error */
                be_raise(vm, "runtime_error", be_pushfstring(vm,
                    "invalid option '%%%c' to 'format'", *p));
                break;
            }
            concat2(vm);
            format = p + 1;
            ++index;
        }
        pushstr(vm, format, strlen(format));
        concat2(vm);
