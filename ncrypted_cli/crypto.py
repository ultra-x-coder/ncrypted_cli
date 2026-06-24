"""Crypto primitives — COPIED VERBATIM from the reference client.

WIRE FORMAT (must not change): salt[16] + nonce[12] + AESGCM(ciphertext)
over zstd(plaintext, level=22). Changing any of this breaks compatibility
with already-uploaded blobs on the server. Do NOT "improve" this module.
"""

import base64
import os

import pyzstd
from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SALT_LEN = 16
NONCE_LEN = 12
ZSTD_LEVEL = 22


def derive_key(passphrase: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret=passphrase.encode(),
        salt=salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=1,
        hash_len=32,
        type=Argon2Type.ID,
    )


def encrypt_blob(plaintext: bytes, passphrase: str) -> bytes:
    # NOTE: one-shot over the whole buffer. This is why crypto cannot show
    # per-chunk progress (see progress.py — crypto uses a spinner instead).
    compressed = pyzstd.compress(plaintext, ZSTD_LEVEL)
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, compressed, None)
    return salt + nonce + ciphertext


def decrypt_blob(blob: bytes, passphrase: str) -> bytes:
    salt = blob[:SALT_LEN]
    nonce = blob[SALT_LEN : SALT_LEN + NONCE_LEN]
    ciphertext = blob[SALT_LEN + NONCE_LEN :]
    key = derive_key(passphrase, salt)
    compressed = AESGCM(key).decrypt(nonce, ciphertext, None)
    return pyzstd.decompress(compressed)


def encrypt_text(text: str, passphrase: str) -> str:
    encrypted = encrypt_blob(text.encode(), passphrase)
    return base64.b64encode(encrypted).decode()


def decrypt_text(b64_encrypted: str, passphrase: str) -> str:
    encrypted = base64.b64decode(b64_encrypted)
    return decrypt_blob(encrypted, passphrase).decode()
