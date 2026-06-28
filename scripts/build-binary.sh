#!/bin/sh
set -eu

APP_NAME="${NCRYPTED_APP_NAME:-ncrypted}"
PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="${NCRYPTED_BUILD_VENV:-.build/venv}"
ENTRYPOINT="${NCRYPTED_ENTRYPOINT:-ncrypted.py}"

if [ ! -f "$ENTRYPOINT" ]; then
    echo "error: entrypoint not found: $ENTRYPOINT" >&2
    exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

bundle_dir="dist/$APP_NAME"
launcher="$bundle_dir/$APP_NAME"

rm -rf build "$bundle_dir"
# --onedir keeps the interpreter and C-extensions as real files on disk, so the
# OS validates their code signatures once (and caches the result) instead of on
# every launch the way --onefile does: onefile re-extracts the whole interpreter
# to a fresh temp dir each run, which makes macOS re-validate every dylib and
# pushes startup to ~10s.
pyinstaller \
    --clean \
    --onedir \
    --name "$APP_NAME" \
    --add-data "ncrypted_cli/assets/common_passwords_1k.txt:ncrypted_cli/assets" \
    "$ENTRYPOINT"

if [ "$(uname -s)" = "Darwin" ] && [ -n "${NCRYPTED_CODESIGN_IDENTITY:-}" ]; then
    # Hardened runtime + disable-library-validation: the embedded
    # Python.framework is signed with a different Team ID, so without this
    # entitlement macOS refuses to dlopen it at runtime ("different Team IDs").
    entitlements="${NCRYPTED_ENTITLEMENTS:-entitlements.plist}"
    if [ ! -f "$entitlements" ]; then
        echo "error: entitlements file not found: $entitlements" >&2
        exit 1
    fi
    # onedir exposes every Mach-O (dylibs, .so, the CPython framework binary) as
    # a separate file on disk; notarization requires each one signed with a
    # hardened runtime. Sign all nested Mach-O code first, then the launcher last
    # (with entitlements).
    find "$bundle_dir" -type f -print0 \
        | while IFS= read -r -d '' f; do
            [ "$f" = "$launcher" ] && continue
            case "$(file -b "$f" 2>/dev/null)" in
                *Mach-O*)
                    codesign --force --timestamp --options runtime \
                        --sign "$NCRYPTED_CODESIGN_IDENTITY" "$f"
                    ;;
            esac
        done
    codesign \
        --force \
        --timestamp \
        --options runtime \
        --entitlements "$entitlements" \
        --sign "$NCRYPTED_CODESIGN_IDENTITY" \
        "$launcher"
    codesign --verify --strict --verbose=2 "$launcher"
fi

"$launcher" --help >/dev/null
echo "Built $launcher"
