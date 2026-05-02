 */

#include "ndpi_protocol_ids.h"

#define NDPI_CURRENT_PROTO NDPI_PROTOCOL_SYSLOG

#include "ndpi_api.h"

static void ndpi_int_syslog_add_connection(struct ndpi_detection_module_struct
					   *ndpi_struct, struct ndpi_flow_struct *flow)
{
  ndpi_set_detected_protocol(ndpi_struct, flow, NDPI_PROTOCOL_SYSLOG, NDPI_PROTOCOL_UNKNOWN, NDPI_CONFIDENCE_DPI);
}

void ndpi_search_syslog(struct ndpi_detection_module_struct
			*ndpi_struct, struct ndpi_flow_struct *flow)
{
  struct ndpi_packet_struct *packet = &ndpi_struct->packet;
  u_int16_t i;

  NDPI_LOG_DBG(ndpi_struct, "search syslog\n");

  if (packet->payload_packet_len > 20 && packet->payload[0] == '<') {
    NDPI_LOG_DBG2(ndpi_struct, "checked len>20 and <1024 and first symbol=<\n");

    for (i = 1; i <= 3; i++) {
      if (packet->payload[i] < '0' || packet->payload[i] > '9') {
		break;
      }
    }
    NDPI_LOG_DBG2(ndpi_struct,
             "read symbols while the symbol is a number.\n");

    if (packet->payload[i++] != '>') {
      NDPI_LOG_DBG(ndpi_struct, "excluded, there is no > following the number\n");
      NDPI_EXCLUDE_PROTO(ndpi_struct, flow);
      return;
    } else {
      NDPI_LOG_DBG2(ndpi_struct, "a > following the number\n");
    }

    if (packet->payload[i] == 0x20) {
      NDPI_LOG_DBG2(ndpi_struct, "a blank following the >: increment i\n");
      i++;
    } else {
      NDPI_LOG_DBG2(ndpi_struct, "no blank following the >: do nothing\n");
    }

    while (i < packet->payload_packet_len - 1)
    {
        if (ndpi_isalnum(packet->payload[i]) == 0)
        {
            if (packet->payload[i] == ' ' || packet->payload[i] == ':' ||
                packet->payload[i] == '=')
            {
                break;
            }
            NDPI_EXCLUDE_PROTO(ndpi_struct, flow);
            return;
        }

        i++;
    }

    if (packet->payload[i] == ':')
    {
        if (++i >= packet->payload_packet_len ||
            packet->payload[i] != ' ')
        {
            NDPI_EXCLUDE_PROTO(ndpi_struct, flow);
            return;
        }
    }

    NDPI_LOG_INFO(ndpi_struct, "found syslog\n");
    ndpi_int_syslog_add_connection(ndpi_struct, flow);
    return;
  }
  NDPI_EXCLUDE_PROTO(ndpi_struct, flow);
}


void init_syslog_dissector(struct ndpi_detection_module_struct *ndpi_struct, u_int32_t *id, NDPI_PROTOCOL_BITMASK *detection_bitmask)
{
  ndpi_set_bitmask_protocol_detection("Syslog", ndpi_struct, detection_bitmask, *id,
				      NDPI_PROTOCOL_SYSLOG,
				      ndpi_search_syslog,
				      NDPI_SELECTION_BITMASK_PROTOCOL_V4_V6_TCP_OR_UDP_WITH_PAYLOAD_WITHOUT_RETRANSMISSION,
				      SAVE_DETECTION_BITMASK_AS_UNKNOWN,
				      ADD_TO_DETECTION_BITMASK);

  *id += 1;
}
