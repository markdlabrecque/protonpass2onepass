"""OnePuxWriter — assemble and write a .1pux archive.

A .1pux is a ZIP containing:
    export.attributes   {version, description, timestamp}
    export.data         {accounts:[{attrs, vaults:[{attrs, items:[...]}]}]}
    files/              attachments (we ship an empty dir; attachments are
                        extracted separately for manual re-attach)
"""
from __future__ import annotations

import json
import secrets
import time
import zipfile

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"  # base32-ish, matches 1Password


def new_id() -> str:
    """26-char lowercase id in the style 1Password uses for uuids."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(26))


def attributes(now: int | None = None) -> dict:
    return {
        "version": 3,
        "description": "1Password Unencrypted Export",
        "timestamp": int(now if now is not None else time.time()),
    }


def account_block(vault_blocks: list[dict], email: str = "import@example.com") -> dict:
    uuid = new_id()
    return {
        "attrs": {
            "accountName": "Proton Pass Import",
            "name": "Proton Pass Import",
            "avatar": "",
            "email": email,
            "uuid": uuid,
            "domain": "https://my.1password.com/",
        },
        "vaults": vault_blocks,
    }


def vault_block(name: str, desc: str, items: list[dict], vtype: str = "U") -> dict:
    return {
        "attrs": {
            "uuid": new_id(),
            "desc": desc or "",
            "avatar": "",
            "name": name or "Proton Pass",
            "type": vtype,
        },
        "items": items,
    }


def write(out_path: str, accounts: list[dict], now: int | None = None) -> None:
    export_data = {"accounts": accounts}
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("export.attributes", json.dumps(attributes(now)))
        zf.writestr("export.data", json.dumps(export_data))
        # empty files/ directory entry
        zi = zipfile.ZipInfo("files/")
        zf.writestr(zi, b"")
