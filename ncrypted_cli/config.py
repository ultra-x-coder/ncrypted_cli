"""Configuration / settings resolution."""

import os
from dataclasses import dataclass
from pathlib import Path

from .throttle import parse_rate

DEFAULT_SERVER = "https://api.ncrypted.app"  # API host: upload/download/auth/account
DEFAULT_SITE = "https://ncrypted.app"  # apex: web UI + /releases/ + /install.sh
DEFAULT_BRAND = "Ncrypted"


@dataclass
class Settings:
    server: str
    site: str
    brand: str
    max_up: int | None = None
    max_down: int | None = None


def _dotenv_paths() -> list[Path]:
    package_root = Path(__file__).resolve().parent.parent
    paths = [package_root / ".env", Path.cwd() / ".env"]
    unique = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env_files() -> None:
    for path in _dotenv_paths():
        if not path.exists():
            continue
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = _strip_quotes(value.strip())
            if key and key not in os.environ:
                os.environ[key] = value


def load_settings(
    server_opt: str | None = None,
    max_up_opt: str | None = None,
    max_down_opt: str | None = None,
) -> Settings:
    load_env_files()
    server = (
        server_opt
        or os.getenv("NCRYPTED_SERVER")
        or DEFAULT_SERVER
    ).rstrip("/")
    site = (
        os.getenv("NCRYPTED_SITE_URL")
        or DEFAULT_SITE
    ).rstrip("/")
    brand = (
        os.getenv("NCRYPTED_BRAND")
        or os.getenv("BRAND_NAME")
        or DEFAULT_BRAND
    )
    max_up_env = os.getenv("NCRYPTED_MAX_UP")
    max_down_env = os.getenv("NCRYPTED_MAX_DOWN")
    max_up = parse_rate(max_up_opt if max_up_opt is not None else max_up_env)
    max_down = parse_rate(max_down_opt if max_down_opt is not None else max_down_env)
    return Settings(server=server, site=site, brand=brand, max_up=max_up, max_down=max_down)
