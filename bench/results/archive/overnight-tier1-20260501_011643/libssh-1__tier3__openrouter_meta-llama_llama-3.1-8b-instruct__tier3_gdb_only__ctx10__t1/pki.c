#ifdef HAVE_GCRYPT_ECC
            gcry_sexp_release(sig->ecdsa_sig);
#elif defined HAVE_LIBMBEDCRYPTO
            bignum_safe_free(sig->ecdsa_sig.r);
            bignum_safe_free(sig->ecdsa_sig.s);
#endif
            break;
        case SSH_KEYTYPE_ED25519:
            SAFE_FREE(sig->ed25519_sig);
            break;
        case SSH_KEYTYPE_DSS_CERT01:
        case SSH_KEYTYPE_RSA_CERT01:
        case SSH_KEYTYPE_ECDSA_P256_CERT01:
        case SSH_KEYTYPE_ECDSA_P384_CERT01:
        case SSH_KEYTYPE_ECDSA_P521_CERT01:
        case SSH_KEYTYPE_ED25519_CERT01:
        case SSH_KEYTYPE_RSA1:
        case SSH_KEYTYPE_ECDSA:
        case SSH_KEYTYPE_UNKNOWN:
            break;
    }

    /* Explicitly zero the signature content before free */
    ssh_string_burn(sig->raw_sig);
    ssh_string_free(sig->raw_sig);
    SAFE_FREE(sig);
}

/**
 * @brief import a base64 formated key from a memory c-string
 *
 * @param[in]  b64_key  The c-string holding the base64 encoded key
 *
 * @param[in]  passphrase The passphrase to decrypt the key, or NULL
 *
 * @param[in]  auth_fn  An auth function you may want to use or NULL.
 *
 * @param[in]  auth_data Private data passed to the auth function.
 *
 * @param[out] pkey     A pointer where the allocated key can be stored. You
 *                      need to free the memory.
 *
 * @return  SSH_ERROR in case of error, SSH_OK otherwise.
 *
 * @see ssh_key_free()
 */
int ssh_pki_import_privkey_base64(const char *b64_key,
                                  const char *passphrase,
                                  ssh_auth_callback auth_fn,
                                  void *auth_data,
                                  ssh_key *pkey)
{
    ssh_key key;
    int cmp;

    if (b64_key == NULL || pkey == NULL) {
        return SSH_ERROR;
    }

    if (b64_key == NULL || !*b64_key) {
        return SSH_ERROR;
    }

    SSH_LOG(SSH_LOG_INFO,
            "Trying to decode privkey passphrase=%s",
            passphrase ? "true" : "false");

    /* Test for OpenSSH key format first */
    cmp = strncmp(b64_key, OPENSSH_HEADER_BEGIN, strlen(OPENSSH_HEADER_BEGIN));
    if (cmp == 0) {
        key = ssh_pki_openssh_privkey_import(b64_key,
                                             passphrase,
                                             auth_fn,
                                             auth_data);
    } else {
        /* fallback on PEM decoder */
        key = pki_private_key_from_base64(b64_key,
                                          passphrase,
                                          auth_fn,
                                          auth_data);
    }
    if (key == NULL) {
        return SSH_ERROR;
    }

    *pkey = key;

    return SSH_OK;
}
 /**
 * @brief Convert a private key to a pem base64 encoded key, or OpenSSH format for
 *        keytype ssh-ed25519
 *
 * @param[in]  privkey  The private key to export.
 *
 * @param[in]  passphrase The passphrase to use to encrypt the key with or
 *             NULL. An empty string means no passphrase.
 *
 * @param[in]  auth_fn  An auth function you may want to use or NULL.
 *
 * @param[in]  auth_data Private data passed to the auth function.
