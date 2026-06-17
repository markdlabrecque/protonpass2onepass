# Pre-work guide: what to gather from Proton Pass and 1Password

Before any mapping code is written, two **source artifacts** must be produced —
one from each app — plus a couple of facts to confirm while you're in there.
This guide explains what each piece is, *why* it's needed, and exactly how to
produce it (including which options to choose on export).

> **Standing rule:** both exports are plaintext credentials. Keep them on this
> machine, hand over local paths only, and the converter never logs field
> values. (See the spec's "never move the export off this machine.")

---

## 1. The Proton Pass export (the input)

### Why
This is the data we convert. The spec's **Step 0** exists because Proton has
quietly changed its JSON shape across `contentFormatVersion` revisions (e.g. the
login email moved from `username` → `itemEmail`). Coding against an assumed
schema risks silently dropping TOTP seeds and custom fields — the exact failure
this project avoids. The real file is needed to read the actual key names before
the mapper is written.

### What format to choose — this matters
- **Format: JSON. Not CSV.** CSV is the whole reason this project exists — it
  drops TOTP seeds and custom fields.
- **Encryption: optional.** Proton offers a "PGP-encrypt the export" option with
  a passphrase. The file is plaintext credentials either way once decrypted, so
  it only changes whether you decrypt it before handing over a path.

### How to export (Proton Pass desktop app or web at pass.proton.me)
> Export is available in the **desktop apps and the web app** — not mobile.

1. Open Proton Pass and unlock it.
2. Open **Settings** (gear icon).
3. Go to the **Export** tab.
4. **Format → JSON.**
5. Optionally tick **"Encrypt your Proton Pass export"** and set a passphrase.
6. Click **Export**. You'll get either:
   - an unencrypted **`.zip`** (contains `data.json`, possibly under a
     `Proton Pass/` prefix, plus an `attachments/` folder if you have file
     attachments), or
   - a **PGP-encrypted file** that decrypts to that same ZIP.
7. Save it to a **local path** and provide that path.

### Caveats
- **Only vaults you own get exported.** Vaults shared *to* you may be excluded —
  verify they're present (acceptance criterion #4: item counts must match).
- **Attachments** are a paid Proton feature; if present they'll be in the ZIP
  and we copy them into the `.1pux` `files/` dir.
- **Passkeys** won't survive any file-based import (device-bound). They're
  detected and reported, not converted.

---

## 2. The golden `.1pux` fixture (the target reference)

### Why
The spec (its "Golden fixture" section) prescribes this but can't contain it —
only the 1Password app can produce it. Its purpose: `.1pux` encodes a field's
*type* by the **key name inside a `value` wrapper** (`{"totp": "..."}` vs
`{"concealed": "..."}` vs `{"string": "..."}`), and the section/field nesting is
fiddly. Copying these shapes byte-for-byte from a real export de-risks acceptance
criteria #2 (TOTP works) and #3 (concealed field stays concealed).

### How to build it (1Password 8 **desktop app** — required)
> `.1pux` export is **desktop-only**. The browser extension and 1Password.com web
> app cannot produce it.

**Create two dummy items** (use throwaway values — never real secrets):

**Item (a) — a Login with a TOTP:**
1. New Item → **Login**.
2. Fill a dummy **username**, **password**, and **website** (e.g.
   `https://example.com`).
3. Add a one-time-password field via the field's **+ / "Add more"** menu →
   **One-Time Password**, and paste a dummy seed:
   `otpauth://totp/Test:test@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Test`
4. Save.

**Item (b) — something with a custom concealed field:**
1. New Item → **Login** (or Password/Secure Note — doesn't matter).
2. Add a **section**, then a **field**, and set its type to **Password** (this
   renders as a *concealed* custom field).
3. Give it a label (e.g. "Recovery key") and a dummy value. Save.

**Export to `.1pux`:**
1. In the sidebar, click your **account name** (top of the sidebar).
2. Choose **Export** → select the account.
3. Enter your **1Password account password** when prompted.
4. **File format → "1Password Unencrypted Export (.1pux)"** (not CSV).
5. Save the `.1pux` locally and provide the path. It goes in `fixtures/`.

### Caveat
1Password exports the **whole account** (all vaults) in plaintext, not a single
item. Either export as-is and we read only the two dummy items (then delete the
file), or create the dummy items in a throwaway vault/account and export that.

---

## 3. Two facts that fall out of the fixture (no extra work)

The spec flags these as "verify before trusting":

- **`categoryUuid` values** — spec assumes `001` Login, `002` Credit Card,
  `003` Secure Note, `004` Identity, `005` Password. The fixture confirms Login
  (`001`) directly; adding a Credit Card / Identity / Secure Note to the
  exported account confirms the rest. A wrong UUID imports an item under the
  wrong template.
- **`export.attributes`** shape — the fixture confirms `version` / `description`
  / `createdAt` exactly.

---

## Checklist

| # | Artifact | App | Key choices | Gives us |
|---|---|---|---|---|
| 1 | Proton Pass export | Proton Pass desktop/web | **JSON** (not CSV); encryption optional | Real input schema (Step 0) |
| 2 | Golden `.1pux` | 1Password **8 desktop** | **1PUX** format (not CSV); 1 Login+TOTP item, 1 concealed-custom-field item | Exact `value`-wrapper & section shapes (the target) |
| 3 | Category / attrs check | (falls out of #2) | — | Confirms `categoryUuid` + `export.attributes` |

Once paths to **#1** and **#2** exist, the redacting inspector runs on the
Proton file, the real schema is eyeballed, and the mapper is built against both
verified references.
