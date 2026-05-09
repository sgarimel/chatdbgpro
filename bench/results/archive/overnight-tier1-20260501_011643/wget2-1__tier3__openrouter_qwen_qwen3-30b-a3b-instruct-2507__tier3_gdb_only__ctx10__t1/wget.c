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
		if (oflag == O_TRUNC && (!(config.recursive && config.directories) || !config.clobber)) {
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
					error_printf(_("Failed to load partial content from '%s' (errno=%d)\n"),
						fname, errno);
					set_exit_status(EXIT_STATUS_IO);
				}
				close(fd);
			} else {
				error_printf(_("Failed to load partial content from '%s' (errno=%d)\n"),
					fname, errno);
				set_exit_status(EXIT_STATUS_IO);
			}
		}
	}

	if (config.unlink && flag == O_TRUNC) {
		if (unlink(fname) < 0 && errno != ENOENT) {
			error_printf(_("Failed to unlink '%s' (errno=%d)\n"), fname, errno);
			set_exit_status(EXIT_STATUS_IO);
			return -1;
		}
	}

	fd = open_unique(fname, O_WRONLY | flag | O_CREAT | O_NONBLOCK | O_BINARY, S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH,
		multiple, unique, sizeof(unique));
	// debug_printf("1 fd=%d flag=%02x (%02x %02x %02x) errno=%d %s\n",fd,flag,O_EXCL,O_TRUNC,O_APPEND,errno,fname);

	// Store the "actual" file name (with any extensions that were added present)
	wget_asprintf(actual_file_name, "%s", unique[0] ? unique : fname);

	if (fd >= 0) {
		ssize_t rc;

		if (config.hyperlink) {
			const char *canon_file_name = canonicalize_file_name(*actual_file_name);
			info_printf(_("Saving '\033]8;;file://%s%s\033\\%s\033]8;;\033\\'\n"),
					config.hostname, canon_file_name, *actual_file_name);
			xfree(canon_file_name);
		} else {
			info_printf(_("Saving '%s'\n"), *actual_file_name);
		}
