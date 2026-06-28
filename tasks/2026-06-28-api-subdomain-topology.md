# CLI: переезд API на поддомен `api.ncrypted.app`

**Дата:** 2026-06-28
**Статус:** требуется правка кода (этот документ — инструкция, сам код не менялся)

## Контекст: новая топология nginx

В `syphr_filesharing/deploy/nginx.conf` трафик разделён по двум хостам:

| Хост | Что обслуживает | Пути |
|---|---|---|
| `https://ncrypted.app` | веб-клиент (UI) + статика с диска | `/`, `/login`, `/register`, `/dashboard`, `/install.sh`, `/releases/`, `/static/` |
| `https://api.ncrypted.app` | бэкенд-API (этот CLI ходит сюда) | `/upload`, `/d/{slug}`, `/info/{slug}`, `/auth/*`, `POST /register`, `/files`, `/account/limits`, `/challenge/` |

Дополнительно в бэкенде выставляется `SYPHR_BASE_URL=https://api.ncrypted.app`, поэтому
ссылки на скачивание, которые отдаёт сервер (`data["url"]`), теперь вида
`https://api.ncrypted.app/d/{slug}`.

**Проблема:** CLI использует единственный base-URL `settings.server`
(по умолчанию `https://ncrypted.app`) сразу для трёх разных групп ресурсов,
которые теперь живут на разных хостах:

1. **API-вызовы** (`ncrypted_cli/api.py`) — `/upload`, `/d/`, `/info/`, `/auth/*`,
   `/register`, `/files`, `/account/limits`. → должны идти на `api.ncrypted.app`.
2. **Проверка версии** (`version_check.py`) — `/releases/latest/VERSION`.
   → живёт на апексе `ncrypted.app`, **не** на API-хосте.
3. **Ссылки на страницы аккаунта** (`cli.py:_account_urls`) — регистрация/логин в браузере.
   → живут на апексе `ncrypted.app`.

Если просто переключить `server` на `api.ncrypted.app`, то сломаются (2) и (3);
если оставить `ncrypted.app`, сломаются все API-вызовы (1). Нужны **две** базы.

## Что уже корректно (менять НЕ нужно)

- `version_check.py:26` `INSTALL_URL = "https://ncrypted.app/install.sh"` — апекс, верно.
- `install.sh:10` `BASE_URL=...https://ncrypted.app/releases/$VERSION` — апекс, верно.
- `actions.py:51 extract_slug()` — берёт только последний сегмент пути и игнорирует хост,
  поэтому вставка ссылок вида `api.ncrypted.app/d/SLUG` или `ncrypted.app/s/SLUG`
  одинаково корректно извлекает slug. Скачивание затем идёт на `settings.server`.

## Требуемые изменения

### 1. Ввести вторую базу — «сайт/апекс» — и переключить API-базу на поддомен

**`ncrypted_cli/config.py`**

```python
# было
DEFAULT_SERVER = "https://ncrypted.app"

# стало
DEFAULT_SERVER = "https://api.ncrypted.app"   # API-хост: upload/download/auth/account
DEFAULT_SITE   = "https://ncrypted.app"        # апекс: веб-UI + /releases/ + /install.sh
```

Добавить поле `site` в `Settings` и резолвить его в `load_settings()`:

```python
@dataclass
class Settings:
    server: str
    site: str            # NEW
    brand: str
    max_up: int | None = None
    max_down: int | None = None
```

```python
def load_settings(server_opt=None, max_up_opt=None, max_down_opt=None) -> Settings:
    load_env_files()
    server = (server_opt or os.getenv("NCRYPTED_SERVER") or DEFAULT_SERVER).rstrip("/")
    site   = (os.getenv("NCRYPTED_SITE_URL") or DEFAULT_SITE).rstrip("/")   # NEW
    ...
    return Settings(server=server, site=site, brand=brand, max_up=max_up, max_down=max_down)
```

> Если нужно автодеривить `site` из `--server` при кастомном сервере — можно
> при незаданном `NCRYPTED_SITE_URL` снимать префикс `api.` с хоста `server`.
> Но это хрупко для `localhost`/нестандартных портов, поэтому отдельная env-переменная
> `NCRYPTED_SITE_URL` предпочтительнее.

### 2. Проверка версии должна брать апекс, а не API-хост

**`ncrypted_cli/cli.py`** (функция `_maybe_check_update`, ~строка 78):

```python
# было
version_check.maybe_notify_update(settings.server)
# стало
version_check.maybe_notify_update(settings.site)
```

`version_check._version_url()` строит `{base}/releases/latest/VERSION`; передавать туда
`settings.site` (апекс). Сигнатуру `maybe_notify_update(server)` можно оставить —
важно лишь, какой URL приходит. (Опционально переименовать параметр в `site`.)

### 3. URL страниц аккаунта: правильный хост И правильный путь

**`ncrypted_cli/cli.py`** (`_account_urls`, ~строка 88):

```python
# было
def _account_urls(server: str) -> tuple[str, str]:
    base = server.rstrip("/")
    return f"{base}/web/login", f"{base}/web/register"

# стало
def _account_urls(site: str) -> tuple[str, str]:
    base = site.rstrip("/")
    return f"{base}/login", f"{base}/register"
```

Две правки:
- **Хост:** передавать `settings.site` (апекс), а не `settings.server`.
  Обновить всех вызывающих — сейчас это `cli.py:~72`
  (`_, register_url = _account_urls(settings.server)` → `settings.site`).
  Проверить грепом: `grep -rn "_account_urls(" ncrypted_cli/`.
- **Путь:** веб-клиент отдаёт страницы на `/login` и `/register`, а **не** `/web/login` /
  `/web/register` (такого маршрута нет — сейчас это 404 в любом случае). Убрать `/web`.

### 4. Конфиг `.env` (в этом репозитории)

```ini
# было
NCRYPTED_SERVER=https://ncrypted.app
# стало
NCRYPTED_SERVER=https://api.ncrypted.app
# (опционально, если включён сайт-override)
# NCRYPTED_SITE_URL=https://ncrypted.app
```

### 5. Документация (функционально не критично, но привести в соответствие)

- `README.md:43` — `NCRYPTED_SERVER=https://ncrypted.app` → `https://api.ncrypted.app`
  (плюс упомянуть `NCRYPTED_SITE_URL`, если он введён).
- `README.md:82` — пример `ncrypted https://ncrypted.app/s/SLUG`: путь скачивания — `/d/`,
  а ссылки теперь на `api.ncrypted.app`; привести к `https://api.ncrypted.app/d/SLUG`
  (хост в аргументе не важен для работы, но пример должен быть верным).
- `docs/releasing.md` — раздел про хостинг релизов: `/install.sh` и `/releases/` остаются
  на `ncrypted.app` (апекс) — это уже верно, просто подтвердить.

## Проверка после правок

1. `ncrypted --help` / запуск без аргументов — баннер регистрации показывает
   `https://ncrypted.app/register` (апекс).
2. Загрузка файла идёт на `https://api.ncrypted.app/upload`; в выводе `URL` —
   `https://api.ncrypted.app/d/{slug}`.
3. Скачивание по вставленной ссылке (любого хоста) и по голому slug работает.
4. Проверка обновлений дергает `https://ncrypted.app/releases/latest/VERSION` (апекс),
   а не `api.*` (иначе будет 404 и тихо отключится).
5. `NCRYPTED_SERVER` / `--server` по-прежнему переопределяют API-хост;
   `NCRYPTED_SITE_URL` (если введён) — апекс.
