    field_info *fi       = NULL;

    // Raw name
    ek_write_name(pnode, "_raw", pdata);

    if (g_slist_length(attr_instances) > 1) {
        json_dumper_begin_array(pdata->dumper);
    }

    // Raw value(s)
    while (current_node != NULL) {
        pnode = (proto_node *) current_node->data;
        fi    = PNODE_FINFO(pnode);

        ek_write_hex(fi, pdata);

        current_node = current_node->next;
    }

    if (g_slist_length(attr_instances) > 1) {
        json_dumper_end_array(pdata->dumper);
    }
}

static void
ek_write_attr(GSList *attr_instances, write_json_data *pdata)
{
    GSList *current_node = attr_instances;
    proto_node *pnode    = (proto_node *) current_node->data;
    field_info *fi       = PNODE_FINFO(pnode);

    // Hex dump -x
    if (pdata->print_hex && fi && fi->length > 0 && fi->hfinfo->id != hf_text_only) {
        ek_write_attr_hex(attr_instances, pdata);
    }

    // Print attr name
    ek_write_name(pnode, NULL, pdata);

    if (g_slist_length(attr_instances) > 1) {
        json_dumper_begin_array(pdata->dumper);
    }

    while (current_node != NULL) {
        pnode = (proto_node *) current_node->data;
        fi    = PNODE_FINFO(pnode);

        /* Field */
        if (fi->hfinfo->type != FT_PROTOCOL) {
            if (pdata->filter != NULL
                && !ek_check_protocolfilter(pdata->filter, fi->hfinfo->abbrev)) {

                /* print dummy field */
                json_dumper_set_member_name(pdata->dumper, "filtered");
                json_dumper_value_string(pdata->dumper, fi->hfinfo->abbrev);
            } else {
                ek_write_field_value(fi, pdata);
            }
        } else {
            /* Object */
            json_dumper_begin_object(pdata->dumper);

            if (pdata->filter != NULL) {
                if (ek_check_protocolfilter(pdata->filter, fi->hfinfo->abbrev)) {
                    gchar **_filter = NULL;
                    /* Remove protocol filter for children, if children should be included */
                    if ((pdata->filter_flags&PF_INCLUDE_CHILDREN) == PF_INCLUDE_CHILDREN) {
                        _filter = pdata->filter;
                        pdata->filter = NULL;
                    }

                    proto_tree_write_node_ek(pnode, pdata);

                    /* Put protocol filter back */
                    if ((pdata->filter_flags&PF_INCLUDE_CHILDREN) == PF_INCLUDE_CHILDREN) {
                        pdata->filter = _filter;
                    }
                } else {
                    /* print dummy field */
                    json_dumper_set_member_name(pdata->dumper, "filtered");
                    json_dumper_value_string(pdata->dumper, fi->hfinfo->abbrev);
                }
            } else {
                proto_tree_write_node_ek(pnode, pdata);
            }

            json_dumper_end_object(pdata->dumper);
        }

        current_node = current_node->next;
    }

    if (g_slist_length(attr_instances) > 1) {
        json_dumper_end_array(pdata->dumper);
    }
}

/* Write out a tree's data, and any child nodes, as JSON for EK */
static void
proto_tree_write_node_ek(proto_node *node, write_json_data *pdata)
{
