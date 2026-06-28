"""Client-side file-encryption passphrase policy.

Ported from the server's account-password policy
(``syphr_filesharing/password_policy.py``) and applies the *same principles* to
the file-encryption *passphrase*. The passphrase never reaches the server
(zero-knowledge), so — exactly as the server policy's own docstring notes — it
must be validated client-side instead.

Policy (identical to the server's, minus the username check, which has no
meaning for a file passphrase):
- minimum length (``NCRYPTED_MIN_PASSPHRASE_LENGTH``, default 6),
- not a single repeated character,
- not an obvious ascending/descending run,
- not one of the most common leaked passwords (bundled top-1000 list; override
  the path via ``NCRYPTED_COMMON_PASSWORDS_FILE``).

Mirroring the server (which validates on ``/auth/register`` but NOT on
``/auth/login``), this runs only when a passphrase is used to ENCRYPT new
content (upload / new private description). Decrypting existing files never
re-validates, so files created with a weak passphrase stay accessible.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("passphrase_policy")

DEFAULT_MIN_LENGTH = 6
DEFAULT_COMMON_PASSWORDS_FILE = "assets/common_passwords_1k.txt"

_common_passwords: frozenset[str] | None = None


def _min_length() -> int:
    raw = os.getenv("NCRYPTED_MIN_PASSPHRASE_LENGTH")
    if raw is None:
        return DEFAULT_MIN_LENGTH
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MIN_LENGTH


def _common_passwords_path() -> Path:
    raw = os.getenv("NCRYPTED_COMMON_PASSWORDS_FILE", DEFAULT_COMMON_PASSWORDS_FILE)
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def load_common_passwords() -> frozenset[str]:
    """Load (and cache) the common-password blocklist, normalized to lowercase.

    Missing file is non-fatal: we log a warning and fall back to the structural
    checks so uploads keep working without the wordlist (mirrors the server).
    """
    global _common_passwords
    if _common_passwords is not None:
        return _common_passwords

    path = _common_passwords_path()
    words: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                pw = line.strip()
                if pw:
                    words.add(pw.lower())
    except FileNotFoundError:
        logger.warning(
            "common passwords file not found at %s; structural checks only", path
        )
    _common_passwords = frozenset(words)
    return _common_passwords


def _is_sequential(pw: str) -> bool:
    """True for runs like ``123456`` / ``abcdef`` / ``654321`` (>= 5 chars)."""
    if len(pw) < 5:
        return False
    diffs = {ord(b) - ord(a) for a, b in zip(pw, pw[1:])}
    return diffs in ({1}, {-1})


class PassphrasePolicyError(ValueError):
    """Raised with a user-facing reason when a passphrase is rejected."""


def validate_passphrase(passphrase: str) -> None:
    """Raise :class:`PassphrasePolicyError` if the passphrase is unacceptable."""
    min_length = _min_length()
    if len(passphrase) < min_length:
        raise PassphrasePolicyError(
            f"Passphrase must be at least {min_length} characters"
        )

    normalized = passphrase.strip().lower()

    if len(set(passphrase)) == 1:
        raise PassphrasePolicyError(
            "Passphrase must not be a single repeated character"
        )

    if _is_sequential(normalized):
        raise PassphrasePolicyError(
            "Passphrase must not be a simple character sequence"
        )

    if normalized in load_common_passwords():
        raise PassphrasePolicyError(
            "Passphrase is too common; choose a stronger one"
        )
