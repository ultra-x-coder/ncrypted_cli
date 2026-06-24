# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - 2026-06-25

Initial release.

### Added
- Terminal client for encrypted file exchange with `ncrypted.app`:
  upload, download, list, info, update, delete, and user accounts.
- Client-side compression and encryption before upload — the server only
  receives the encrypted blob plus integrity metadata.
- `--version` flag.
- `install.sh` local mode: install from a cloned repository (reuse
  `dist/ncrypted` or build it) instead of downloading a release.
- GitHub Actions release pipeline producing Linux and macOS binaries plus
  `SHA256SUMS`.

### Changed
- The project version now lives in a single source
  (`ncrypted_cli/__init__.py`) and is read from there by `pyproject.toml`.
