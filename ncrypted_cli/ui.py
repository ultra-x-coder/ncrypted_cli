"""Plain terminal helpers for the Ncrypted client."""

import getpass
import sys


def write(msg: str = "") -> None:
    print(msg)


def ok(msg: str) -> None:
    print(msg)


def err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(msg)


def human_bytes(n) -> str:
    try:
        value = float(n)
    except (TypeError, ValueError):
        return str(n)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


def human_rate(bps) -> str:
    if not bps:
        return "unlimited"
    return f"{human_bytes(bps)}/s"


def human_eta(seconds) -> str:
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return "-"
    if value < 0:
        return "-"
    if value < 60:
        return f"{value}s"
    minutes, secs = divmod(value, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def format_uploads_remaining(limits: dict | None) -> str:
    if not limits:
        return "unavailable"
    remaining = limits.get("remaining_uploads")
    maximum = limits.get("max_uploads")
    if remaining is None:
        return "unavailable"
    if maximum is None:
        return f"{remaining}/unlimited"
    return f"{remaining}/{maximum}"


def format_max_file_size(limits: dict | None) -> str:
    if not limits or limits.get("max_file_size_bytes") is None:
        return "unavailable"
    size = limits["max_file_size_bytes"]
    return f"{human_bytes(size)} ({size} bytes)"


def prompt_text(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{label}{suffix}: ")
    if value == "" and default is not None:
        return default
    return value


def prompt_passphrase(confirm: bool = False) -> str:
    passphrase = getpass.getpass("Passphrase: ")
    if confirm:
        again = getpass.getpass("Confirm passphrase: ")
        if passphrase != again:
            raise ValueError("Passphrases do not match.")
    return passphrase


def prompt_password(label: str = "Password", confirm: bool = False) -> str:
    password = getpass.getpass(f"{label}: ")
    if confirm:
        again = getpass.getpass(f"Confirm {label.lower()}: ")
        if password != again:
            raise ValueError("Passwords do not match.")
    return password


def confirm(label: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    answer = input(f"{label} [{marker}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}
