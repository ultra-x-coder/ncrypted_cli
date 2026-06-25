# Ncrypted terminal client

Small encrypted file sharing client for `https://ncrypted.app`.

Files are compressed and encrypted locally before upload. The server receives
only the encrypted blob plus metadata needed for integrity checks.

## User Install

The public install command is:

```bash
curl -fsSL https://ncrypted.app/install.sh | sh
```

The installer downloads the right `ncrypted` bundle for the current OS and CPU,
verifies `SHA256SUMS`, unpacks it to `~/.local/lib/ncrypted/`, and links the
launcher onto your `PATH`:

```bash
~/.local/bin/ncrypted -> ~/.local/lib/ncrypted/ncrypted
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

Environment variables (also read from a `.env` file in the current directory or
next to the client):

```bash
NCRYPTED_SERVER=https://ncrypted.app    # default server
NCRYPTED_BRAND=Ncrypted                 # display name (or BRAND_NAME)
NCRYPTED_MAX_UP=1m                      # default upload speed limit
NCRYPTED_MAX_DOWN=5m                    # default download speed limit
```

Real environment variables take precedence over `.env` entries. The CLI flags
`--server`, `--max-up`, and `--max-down` override the matching variable.

Speed limits are bytes/sec; suffixes `k`/`m`/`g` are 1000-based and
`ki`/`mi`/`gi` are 1024-based (e.g. `500k`, `1m`, `2mib`). Use `0`, `none`, or
`off` for no limit.

## Usage

Run with no command to print the resolved settings and a short intro.
`ncrypted SLUG` is shorthand for `download`, and `ncrypted <path>` is shorthand
for `upload`:

```bash
ncrypted                                   # show settings / intro
ncrypted SLUG                              # = ncrypted download SLUG
ncrypted https://ncrypted.app/s/SLUG       # download by URL
ncrypted /path/to/file.ext                 # = ncrypted upload /path/to/file.ext
```

### Global options

Placed before the command:

```bash
ncrypted --version
ncrypted --server https://example.com ...  # override NCRYPTED_SERVER
ncrypted --max-up 1m --max-down 5m ...     # default speed limits for the run
```

### Commands

```bash
# List your uploads (compact table by default)
ncrypted list
ncrypted list --full                          # every field, one block per file
ncrypted list --json                          # machine-readable

# Show file info (optionally decrypt the private description)
ncrypted info SLUG
ncrypted info SLUG --show-private [--passphrase PASS]

# Upload (private by default; PATH may be a file or a directory)
ncrypted upload PATH
ncrypted upload PATH --public                 # or --no-public (default)
ncrypted upload PATH --passphrase PASS
ncrypted upload PATH --public-desc "caption" --private-desc "secret note"
ncrypted upload PATH --archive                # wrap encrypted data in a ZIP
ncrypted upload PATH -y                        # skip confirmation
ncrypted upload PATH --max-up 500k             # throttle this transfer

# Download (auto-decrypts; auto-extracts archives)
ncrypted download SLUG
ncrypted download SLUG -o /tmp                 # existing dir -> keep original name
ncrypted download SLUG -o /tmp/new-name.ext
ncrypted download SLUG --passphrase PASS
ncrypted download SLUG --no-extract            # do not auto-extract archives
ncrypted download SLUG --max-down 5m           # throttle this transfer
# The blob is downloaded once, then you get up to 3 passphrase attempts. If all
# fail, the still-encrypted blob is saved as <name>.enc so the download is not
# wasted — decrypt it later without re-downloading:

# Decrypt a previously saved .enc file (offline, no network, 3 attempts)
ncrypted decrypt FILE.enc
ncrypted decrypt FILE.enc -o /tmp
ncrypted decrypt FILE.enc --passphrase PASS --no-extract

# Update descriptions
ncrypted update SLUG --public-desc "new caption"
ncrypted update SLUG --private-desc "new note" [--passphrase PASS]

# Delete
ncrypted delete SLUG
ncrypted delete SLUG -y                         # skip confirmation

# Accounts / session
ncrypted register-user
ncrypted login-user
ncrypted log-out                                # alias: logout
ncrypted settings                               # print resolved settings
```

Every command also accepts `--server`. For `download`, `-o`/`--output` takes a
new file path, or an existing directory (the client then keeps the original
file name). Run `ncrypted COMMAND --help` for the full flag list of any command.

## Local Binary Build

```bash
scripts/build-binary.sh
scripts/package-binary.sh
```

Outputs:

```bash
dist/ncrypted/                            # onedir bundle (launcher + _internal/)
dist/release/ncrypted-<os>-<arch>.tar.gz  # Linux archive
dist/release/ncrypted-<os>-<arch>.zip     # macOS archive
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
