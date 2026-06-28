"""Crypto primitives — derived from the reference client.

WIRE FORMAT (must not change): salt[16] + nonce[12] + AESGCM(ciphertext)
over a zstd frame of the plaintext. Changing the cipher, the salt/nonce
lengths, or their order breaks compatibility with blobs already on the
server. Do NOT "improve" those.

The zstd COMPRESSION LEVEL is the one safe knob: it is an encoder-only choice
and is NOT part of the wire format. A zstd frame is self-describing, so
decrypt_blob/decompress never need to know the level a blob was compressed at —
old blobs (made at level 22) and new ones decode identically. The level is
therefore configurable via NCRYPTED_ZSTD_LEVEL (see ZSTD_LEVEL below).
"""

import base64
import os

import pyzstd
from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SALT_LEN = 16
NONCE_LEN = 12

# zstd level applied BEFORE encryption — pure speed/size tradeoff, with ZERO
# effect on cryptographic strength (the cipher is AES-256-GCM, the KDF Argon2id).
# Override per-machine with NCRYPTED_ZSTD_LEVEL in .env.
#   min = -131072  (ultra-fast; negative levels barely compress)
#   max = 22       (slowest, best ratio; ~30x more CPU than level 9 for ~5% less size)
# Default 3 is zstd's own default — ~100x faster than 22. Practical range: 1-9.
ZSTD_LEVEL = 3
ZSTD_LEVEL_MIN = -131072
ZSTD_LEVEL_MAX = 22


def _zstd_level() -> int:
    """Resolve the compression level from NCRYPTED_ZSTD_LEVEL, clamped to the
    valid range. Read at call time so .env (loaded by config.load_env_files)
    is honored; falls back to ZSTD_LEVEL on an unset or invalid value."""
    raw = os.getenv("NCRYPTED_ZSTD_LEVEL")
    if raw is None:
        return ZSTD_LEVEL
    try:
        level = int(raw)
    except ValueError:
        return ZSTD_LEVEL
    return max(ZSTD_LEVEL_MIN, min(ZSTD_LEVEL_MAX, level))


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
    compressed = pyzstd.compress(plaintext, _zstd_level())
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
