  } else
    ret.app_protocol = flow->detected_protocol_stack[0];

  /* Don't overwrite the category if already set */
  if((flow->category == NDPI_PROTOCOL_CATEGORY_UNSPECIFIED) && (ret.app_protocol != NDPI_PROTOCOL_UNKNOWN))
    ndpi_fill_protocol_category(ndpi_str, flow, &ret);
  else
    ret.category = flow->category;

  if((flow->num_processed_pkts == 1) && (ret.master_protocol == NDPI_PROTOCOL_UNKNOWN) &&
     (ret.app_protocol == NDPI_PROTOCOL_UNKNOWN) && flow->packet.tcp && (flow->packet.tcp->syn == 0) &&
     (flow->guessed_protocol_id == 0)) {
    u_int8_t protocol_was_guessed;

    /*
      This is a TCP flow
      - whose first packet is NOT a SYN
      - no protocol has been detected

      We don't see how future packets can match anything
      hence we giveup here
    */
    ret = ndpi_detection_giveup(ndpi_str, flow, 0, &protocol_was_guessed);
  }

  if((ret.master_protocol == NDPI_PROTOCOL_UNKNOWN) && (ret.app_protocol != NDPI_PROTOCOL_UNKNOWN) &&
     (flow->guessed_host_protocol_id != NDPI_PROTOCOL_UNKNOWN)) {
    ret.master_protocol = ret.app_protocol;
    ret.app_protocol = flow->guessed_host_protocol_id;
  }

  if((!flow->risk_checked) && (ret.master_protocol != NDPI_PROTOCOL_UNKNOWN)) {
    ndpi_default_ports_tree_node_t *found;
    u_int16_t *default_ports, sport, dport;

    if(flow->packet.udp)
      found = ndpi_get_guessed_protocol_id(ndpi_str, IPPROTO_UDP,
					   sport = ntohs(flow->packet.udp->source),
					   dport = ntohs(flow->packet.udp->dest)),
	default_ports = ndpi_str->proto_defaults[ret.master_protocol].udp_default_ports;
    else if(flow->packet.tcp)
      found = ndpi_get_guessed_protocol_id(ndpi_str, IPPROTO_TCP,
					   sport = ntohs(flow->packet.tcp->source),
					   dport = ntohs(flow->packet.tcp->dest)),
	default_ports = ndpi_str->proto_defaults[ret.master_protocol].tcp_default_ports;
    else
      found = NULL, default_ports = NULL;

    if(found
       && (found->proto->protoId != NDPI_PROTOCOL_UNKNOWN)
       && (found->proto->protoId != ret.master_protocol)) {
      // printf("******** %u / %u\n", found->proto->protoId, ret.master_protocol);

	NDPI_SET_BIT(flow->risk, NDPI_KNOWN_PROTOCOL_ON_NON_STANDARD_PORT);
    } else if(default_ports && (default_ports[0] != 0)) {
      u_int8_t found = 0, i;

      for(i=0; (i<MAX_DEFAULT_PORTS) && (default_ports[i] != 0); i++) {
	if((default_ports[i] == sport) || (default_ports[i] == dport)) {
	  found = 1;
	  break;
	}
      } /* for */

      if(!found) {
	// printf("******** Invalid default port\n");
	NDPI_SET_BIT(flow->risk, NDPI_KNOWN_PROTOCOL_ON_NON_STANDARD_PORT);
      }
    }

    flow->risk_checked = 1;
  }

  ndpi_reconcile_protocols(ndpi_str, flow, &ret);

 invalidate_ptr:
  /*
    Invalidate packet memory to avoid accessing the pointers below
    when the packet is no longer accessible
  */
  flow->packet.iph = NULL, flow->packet.tcp = NULL, flow->packet.udp = NULL, flow->packet.payload = NULL;
  ndpi_reset_packet_line_info(&flow->packet);

  return(ret);
}

/* ********************************************************************************* */

u_int32_t ndpi_bytestream_to_number(const u_int8_t *str, u_int16_t max_chars_to_read, u_int16_t *bytes_read) {
  u_int32_t val;
  val = 0;

  // cancel if eof, ' ' or line end chars are reached
  while (*str >= '0' && *str <= '9' && max_chars_to_read > 0) {
    val *= 10;
    val += *str - '0';
    str++;
    max_chars_to_read = max_chars_to_read - 1;
    *bytes_read = *bytes_read + 1;
  }

