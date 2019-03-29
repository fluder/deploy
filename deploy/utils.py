import hashlib
import time
from socket import create_connection


def get_nonce(struct):
    cipher = hashlib.md5()

    if isinstance(struct, dict):
        struct = list(struct.items())

    if isinstance(struct, list):
        for x in sorted(struct):
            cipher.update(get_nonce(x).encode("utf8"))
    elif isinstance(struct, tuple):
        for x in struct:
            cipher.update(get_nonce(x).encode("utf8"))
    else:
        cipher.update(repr(struct).encode("utf8"))

    return cipher.hexdigest()


def wait_for_port(address, port=22):
    while True:
        try:
            create_connection((address, port), 5)
            return
        except Exception as e:
            print("Still waiting for %s:%s" % (address, port))
        time.sleep(5)


def wait_for_cloud_init(env):
    while not env.run(
        "ls /var/lib/cloud/instance/ | grep boot-finished",
        hide=True
    )["stdout"].strip():
        print("Still waiting for cloud-init")
        time.sleep(5)
