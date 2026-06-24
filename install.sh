#!/bin/sh
set -eu

APP_NAME="ncrypted"
VERSION="${NCRYPTED_VERSION:-latest}"
INSTALL_DIR="${NCRYPTED_INSTALL_DIR:-$HOME/.local/bin}"
BASE_URL="${NCRYPTED_DOWNLOAD_BASE_URL:-https://ncrypted.app/releases/$VERSION}"

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "error: $1 is required" >&2
        exit 1
    fi
}

download() {
    url="$1"
    dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$dest"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$dest" "$url"
    else
        echo "error: curl or wget is required" >&2
        exit 1
    fi
}

sha256_file() {
    file="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        LC_ALL=C shasum -a 256 "$file" | awk '{print $1}'
    else
        echo "error: sha256sum or shasum is required" >&2
        exit 1
    fi
}

detect_target() {
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

    printf "%s-%s" "$os" "$arch"
}

target="$(detect_target)"
case "$target" in
    macos-*) artifact="$APP_NAME-$target.zip" ;;
    *) artifact="$APP_NAME-$target.tar.gz" ;;
esac

tmp="$(mktemp -d 2>/dev/null || mktemp -d -t ncrypted)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

artifact_url="$BASE_URL/$artifact"
checksums_url="$BASE_URL/SHA256SUMS"

echo "Downloading $artifact_url"
download "$artifact_url" "$tmp/$artifact"

echo "Verifying checksum"
download "$checksums_url" "$tmp/SHA256SUMS"
expected="$(awk -v name="$artifact" '$2 == name { print $1 }' "$tmp/SHA256SUMS" | head -n 1)"
if [ -z "$expected" ]; then
    echo "error: checksum for $artifact not found in SHA256SUMS" >&2
    exit 1
fi
actual="$(sha256_file "$tmp/$artifact")"
if [ "$expected" != "$actual" ]; then
    echo "error: checksum mismatch for $artifact" >&2
    echo "expected: $expected" >&2
    echo "actual:   $actual" >&2
    exit 1
fi

case "$artifact" in
    *.zip)
        need_cmd unzip
        unzip -q "$tmp/$artifact" -d "$tmp/unpack"
        ;;
    *.tar.gz)
        need_cmd tar
        mkdir -p "$tmp/unpack"
        tar -xzf "$tmp/$artifact" -C "$tmp/unpack"
        ;;
    *)
        echo "error: unsupported artifact format: $artifact" >&2
        exit 1
        ;;
esac

if [ ! -f "$tmp/unpack/$APP_NAME" ]; then
    echo "error: artifact did not contain $APP_NAME" >&2
    exit 1
fi

mkdir -p "$INSTALL_DIR"
cp "$tmp/unpack/$APP_NAME" "$INSTALL_DIR/$APP_NAME"
chmod 755 "$INSTALL_DIR/$APP_NAME"

echo "Installed $APP_NAME to $INSTALL_DIR/$APP_NAME"

case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
        echo ""
        echo "$INSTALL_DIR is not in PATH."
        echo "Add this to your shell profile:"
        echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
        ;;
esac

echo ""
echo "Done. Try: $APP_NAME"
