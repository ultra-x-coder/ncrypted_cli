#!/bin/sh
set -eu

APP_NAME="${NCRYPTED_APP_NAME:-ncrypted}"
RELEASE_DIR="${NCRYPTED_RELEASE_DIR:-dist/release}"
BUNDLE_DIR="${NCRYPTED_BUNDLE_DIR:-dist/$APP_NAME}"

if [ ! -d "$BUNDLE_DIR" ] || [ ! -e "$BUNDLE_DIR/$APP_NAME" ]; then
    echo "error: onedir bundle not found: $BUNDLE_DIR" >&2
    echo "       run scripts/build-binary.sh first" >&2
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

# Archive the whole onedir tree (launcher + _internal/) preserving symlinks, so
# the embedded framework structure and its code signatures stay intact.
parent="$(cd "$(dirname "$BUNDLE_DIR")" && pwd)"
base="$(basename "$BUNDLE_DIR")"
release_abs="$(cd "$RELEASE_DIR" && pwd)"

if [ "$os" = "macos" ]; then
    artifact="$RELEASE_DIR/$APP_NAME-$target.zip"
    artifact_abs="$release_abs/$APP_NAME-$target.zip"
    rm -f "$artifact"
    # ditto is Apple's recommended archiver for notarization: it keeps the
    # framework's symlinks, extended attributes, and embedded signatures intact.
    # --keepParent puts the whole bundle under a top-level "$base/" directory.
    ( cd "$parent" && ditto -c -k --keepParent "$base" "$artifact_abs" )
else
    artifact="$RELEASE_DIR/$APP_NAME-$target.tar.gz"
    rm -f "$artifact"
    tar -czf "$artifact" -C "$parent" "$base"
fi

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$RELEASE_DIR" && sha256sum "$(basename "$artifact")" > "$(basename "$artifact").sha256")
else
    (cd "$RELEASE_DIR" && LC_ALL=C shasum -a 256 "$(basename "$artifact")" > "$(basename "$artifact").sha256")
fi

echo "$artifact"
