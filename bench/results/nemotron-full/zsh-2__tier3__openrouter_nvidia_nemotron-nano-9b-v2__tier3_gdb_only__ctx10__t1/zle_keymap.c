
/* This structure is used when scanning for prefix bindings to remove */

struct remprefstate {
    Keymap km;
    char *prefix;
    int prefixlen;
};

#define BS_LIST (1<<0)
#define BS_ALL  (1<<1)

/* local functions */

#include "zle_keymap.pro"

/* currently selected keymap, and its name */

/**/
Keymap curkeymap, localkeymap;
/**/
char *curkeymapname;

/* the hash table of keymap names */

/**/
mod_export HashTable keymapnamtab;

/* key sequence reading data */

/**/
char *keybuf;

/**/
int keybuflen;

static int keybufsz = 20;

/* last command executed with execute-named-command */

static Thingy lastnamed;

/**********************************/
/* hashtable management functions */
/**********************************/

/**/
static void
createkeymapnamtab(void)
{
    keymapnamtab = newhashtable(7, "keymapnamtab", NULL);

    keymapnamtab->hash        = hasher;
    keymapnamtab->emptytable  = emptyhashtable;
    keymapnamtab->filltable   = NULL;
    keymapnamtab->cmpnodes    = strcmp;
    keymapnamtab->addnode     = addhashnode;
    keymapnamtab->getnode     = gethashnode2;
    keymapnamtab->getnode2    = gethashnode2;
    keymapnamtab->removenode  = removehashnode;
    keymapnamtab->disablenode = NULL;
    keymapnamtab->enablenode  = NULL;
    keymapnamtab->freenode    = freekeymapnamnode;
    keymapnamtab->printnode   = NULL;
}

/**/
static KeymapName
makekeymapnamnode(Keymap keymap)
{
    KeymapName kmn = (KeymapName) zshcalloc(sizeof(*kmn));

    kmn->keymap = keymap;
    return kmn;
}

/**/

/*
 * Reference a keymap from a keymapname.
 * Used when linking keymaps.  This includes the first link to a
 * newly created keymap.
 */

static void
refkeymap_by_name(KeymapName kmn)
{
    refkeymap(kmn->keymap);
    if (!kmn->keymap->primary && strcmp(kmn->nam, "main") != 0)
	kmn->keymap->primary = kmn;
}

/*
 * Communication to keymap scanner when looking for a new primary name.
 */
static Keymap km_rename_me;

/* Find a new primary name for a keymap.  See below. */

static void
scanprimaryname(HashNode hn, int ignored)
