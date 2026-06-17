# Proton Pass → 1Password (`.1pux`) converter

Converts a Proton Pass JSON export into a 1Password Unencrypted Export
(`.1pux`) that imports into 1Password 8 **with TOTP seeds and custom fields
intact** — the things CSV and the Bitwarden workaround drop.

Python 3, standard library only (`zipfile` + `json`). No third-party packages.

See `docs/proton-to-1pux.spec.md` for the full spec and the verified schema
findings, and `docs/export-prep-guide.md` for how to produce the source files.

## Security

Exports are plaintext credentials. Everything stays local: the tool reads a
local ZIP, writes a local `.1pux`, and **never prints field values** (only
counts). `source_files/`, `out/`, and `*.1pux` are gitignored — never commit
them.

## Usage

```bash
# 1) (optional) inspect the real Proton schema, all values redacted:
python3 inspect_schema.py --proton "source_files/your-export.zip"

# 2) convert:
python3 convert.py --in "source_files/your-export.zip" --out out/account.1pux
```

### Options

| Flag | Default | Meaning |
|---|---|---|
| `--in` | (required) | Proton Pass export `.zip` |
| `--out` | (required) | output `.1pux` path |
| `--alias-as login\|note` | `login` | how SimpleLogin aliases land |
| `--include-trashed` | off | also convert items in Proton's trash (`state=2`) |
| `--skip id,id` | — | Proton `itemId`s to omit |
| `--email addr` | `import@example.com` | cosmetic account email in the export |

## Output

- `out/account.1pux` — import via **1Password → Import → 1Password (1PUX)**.
- `out/account-report.md` — per-vault reconciliation, passkeys that need manual
  re-registration, and extracted attachments.
- `out/account_attachments/` — files pulled from the Proton export for **manual
  re-attach** (1Password file import isn't done automatically).

## What maps where

| Proton | 1Password |
|---|---|
| `login` | Login (`001`) — username/password, URLs, `totpUri` → TOTP field, extra fields → section |
| `alias` | Login (`001`, alias as username) or Secure Note (`--alias-as note`) |
| `note` | Secure Note (`003`) |
| `creditCard` | Credit Card (`002`) — number/expiry/CVV/PIN |
| `identity` | Identity (`004`) — fields preserved in a section |
| `custom` | Secure Note (`003`) |

`extraFields`: `text` → `string`, `hidden` → `concealed`, `timestamp` → `date`.

## Known limitations

- **Passkeys** are device-bound and cannot be file-imported — reported, not
  converted.
- **Attachments** are extracted for manual re-attach, not embedded (the per-item
  `.1pux` attachment-reference shape isn't verified against a fixture).
- **Credit-card brand** (Proton's numeric `cardType` enum) is not carried over.
- **Identity** fields land in a single section rather than 1Password's native
  identity template slots.
- Field ordering within an item is best-effort.

## After importing — verify (spec acceptance criteria)

1. Imports with zero errors.
2. A login with TOTP shows a live code.
3. A custom concealed field is still concealed.
4. Item counts match the report's reconciliation.
