"""Update check: compare the running version against the latest published
VERSION file and, when a newer one exists, nudge the user to re-run the
installer.

Policy mirrors the register banner — TTY-only and fail-safe (any network or
parse error is swallowed, never breaking a command). The network is hit at most
once per NCRYPTED_UPDATE_CHECK_INTERVAL hours; the last result is cached next to
the auth token so we can keep nudging between checks without re-fetching.

Controls:
  - NCRYPTED_NO_UPDATE_CHECK       -> disable entirely,
  - NCRYPTED_UPDATE_CHECK_INTERVAL -> hours between network checks (0 = always),
  - NCRYPTED_VERSION_URL           -> override where the VERSION file is fetched,
  - NCRYPTED_INSTALL_URL           -> override the installer URL shown in the hint.
"""

import os
import sys
import time

import httpx

from . import __version__, auth

CHECK_INTERVAL_HOURS = 24
INSTALL_URL = "https://ncrypted.app/install.sh"

RESET = "\033[0m"
C_NEW = "\033[1;32m"   # bold green: the new version + arrows (the upgrade)
C_OLD = "\033[2m"      # dim: the version you currently have
C_CMD = "\033[36m"     # cyan: the install command


def _stamp_file():
    return auth.TOKEN_DIR / "update_check"


def _interval_seconds() -> float:
    """Hours between network checks. 0 means check every run; unparseable or
    negative values fall back to the default."""
    raw = os.environ.get("NCRYPTED_UPDATE_CHECK_INTERVAL")
    if raw is None:
        return CHECK_INTERVAL_HOURS * 3600
    try:
        hours = float(raw)
    except ValueError:
        return CHECK_INTERVAL_HOURS * 3600
    if hours < 0:
        return CHECK_INTERVAL_HOURS * 3600
    return hours * 3600


def _version_url(server: str) -> str:
    override = os.environ.get("NCRYPTED_VERSION_URL")
    if override:
        return override
    return f"{server.rstrip('/')}/releases/latest/VERSION"


def _parse(version: str):
    """Parse a dotted version into a tuple of ints, stopping each component at
    the first non-digit (so '1.2.3-rc1' -> (1, 2, 3)). Returns None if any
    leading component has no digits, so unparseable versions never nag."""
    parts = []
    for chunk in version.strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            return None
        parts.append(int(digits))
    return tuple(parts) if parts else None


def _is_newer(latest: str, current: str) -> bool:
    a = _parse(latest)
    b = _parse(current)
    if a is None or b is None:
        return False
    return a > b


def _fetch_latest(server: str) -> str | None:
    try:
        resp = httpx.get(_version_url(server), timeout=3, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    lines = (resp.text or "").strip().splitlines()
    return lines[0].strip() if lines else None


def _read_cache():
    """Return (last_check_ts, latest_version) or (None, None)."""
    try:
        lines = _stamp_file().read_text().splitlines()
    except OSError:
        return None, None
    if not lines:
        return None, None
    try:
        ts = float(lines[0].strip())
    except ValueError:
        return None, None
    latest = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
    return ts, latest


def _write_cache(ts: float, latest: str) -> None:
    try:
        auth.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        _stamp_file().write_text(f"{ts!r}\n{latest}\n")
    except OSError:
        pass


def _current_latest(server: str) -> str | None:
    """Latest published version, served from the cache while it is fresh and
    refreshed over the network otherwise. None when the network check fails."""
    now = time.time()
    last_ts, cached = _read_cache()
    if last_ts is not None and 0 <= (now - last_ts) < _interval_seconds():
        return cached
    latest = _fetch_latest(server)
    if latest is None:
        return None
    _write_cache(now, latest)
    return latest


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stderr.isatty()


def _supports_unicode() -> bool:
    enc = (getattr(sys.stderr, "encoding", "") or "").lower()
    return "utf" in enc


def _print_update_notice(latest: str) -> None:
    """Render the 'upgrade' notice: green arrow + new version, dim current
    version, cyan install command. Falls back to ASCII glyphs on non-UTF-8
    terminals and drops color under NO_COLOR / non-TTY."""
    install = os.environ.get("NCRYPTED_INSTALL_URL") or INSTALL_URL
    color = _use_color()
    unicode_ok = _supports_unicode()
    up = "⬆" if unicode_ok else ">>"
    arrow = "→" if unicode_ok else "->"

    def c(code: str, s: str) -> str:
        return f"{code}{s}{RESET}" if color else s

    head = (
        f"{c(C_NEW, up)}  ncrypted "
        f"{c(C_OLD, __version__)} {c(C_NEW, f'{arrow} {latest}')}  (update available)"
    )
    cmd = f"   {c(C_CMD, f'curl -fsSL {install} | sh')}"
    try:
        sys.stderr.write(f"\n{head}\n{cmd}\n\n")
    except Exception:
        pass


def maybe_notify_update(server: str) -> None:
    """Print an update hint to stderr when a newer version is published. Honors
    the env controls and never raises into the command flow."""
    if os.environ.get("NCRYPTED_NO_UPDATE_CHECK"):
        return
    if not sys.stderr.isatty():
        return
    try:
        latest = _current_latest(server)
    except Exception:
        return
    if latest and _is_newer(latest, __version__):
        _print_update_notice(latest)
