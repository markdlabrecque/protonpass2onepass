"""ProtonReader — locate and load a Proton Pass export from a ZIP archive.

Reads only from a local path. Never logs field values.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field


@dataclass
class ProtonExport:
    version: str
    user_id: str
    vaults: dict  # vaultId -> vault dict (as in data.json)
    files_prefix: str  # archive prefix under which attachments live, e.g. "Proton Pass/files/"
    archive_path: str

    def iter_items(self):
        """Yield (vault_id, vault, item) for every item in every vault."""
        for vid, vault in self.vaults.items():
            for item in vault.get("items", []):
                yield vid, vault, item


@dataclass
class AttachmentRef:
    item_uuid: str          # Proton itemId
    item_title: str         # metadata.name (for the report)
    archive_name: str       # full name inside the ZIP
    rel_name: str           # value as stored in item["files"]


def _find_data_json(zf: zipfile.ZipFile) -> str:
    candidates = [n for n in zf.namelist()
                  if n.endswith("data.json") and not n.endswith("/")]
    if not candidates:
        raise FileNotFoundError("no data.json found in the archive")
    # Prefer the shallowest data.json (handles the 'Proton Pass/' prefix).
    candidates.sort(key=lambda n: n.count("/"))
    return candidates[0]


def load(archive_path: str) -> ProtonExport:
    with zipfile.ZipFile(archive_path) as zf:
        data_name = _find_data_json(zf)
        data = json.loads(zf.read(data_name))
    prefix = data_name[: -len("data.json")]  # e.g. "Proton Pass/"
    return ProtonExport(
        version=str(data.get("version", "")),
        user_id=str(data.get("userId", "")),
        vaults=data.get("vaults", {}) or {},
        files_prefix=f"{prefix}files/",
        archive_path=archive_path,
    )
