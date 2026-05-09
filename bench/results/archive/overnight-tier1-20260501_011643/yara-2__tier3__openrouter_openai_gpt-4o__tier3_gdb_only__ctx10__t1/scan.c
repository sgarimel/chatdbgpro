  const uint8_t* s2 = string;

  size_t i = 0;

  if (data_size < string_length)
    return 0;

  while (i < string_length && yr_lowercase[*s1++] == yr_lowercase[*s2++])
    i++;

  return (int) ((i == string_length) ? i : 0);
}


static int _yr_scan_wcompare(
    const uint8_t* data,
    size_t data_size,
    uint8_t* string,
    size_t string_length)
{
  const uint8_t* s1 = data;
  const uint8_t* s2 = string;

  size_t i = 0;

  if (data_size < string_length * 2)
    return 0;

  while (i < string_length && *s1 == *s2 && *(s1 + 1) == 0x00)
  {
    s1+=2;
    s2++;
    i++;
  }

  return (int) ((i == string_length) ? i * 2 : 0);
}


static int _yr_scan_wicompare(
    const uint8_t* data,
    size_t data_size,
    uint8_t* string,
    size_t string_length)
{
  const uint8_t* s1 = data;
  const uint8_t* s2 = string;

  size_t i = 0;

  if (data_size < string_length * 2)
    return 0;

  while (i < string_length && yr_lowercase[*s1] == yr_lowercase[*s2])
  {
    s1+=2;
    s2++;
    i++;
  }

  return (int) ((i == string_length) ? i * 2 : 0);
}


static void _yr_scan_update_match_chain_length(
    int tidx,
    YR_STRING* string,
    YR_MATCH* match_to_update,
    int chain_length)
{
  YR_MATCH* match;

  if (match_to_update->chain_length == chain_length)
    return;

  match_to_update->chain_length = chain_length;

  if (string->chained_to == NULL)
    return;

  match = string->chained_to->unconfirmed_matches[tidx].head;

  while (match != NULL)
  {
    int64_t ending_offset = match->offset + match->match_length;

    if (ending_offset + string->chain_gap_max >= match_to_update->offset &&
        ending_offset + string->chain_gap_min <= match_to_update->offset)
    {
      _yr_scan_update_match_chain_length(
          tidx, string->chained_to, match, chain_length + 1);
    }

    match = match->next;
  }
}


static int _yr_scan_add_match_to_list(
    YR_MATCH* match,
    YR_MATCHES* matches_list,
