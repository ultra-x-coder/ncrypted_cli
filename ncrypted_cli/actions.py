"""Shared action functions used by the plain CLI commands.

Each action raises on hard failure:
  - api.ApiError      -> server returned non-2xx
  - api.Tombstone     -> 410 (deleted file)
  - auth.AuthError    -> cannot authenticate
  - CryptoFailure     -> wrong passphrase / corrupt blob
  - ValueError        -> bad local input (e.g. nothing to update)
Callers (cli/interactive) decide how to present/exit.
"""

import hashlib
import tarfile
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from . import auth
from .api import NcryptedClient
from .crypto import decrypt_blob, decrypt_text, encrypt_blob, encrypt_text
from .progress import spinner
from .ui import human_bytes


class CryptoFailure(Exception):
    """Decryption failed — wrong passphrase or corrupt data."""


ARCHIVE_SUFFIXES = {
    ".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".zst", ".zstd", ".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst",
}


class ArchiveWouldNotShrink(Exception):
    """Encrypted data is expected not to shrink when archived."""

    def __init__(self, source_size: int, estimated_size: int, reason: str):
        self.source_size = source_size
        self.archive_size = estimated_size
        self.reason = reason
        super().__init__(
            f"Archive is unlikely to shrink the encrypted file ({estimated_size} >= {source_size} bytes): {reason}."
        )


# --- helpers (safe_filename / extract_slug copied verbatim from reference) ---


def extract_slug(url_or_slug: str) -> str:
    if "/" in url_or_slug:
        path = urlparse(url_or_slug).path
        return path.rstrip("/").split("/")[-1]
    return url_or_slug


def safe_filename(directory: Path, name: str) -> Path:
    safe_name = Path(name).name
    if safe_name in {"", ".", ".."}:
        safe_name = "download.bin"
    target = directory / safe_name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _archive_stem(name: str) -> str:
    lowered = name.lower()
    for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if lowered.endswith(suffix):
            return name[: -len(suffix)] or "archive"
    return Path(name).stem or "archive"


def _is_archive_name(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _source_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _create_zip_archive(path: Path) -> tuple[bytes, str, int, int]:
    source_size = _source_size(path)
    archive_name = f"{path.name.rstrip('/')}.zip"
    with TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir, archive_name)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            if path.is_file():
                zf.write(path, arcname=path.name)
            else:
                root = path.resolve()
                for child in sorted(path.rglob("*")):
                    arcname = Path(path.name) / child.resolve().relative_to(root)
                    if child.is_dir():
                        zf.writestr(str(arcname).rstrip("/") + "/", b"")
                    elif child.is_file():
                        zf.write(child, arcname=str(arcname))
        archive_size = archive_path.stat().st_size
        return archive_path.read_bytes(), archive_name, source_size, archive_size


def _create_zip_from_bytes(data: bytes, archive_name: str, member_name: str) -> tuple[bytes, int, int]:
    with TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir, archive_name)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr(member_name, data)
        archive_size = archive_path.stat().st_size
        return archive_path.read_bytes(), len(data), archive_size


def _unwrap_encrypted_archive(blob: bytes) -> bytes:
    with TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir, "payload.zip")
        archive_path.write_bytes(blob)
        try:
            with zipfile.ZipFile(archive_path) as zf:
                members = [info for info in zf.infolist() if not info.is_dir()]
                if len(members) != 1:
                    return blob
                with zf.open(members[0]) as src:
                    return src.read()
        except zipfile.BadZipFile:
            return blob


def _safe_child(base: Path, name: str) -> Path:
    target = (base / name).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise ValueError(f"Unsafe archive member path: {name}")
    return target


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            target = _safe_child(dest_dir, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                out.write(src.read())


def _extract_tar(archive_path: Path, dest_dir: Path) -> None:
    with tarfile.open(archive_path, mode="r:*") as tf:
        for member in tf.getmembers():
            target = _safe_child(dest_dir, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with src, target.open("wb") as out:
                out.write(src.read())


def _extract_archive_file(
    archive_path: Path,
    original_filename: str,
    output: Path,
    *,
    exact_output: bool = False,
) -> Path | None:
    lowered = original_filename.lower()
    if exact_output:
        if output.exists():
            raise ValueError(f"Output path already exists: {output}")
        extract_dir = output
    else:
        output.mkdir(parents=True, exist_ok=True)
        extract_dir = safe_filename(output, _archive_stem(original_filename))
    if lowered.endswith(".zip"):
        extract_dir.mkdir(parents=True, exist_ok=False)
        _extract_zip(archive_path, extract_dir)
        return extract_dir
    if any(lowered.endswith(s) for s in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        extract_dir.mkdir(parents=True, exist_ok=False)
        _extract_tar(archive_path, extract_dir)
        return extract_dir
    return None


def _save_downloaded_file(plaintext: bytes, output: Path, original_filename: str, *, exact_output: bool) -> Path:
    if exact_output:
        if output.exists():
            raise ValueError(f"Output file already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        dest = output
    else:
        output.mkdir(parents=True, exist_ok=True)
        dest = safe_filename(output, original_filename)
    dest.write_bytes(plaintext)
    return dest


# --- actions ---


def do_list(server: str) -> list[dict]:
    return NcryptedClient(server).list_files()


def do_account_limits(server: str) -> dict:
    return NcryptedClient(server).account_limits()


def do_info(server: str, slug: str) -> dict:
    return NcryptedClient(server).info(extract_slug(slug))


def decrypt_private_description(info: dict, passphrase: str) -> str | None:
    """Returns decrypted private description or None if not set. Raises
    CryptoFailure on a bad passphrase (callers tolerate it with a warning)."""
    enc = info.get("private_description")
    if not enc:
        return None
    try:
        return decrypt_text(enc, passphrase)
    except Exception as e:
        raise CryptoFailure(str(e))


def do_update(
    server: str,
    slug: str,
    public_desc: str | None,
    private_desc: str | None,
    passphrase: str | None,
    *,
    passphrase_prompt=None,
) -> dict:
    slug = extract_slug(slug)
    body: dict = {}
    if public_desc:
        body["public_description"] = public_desc
    if private_desc:
        if not passphrase:
            if passphrase_prompt is None:
                raise ValueError("Passphrase required to encrypt private description.")
            passphrase = passphrase_prompt()
        body["private_description"] = encrypt_text(private_desc, passphrase)
    if not body:
        raise ValueError("Nothing to update.")
    return NcryptedClient(server).update(slug, body)


def do_delete(
    server: str,
    slug: str,
) -> dict:
    slug = extract_slug(slug)
    return NcryptedClient(server).delete(slug)


def do_upload(
    server: str,
    filepath: Path,
    public: bool,
    passphrase: str,
    public_desc: str | None,
    private_desc: str | None,
    *,
    max_up: int | None = None,
    archive: bool = False,
    yes: bool = False,
    archive_confirm=None,
    archive_info=None,
) -> dict:
    if not filepath.exists():
        raise ValueError(f"File not found: {filepath}")
    if filepath.is_dir() and not archive:
        raise ValueError("Directory upload requires --archive.")

    if filepath.is_dir():
        # A directory needs a single byte payload before encryption. We create
        # that bundle first; the user-facing --archive wrapper still happens
        # after encryption below.
        with spinner("Bundling directory"):
            plaintext, original_filename, _source_size_bytes, _bundle_size = _create_zip_archive(filepath)
    else:
        plaintext = filepath.read_bytes()
        original_filename = filepath.name
    archive_flag = archive or _is_archive_name(original_filename)

    original_size = len(plaintext)
    # content_sha256 and original_size are over the PLAINTEXT (server stores
    # them for integrity). Do NOT hash the encrypted blob.
    content_sha256 = hashlib.sha256(plaintext).hexdigest()

    with spinner("Encrypting file before upload") as enc_status:
        blob = encrypt_blob(plaintext, passphrase)
        enc_status.done(f"Encrypting file before upload ({human_bytes(len(blob))})")

    if archive:
        encrypted_size = len(blob)
        if not yes:
            reason = "encrypted data is usually not compressible"
            if archive_confirm is None:
                raise ArchiveWouldNotShrink(encrypted_size, encrypted_size, reason)
            if not archive_confirm(encrypted_size, encrypted_size, reason):
                raise ValueError("Upload aborted.")
        archive_name = f"{original_filename}.zip"
        with spinner("Creating archive from encrypted data"):
            blob, encrypted_size, archive_size = _create_zip_from_bytes(
                blob,
                archive_name,
                f"{original_filename}.enc",
            )
        if archive_info is not None:
            archive_info(encrypted_size, archive_size)

    fields = {
        "original_filename": original_filename,
        "original_size": str(original_size),
        "content_sha256": content_sha256,
        "public": str(public).lower(),
        "archive": str(archive_flag).lower(),
    }
    if public_desc is not None:
        fields["public_description"] = public_desc
    if private_desc is not None:
        fields["private_description"] = encrypt_text(private_desc, passphrase)

    return NcryptedClient(server).upload(blob, fields, max_up=max_up)


def fetch_encrypted_blob(
    server: str,
    slug: str,
    *,
    info: dict | None = None,
    max_down: int | None = None,
) -> tuple[bytes, dict]:
    """Download the still-encrypted blob (archive wrapper already removed) plus
    its metadata. Decryption is intentionally separate so the caller can retry
    the passphrase against the in-memory blob without re-downloading, and can
    persist the blob if every attempt fails."""
    slug = extract_slug(slug)
    client = NcryptedClient(server)
    if info is None:
        info = client.info(slug)

    blob = client.download(slug, fallback_total=info.get("original_size"), max_down=max_down)
    if info.get("archive"):
        blob = _unwrap_encrypted_archive(blob)
    return blob, info


def is_archive_name(name: str) -> bool:
    return _is_archive_name(name)


def decrypt_and_save(
    blob: bytes,
    passphrase: str,
    output: Path | None,
    original_filename: str,
    is_archive: bool,
    *,
    extract: bool = False,
) -> Path:
    """Decrypt an in-memory blob and write it out. Archives are extracted only
    when `extract` is set (otherwise the archive file is saved as-is). Raises
    CryptoFailure on a wrong passphrase so the caller can retry."""
    explicit_output = output is not None
    output = (output.expanduser() if output is not None else Path.cwd())
    if output.exists() and not output.is_dir():
        raise ValueError(f"Output path already exists and is not a directory: {output}")
    exact_output = explicit_output and not output.is_dir()

    with spinner("Decrypting file"):
        try:
            plaintext = decrypt_blob(blob, passphrase)
        except Exception as e:
            raise CryptoFailure(str(e))

    if is_archive and extract:
        with TemporaryDirectory() as tmp_dir:
            archive_path = Path(tmp_dir, original_filename)
            archive_path.write_bytes(plaintext)
            extracted = _extract_archive_file(
                archive_path,
                original_filename,
                output,
                exact_output=exact_output,
            )
        if extracted is not None:
            return extracted

    return _save_downloaded_file(
        plaintext,
        output,
        original_filename,
        exact_output=exact_output,
    )


def do_download(
    server: str,
    slug: str,
    passphrase: str,
    output: Path | None,
    *,
    info: dict | None = None,
    max_down: int | None = None,
    extract: bool = False,
) -> Path:
    """Single-attempt download + decrypt (kept for callers that already hold the
    passphrase). Returns the path the decrypted file was saved to."""
    blob, info = fetch_encrypted_blob(server, slug, info=info, max_down=max_down)
    return decrypt_and_save(
        blob,
        passphrase,
        output,
        info["original_filename"],
        bool(info.get("archive")),
        extract=extract,
    )


def do_register_user(server: str, username: str, password: str) -> dict:
    return NcryptedClient(server).auth_register(username, password)


def do_login_user(server: str, username: str, password: str) -> dict:
    device_hash = auth.get_device_hash()
    data = NcryptedClient(server).auth_login(username, password, device_hash)
    if data.get("token"):
        auth.save_token(data["token"])
    auth.save_auth_mode("user")
    auth.save_username(username)
    return data
