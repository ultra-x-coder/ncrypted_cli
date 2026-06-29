"""Client-side account username/password policy.

A fast, friendly pre-check before ``/auth/register`` that mirrors the server's
authoritative rules, so the user gets an immediate, readable rejection instead of
a round-trip. The server still re-validates; this is only an early gate.

This is separate from :mod:`ncrypted_cli.passphrase_policy`, which guards the
file-encryption *passphrase* — here we guard the *account* username/password.

Rules (mirrored from the server):
- username: 5–15 chars, only ``a-zA-Z0-9_-``, at least one letter (purely numeric
  is rejected); the server stores it lowercased / matches case-insensitively.
- password: 8–64 chars (the server also applies dictionary/structural checks).
"""

import re

USERNAME_MIN = 5
USERNAME_MAX = 15
PASSWORD_MIN = 8
PASSWORD_MAX = 64

_USERNAME_CHARS = re.compile(r"^[a-zA-Z0-9_-]+$")
_HAS_LETTER = re.compile(r"[a-zA-Z]")


class AccountPolicyError(ValueError):
    """Raised with a user-facing reason when a username/password is rejected."""


def validate_username(username: str) -> None:
    if not (USERNAME_MIN <= len(username) <= USERNAME_MAX):
        raise AccountPolicyError(
            f"Username must be {USERNAME_MIN}–{USERNAME_MAX} characters"
        )
    if not _USERNAME_CHARS.match(username):
        raise AccountPolicyError(
            "Username may contain only letters, digits, '_' and '-'"
        )
    if not _HAS_LETTER.search(username):
        raise AccountPolicyError("Username must contain at least one letter")


def validate_password(password: str) -> None:
    if not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        raise AccountPolicyError(
            f"Password must be {PASSWORD_MIN}–{PASSWORD_MAX} characters"
        )
