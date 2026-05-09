        }
      *number = tmp_long;
    }
}

/* Set parameters related to formatting. */

static void
init_parameters (int number_of_files)
{
  int chars_used_by_number = 0;

  lines_per_body = lines_per_page - lines_per_header - lines_per_footer;
  if (lines_per_body <= 0)
    {
      extremities = false;
      keep_FF = true;
    }
  if (extremities == false)
    lines_per_body = lines_per_page;

  if (double_space)
    lines_per_body = lines_per_body / 2;

  /* If input is stdin, cannot print parallel files.  BSD dumps core
     on this. */
  if (number_of_files == 0)
    parallel_files = false;

  if (parallel_files)
    columns = number_of_files;

  /* One file, multi columns down: -b option is set to get a consistent
     formulation with "FF set by hand" in input files. */
  if (storing_columns)
    balance_columns = true;

  /* Tabification is assumed for multiple columns. */
  if (columns > 1)
    {
      if (!use_col_separator)
        {
          /* Use default separator */
          if (join_lines)
            col_sep_string = line_separator;
          else
            col_sep_string = column_separator;

          col_sep_length = 1;
          use_col_separator = true;
        }
      /* It's rather pointless to define a TAB separator with column
         alignment */
      else if (!join_lines && *col_sep_string == '\t')
        col_sep_string = column_separator;

      truncate_lines = true;
      tabify_output = true;
    }
  else
    storing_columns = false;

  /* -J dominates -w in any case */
  if (join_lines)
    truncate_lines = false;

  if (numbered_lines)
    {
      int chars_per_default_tab = 8;

      line_count = start_line_num;

      /* To allow input tab-expansion (-e sensitive) use:
         if (number_separator == input_tab_char)
           number_width = chars_per_number
             + TAB_WIDTH (chars_per_input_tab, chars_per_number);   */

      /* Estimate chars_per_text without any margin and keep it constant. */
      if (number_separator == '\t')
        number_width = (chars_per_number
                        + TAB_WIDTH (chars_per_default_tab, chars_per_number));
      else
        number_width = chars_per_number + 1;

      /* The number is part of the column width unless we are
         printing files in parallel. */
      if (parallel_files)
        chars_used_by_number = number_width;
    }

  int sep_chars, useful_chars;
  if (INT_MULTIPLY_WRAPV (columns - 1, col_sep_length, &sep_chars))
    sep_chars = INT_MAX;
  if (INT_SUBTRACT_WRAPV (chars_per_line - chars_used_by_number, sep_chars,
                          &useful_chars))
    useful_chars = 0;
  chars_per_column = useful_chars / columns;

  if (chars_per_column < 1)
    die (EXIT_FAILURE, 0, _("page width too narrow"));

