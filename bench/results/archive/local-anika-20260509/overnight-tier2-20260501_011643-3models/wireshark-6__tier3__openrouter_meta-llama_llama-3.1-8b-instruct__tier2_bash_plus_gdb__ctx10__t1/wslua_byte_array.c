    if (idx == 0 && ! g_str_equal(luaL_optstring(L,2,""),"0") ) {
        luaL_argerror(L,2,"bad index");
        return 0;
    }

    if (idx < 0 || (guint)idx >= ba->len) {
        luaL_argerror(L,2,"index out of range");
        return 0;
    }
    lua_pushnumber(L,ba->data[idx]);

    WSLUA_RETURN(1); /* The value [0-255] of the byte. */
}

WSLUA_METHOD ByteArray_len(lua_State* L) {
    /* Obtain the length of a <<lua_class_ByteArray,`ByteArray`>>. */
    ByteArray ba = checkByteArray(L,1);

    lua_pushnumber(L,(lua_Number)ba->len);

    WSLUA_RETURN(1); /* The length of the <<lua_class_ByteArray,`ByteArray`>>. */
}

WSLUA_METHOD ByteArray_subset(lua_State* L) {
    /* Obtain a segment of a <<lua_class_ByteArray,`ByteArray`>>, as a new <<lua_class_ByteArray,`ByteArray`>>. */
#define WSLUA_ARG_ByteArray_set_index_OFFSET 2 /* The position of the first byte (0=first). */
#define WSLUA_ARG_ByteArray_set_index_LENGTH 3 /* The length of the segment. */
    ByteArray ba = checkByteArray(L,1);
    int offset = (int)luaL_checkinteger(L,WSLUA_ARG_ByteArray_set_index_OFFSET);
    int len = (int)luaL_checkinteger(L,WSLUA_ARG_ByteArray_set_index_LENGTH);
    ByteArray sub;

    if ((offset + len) > (int)ba->len || offset < 0 || len < 1) {
        luaL_error(L,"Out Of Bounds");
        return 0;
    }

    sub = g_byte_array_new();
    g_byte_array_append(sub,ba->data + offset,len);

    pushByteArray(L,sub);

    WSLUA_RETURN(1); /* A <<lua_class_ByteArray,`ByteArray`>> containing the requested segment. */
}

WSLUA_METHOD ByteArray_base64_decode(lua_State* L) {
    /* Obtain a Base64 decoded <<lua_class_ByteArray,`ByteArray`>>.

       @since 1.11.3
     */
    ByteArray ba = checkByteArray(L,1);
    ByteArray ba2;
    gchar *data;

    gsize len;

    ba2 = g_byte_array_new();
    if (ba->len > 1) {
        data = (gchar*)g_malloc(ba->len + 1);
        memcpy(data, ba->data, ba->len);
        data[ba->len] = '\0';

        g_base64_decode_inplace(data, &len);
        g_byte_array_append(ba2, data, (int)len);
        g_free(data);
    }

    pushByteArray(L,ba2);
    WSLUA_RETURN(1); /* The created <<lua_class_ByteArray,`ByteArray`>>. */
}

WSLUA_METHOD ByteArray_raw(lua_State* L) {
    /* Obtain a Lua string of the binary bytes in a <<lua_class_ByteArray,`ByteArray`>>.

       @since 1.11.3
     */
#define WSLUA_OPTARG_ByteArray_raw_OFFSET 2 /* The position of the first byte (default=0/first). */
#define WSLUA_OPTARG_ByteArray_raw_LENGTH 3 /* The length of the segment to get (default=all). */
    ByteArray ba = checkByteArray(L,1);
    guint offset = (guint) luaL_optinteger(L,WSLUA_OPTARG_ByteArray_raw_OFFSET,0);
    int len;

    if (!ba) return 0;
    if (offset > ba->len) {
        WSLUA_OPTARG_ERROR(ByteArray_raw,OFFSET,"offset beyond end of byte array");
        return 0;
    }

    len = (int) luaL_optinteger(L,WSLUA_OPTARG_ByteArray_raw_LENGTH, ba->len - offset);
    if ((len < 0) || ((guint)len > (ba->len - offset)))
        len = ba->len - offset;

    lua_pushlstring(L, &(ba->data[offset]), len);

    WSLUA_RETURN(1); /* A Lua string of the binary bytes in the ByteArray. */
}

WSLUA_METHOD ByteArray_tohex(lua_State* L) {
    /* Obtain a Lua string of the bytes in a <<lua_class_ByteArray,`ByteArray`>> as hex-ascii, with given separator

       @since 1.11.3
