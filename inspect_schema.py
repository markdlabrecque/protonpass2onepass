#!/usr/bin/env python3
"""Step 0 inspector: print the *structural shape* of a Proton Pass export's
data.json (and optionally a .1pux export.data) with every scalar value replaced
by its type name. No secret values are ever emitted.

Usage:
    python3 inspect_schema.py --proton path/to/export.zip
    python3 inspect_schema.py --pux path/to/account.1pux
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter


def shape(value):
    """Return a redacted structural shape: scalars -> type name, dicts recurse,
    lists -> merged shape of all elements so we see the union of keys."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return ["<empty>"]
        merged = {}
        scalar_types = set()
        for el in value:
            s = shape(el)
            if isinstance(s, dict):
                for k, v in s.items():
                    merged[k] = v  # last-wins; union of keys is what matters
            else:
                scalar_types.add(json.dumps(s))
        if merged:
            return [merged]
        return [sorted(scalar_types)]
    if value is None:
        return "null"
    return type(value).__name__  # str, int, float, bool


def read_member(zf: zipfile.ZipFile, suffix: str) -> bytes:
    for name in zf.namelist():
        if name.endswith(suffix) and not name.endswith("/"):
            return zf.read(name)
    raise FileNotFoundError(f"no member ending in {suffix!r}")


def inspect_proton(path: str) -> None:
    with zipfile.ZipFile(path) as zf:
        raw = read_member(zf, "data.json")
    data = json.loads(raw)

    print("=== TOP-LEVEL KEYS ===")
    print(sorted(data.keys()))
    for k in ("version", "encrypted"):
        if k in data:
            print(f"  {k}: {data[k]!r}")

    vaults = data.get("vaults", {})
    print(f"\n=== VAULTS ({len(vaults)}) ===")
    type_counter: Counter[str] = Counter()
    extrafield_types: Counter[str] = Counter()
    content_shapes: dict[str, dict] = {}
    item_keys: set = set()
    passkey_items = 0
    items_with_files = 0
    cfv_counter: Counter = Counter()

    for vid, vault in vaults.items():
        items = vault.get("items", [])
        print(f"  vault {vid[:8]}…  name=<redacted>  items={len(items)}")
        for item in items:
            item_keys.update(item.keys())
            d = item.get("data", {})
            itype = d.get("type", "?")
            type_counter[itype] += 1
            # record merged content shape per type
            content = d.get("content", {})
            merged = content_shapes.setdefault(itype, {})
            for k, v in shape(content).items():
                merged[k] = v
            for ef in d.get("extraFields", []) or []:
                extrafield_types[ef.get("type", "?")] += 1
            # contentFormatVersion may live at item or data level
            for holder in (item, d, d.get("metadata", {})):
                if isinstance(holder, dict) and "contentFormatVersion" in holder:
                    cfv_counter[holder["contentFormatVersion"]] += 1
            # passkeys
            if content.get("passkeys"):
                passkey_items += 1
            # attachments / files reference
            if item.get("files") or d.get("files") or content.get("files"):
                items_with_files += 1

    print(f"\n=== ITEM TYPES ===\n{dict(type_counter)}")
    print(f"\n=== contentFormatVersion values ===\n{dict(cfv_counter)}")
    print(f"\n=== extraFields[].type values ===\n{dict(extrafield_types)}")
    print(f"\n=== items with passkeys: {passkey_items} ===")
    print(f"=== items referencing files/attachments: {items_with_files} ===")
    print("\n=== ITEM WRAPPER KEYS (union) ===")
    print(sorted(item_keys))
    print("\n=== content shape per item type (values redacted to types) ===")
    for itype, sh in content_shapes.items():
        print(f"\n--- type: {itype} ---")
        print(json.dumps(sh, indent=2, sort_keys=True))

    # show one full extraField shape and metadata shape for reference
    for vid, vault in vaults.items():
        for item in vault.get("items", []):
            d = item.get("data", {})
            efs = d.get("extraFields") or []
            if efs:
                print("\n=== sample extraField shape (redacted) ===")
                print(json.dumps(shape(efs[0]), indent=2, sort_keys=True))
                print("\n=== metadata shape (redacted) ===")
                print(json.dumps(shape(d.get("metadata", {})), indent=2, sort_keys=True))
                return


def inspect_pux(path: str) -> None:
    # Fixture is intentionally dummy data, but still redact long strings so we
    # only reveal the structural *wrappers*, not values.
    with zipfile.ZipFile(path) as zf:
        attrs = json.loads(read_member(zf, "export.attributes"))
        data = json.loads(read_member(zf, "export.data"))
    print("=== export.attributes ===")
    print(json.dumps(attrs, indent=2))
    print("\n=== export.data shape (redacted to types) ===")
    print(json.dumps(shape(data), indent=2, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proton")
    ap.add_argument("--pux")
    args = ap.parse_args()
    if args.proton:
        inspect_proton(args.proton)
    if args.pux:
        inspect_pux(args.pux)
    if not args.proton and not args.pux:
        ap.error("pass --proton and/or --pux")
    return 0


if __name__ == "__main__":
    sys.exit(main())
