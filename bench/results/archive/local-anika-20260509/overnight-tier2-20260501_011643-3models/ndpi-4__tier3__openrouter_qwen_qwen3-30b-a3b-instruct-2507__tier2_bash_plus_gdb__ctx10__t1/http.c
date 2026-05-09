static void rtsp_parse_packet_acceptline(struct ndpi_detection_module_struct
					 *ndpi_struct, struct ndpi_flow_struct *flow)
{
  struct ndpi_packet_struct *packet = &ndpi_struct->packet;

  if((packet->accept_line.len >= 28)
     && (memcmp(packet->accept_line.ptr, "application/x-rtsp-tunnelled", 28) == 0)) {
    NDPI_LOG_INFO(ndpi_struct, "found RTSP accept line\n");
    ndpi_int_http_add_connection(ndpi_struct, flow, NDPI_PROTOCOL_RTSP, NDPI_PROTOCOL_CATEGORY_MEDIA);
  }
}

/* ************************************************************* */

static void setHttpUserAgent(struct ndpi_detection_module_struct *ndpi_struct,
			     struct ndpi_flow_struct *flow, char *ua) {
  if(    !strcmp(ua, "Windows NT 5.0"))  ua = "Windows 2000";
  else if(!strcmp(ua, "Windows NT 5.1"))  ua = "Windows XP";
  else if(!strcmp(ua, "Windows NT 5.2"))  ua = "Windows Server 2003";
  else if(!strcmp(ua, "Windows NT 6.0"))  ua = "Windows Vista";
  else if(!strcmp(ua, "Windows NT 6.1"))  ua = "Windows 7";
  else if(!strcmp(ua, "Windows NT 6.2"))  ua = "Windows 8";
  else if(!strcmp(ua, "Windows NT 6.3"))  ua = "Windows 8.1";
  else if(!strcmp(ua, "Windows NT 10.0")) ua = "Windows 10";

  /* Good reference for future implementations:
   * https://github.com/ua-parser/uap-core/blob/master/regexes.yaml */

  if(flow->http.detected_os == NULL)
    flow->http.detected_os = ndpi_strdup(ua);
}

/* ************************************************************* */

static void ndpi_http_parse_subprotocol(struct ndpi_detection_module_struct *ndpi_struct,
				 struct ndpi_flow_struct *flow) {
  if((flow->l4.tcp.http_stage == 0) || (flow->http.url && flow->http_detected)) {
    char *double_col = strchr((char*)flow->host_server_name, ':');

    if(double_col) double_col[0] = '\0';

    if(ndpi_match_hostname_protocol(ndpi_struct, flow,
				    flow->detected_protocol_stack[1],
				    flow->host_server_name,
				    strlen(flow->host_server_name)) == 0) {
      if(flow->http.url &&
         ((strstr(flow->http.url, ":8080/downloading?n=0.") != NULL)
          || (strstr(flow->http.url, ":8080/upload?n=0.") != NULL))) {
	/* This looks like Ookla speedtest */
	ndpi_set_detected_protocol(ndpi_struct, flow, NDPI_PROTOCOL_OOKLA, NDPI_PROTOCOL_HTTP, NDPI_CONFIDENCE_DPI);
      }
    }

  }
}

/* ************************************************************* */

static void ndpi_check_user_agent(struct ndpi_detection_module_struct *ndpi_struct,
				  struct ndpi_flow_struct *flow,
				  char const *ua, size_t ua_len) {
  char *double_slash;
  
  if((!ua) || (ua[0] == '\0'))
    return;

  if (ua_len > 12)
  {
    size_t i, upper_case_count = 0;

    for (i = 0; i < ua_len; ++i)
    {
      /*
       * We assume at least one non alpha char.
       * e.g. ' ', '-' or ';' ...
       */
      if (isalpha(ua[i]) == 0)
      {
        break;
      }
      if (isupper(ua[i]) != 0)
      {
        upper_case_count++;
      }
    }

    if (i == ua_len)
    {
      float upper_case_ratio = (float)upper_case_count / (float)ua_len;
      if (upper_case_ratio >= 0.2f)
      {
        ndpi_set_risk(ndpi_struct, flow, NDPI_HTTP_SUSPICIOUS_USER_AGENT);
      }
    }
  }

  if((!strncmp(ua, "<?", 2))
     || strchr(ua, '$')
     )
    ndpi_set_risk(ndpi_struct, flow, NDPI_HTTP_SUSPICIOUS_USER_AGENT);

