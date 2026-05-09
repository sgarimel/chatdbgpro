        return;

    for (num = 0; num < length; num++)
        if ((text[num] == '\r') || (text[num] == '\n'))
            text[num] = ' ';
}

DltReturnValue dlt_filter_init(DltFilter *filter, int verbose)
{
    PRINT_FUNCTION_VERBOSE(verbose);

    if (filter == NULL)
        return DLT_RETURN_WRONG_PARAMETER;

    filter->counter = 0;

    return DLT_RETURN_OK;
}

DltReturnValue dlt_filter_free(DltFilter *filter, int verbose)
{
    PRINT_FUNCTION_VERBOSE(verbose);

    if (filter == NULL)
        return DLT_RETURN_WRONG_PARAMETER;

    return DLT_RETURN_OK;
}

DltReturnValue dlt_filter_load(DltFilter *filter, const char *filename, int verbose)
{
    if ((filter == NULL) || (filename == NULL))
        return DLT_RETURN_WRONG_PARAMETER;

    FILE *handle;
    char str1[DLT_COMMON_BUFFER_LENGTH];
    char apid[DLT_ID_SIZE], ctid[DLT_ID_SIZE];

    PRINT_FUNCTION_VERBOSE(verbose);

    handle = fopen(filename, "r");

    if (handle == NULL) {
        dlt_vlog(LOG_WARNING, "Filter file %s cannot be opened!\n", filename);
        return DLT_RETURN_ERROR;
    }

    /* Reset filters */
    filter->counter = 0;

    while (!feof(handle)) {
        str1[0] = 0;

        if (fscanf(handle, "%s", str1) != 1)
            break;

        if (str1[0] == 0)
            break;

        printf(" %s", str1);

        if (strcmp(str1, "----") == 0)
            dlt_set_id(apid, "");
        else
            dlt_set_id(apid, str1);

        str1[0] = 0;

        if (fscanf(handle, "%254s", str1) != 1)
            break;

        if (str1[0] == 0)
            break;

        printf(" %s\r\n", str1);

        if (strcmp(str1, "----") == 0)
            dlt_set_id(ctid, "");
        else
            dlt_set_id(ctid, str1);

        if (filter->counter < DLT_FILTER_MAX) {
            dlt_filter_add(filter, apid, ctid, verbose);
        }
        else {
            dlt_vlog(LOG_WARNING,
                     "Maximum number (%d) of allowed filters reached, ignoring rest of filters!\n",
                     DLT_FILTER_MAX);
        }
    }

    fclose(handle);

    return DLT_RETURN_OK;
}

DltReturnValue dlt_filter_save(DltFilter *filter, const char *filename, int verbose)
{
    if ((filter == NULL) || (filename == NULL))
        return DLT_RETURN_WRONG_PARAMETER;

