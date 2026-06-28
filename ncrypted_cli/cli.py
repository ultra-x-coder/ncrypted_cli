"""Plain argparse CLI for the Ncrypted terminal client."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__, auth, banner, instance, ui, version_check
from .actions import (
    ArchiveWouldNotShrink,
    CryptoFailure,
    decrypt_and_save,
    decrypt_private_description,
    do_account_limits,
    do_delete,
    do_info,
    do_list,
    do_login_user,
    do_register_user,
    do_update,
    do_upload,
    extract_slug,
    fetch_encrypted_blob,
    is_archive_name,
    safe_filename,
)
from .api import ApiError, ServerUnavailable, NcryptedClient, Tombstone
from .config import load_settings
from .throttle import parse_rate

CLIENT_ERRORS = (ApiError, ServerUnavailable, auth.AuthError)
RECOVERABLE_ERRORS = (*CLIENT_ERRORS, ValueError)

COMMANDS = {
    "list",
    "info",
    "upload",
    "download",
    "decrypt",
    "update",
    "delete",
    "register-user",
    "login-user",
    "settings",
    "log-out",
    "logout",
}
MAX_PASSPHRASE_ATTEMPTS = 3
GLOBAL_OPTIONS_WITH_VALUE = {"--server", "--max-up", "--max-down"}


def _fail(msg: str) -> None:
    ui.err(msg)
    raise SystemExit(1)


def _prog() -> str:
    return Path(sys.argv[0]).name or "ncrypted"


def _maybe_register_cta(args, settings) -> None:
    """Footer call-to-action nudging device-mode users to register. Never raises
    into the command flow."""
    try:
        if auth.get_auth_mode() == "user":
            return
        command = getattr(args, "command", None)
        if command in {"register-user", "login-user", "log-out", "logout"}:
            return
        if getattr(args, "json_output", False):
            return
        _, register_url = _account_urls(settings.site)
        banner.maybe_print_register_cta(register_url, f"{_prog()} register-user")
    except Exception:
        pass


def _maybe_check_update(args, settings) -> None:
    """Footer notice when a newer client version is published. Never raises into
    the command flow."""
    try:
        if getattr(args, "json_output", False):
            return
        version_check.maybe_notify_update(settings.site)
    except Exception:
        pass


def _account_urls(site: str) -> tuple[str, str]:
    base = site.rstrip("/")
    return f"{base}/login", f"{base}/register"


def _get_account_limits(server: str) -> dict | None:
    try:
        return do_account_limits(server)
    except CLIENT_ERRORS as e:
        ui.warn(f"account limits unavailable: {e}")
    except Exception as e:
        ui.warn(f"account limits unavailable: {e}")
    return None


def _bool(value) -> str:
    return "yes" if bool(value) else "no"


def _clean(value) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _size_bytes(value) -> int | str:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value if value is not None else 0


def _file_url(server: str, data: dict) -> str:
    if data.get("url"):
        return data["url"]
    slug = data.get("slug", "")
    return f"{server.rstrip('/')}/d/{slug}" if slug else "-"


def _retention(data: dict) -> str:
    seconds = data.get("keep_alive_seconds")
    if seconds is None:
        return "-"
    return f"{seconds}s after last download"


def _normalized_file(data: dict, server: str) -> dict:
    size = _size_bytes(data.get("original_size", 0))
    return {
        "slug": data.get("slug", ""),
        "name": data.get("original_filename", ""),
        "size": ui.human_bytes(size),
        "size_bytes": size,
        "retention": _retention(data),
        "downloads": data.get("download_count", 0),
        "public": bool(data.get("public")),
        "archive": bool(data.get("archive")),
        "created": data.get("created_at") or "",
        "last_download": data.get("last_downloaded_at") or None,
        "url": _file_url(server, data),
        "description": data.get("public_description") or None,
    }


def _print_kv(rows: list[tuple[str, object]]) -> None:
    for key, value in rows:
        ui.write(f"{key}\t\t{_clean(value)}")


def _print_intro(settings) -> None:
    login_url, register_url = _account_urls(settings.site)
    limits = _get_account_limits(settings.server)
    auth_mode = auth.get_auth_mode()
    if auth_mode == "user":
        username = auth.get_saved_username()
        auth_line = f"user auth{f' ({username})' if username else ''} - files are linked to your account."
    else:
        auth_line = "device auth - means you can manage your uploaded files only from this terminal."

    ui.write(
        f"`{settings.brand}` is secure file sharing for encrypted uploads and downloads from your terminal."
    )
    ui.write(f"server: {settings.server}")
    ui.write(f"auth: {auth_line}")
    ui.write(f"max upload size: {ui.format_max_file_size(limits)}")
    ui.write(f"uploads remaining: {ui.format_uploads_remaining(limits)}")
    ui.write()
    ui.write(f"Already have account? Sign in: {login_url}")
    ui.write(f"Register to use this account from different devices: {register_url}")
    ui.write()
    ui.write("Use --help to see usage guide.")


def _print_file_info(data: dict, server: str, private_decrypted: str | None = None) -> None:
    size = _size_bytes(data.get("original_size", 0))
    rows = [
        ("Slug", data.get("slug", "")),
        ("Size", f"{ui.human_bytes(size)} ({size} bytes)"),
        ("Retention", _retention(data)),
        ("Downloads", data.get("download_count", 0)),
        ("Public", _bool(data.get("public"))),
        ("Archive", _bool(data.get("archive"))),
        ("Created", data.get("created_at") or "-"),
        ("Last DL", data.get("last_downloaded_at") or "-"),
        ("URL", _file_url(server, data)),
    ]
    if data.get("public_description"):
        rows.append(("Description", data["public_description"]))
    if private_decrypted is not None:
        rows.append(("Private", private_decrypted))
    _print_kv(rows)


def _fmt_created(value, *, seconds: bool = False) -> str:
    """2026-06-25T21:10:27.052000 -> '2026-06-25 21:10' (or HH:MM:SS with seconds)."""
    if not value:
        return "-"
    text = str(value)
    if "T" not in text:
        return text
    date_part, _, time_part = text.partition("T")
    time_part = time_part.split(".")[0].split("+")[0]
    if not seconds:
        time_part = ":".join(time_part.split(":")[:2])
    return f"{date_part} {time_part}".strip()


def _print_files_table(files: list[dict]) -> None:
    has_desc = any(f["description"] for f in files)
    headers = ["NAME", "SLUG", "SIZE", "DL", "ACCESS", "CREATED"]
    rows = [
        [
            _clean(f["name"]),
            _clean(f["slug"]),
            f["size"],
            str(f["downloads"]),
            "public" if f["public"] else "private",
            _fmt_created(f["created"]),
        ]
        for f in files
    ]
    if has_desc:
        headers.append("DESCRIPTION")
        for row, f in zip(rows, files):
            row.append(_clean(f["description"]))

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: list[str]) -> str:
        out = []
        for i, cell in enumerate(cells):
            # The DL column (index 3) is numeric: right-align it.
            out.append(cell.rjust(widths[i]) if i == 3 else cell.ljust(widths[i]))
        return "  ".join(out).rstrip()

    ui.write(fmt(headers))
    for row in rows:
        ui.write(fmt(row))


def _print_files_full(files: list[dict]) -> None:
    last = len(files) - 1
    for idx, f in enumerate(files):
        ui.write(_clean(f["name"]))
        rows = [
            ("slug", f["slug"]),
            ("size", f"{f['size']} ({f['size_bytes']} bytes)"),
            ("access", "public" if f["public"] else "private"),
            ("archive", _bool(f["archive"])),
            ("downloads", f["downloads"]),
            ("created", _fmt_created(f["created"], seconds=True)),
            ("last_dl", _fmt_created(f["last_download"], seconds=True)),
            ("retention", f["retention"]),
            ("url", f["url"]),
            ("description", f["description"] or "-"),
        ]
        label_w = max(len(k) for k, _ in rows)
        for key, value in rows:
            ui.write(f"  {key.ljust(label_w)}  {_clean(value)}")
        if idx != last:
            ui.write()


def cmd_list(args, settings) -> None:
    try:
        files = do_list(settings.server)
    except CLIENT_ERRORS as e:
        _fail(str(e))
    normalized = [_normalized_file(item, settings.server) for item in files]
    if args.json_output:
        ui.write(json.dumps(normalized, ensure_ascii=False, indent=2))
        return
    if not normalized:
        ui.info("No files uploaded yet.")
        return
    if args.full:
        _print_files_full(normalized)
    else:
        _print_files_table(normalized)


def cmd_info(args, settings) -> None:
    try:
        data = do_info(settings.server, args.slug)
    except Tombstone as t:
        ui.err(f"File was deleted: {t.detail}")
        raise SystemExit(1)
    except CLIENT_ERRORS as e:
        _fail(str(e))

    private_decrypted = None
    if args.show_private:
        if data.get("private_description"):
            passphrase = args.passphrase or ui.prompt_passphrase(confirm=False)
            try:
                private_decrypted = decrypt_private_description(data, passphrase)
            except CryptoFailure:
                ui.warn("Could not decrypt private description (wrong passphrase?)")
        else:
            ui.info("No private description set.")
    _print_file_info(data, settings.server, private_decrypted)


def cmd_upload(args, settings) -> None:
    path = Path(args.path)
    if not path.exists():
        _fail(f"File not found: {path}")
    try:
        limit = parse_rate(args.max_up) if args.max_up is not None else settings.max_up
    except ValueError as e:
        _fail(str(e))
    passphrase = args.passphrase
    if passphrase is None:
        try:
            passphrase = ui.prompt_passphrase(confirm=True)
        except ValueError as e:
            _fail(str(e))
    if limit:
        ui.info(f"Upload limited to {ui.human_rate(limit)}")

    def confirm_archive(source_size: int, archive_size: int, reason: str) -> bool:
        ui.warn(
            "Archive is unlikely to shrink the encrypted file "
            f"(estimated {ui.human_bytes(archive_size)} from {ui.human_bytes(source_size)}; {reason})."
        )
        return ui.confirm("Upload the archive anyway?", default=False)

    def show_archive_info(source_size: int, archive_size: int) -> None:
        delta = archive_size - source_size
        ratio = (archive_size / source_size * 100) if source_size else 0
        if delta <= 0:
            ui.info(
                "Encrypted/archive size: "
                f"{ui.human_bytes(source_size)} -> {ui.human_bytes(archive_size)} "
                f"({ratio:.1f}%, saved {ui.human_bytes(abs(delta))})"
            )
        else:
            ui.warn(
                "Encrypted/archive size: "
                f"{ui.human_bytes(source_size)} -> {ui.human_bytes(archive_size)} "
                f"({ratio:.1f}%, larger by {ui.human_bytes(delta)})"
            )

    try:
        data = do_upload(
            settings.server,
            path,
            args.public,
            passphrase,
            args.public_desc,
            args.private_desc,
            max_up=limit,
            archive=args.archive,
            yes=args.yes,
            archive_confirm=confirm_archive,
            archive_info=show_archive_info,
        )
    except ArchiveWouldNotShrink as e:
        _fail(str(e))
    except RECOVERABLE_ERRORS as e:
        _fail(str(e))

    rows = [("Uploaded", "yes"), ("Slug", data.get("slug", "")), ("URL", data.get("url", ""))]
    if data.get("archive"):
        rows.append(("Archive", "yes"))
    _print_kv(rows)


def _decrypt_with_retries(
    blob: bytes,
    original_filename: str,
    is_archive: bool,
    output,
    extract: bool,
    initial_passphrase: str | None,
) -> Path | None:
    """Decrypt `blob` in memory, re-prompting on a wrong passphrase up to
    MAX_PASSPHRASE_ATTEMPTS times (no re-download). Returns the saved Path, or
    None if every attempt failed or the user aborted the prompt."""
    for attempt in range(MAX_PASSPHRASE_ATTEMPTS):
        if attempt == 0 and initial_passphrase is not None:
            passphrase = initial_passphrase
        else:
            try:
                passphrase = ui.prompt_passphrase(confirm=False)
            except (EOFError, KeyboardInterrupt):
                ui.err("Aborted.")
                return None
        try:
            return decrypt_and_save(
                blob, passphrase, output, original_filename, is_archive,
                extract=extract,
            )
        except CryptoFailure:
            remaining = MAX_PASSPHRASE_ATTEMPTS - attempt - 1
            if remaining:
                ui.warn(f"Decryption failed - wrong passphrase? ({remaining} attempt(s) left)")
            else:
                ui.err("Decryption failed - wrong passphrase? No attempts left.")
        except ValueError as e:
            _fail(str(e))
    return None


def _save_encrypted_blob(blob: bytes, original_filename: str, output) -> Path:
    """Persist the still-encrypted blob as <name>.enc so a failed download is
    not wasted; it can be decrypted later with the `decrypt` command."""
    if output is not None:
        out = output.expanduser()
        directory = out if out.is_dir() else (out.parent if out.parent.exists() else Path.cwd())
    else:
        directory = Path.cwd()
    dest = safe_filename(directory, f"{original_filename}.enc")
    dest.write_bytes(blob)
    return dest


def cmd_download(args, settings) -> None:
    slug = extract_slug(args.slug)
    try:
        limit = parse_rate(args.max_down) if args.max_down is not None else settings.max_down
    except ValueError as e:
        _fail(str(e))

    try:
        meta = NcryptedClient(settings.server).info(slug)
    except Tombstone as t:
        ui.err(f"File was deleted: {t.detail}")
        raise SystemExit(1)
    except CLIENT_ERRORS as e:
        _fail(str(e))

    size = _size_bytes(meta.get("original_size", 0))
    _print_kv(
        [
            ("File", meta.get("original_filename", "")),
            ("Size", f"{ui.human_bytes(size)} ({size} bytes)"),
            ("Archive", f"yes{' (will extract)' if meta.get('archive') and args.extract else ''}" if meta.get("archive") else "no"),
        ]
    )

    if limit:
        ui.info(f"Download limited to {ui.human_rate(limit)}")
    try:
        blob, meta = fetch_encrypted_blob(settings.server, slug, info=meta, max_down=limit)
    except Tombstone as t:
        ui.err(f"File was deleted: {t.detail}")
        raise SystemExit(1)
    except CLIENT_ERRORS as e:
        _fail(str(e))

    original_filename = meta.get("original_filename") or slug
    dest = _decrypt_with_retries(
        blob,
        original_filename,
        bool(meta.get("archive")),
        args.output,
        args.extract,
        args.passphrase,
    )
    if dest is None:
        enc_path = _save_encrypted_blob(blob, original_filename, args.output)
        ui.warn(f"Saved still-encrypted file to {enc_path}")
        ui.info(f"Decrypt it later with: {_prog()} decrypt {enc_path}")
        raise SystemExit(1)
    label = "Extracted to" if dest.is_dir() else "Saved to"
    ui.ok(f"{label}\t\t{dest}")


def _enc_original_name(path: Path) -> str:
    name = path.name
    if name.lower().endswith(".enc"):
        return name[:-4] or "download.bin"
    return name


def _maybe_remove_encrypted(src: Path, dest: Path, remove: bool) -> None:
    """After a successful decrypt, optionally delete the source encrypted file.
    With --remove it is deleted unconditionally; otherwise we ask (TTY only,
    default no). Never deletes the freshly written output, never raises."""
    try:
        if src.resolve() == dest.resolve():
            return
    except OSError:
        return
    if remove:
        should = True
    elif sys.stdin.isatty():
        try:
            should = ui.confirm("Delete the encrypted file?", default=False)
        except (EOFError, KeyboardInterrupt):
            ui.write()
            return
    else:
        should = False
    if not should:
        return
    try:
        src.unlink()
        ui.ok(f"Removed\t\t{src}")
    except OSError as e:
        ui.warn(f"Could not remove {src}: {e}")


def cmd_decrypt(args, settings) -> None:
    del settings
    src = Path(args.path).expanduser()
    if not src.is_file():
        _fail(f"File not found: {src}")
    blob = src.read_bytes()
    original_filename = _enc_original_name(src)
    dest = _decrypt_with_retries(
        blob,
        original_filename,
        is_archive_name(original_filename),
        args.output,
        args.extract,
        args.passphrase,
    )
    if dest is None:
        raise SystemExit(1)
    label = "Extracted to" if dest.is_dir() else "Saved to"
    ui.ok(f"{label}\t\t{dest}")
    _maybe_remove_encrypted(src, dest, args.remove)


def cmd_update(args, settings) -> None:
    try:
        do_update(
            settings.server,
            args.slug,
            args.public_desc,
            args.private_desc,
            args.passphrase,
            passphrase_prompt=lambda: ui.prompt_passphrase(confirm=True),
        )
    except RECOVERABLE_ERRORS as e:
        _fail(str(e))
    ui.ok(f"Updated\t\t{extract_slug(args.slug)}")


def cmd_delete(args, settings) -> None:
    slug = extract_slug(args.slug)
    try:
        meta = NcryptedClient(settings.server).info(slug)
    except Tombstone as t:
        ui.err(f"File was deleted: {t.detail}")
        raise SystemExit(1)
    except CLIENT_ERRORS as e:
        _fail(str(e))

    filename = meta.get("original_filename", slug)
    if not args.yes and not ui.confirm(f"Delete {filename} ({slug})?", default=False):
        ui.info("Aborted.")
        return
    try:
        do_delete(settings.server, slug)
    except CLIENT_ERRORS as e:
        _fail(str(e))
    ui.ok(f"Deleted\t\t{filename} ({slug})")


def cmd_register_user(args, settings) -> None:
    del args
    username = ui.prompt_text("Username")
    try:
        password = ui.prompt_password("Password", confirm=True)
    except ValueError as e:
        _fail(str(e))
    try:
        do_register_user(settings.server, username, password)
    except CLIENT_ERRORS as e:
        _fail(str(e))
    ui.ok(f"Registered\t{username}")
    ui.info("Run login-user to link this device.")


def cmd_login_user(args, settings) -> None:
    del args
    username = ui.prompt_text("Username")
    password = ui.prompt_password("Password")
    try:
        do_login_user(settings.server, username, password)
    except CLIENT_ERRORS as e:
        _fail(str(e))
    ui.ok(f"Logged in\t{username}")


def cmd_settings(args, settings) -> None:
    del args
    limits = _get_account_limits(settings.server)
    login_url, register_url = _account_urls(settings.site)
    rows = [
        ("Brand", settings.brand),
        ("Server", settings.server),
        ("Auth mode", auth.get_auth_mode()),
        ("Username", auth.get_saved_username() or "-"),
        ("Token present", _bool(auth.load_token() is not None)),
        ("Uploads remaining", ui.format_uploads_remaining(limits)),
        ("Max file size", ui.format_max_file_size(limits)),
        ("Max upload speed", ui.human_rate(settings.max_up)),
        ("Max download speed", ui.human_rate(settings.max_down)),
        ("Sign in", login_url),
        ("Register", register_url),
        ("State dir", str(auth.TOKEN_DIR)),
    ]
    _print_kv(rows)


def cmd_logout(args, settings) -> None:
    del args, settings
    auth.delete_token()
    auth.delete_username()
    auth.save_auth_mode("device")
    ui.ok("Logged out")
    ui.info(f"Device identity kept in {auth.TOKEN_DIR / 'device_uuid'}")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", default=argparse.SUPPRESS, help="Server URL (overrides NCRYPTED_SERVER).")


def build_parser() -> argparse.ArgumentParser:
    prog = Path(sys.argv[0]).name or "ncrypted"
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Secure encrypted file sharing from the terminal.",
        epilog=(
            "Examples:\n"
            f"  {prog}                          # show settings\n"
            f"  {prog} SLUG                     # download by slug or URL\n"
            f"  {prog} /path/to/file.ext        # upload a file\n"
            f"  {prog} upload FILE --public\n"
            f"  {prog} download SLUG -o /tmp\n"
            f"  {prog} decrypt FILE.enc          # decrypt a saved download\n"
            f"  {prog} list                     # add --full or --json\n"
            f"  {prog} info SLUG\n"
            f"  {prog} delete SLUG -y\n"
            f"  {prog} log-out\n"
            "\n"
            f"Run '{prog} COMMAND --help' for the full options of any command."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--server", help="Server URL (overrides NCRYPTED_SERVER).")
    parser.add_argument("--max-up", dest="global_max_up", metavar="RATE", help="Default upload speed limit.")
    parser.add_argument("--max-down", dest="global_max_down", metavar="RATE", help="Default download speed limit.")

    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List uploaded files.")
    _add_common(list_parser)
    list_parser.add_argument("--full", action="store_true", help="Show every field per file.")
    list_parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON.")
    list_parser.set_defaults(func=cmd_list)

    info_parser = subparsers.add_parser("info", help="Show file information.")
    _add_common(info_parser)
    info_parser.add_argument("slug", help="File slug or URL.")
    info_parser.add_argument("--show-private", action="store_true", help="Decrypt private description.")
    info_parser.add_argument("--passphrase", help="Passphrase for private description.")
    info_parser.set_defaults(func=cmd_info)

    upload_parser = subparsers.add_parser("upload", help="Encrypt and upload a file.")
    _add_common(upload_parser)
    upload_parser.add_argument("path", help="File or directory path.")
    visibility = upload_parser.add_mutually_exclusive_group()
    visibility.add_argument("--public", dest="public", action="store_true", help="Make file public.")
    visibility.add_argument("--no-public", dest="public", action="store_false", help="Keep file private.")
    upload_parser.set_defaults(public=False)
    upload_parser.add_argument("--passphrase", help="Encryption passphrase.")
    upload_parser.add_argument("--public-desc", help="Public description text.")
    upload_parser.add_argument("--private-desc", help="Private description, encrypted client-side.")
    upload_parser.add_argument("--archive", action="store_true", help="Wrap encrypted upload data in a ZIP archive.")
    upload_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation.")
    upload_parser.add_argument("--max-up", metavar="RATE", help="Throttle upload speed for this transfer.")
    upload_parser.set_defaults(func=cmd_upload)

    download_parser = subparsers.add_parser("download", help="Download and decrypt a file.")
    _add_common(download_parser)
    download_parser.add_argument("slug", help="File slug or URL.")
    download_parser.add_argument("--passphrase", help="Decryption passphrase.")
    download_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file path, or an existing directory to keep the original name.",
    )
    download_parser.add_argument("-x", "--extract", action="store_true", help="Extract the archive after decrypting (default: keep the archive file).")
    download_parser.add_argument("--max-down", metavar="RATE", help="Throttle download speed for this transfer.")
    download_parser.set_defaults(func=cmd_download)

    decrypt_parser = subparsers.add_parser("decrypt", help="Decrypt a previously downloaded .enc file (offline).")
    decrypt_parser.add_argument("path", help="Path to the encrypted .enc file.")
    decrypt_parser.add_argument("--passphrase", help="Decryption passphrase.")
    decrypt_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file path, or an existing directory to keep the original name.",
    )
    decrypt_parser.add_argument("-x", "--extract", action="store_true", help="Extract the archive after decrypting (default: keep the archive file).")
    decrypt_parser.add_argument("-r", "--remove", action="store_true", help="Delete the encrypted source file after a successful decrypt.")
    decrypt_parser.set_defaults(func=cmd_decrypt)

    update_parser = subparsers.add_parser("update", help="Update public/private description.")
    _add_common(update_parser)
    update_parser.add_argument("slug", help="File slug or URL.")
    update_parser.add_argument("--public-desc", help="New public description.")
    update_parser.add_argument("--private-desc", help="New private description, encrypted client-side.")
    update_parser.add_argument("--passphrase", help="Passphrase for private description.")
    update_parser.set_defaults(func=cmd_update)

    delete_parser = subparsers.add_parser("delete", help="Delete a file.")
    _add_common(delete_parser)
    delete_parser.add_argument("slug", help="File slug or URL.")
    delete_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation.")
    delete_parser.set_defaults(func=cmd_delete)

    register_parser = subparsers.add_parser("register-user", help="Register a permanent user account.")
    _add_common(register_parser)
    register_parser.set_defaults(func=cmd_register_user)

    login_parser = subparsers.add_parser("login-user", help="Login with a permanent user account.")
    _add_common(login_parser)
    login_parser.set_defaults(func=cmd_login_user)

    settings_parser = subparsers.add_parser("settings", help="Print resolved client settings.")
    _add_common(settings_parser)
    settings_parser.set_defaults(func=cmd_settings)

    logout_parser = subparsers.add_parser("log-out", aliases=["logout"], help="Clear saved auth session.")
    _add_common(logout_parser)
    logout_parser.set_defaults(func=cmd_logout)

    return parser


def _first_positional_index(argv: list[str]) -> int | None:
    skip_next = False
    for index, token in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            return index + 1 if index + 1 < len(argv) else None
        if token in GLOBAL_OPTIONS_WITH_VALUE:
            skip_next = True
            continue
        if any(token.startswith(f"{option}=") for option in GLOBAL_OPTIONS_WITH_VALUE):
            continue
        if token.startswith("-"):
            continue
        return index
    return None


def _normalize_argv(argv: list[str]) -> list[str]:
    index = _first_positional_index(argv)
    if index is None:
        return argv
    if argv[index] in COMMANDS:
        return argv
    command = "upload" if _looks_like_upload_path(argv[index]) else "download"
    return [*argv[:index], command, *argv[index:]]


def _looks_like_upload_path(value: str) -> bool:
    if value.startswith(("http://", "https://")):
        return False
    path = Path(value).expanduser()
    if path.exists():
        return True
    return value.startswith(("/", "./", "../", "~")) or "/" in value or "\\" in value


def run(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(argv))

    server = getattr(args, "server", None)
    max_up = getattr(args, "global_max_up", None)
    max_down = getattr(args, "global_max_down", None)
    try:
        settings = load_settings(server, max_up, max_down)
    except ValueError as e:
        _fail(str(e))

    # One ncrypted process at a time per machine, so the client cannot be turned
    # into a parallel request generator against the server.
    try:
        instance.acquire()
    except instance.AlreadyRunning as e:
        _fail(str(e))

    if not getattr(args, "command", None):
        _print_intro(settings)
        _maybe_check_update(args, settings)
        return

    try:
        args.func(args, settings)
    except KeyboardInterrupt:
        ui.err("Aborted.")
        raise SystemExit(1)
    _maybe_register_cta(args, settings)
    _maybe_check_update(args, settings)
