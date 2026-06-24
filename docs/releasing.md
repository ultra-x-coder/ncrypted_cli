# Ncrypted release guide

This guide explains how to publish the CLI so users can install it with:

```bash
curl -fsSL https://ncrypted.app/install.sh | sh
```

After install, the command is:

```bash
ncrypted
ncrypted upload file.txt
ncrypted list
```

## One-time setup

### 1. GitHub repository secrets

Open the GitHub repository, then go to:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

For macOS signing and notarization, add:

```text
MACOS_CERTIFICATE_P12
MACOS_CERTIFICATE_PASSWORD
APPLE_ID
APPLE_TEAM_ID
APPLE_APP_SPECIFIC_PASSWORD
```

If these secrets are absent, the workflow still builds macOS artifacts, but they
will not be signed or notarized.

### 2. Apple Developer ID certificate

Create a **Developer ID Application** certificate in the Apple Developer portal.
Install it into Keychain Access, then export it as a `.p12` file.

Convert the `.p12` to base64 for GitHub:

```bash
base64 -i DeveloperIDApplication.p12 | pbcopy
```

Paste that value into `MACOS_CERTIFICATE_P12`. Put the `.p12` export password in
`MACOS_CERTIFICATE_PASSWORD`.

### 3. Apple app-specific password

Create an app-specific password for your Apple ID and save it as:

```text
APPLE_APP_SPECIFIC_PASSWORD
```

Also set:

```text
APPLE_ID=you@example.com
APPLE_TEAM_ID=YOURTEAMID
```

## Releasing a new version

Update code, commit it, then push a version tag:

```bash
git tag v1.0.1
git push origin main
git push origin v1.0.1
```

The GitHub Actions workflow `.github/workflows/release.yml` runs automatically
for tags matching `v*`.

It builds:

```text
ncrypted-linux-x86_64.tar.gz
ncrypted-linux-arm64.tar.gz
ncrypted-macos-x86_64.zip
ncrypted-macos-arm64.zip
SHA256SUMS
```

The workflow creates or updates the GitHub Release for that tag and uploads the
files.

## Does install.sh change for every version?

No. Keep `install.sh` stable.

By default it downloads from:

```text
https://ncrypted.app/releases/latest/
```

For a specific version, users can run:

```bash
curl -fsSL https://ncrypted.app/install.sh | NCRYPTED_VERSION=v1.0.1 sh
```

That downloads from:

```text
https://ncrypted.app/releases/v1.0.1/
```

## Hosting on ncrypted.app

Serve this file:

```text
https://ncrypted.app/install.sh
```

Mirror the release artifacts to:

```text
https://ncrypted.app/releases/latest/ncrypted-linux-x86_64.tar.gz
https://ncrypted.app/releases/latest/ncrypted-linux-arm64.tar.gz
https://ncrypted.app/releases/latest/ncrypted-macos-x86_64.zip
https://ncrypted.app/releases/latest/ncrypted-macos-arm64.zip
https://ncrypted.app/releases/latest/SHA256SUMS
```

For versioned installs, also mirror to:

```text
https://ncrypted.app/releases/v1.0.1/...
```

If you do not want to mirror files to `ncrypted.app`, users can install directly
from GitHub Releases:

```bash
curl -fsSL https://ncrypted.app/install.sh | \
  NCRYPTED_DOWNLOAD_BASE_URL=https://github.com/OWNER/REPO/releases/latest/download sh
```

## Local test build

Build and package on your own machine:

```bash
scripts/build-binary.sh
scripts/package-binary.sh
```

Output:

```text
dist/ncrypted
dist/release/ncrypted-<os>-<arch>.tar.gz
dist/release/ncrypted-<os>-<arch>.zip
```

Test install from a local folder by serving `dist/release` and overriding:

```bash
NCRYPTED_DOWNLOAD_BASE_URL=http://localhost:8080 sh install.sh
```
