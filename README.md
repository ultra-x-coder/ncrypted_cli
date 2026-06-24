# Ncrypted terminal client

Small encrypted file sharing client for `https://ncrypted.app`.

Files are compressed and encrypted locally before upload. The server receives
only the encrypted blob plus metadata needed for integrity checks.

## User Install

The public install command is:

```bash
curl -fsSL https://ncrypted.app/install.sh | sh
```

The installer downloads the right `ncrypted` binary for the current OS and CPU,
verifies `SHA256SUMS`, and installs it to:

```bash
~/.local/bin/ncrypted
```

Override the install directory:

```bash
curl -fsSL https://ncrypted.app/install.sh | NCRYPTED_INSTALL_DIR=/usr/local/bin sh
```

Use GitHub Releases directly instead of the `ncrypted.app` mirror:

```bash
curl -fsSL https://ncrypted.app/install.sh | \
  NCRYPTED_DOWNLOAD_BASE_URL=https://github.com/OWNER/REPO/releases/latest/download sh
```

## Configuration

Supported environment variables:

```bash
NCRYPTED_BRAND=Ncrypted
NCRYPTED_SERVER=https://ncrypted.app
NCRYPTED_MAX_UP=1m
NCRYPTED_MAX_DOWN=5m
```

`--server` overrides `NCRYPTED_SERVER`.

## Usage

```bash
ncrypted
ncrypted SLUG
ncrypted /path/to/file.ext
ncrypted upload /path/to/file.ext
ncrypted list
ncrypted list --json
ncrypted info SLUG
ncrypted download SLUG -o /tmp
ncrypted download SLUG -o /tmp/new-name.ext
ncrypted update SLUG --public-desc "new caption"
ncrypted delete SLUG -y
ncrypted register-user
ncrypted login-user
ncrypted log-out
ncrypted settings
```

For downloads, `-o` accepts a new file path. If it points to an existing
directory, the client saves into that directory using the original file name.

Run `ncrypted --help` for the full command guide.

## Local Binary Build

```bash
scripts/build-binary.sh
scripts/package-binary.sh
```

Outputs:

```bash
dist/ncrypted
dist/release/ncrypted-<os>-<arch>.tar.gz
dist/release/ncrypted-<os>-<arch>.zip
```

macOS signing is automatic when this variable is set:

```bash
NCRYPTED_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
  scripts/build-binary.sh
```

## Release Flow

The public command is always `ncrypted`.

Short version:

1. Create the GitHub Secrets for Apple signing.
2. Push a tag such as `v1.0.0`.
3. GitHub Actions builds Linux and macOS artifacts.
4. The release job publishes artifacts plus `SHA256SUMS`.
5. Mirror the release files to `https://ncrypted.app/releases/latest/`.
6. Serve this repository's `install.sh` at `https://ncrypted.app/install.sh`.

Expected hosted files:

```text
https://ncrypted.app/install.sh
https://ncrypted.app/releases/latest/ncrypted-linux-x86_64.tar.gz
https://ncrypted.app/releases/latest/ncrypted-linux-arm64.tar.gz
https://ncrypted.app/releases/latest/ncrypted-macos-x86_64.zip
https://ncrypted.app/releases/latest/ncrypted-macos-arm64.zip
https://ncrypted.app/releases/latest/SHA256SUMS
```

## Apple Developer Secrets

For signed and notarized macOS builds, add these GitHub Secrets:

```text
MACOS_CERTIFICATE_P12
MACOS_CERTIFICATE_PASSWORD
APPLE_ID
APPLE_TEAM_ID
APPLE_APP_SPECIFIC_PASSWORD
```

`MACOS_CERTIFICATE_P12` must be a base64-encoded Developer ID Application `.p12`
certificate:

```bash
base64 -i DeveloperIDApplication.p12 | pbcopy
```

If the Apple secrets are absent, macOS artifacts are still built, but they are
not signed or notarized.

See [docs/releasing.md](docs/releasing.md) for the full step-by-step release
guide.
