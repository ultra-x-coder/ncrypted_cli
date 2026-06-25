# Deferred: duplicate-upload detection (task #3)

Status: **deferred** — wait until the server is reconfigured to expose
`content_sha256` in the file listing. This is the design note so we do not
re-derive it later.

## Goal

Before uploading, detect that the same file was already uploaded and ask the
user to confirm a re-upload instead of silently creating a duplicate.

## What the client already does

`actions.do_upload()` already computes, over the **plaintext** (not the
encrypted blob):

- `content_sha256 = hashlib.sha256(plaintext).hexdigest()`
- `original_size = len(plaintext)`

and sends both to the server as upload fields. So "collect hash/SHA/size" is
already done — we only need to *use* it for a pre-upload check.

## Proposed mechanism

1. Read the file and compute `sha256` **early — before encryption** (cheap).
2. Fetch the existing list (`do_list(server)`) and look for a file with the
   same `content_sha256`.
3. If found, prompt:
   `Identical file already uploaded as <slug> (<url>). Upload again? [y/N]`
4. Skip the prompt when `-y/--yes` is already passed (upload's existing flag).

Bonus: if the user declines, we skip the expensive Argon2 + AES-GCM + zstd-22
work because we bail out *before* encrypting.

Cost: one extra `GET /files` before each upload (gated by `-y`).

## Blocker / decision to make

Does the server return `content_sha256` in `GET /files` (list) and/or
`GET /info/{slug}`? Today `cli._normalized_file` does **not** read it, so it is
unknown.

- **Server returns sha** → reliable hash comparison. **Preferred.**
- **Server does not return sha** → weaker fallback: match on
  `(original_filename, original_size)` from the listing, clearly labeled as
  "possibly a duplicate".

Action when resumed: confirm what the reconfigured server exposes (e.g.
`ncrypted list --json` against a real account), then implement the matching
path accordingly. The check stays entirely client-side; no server code is
changed by the client.

## Scope: ONLY the current user's own files (hard requirement)

The duplicate check must compare the new file **only against files owned by the
authenticated user** (the existing per-account `GET /files` listing already
does this). It must **never** answer the question "does this exact file exist
anywhere on the server, for anyone?".

Do **not** add — now or later — a global "does this `content_sha256` exist?"
endpoint or any cross-user matching exposed to clients.

### Why this matters (existence / confirmation-of-a-file oracle)

`content_sha256` is computed over the **plaintext**. So anyone who already holds
a copy of some plaintext can compute its hash and, if a global existence check
existed, probe the server to learn whether that exact file is hosted — *even
though the stored blob is end-to-end encrypted*. That single capability would
quietly defeat the whole point of client-side encryption. Concrete abuses:

- **DMCA / takedown hunters:** hold a copyrighted file, hash it, and probe the
  server to confirm it is hosted and worth a takedown — turning the service into
  a search tool against its own users.
- **Confirmation attacks on known/low-entropy files:** confirm that a specific
  leaked document, whistleblower file, or sensitive form is present.
- **Deanonymization / linkage:** cross-user dedup reveals that two different
  accounts uploaded the same file, linking otherwise-unrelated users.

Per-user scope leaks nothing new: a user learning "you already uploaded this"
only learns about their own data, which they already control.

### Residual note (server-side, out of client scope)

Storing the plaintext `content_sha256` already gives the **server operator** a
cross-user matching capability internally (they can detect known files and
duplicates across accounts). The client cannot fix that. If that metadata leak
is ever a concern, the deeper mitigation lives server-side / in the wire format
(e.g. a keyed or per-account-salted hash instead of a raw plaintext sha) — note
this is a compatibility-breaking change and explicitly out of scope here.

**Decision:** dedup = own files only; no global existence oracle, ever.
