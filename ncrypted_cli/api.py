"""Thin httpx wrapper around the Ncrypted server API.

One method per endpoint. Non-2xx (other than the special-cased 410 tombstone)
is mapped to ApiError(status, detail). The 401 -> re-register -> retry-once
pattern is centralized here (mirrors the reference _retry_on_401), including the
open-coded variants for streaming download and multipart upload where the body
cannot be replayed.
"""

import httpx

from . import auth
from .progress import ProgressReader, make_progress
from .throttle import RateLimiter


SERVER_UNAVAILABLE_MESSAGE = "Server unavailable, please try again later."


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"({status}) {detail}")


class ServerUnavailable(Exception):
    def __init__(self):
        super().__init__(SERVER_UNAVAILABLE_MESSAGE)


class Tombstone(Exception):
    """A 410: file was deleted."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and "detail" in data:
            return str(data["detail"])
    except Exception:
        pass
    return resp.text or f"HTTP {resp.status_code}"


def _server_unavailable(exc: httpx.RequestError) -> ServerUnavailable:
    return ServerUnavailable()


class NcryptedClient:
    def __init__(self, server: str):
        self.server = server.rstrip("/")

    # --- token bootstrap (mirrors reference ensure_token) ---

    def ensure_token(self) -> str:
        token = auth.load_token()
        if token:
            return token
        mode = auth.get_auth_mode()
        if mode == "user":
            # Preserve reference behaviour: never silently downgrade a
            # logged-out user account back to device auth.
            raise auth.AuthError(
                "Device linked to user account. Run 'ncrypted login-user' to re-authenticate."
            )
        device_hash = auth.get_device_hash()
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(f"{self.server}/register", json={"device_hash": device_hash})
        except httpx.RequestError as e:
            raise _server_unavailable(e) from e
        if resp.status_code == 403:
            raise auth.AuthError(
                "Device linked to permanent account. Run 'ncrypted login-user'."
            )
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        token = resp.json()["token"]
        auth.save_token(token)
        return token

    # --- generic retry-on-401 (non-streaming, replayable bodies) ---

    def _request(self, method: str, url: str, **kwargs):
        token = self.ensure_token()
        hdrs = auth.auth_headers(token)
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.request(method, url, headers=hdrs, **kwargs)
                if resp.status_code == 401:
                    auth.delete_token()
                    token = self.ensure_token()
                    hdrs = auth.auth_headers(token)
                    resp = client.request(method, url, headers=hdrs, **kwargs)
        except httpx.RequestError as e:
            raise _server_unavailable(e) from e
        return resp

    # --- auth endpoints (no bearer token needed) ---

    def register_device(self, device_hash: str) -> dict:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(f"{self.server}/register", json={"device_hash": device_hash})
        except httpx.RequestError as e:
            raise _server_unavailable(e) from e
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    def auth_register(self, username: str, password: str) -> dict:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{self.server}/auth/register",
                    json={"username": username, "password": password},
                )
        except httpx.RequestError as e:
            raise _server_unavailable(e) from e
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    def auth_login(self, username: str, password: str, device_hash: str) -> dict:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{self.server}/auth/login",
                    json={"username": username, "password": password, "device_hash": device_hash},
                )
        except httpx.RequestError as e:
            raise _server_unavailable(e) from e
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    # --- file metadata endpoints ---

    def list_files(self) -> list[dict]:
        resp = self._request("GET", f"{self.server}/files")
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    def account_limits(self) -> dict:
        resp = self._request("GET", f"{self.server}/account/limits")
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    def info(self, slug: str) -> dict:
        resp = self._request("GET", f"{self.server}/info/{slug}")
        if resp.status_code == 410:
            data = resp.json()
            raise Tombstone(data.get("detail", "File was deleted"))
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    def update(self, slug: str, body: dict) -> dict:
        # PATCH 400s on an empty body; only send json when non-empty.
        resp = self._request("PATCH", f"{self.server}/files/{slug}", json=body)
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    def delete(self, slug: str, body: dict | None = None) -> dict:
        # Server tolerates a missing body for delete; only send when non-empty.
        kwargs = {"json": body} if body else {}
        resp = self._request("DELETE", f"{self.server}/files/{slug}", **kwargs)
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    # --- upload (multipart, real progress bar via ProgressReader) ---

    def upload(self, blob: bytes, fields: dict, *, max_up: int | None = None) -> dict:
        token = self.ensure_token()
        total = len(blob)

        def _send(client: httpx.Client, tok: str) -> httpx.Response:
            # Fresh progress + fresh reader (and limiter) per attempt: the reader
            # is consumed after one send and cannot be replayed.
            with make_progress() as progress:
                task = progress.add_task("Uploading", total=total)
                reader = ProgressReader(blob, progress, task, limiter=RateLimiter(max_up))
                return client.post(
                    f"{self.server}/upload",
                    files={"file": ("blob", reader, "application/octet-stream")},
                    data=fields,
                    headers=auth.auth_headers(tok),
                )

        try:
            with httpx.Client(timeout=60) as client:
                resp = _send(client, token)
                if resp.status_code == 401:
                    auth.delete_token()
                    token = self.ensure_token()
                    resp = _send(client, token)
        except httpx.RequestError as e:
            raise _server_unavailable(e) from e

        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    # --- download (streaming, real progress bar via iter_bytes) ---

    def download(self, slug: str, *, fallback_total: int | None = None, max_down: int | None = None) -> bytes:
        token = self.ensure_token()
        limiter = RateLimiter(max_down)

        def _stream(client: httpx.Client, tok: str):
            hdrs = auth.auth_headers(tok)
            return client.stream("GET", f"{self.server}/d/{slug}", headers=hdrs)

        try:
            with httpx.Client(timeout=60) as client:
                ctx = _stream(client, token)
                resp = ctx.__enter__()
                try:
                    if resp.status_code == 401:
                        # Streamed response cannot be replayed; close + re-open.
                        ctx.__exit__(None, None, None)
                        auth.delete_token()
                        token = self.ensure_token()
                        ctx = _stream(client, token)
                        resp = ctx.__enter__()

                    if resp.status_code == 410:
                        resp.read()
                        data = resp.json()
                        raise Tombstone(data.get("detail", "File was deleted"))

                    if resp.status_code != 200:
                        resp.read()
                        raise ApiError(resp.status_code, _detail(resp))

                    # Prefer Content-Length (encrypted blob size = bytes on the
                    # wire). Fall back to plaintext original_size only if missing.
                    total = int(resp.headers.get("Content-Length", 0)) or fallback_total
                    chunks = bytearray()
                    with make_progress() as progress:
                        task = progress.add_task("Downloading", total=total or None)
                        for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                            chunks.extend(chunk)
                            limiter.throttle(len(chunk))
                            progress.update(task, advance=len(chunk))
                    return bytes(chunks)
                finally:
                    ctx.__exit__(None, None, None)
        except httpx.RequestError as e:
            raise _server_unavailable(e) from e
