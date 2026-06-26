"""The 'register an account' call-to-action banner (device mode only).

Rendering policy (callers decide *eligibility* — device mode, command kind, not
--json; this module decides *presentation*):
  - only on a TTY (never corrupts piped/redirected output),
  - at most once per NAG_INTERVAL_MINUTES (the first eligible command always
    shows, then no more than once per interval — a persisted timestamp),
  - the interval is overridable via NCRYPTED_NAG_INTERVAL (minutes; 0 = always),
  - honors NCRYPTED_NO_NAG (suppress) and NO_COLOR (no ANSI),
  - falls back to a plain ASCII layout on non-UTF-8 or narrow terminals.
"""

import os
import shutil
import sys
import time

from . import auth

NAG_INTERVAL_MINUTES = 10


def _nag_file():
    return auth.TOKEN_DIR / "nag_last_shown"


def _nag_interval_seconds() -> float:
    """Interval between CTAs, in seconds. Reads NCRYPTED_NAG_INTERVAL (minutes);
    0 means show every time, anything unparseable/negative falls back to the
    NAG_INTERVAL_MINUTES default."""
    raw = os.environ.get("NCRYPTED_NAG_INTERVAL")
    if raw is None:
        return NAG_INTERVAL_MINUTES * 60
    try:
        minutes = float(raw)
    except ValueError:
        return NAG_INTERVAL_MINUTES * 60
    if minutes < 0:
        return NAG_INTERVAL_MINUTES * 60
    return minutes * 60

RESET = "\033[0m"
C_BORDER = "\033[2m"        # dim
C_HEAD = "\033[1;33m"      # bold yellow (the scary bit)
C_CMD = "\033[36m"         # cyan

_WIDE = {"⚡"}          # chars rendered two columns wide (the lightning bolt)


def _dwidth(text: str) -> int:
    return sum(2 if ch in _WIDE else 1 for ch in text)


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except OSError:
        return 80


def _supports_unicode() -> bool:
    enc = (getattr(sys.stderr, "encoding", "") or "").lower()
    return "utf" in enc


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stderr.isatty()


def _should_show() -> bool:
    """Return True when the CTA hasn't been shown within the configured interval:
    the very first eligible command always shows (a brand-new user sees it
    immediately), then at most once per _nag_interval_seconds(). Records "now" as
    the last-shown moment whenever it returns True."""
    nag_file = _nag_file()
    now = time.time()
    try:
        last = float(nag_file.read_text().strip())
    except (OSError, ValueError):
        last = None
    if last is not None and 0 <= (now - last) < _nag_interval_seconds():
        return False
    try:
        auth.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        nag_file.write_text(repr(now))
    except OSError:
        pass
    return True


def _render_plain(headline, body, register_cmd, register_url) -> str:
    head = headline.replace("⚡ ", "! ")
    lines = ["", "  " + head, ""]
    lines += ["  " + line for line in body]
    lines += [
        "",
        f"    {register_cmd}      (register here)",
        f"    {register_url}   (in a browser)",
        "",
    ]
    return "\n".join(lines)


def render(register_url: str, register_cmd: str = "ncrypted register-user") -> str:
    headline = "⚡ Heads up: your files are at risk"
    body = [
        "You're in device mode — files live ONLY on this machine.",
        "Lose it and they're gone for good, with no way to reach",
        "them from anywhere else. Register to keep them safe:",
    ]
    cmd_line = f"→  {register_cmd}      (register here)"
    url_line = f"→  {register_url}   (in a browser)"

    inner = 60
    total = inner + 6
    if not _supports_unicode() or _term_width() < total:
        return _render_plain(headline, body, register_cmd, register_url)

    color = _use_color()

    def c(code: str, s: str) -> str:
        return f"{code}{s}{RESET}" if color else s

    def row(text: str, code: str | None = None) -> str:
        padded = text + " " * max(0, inner - _dwidth(text))
        if code and color:
            padded = f"{code}{padded}{RESET}"
        bar = c(C_BORDER, "│")
        return f"{bar}  {padded}  {bar}"

    top = c(C_BORDER, "╭" + "─" * (inner + 4) + "╮")
    bot = c(C_BORDER, "╰" + "─" * (inner + 4) + "╯")
    empty = row("")

    lines = [top, row(headline, C_HEAD), empty]
    lines += [row(line) for line in body]
    lines += [empty, row(cmd_line, C_CMD), row(url_line, C_CMD), bot]
    return "\n".join(lines)


def maybe_print_register_cta(register_url: str, register_cmd: str) -> None:
    """Print the CTA to stderr if presentation policy allows it."""
    if os.environ.get("NCRYPTED_NO_NAG"):
        return
    if not sys.stderr.isatty():
        return
    if not _should_show():
        return
    try:
        sys.stderr.write("\n" + render(register_url, register_cmd) + "\n")
    except Exception:
        pass
