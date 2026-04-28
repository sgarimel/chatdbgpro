			ext = ".css";
		} else if (!wget_strcasecmp_ascii(resp->content_type, "application/atom+xml")) {
			ext = ".atom";
		} else if (!wget_strcasecmp_ascii(resp->content_type, "application/rss+xml")) {
			ext = ".rss";
		} else
			ext = NULL;

		if (ext) {
			size_t ext_length = strlen(ext);

			if (fname_length >= ext_length && wget_strcasecmp_ascii(fname + fname_length - ext_length, ext)) {
				alloced_fname = wget_malloc(fname_length + ext_length + 1);
				memcpy(alloced_fname, fname, fname_length);
				memcpy(alloced_fname + fname_length, ext, ext_length + 1);
				fname = alloced_fname;
			}
		}
	}

	if (! ignore_patterns) {
		if ((config.accept_patterns && !in_pattern_list(config.accept_patterns, fname))
				|| (config.accept_regex && !regex_match(fname, config.accept_regex)))
		{
			debug_printf("not saved '%s' (doesn't match accept pattern)\n", fname);
			xfree(alloced_fname);
			return -2;
		}

		if ((config.reject_patterns && in_pattern_list(config.reject_patterns, fname))
				|| (config.reject_regex && regex_match(fname, config.reject_regex)))
		{
			debug_printf("not saved '%s' (matches reject pattern)\n", fname);
			xfree(alloced_fname);
			return -2;
		}

		if (config.exclude_directories && in_directory_pattern_list(config.exclude_directories, path)) {
			debug_printf("not saved '%s' (directory excluded)\n", path);
			xfree(alloced_fname);
			return -2;
		}
	}

	wget_thread_mutex_lock(savefile_mutex);

	fname_length += 16;

	if (config.timestamping) {
		if (oflag == O_TRUNC)
			flag = O_TRUNC;
	} else if (!config.clobber || (config.recursive && config.directories)) {
		// debug_printf("oflag=%02x recursive %d directories %d page_requsites %d clobber %d\n",oflag,config.recursive,config.directories,config.page_requisites,config.clobber);
		if (oflag == O_TRUNC && (!(config.recursive && config.directories) || (config.page_requisites && !config.clobber))) {
			flag = O_EXCL;
		}
	} else if (flag != O_APPEND) {
		// wget compatibility: "clobber" means generating of .x files
		multiple = 1;
		flag = O_EXCL;

		if (config.backups) {
			char src[fname_length + 1], dst[fname_length + 1];

			for (int it = config.backups; it > 0; it--) {
				if (it > 1)
					wget_snprintf(src, sizeof(src), "%s.%d", fname, it - 1);
				else
					wget_strscpy(src, fname, sizeof(src));
				wget_snprintf(dst, sizeof(dst), "%s.%d", fname, it);

				if (rename(src, dst) == -1 && errno != ENOENT)
					error_printf(_("Failed to rename %s to %s (errno=%d)\n"), src, dst, errno);
			}
		}
	}

	// create the complete directory path
	mkdir_path((char *) fname, true);

	char unique[fname_length + 1];
	*unique = 0;

	// Load partial content
	if (partial_content) {
		long long size = get_file_size(unique[0] ? unique : fname);
		if (size > 0) {
			fd = open_unique(fname, O_RDONLY | O_BINARY, 0, multiple, unique, sizeof(unique));
			if (fd >= 0) {
				size_t rc;
				if ((unsigned long long) size > max_partial_content)
					size = max_partial_content;
				wget_buffer_memset_append(partial_content, 0, size);
				rc = safe_read(fd, partial_content->data, size);
				if (rc == SAFE_READ_ERROR || (long long) rc != size) {
					error_printf(_("Failed to load partial content from '%s' (errno=%d): %s\n"),
						fname, errno, strerror(errno));
					set_exit_status(EXIT_STATUS_IO);
				}
				close(fd);
			} else {
