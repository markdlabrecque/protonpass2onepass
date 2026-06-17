# Spec: Proton Pass → 1Password (`.1pux`) converter

## Goal

Convert a Proton Pass account export into a valid 1Password Unencrypted Export
(`.1pux`) file that imports into 1Password 8 **with TOTP seeds and custom fields
intact**. CSV and the Bitwarden-importer workaround both drop those, which is
why we build our own.

- **Input:** a Proton Pass export (unencrypted ZIP, or PGP-encrypted ZIP that
  the operator decrypts first). The payload is a `data.json` file.
- **Output:** a single `<uuid>.1pux` file ready to import via
  1Password → Import → 1Password (1PUX).
- **Language:** Python 3.x, standalone CLI script. No framework, no third-party
  packages. Only the standard library is required — `zipfile` and `json` both
  ship with a normal Python build.

## Hard rule: never move the export off this machine

The export is plaintext credentials. Read it from a local path, write the
`.1pux` to a local path, and do not log field values. Acceptance includes
"no secret values written to stdout/stderr."

## Step 0 — Discover the real source schema before writing the mapper

Proton Pass's JSON has shifted across `contentFormatVersion` revisions (for
example, the login email field moved from `username` to `itemEmail`). Do **not**
code against an assumed schema. First:

1. Unzip the export and locate `data.json` (it may sit under a `Proton Pass/`
   prefix inside the archive).
2. Print the structural shape only — keys, item `type` values, and the set of
   `extraFields[].type` values present — **with all values redacted**. Use that
   to build the mapping, then keep it as a fixture-shape reference.

Expected top-level shape (verify against the real file):

```
{
  "version": "...",
  "vaults": {
    "<vaultId>": {
      "name": "...",
      "description": "...",
      "items": [
        {
          "itemId": "...",
          "data": {
            "type": "login | note | creditCard | alias | identity",
            "metadata": { "name": "...", "note": "..." },
            "content": { ...type-specific... },
            "extraFields": [
              { "fieldName": "...", "type": "text | hidden | totp", "data": { "content": "..." } }
            ]
          },
          "state": 1,
          "createTime": 0,
          "modifyTime": 0
        }
      ]
    }
  }
}
```

## Target schema (`.1pux`) — verified against 1Password's spec

A `.1pux` is a ZIP containing three things:

```
<account UUID>.1pux
├── export.attributes
├── export.data
└── files/            (attachments + custom icons; can be empty)
```

### `export.attributes`

```json
{ "version": 3, "description": "1Password Unencrypted Export", "timestamp": 1781661364 }
```

> **Verified 2026-06-16:** the real key is **`timestamp`** (Unix seconds), not
> `createdAt`. Confirmed against the golden fixture.

### `export.data`

Nested tree: `accounts[].vaults[].items[]`.

- **Account attrs:** `accountName`, `name`, `email`, `uuid`, `domain`. For a
  fresh import the values are cosmetic; generate a stable `uuid` (also used as
  the `.1pux` filename).
- **Vault attrs:** `uuid`, `name`, `desc`, `avatar` (`""` is fine), `type`
  (`P` personal, `U` user-created). Map each Proton vault → one 1Password vault.
- **Item:** `uuid`, `favIndex` (0), `createdAt`, `updatedAt` (Unix seconds —
  reuse Proton's `createTime`/`modifyTime`), `state` (`active`),
  `categoryUuid`, `overview`, `details`.

### Field mapping (the part that matters)

| Proton source | 1PUX target |
|---|---|
| `metadata.name` | `overview.title` |
| login `content` URL(s) | `overview.url` (primary) + `overview.urls[]` (`{label, url}`) |
| login username/email | `details.loginFields[]` entry, `designation: "username"` |
| login password | `details.loginFields[]` entry, `designation: "password"` |
| `metadata.note` | `details.notesPlain` |
| login `content.totpUri` | a section field, `value: { "totp": "otpauth://..." }` |
| `extraFields[]` type `totp` | section field, `value: { "totp": "..." }` |
| `extraFields[]` type `hidden` | section field, `value: { "concealed": "..." }` |
| `extraFields[]` type `text` | section field, `value: { "string": "..." }` |

Section fields live in `details.sections[]`, each `{ title, name, fields[] }`,
each field `{ title, id, value: <typed wrapper> }`. The typed wrapper is the
crux: the key inside `value` declares the type (`string`, `concealed`, `totp`,
`date`, `monthYear`, etc.).

### `categoryUuid` values (verify against a real 1Password export)

`001` Login · `002` Credit Card · `003` Secure Note · `004` Identity ·
`005` Password. Confirm before trusting — a wrong category UUID makes an item
import into the wrong template.

## Verified schema (Step 0 results — real export, 2026-06-16)

Run `python3 inspect_schema.py --proton <export.zip> --pux <fixture.1pux>` to
reproduce. Findings from the operator's real export (`version 1.37.0`,
`contentFormatVersion` 6 and 7 both present):

- **Item types:** `login`, `alias`, `note`, `creditCard`, `identity`, and an
  additional **`custom`** type (Proton custom item) not listed in the original
  draft. Counts vary; the mapper handles all six.
- **Login content has BOTH `itemEmail` and `itemUsername`** (independently
  populated). Mapping policy: `itemUsername` → login `username`; if `itemEmail`
  is also present it is added as a separate section field; if only `itemEmail`
  exists it becomes the `username`.
- **TOTP** lives in login `content.totpUri` (string). No `totp`-typed
  `extraFields` were present in this export, but the mapper still handles them.
- **`extraFields[].type`** values seen: `text` → `{"string": …}`, `hidden` →
  `{"concealed": …}`, `timestamp` → `{"date": <unix|null>}`. Shape:
  `{ "fieldName": …, "type": …, "data": { "content": … } }` (timestamp uses
  `data.timestamp`).
- **Alias** address is at **item level** as `aliasEmail` (not in `content`).
  Default lands as a Login with the alias as username (`--alias-as note` to use
  a Secure Note instead).
- **Attachments:** `item.files` is a list of relative filenames that resolve
  under the archive's `Proton Pass/files/` prefix. Policy: extract them to a
  sibling `*_attachments/` folder and list them in the report for manual
  re-attach (the `.1pux` per-item attachment-reference shape is not verified by
  a fixture, so we do not embed).
- **Passkeys:** present on some logins (`content.passkeys`). Device-bound —
  reported, never synthesized.
- **`categoryUuid`** confirmed from the fixture: `001` Login, `004` Identity.
  `002`/`003`/`005` used per the standard mapping.
- **Vault `type`** codes seen: `P` (Private/personal), `E` (shared). Both map to
  a 1Password vault; output uses `P` for the primary, `U` otherwise.
- **`.1pux` value wrappers** confirmed: `{"totp"}`, `{"concealed"}`,
  `{"string"}`, plus `date`/`url`/`email`/`phone`/`address` in identity items.
  `loginFields[]` shape: `{value, id, name, fieldType ("T"/"P"), designation}`.

## Import-rejection rules (learned from a real round-trip, 2026-06-16)

A first import of 373 items had 28 silently rejected. 1Password gives no
per-item log; the failures were identified by exporting the imported vault back
to `.1pux` and diffing titles (`diff_import.py`). Two non-obvious rules emerged
— both now enforced by the mapper:

1. **`overview.subtitle` is mandatory.** Every item 1Password accepts has the
   key (even if `""`); omitting it rejects the whole item. This sank all 12
   Secure Notes (`003`). All overviews now go through a `_overview()` helper that
   always includes `subtitle`.
2. **A Login (`001`) needs real content.** A login with only a username (no
   password, no URL, and no section fields) is rejected. This sank all 16
   aliases (alias address as username only). Aliases now also carry the address
   as a section field, which satisfies the importer (verified: a sections-only
   login imports).

## Golden fixture (do this before coding the mapper)

By hand, create two items in 1Password — (a) a Login with a TOTP and (b) an item
with a custom concealed field — then export to `.1pux` and unzip it. That gives
you the **exact** `value`-wrapper shapes and section structure to target,
rather than inferring them. Keep it in `fixtures/` as the reference.

## Edge cases / explicitly out of scope

- **Passkeys do not migrate** via file import (device-bound). Detect any present
  in the Proton export and emit a report listing the affected logins so they can
  be re-registered manually. Do not attempt to synthesize them.
- **Email aliases** (SimpleLogin) have no native 1Password type. Decide policy:
  land as Login items (alias address as username) or as Secure Notes. Make it a
  flag; default to Login.
- **Attachments:** if the Proton export carries files, copy them into `files/`
  named `<documentId>___<originalName>` and reference them per the spec. If none
  are present, ship an empty `files/`.
- **Field ordering** inside an item is best-effort, not guaranteed.

## Acceptance criteria

1. Output imports into a clean 1Password vault with zero errors.
2. A login with TOTP shows a working one-time-password code after import.
3. A custom concealed field survives as a concealed field (not plaintext, not
   dropped).
4. Item counts per vault match the source (minus any items the operator
   intentionally skipped via flag).
5. No secret values appear in logs or stdout.
6. A passkey/alias report is written for anything that couldn't be carried over.

## Suggested shape

```
proton-to-1pux/
├── convert.py               # CLI: --in export.zip --out account.1pux [--alias-as login|note]
├── proton2onepass/          # package: ProtonReader, OnePuxWriter, item mappers per type
├── fixtures/                # hand-built golden .1pux reference
└── proton-to-1pux.spec.md   # this file
```

---

### Code kickoff prompt

> I'm building a Proton Pass → 1Password `.1pux` converter in Python 3 (CLI,
> standard library only — `zipfile` + `json`, no third-party packages). The full
> spec is in `proton-to-1pux.spec.md` — read it.
> Start with Step 0: unzip my export at `<PATH>`, locate `data.json`, and print
> its structural shape (keys, item `type`s, `extraFields` types) with all values
> redacted, so we map against the real schema. Don't write any secret values to
> output. Once we've confirmed the shape, we'll build the mapper, validating
> against a golden `.1pux` fixture.
