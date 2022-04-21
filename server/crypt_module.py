import rsa


def generate_keys():
    """
    Generate public and private keys.
    """
    pubkey, privkey = rsa.newkeys(1024)
    pubkey = pubkey.save_pkcs1()
    privkey = privkey.save_pkcs1()
    return pubkey, privkey
