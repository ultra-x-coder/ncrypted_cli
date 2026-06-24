"""Device identity, token/auth-mode state, and token-ensure logic.

CRITICAL: get_device_hash() and its helpers are COPIED VERBATIM from the
reference client. Any change to the hash inputs OR to the ~/.ncrypted/device_uuid
dotfile re-keys the device. The server then issues a brand-new token and all
files previously uploaded from this device become inaccessible. Do not touch.

State files:
  ~/.ncrypted/token        bearer token
  ~/.ncrypted/auth_mode    "device" | "user"
  ~/.ncrypted/username     saved username when logged in to a user account
  ~/.ncrypted/device_uuid  per-install random UUID (part of device_hash)
"""

import getpass
import hashlib
import platform
import subprocess
import uuid
from pathlib import Path

TOKEN_DIR = Path.home() / ".ncrypted"
TOKEN_FILE = TOKEN_DIR / "token"
AUTH_MODE_FILE = TOKEN_DIR / "auth_mode"
USERNAME_FILE = TOKEN_DIR / "username"


class AuthError(Exception):
    """Raised when authentication cannot proceed (e.g. user-mode, no token)."""


# --- device_hash derivation (VERBATIM) ---


def _get_machine_id() -> str:
    try:
        system = platform.system()
        if system == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                text=True, timeout=5,
            )
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        elif system == "Linux":
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                p = Path(path)
                if p.exists():
                    return p.read_text().strip()
        elif system == "Windows":
            out = subprocess.check_output(
                ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
                text=True, timeout=5,
            )
            for line in out.splitlines():
                if "MachineGuid" in line:
                    return line.split()[-1]
    except Exception:
        pass
    return ""


def _get_local_uuid() -> str:
    uuid_file = TOKEN_DIR / "device_uuid"
    if uuid_file.exists():
        return uuid_file.read_text().strip()
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    value = str(uuid.uuid4())
    uuid_file.write_text(value)
    return value


def get_device_hash() -> str:
    parts = [
        platform.node(),
        getpass.getuser(),
        str(uuid.getnode()),
        platform.system(),
        platform.machine(),
        _get_machine_id(),
        _get_local_uuid(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


# --- token / mode / username state ---


def load_token() -> str | None:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


def save_token(token: str):
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)


def delete_token():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def delete_username():
    if USERNAME_FILE.exists():
        USERNAME_FILE.unlink()


def get_auth_mode() -> str:
    if AUTH_MODE_FILE.exists():
        return AUTH_MODE_FILE.read_text().strip()
    return "device"


def save_auth_mode(mode: str):
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_MODE_FILE.write_text(mode)


def save_username(username: str):
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    USERNAME_FILE.write_text(username)


def get_saved_username() -> str | None:
    if USERNAME_FILE.exists():
        return USERNAME_FILE.read_text().strip()
    return None


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
