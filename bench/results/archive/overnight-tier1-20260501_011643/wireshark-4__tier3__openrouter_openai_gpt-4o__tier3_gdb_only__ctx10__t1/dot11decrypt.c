    guint offset_rsne,
    guint offset_fte,
    guint offset_timeout,
    guint offset_link,
    guint8 action)
    ;
#ifdef  __cplusplus
}
#endif

/****************************************************************************/

/****************************************************************************/
/* Exported function definitions                                                */

#ifdef  __cplusplus
extern "C" {
#endif

const guint8 broadcast_mac[] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };

#define TKIP_GROUP_KEY_LEN 32
#define CCMP_GROUP_KEY_LEN 16

typedef void (*DOT11DECRYPT_PTK_DERIVE_FUNC)(
    DOT11DECRYPT_SEC_ASSOCIATION *sa,
    const UCHAR *pmk,
    const UCHAR snonce[32],
    const INT x,
    UCHAR *ptk,
    int hash_algo);

#define EAPOL_RSN_KEY_LEN 95

/* Minimum possible key data size (at least one GTK KDE with CCMP key) */
#define GROUP_KEY_MIN_LEN 8 + CCMP_GROUP_KEY_LEN
/* Minimum possible group key msg size (group key msg using CCMP as cipher)*/
#define GROUP_KEY_PAYLOAD_LEN_MIN \
    (EAPOL_RSN_KEY_LEN + GROUP_KEY_MIN_LEN)

static void
Dot11DecryptCopyKey(PDOT11DECRYPT_SEC_ASSOCIATION sa, PDOT11DECRYPT_KEY_ITEM key)
{
    if (key!=NULL) {
        if (sa->key!=NULL)
            memcpy(key, sa->key, sizeof(DOT11DECRYPT_KEY_ITEM));
        else
            memset(key, 0, sizeof(DOT11DECRYPT_KEY_ITEM));
        memcpy(key->KeyData.Wpa.Ptk, sa->wpa.ptk, sa->wpa.ptk_len);
        key->KeyData.Wpa.Akm = sa->wpa.akm;
        key->KeyData.Wpa.Cipher = sa->wpa.cipher;
        if (sa->wpa.key_ver==DOT11DECRYPT_WPA_KEY_VER_NOT_CCMP)
            key->KeyType=DOT11DECRYPT_KEY_TYPE_TKIP;
        else if (sa->wpa.key_ver == DOT11DECRYPT_WPA_KEY_VER_AES_CCMP ||
                sa->wpa.key_ver == 0)
        {
            switch (sa->wpa.cipher) {
                case 1:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_WEP_40;
                    break;
                case 2:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_TKIP;
                    break;
                case 4:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_CCMP;
                    break;
                case 5:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_WEP_104;
                    break;
                case 8:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_GCMP;
                    break;
                case 9:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_GCMP_256;
                    break;
                case 10:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_CCMP_256;
                    break;
                default:
                    key->KeyType = DOT11DECRYPT_KEY_TYPE_UNKNOWN;
                    break;
                /* NOT SUPPORTED YET
                case 3:  Reserved
                case 6:  BIP-CMAC-128
                case 7:  Group addressed traffic not allowed
                case 11: BIP-GMAC-128
                case 12: BIP-GMAC-256
                case 13: BIP-CMAC-256 */
            }
        }
    }
}

static guint8*
Dot11DecryptRc4KeyData(const guint8 *decryption_key, guint decryption_key_len,
                       const guint8 *encrypted_keydata, guint encrypted_keydata_len)
{
    gcry_cipher_hd_t  rc4_handle;
    guint8 dummy[256] = { 0 };
    guint8 *decrypted_key = NULL;

