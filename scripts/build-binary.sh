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

rm -rf build "dist/$APP_NAME"
pyinstaller \
    --clean \
    --onefile \
    --name "$APP_NAME" \
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
    codesign \
        --force \
        --timestamp \
        --options runtime \
        --entitlements "$entitlements" \
        --sign "$NCRYPTED_CODESIGN_IDENTITY" \
        "dist/$APP_NAME"
    codesign --verify --strict --verbose=2 "dist/$APP_NAME"
fi

"dist/$APP_NAME" --help >/dev/null
echo "Built dist/$APP_NAME"
