#!/bin/sh
set -eu

APP_NAME="${NCRYPTED_APP_NAME:-ncrypted}"
RELEASE_DIR="${NCRYPTED_RELEASE_DIR:-dist/release}"
BINARY_PATH="${NCRYPTED_BINARY_PATH:-dist/$APP_NAME}"

if [ ! -f "$BINARY_PATH" ]; then
    echo "error: binary not found: $BINARY_PATH" >&2
    exit 1
fi

os="$(uname -s)"
arch="$(uname -m)"

case "$os" in
    Linux) os="linux" ;;
    Darwin) os="macos" ;;
    *)
        echo "error: unsupported OS: $os" >&2
        exit 1
        ;;
esac

case "$arch" in
    x86_64|amd64) arch="x86_64" ;;
    arm64|aarch64) arch="arm64" ;;
    *)
        echo "error: unsupported architecture: $arch" >&2
        exit 1
        ;;
esac

target="${NCRYPTED_TARGET:-$os-$arch}"
mkdir -p "$RELEASE_DIR"

if [ "$os" = "macos" ]; then
    artifact="$RELEASE_DIR/$APP_NAME-$target.zip"
    artifact_abs="$(pwd)/$artifact"
    rm -f "$artifact"
    tmp="$(mktemp -d 2>/dev/null || mktemp -d -t ncrypted-package)"
    trap 'rm -rf "$tmp"' EXIT HUP INT TERM
    cp "$BINARY_PATH" "$tmp/$APP_NAME"
    chmod 755 "$tmp/$APP_NAME"
    (cd "$tmp" && zip -q "$artifact_abs" "$APP_NAME")
else
    artifact="$RELEASE_DIR/$APP_NAME-$target.tar.gz"
    rm -f "$artifact"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT HUP INT TERM
    cp "$BINARY_PATH" "$tmp/$APP_NAME"
    chmod 755 "$tmp/$APP_NAME"
    tar -czf "$artifact" -C "$tmp" "$APP_NAME"
fi

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$RELEASE_DIR" && sha256sum "$(basename "$artifact")" > "$(basename "$artifact").sha256")
else
    (cd "$RELEASE_DIR" && LC_ALL=C shasum -a 256 "$(basename "$artifact")" > "$(basename "$artifact").sha256")
fi

echo "$artifact"
